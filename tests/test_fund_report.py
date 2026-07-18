from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fund_report.config import load_config
from fund_report.errors import SourceUnavailableError
from fund_report.market import reference_cny_return
from fund_report.metrics import annualized_volatility, cagr, max_drawdown, performance_summary, seven_nav_day_return, window_for
from fund_report.models import FundIdentity, NavPoint
from fund_report.notifications import send_pushplus
from fund_report.renderer import render_html
from fund_report.sources import EastmoneyNavSource, HttpClient, parse_amount, resolve_subscription
from fund_report.storage import HistoryStore


def identity(code: str = "270042") -> FundIdentity:
    return FundIdentity.from_mapping(
        {
            "code": code,
            "official_name": "测试基金",
            "display_name": "测试基金A",
            "share_class": "A",
            "currency": "CNY",
            "fund_type": "QDII",
            "platform": "支付宝（购买渠道）",
            "enabled": True,
        }
    )


def points(days: int, start: dt.date = dt.date(2022, 1, 1)) -> list[NavPoint]:
    rows = []
    nav = Decimal("1")
    for offset in range(days):
        nav *= Decimal("1.0005")
        rows.append(NavPoint("270042", start + dt.timedelta(days=offset), nav, nav, 0.0005))
    return rows


class EastmoneySourceTests(unittest.TestCase):
    def test_parse_history_keeps_identity_and_decimal_nav(self):
        payload = {
            "ErrCode": 0,
            "TotalCount": 1,
            "Data": {"LSJZList": [{"FSRQ": "2026-07-16", "DWJZ": "8.0725", "LJJZ": "8.3425", "JZZZL": "-1.63"}]},
        }
        rows, total = EastmoneyNavSource(HttpClient()).parse_history_response("270042", json.dumps(payload))
        self.assertEqual(total, 1)
        self.assertEqual(rows[0].fund_code, "270042")
        self.assertEqual(rows[0].unit_nav, Decimal("8.0725"))
        self.assertEqual(rows[0].official_daily_return, -0.0163)

    def test_history_pagination_reads_all_pages(self):
        class FakeClient:
            def get_text(self, url, **_kwargs):
                page = 2 if "pageIndex=2" in url else 1
                records = [
                    {"FSRQ": f"2026-01-{day:02d}", "DWJZ": "1.0", "LJJZ": "1.0", "JZZZL": "0"}
                    for day in range(1 if page == 1 else 29, 29 if page == 1 else 31)
                ]
                return json.dumps({"ErrCode": 0, "TotalCount": 150, "Data": {"LSJZList": records}})

        source = EastmoneyNavSource(FakeClient())
        rows, _ = source.fetch_nav_history(identity(), dt.date(2026, 1, 1), dt.date(2026, 1, 31))
        self.assertEqual(len(rows), 30)


class MetricTests(unittest.TestCase):
    def test_complete_windows_and_insufficient_three_years(self):
        rows = points(500)
        summary = performance_summary(rows)
        self.assertIsNotNone(summary["periods"]["1y"]["return"])
        self.assertIsNone(summary["periods"]["3y"]["return"])
        self.assertFalse(summary["periods"]["3y"]["complete"])

    def test_seven_nav_days_requires_eight_points(self):
        self.assertIsNone(seven_nav_day_return(points(7)))
        self.assertIsNotNone(seven_nav_day_return(points(8)))

    def test_drawdown_volatility_and_cagr_have_documented_inputs(self):
        rows = points(40)
        rows[20] = NavPoint("270042", rows[20].nav_date, Decimal("0.7"), Decimal("0.7"), -0.3)
        draw = max_drawdown(rows)
        self.assertLess(draw["value"], -0.2)
        self.assertIsNotNone(annualized_volatility(rows))
        self.assertIsNotNone(cagr(window_for(points(400), "近1年", years=1)))

    def test_tracking_windows_do_not_relabel_short_history(self):
        summary = performance_summary(points(900))
        self.assertTrue(summary["periods"]["1y"]["complete"])
        self.assertFalse(summary["periods"]["3y"]["complete"])

    def test_usd_cny_reference_direction(self):
        self.assertAlmostEqual(reference_cny_return(0.10, 0.02), 0.122)
        self.assertAlmostEqual(reference_cny_return(0.10, -0.02), 0.078)
        self.assertIsNone(reference_cny_return(0.10, None))


class AmountAndSubscriptionTests(unittest.TestCase):
    def test_decimal_amount_parser(self):
        self.assertEqual(parse_amount("10元"), Decimal("10"))
        self.assertEqual(parse_amount("100.00元"), Decimal("100.00"))
        self.assertEqual(parse_amount("2,000元"), Decimal("2000"))
        self.assertEqual(parse_amount("1万元"), Decimal("10000"))
        self.assertEqual(parse_amount("10万元"), Decimal("100000"))
        self.assertEqual(parse_amount("100万美元"), Decimal("1000000"))
        self.assertIsNone(parse_amount("不限额"))
        self.assertEqual(parse_amount("暂停申购"), Decimal("0"))

    def test_announcement_state_machine_uses_latest_effective_matching_record(self):
        config = {
            "subscription_announcements": [
                {"fund_code": "270042", "share_class": "A", "currency": "CNY", "status": "PAUSED", "effective_date": "2025-01-01"},
                {
                    "fund_code": "270042",
                    "share_class": "A",
                    "currency": "CNY",
                    "status": "LIMITED",
                    "official_account_limit": "2,000元",
                    "effective_date": "2026-01-01",
                    "source_url": "https://manager.example/a",
                },
                {"fund_code": "270042", "share_class": "C", "currency": "CNY", "status": "OPEN", "effective_date": "2026-01-01"},
            ],
            "manual_alipay": {},
        }
        result = resolve_subscription(identity(), config, dt.date(2026, 7, 1))
        self.assertEqual(result.status.value, "LIMITED")
        self.assertEqual(result.official_account_limit, Decimal("2000"))
        self.assertIsNone(result.alipay_verified_limit)


class StorageAndHtmlTests(unittest.TestCase):
    def test_history_upsert_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(Path(tmp) / "history.json")
            record = {
                "fund_code": "270042",
                "data_type": "official_nav",
                "data_date": "2026-07-16",
                "source_name": "fixture",
                "unit_nav": "1.0",
            }
            store.upsert([record])
            store.upsert([{**record, "unit_nav": "1.1"}])
            data = json.loads((Path(tmp) / "history.json").read_text(encoding="utf-8"))
            self.assertEqual(len(data["records"]), 1)
            self.assertEqual(data["records"][0]["unit_nav"], "1.1")

    def test_mobile_html_prevents_date_character_wrapping(self):
        report = {
            "report_status": "DEGRADED",
            "report_generated_at": "2026-07-18T10:00:00+08:00",
            "warnings": [],
            "market_news": [],
            "funds": [
                {
                    "identity": identity().to_dict(),
                    "official_nav": {
                        "unit_nav": "1.2345",
                        "nav_date": "2026-07-16",
                        "daily_return": 0.01,
                        "freshness_status": "NORMAL",
                        "source": {
                            "source_name": "fixture",
                            "data_date": "2026-07-16",
                            "fetched_at": "2026-07-18T10:00:00+08:00",
                            "is_fallback": True,
                        },
                    },
                    "estimate": {"estimated_return": None, "source": {}},
                    "performance": {"periods": {}, "risk": {}, "return_7_nav_days": None, "ytd": None},
                    "subscription": {"status": "UNKNOWN", "source": {}, "alipay_verification_status": "MANUAL_REQUIRED"},
                    "benchmark": {},
                    "chart": None,
                }
            ],
        }
        page = render_html(report)
        self.assertIn("white-space:nowrap", page)
        self.assertIn("word-break:keep-all", page)
        self.assertIn("overflow-x:auto", page)


class NotificationTests(unittest.TestCase):
    def test_pushplus_failure_is_raised(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timeout")):
            with self.assertRaises(SourceUnavailableError):
                send_pushplus("secret", "title", "content")


class ConfigurationTests(unittest.TestCase):
    def test_all_configured_funds_have_distinct_identities(self):
        config = load_config(ROOT)
        codes = [item.code for item in config["fund_identities"]]
        self.assertEqual(codes, ["270042", "000834", "019172"])
        self.assertEqual(len(set(codes)), len(codes))


if __name__ == "__main__":
    unittest.main()

