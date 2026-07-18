from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import SCHEMA_VERSION
from .config import load_config
from .errors import FundReportError
from .market import market_reference
from .metrics import performance_summary, validate_nav_history, window_for
from .models import FreshnessStatus, FundIdentity, SourceHealth, SourceMetadata
from .notifications import send_pushplus
from .renderer import render_html, render_pushplus_html
from .sources import CHINA_TZ, EastmoneyNavSource, HttpClient, now_iso, resolve_subscription
from .storage import HistoryStore, atomic_write_json, atomic_write_text

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_STATE_FILE = BASE_DIR / ".github" / "fund-report-state.json"


def today() -> dt.date:
    return dt.datetime.now(CHINA_TZ).date()


def current_slot() -> str | None:
    hour = dt.datetime.now(CHINA_TZ).hour
    if 5 <= hour < 13:
        return "morning"
    if 13 <= hour < 21:
        return "afternoon"
    return None


def freshness(latest: dt.date, maximum_lag_days: int) -> str:
    lag = (today() - latest).days
    if lag <= 3:
        return FreshnessStatus.NORMAL.value
    if lag <= maximum_lag_days:
        return FreshnessStatus.NORMAL_DELAYED.value
    if lag <= maximum_lag_days + 3:
        return FreshnessStatus.POSSIBLY_STALE.value
    return FreshnessStatus.STALE.value


def failed_fund(identity: FundIdentity, message: str) -> dict[str, Any]:
    source = SourceMetadata(
        source_name="数据抓取失败",
        source_type="unavailable",
        source_level=0,
        source_url=None,
        fetched_at=now_iso(),
        is_official=False,
        is_fallback=False,
        freshness_status=FreshnessStatus.FETCH_FAILED.value,
        parser_version="2.0",
        health=SourceHealth.FAILED.value,
    )
    return {
        "identity": identity.to_dict(),
        "official_nav": {
            "nav_date": None,
            "unit_nav": None,
            "accumulated_nav": None,
            "daily_return": None,
            "published_at": None,
            "status": "FETCH_FAILED",
            "freshness_status": FreshnessStatus.FETCH_FAILED.value,
            "source": source.to_dict(),
        },
        "subscription": {
            "official_account_limit": None,
            "public_channel_reference_limit": None,
            "alipay_verified_limit": None,
            "user_planned_amount": None,
            "actual_order_amount": None,
            "remaining_planned_amount": None,
            "status": "FETCH_FAILED",
            "source": source.to_dict(),
            "alipay_verification_status": "MANUAL_REQUIRED",
        },
        "estimate": {
            "target_nav_date": None,
            "estimated_nav": None,
            "estimated_return": None,
            "confidence": "LOW",
            "is_official": False,
            "source": source.to_dict(),
        },
        "performance": {"periods": {}, "risk": {}, "return_7_nav_days": None, "ytd": None},
        "benchmark": {
            "official_benchmark": identity.official_benchmark,
            "target_etf": identity.target_etf,
            "target_index": identity.target_index,
        },
        "fees": {"official_subscription_fee": None, "alipay_discounted_fee": None, "alipay_fee_verified": "NOT_VERIFIED"},
        "portfolio": None,
        "warnings": [message],
        "provenance": [source.to_dict()],
        "chart": None,
    }


def collect_fund(identity: FundIdentity, config: dict[str, Any], source: EastmoneyNavSource) -> dict[str, Any]:
    end = today()
    start = end - dt.timedelta(days=max(int(config["history_days"]), 1900))
    warnings: list[str] = []
    rows, nav_source = source.fetch_nav_history(identity, start, end)
    rows = validate_nav_history(rows, end)
    status = freshness(rows[-1].nav_date, int(config["max_nav_lag_days"]))
    nav_source = replace(nav_source, freshness_status=status)
    if nav_source.is_fallback:
        warnings.append("官方基金管理人净值源未配置；当前使用第三方公开数据，关键指标按降级状态展示。")
    summary = performance_summary(rows)
    try:
        estimate = source.fetch_estimate(identity).to_dict()
    except FundReportError as exc:
        warnings.append(f"下一待公布净值估算不可用：{exc}")
        estimate_source = SourceMetadata(
            source_name="东方财富估算接口",
            source_type="third_party_estimate",
            source_level=4,
            source_url=None,
            fetched_at=now_iso(),
            is_official=False,
            is_estimate=True,
            is_fallback=True,
            freshness_status="FETCH_FAILED",
            parser_version="third-party-estimate-v1",
            health=SourceHealth.FAILED.value,
        )
        estimate = {
            "target_nav_date": None,
            "estimated_nav": None,
            "estimated_return": None,
            "estimate_generated_at": None,
            "estimate_model_version": "third-party-estimate-v1",
            "confidence": "LOW",
            "error_band": None,
            "is_official": False,
            "source": estimate_source.to_dict(),
        }
    subscription = resolve_subscription(identity, config, end).to_dict()
    if subscription["status"] == "UNKNOWN":
        warnings.append("未配置经核验的最新基金公告；申购状态和公告限额均保持未知，不以 0 代替。")
    chart = None
    one_year = window_for(rows, "近1年", years=1)
    if one_year.complete:
        chart_points = [
            {"date": point.nav_date.isoformat(), "value": str(point.accumulated_nav)}
            for point in one_year.points
            if point.accumulated_nav is not None
        ]
        if len(chart_points) >= 2:
            chart = {
                "points": chart_points,
                "start_date": one_year.points[0].nav_date.isoformat(),
                "end_date": one_year.points[-1].nav_date.isoformat(),
                "point_count": len(chart_points),
                "source_name": nav_source.source_name,
            }
    return {
        "identity": identity.to_dict(),
        "official_nav": {
            "nav_date": rows[-1].nav_date.isoformat(),
            "unit_nav": str(rows[-1].unit_nav),
            "accumulated_nav": str(rows[-1].accumulated_nav) if rows[-1].accumulated_nav is not None else None,
            "daily_return": rows[-1].official_daily_return,
            "published_at": None,
            "status": "CONFIRMED_PUBLIC_FALLBACK" if nav_source.is_fallback else "CONFIRMED_OFFICIAL",
            "freshness_status": status,
            "source": nav_source.to_dict(),
        },
        "estimate": estimate,
        "performance": summary,
        "subscription": subscription,
        "benchmark": {
            "official_benchmark": identity.official_benchmark,
            "target_etf": identity.target_etf,
            "target_index": identity.target_index,
        },
        "fees": {"official_subscription_fee": None, "alipay_discounted_fee": None, "alipay_fee_verified": "NOT_VERIFIED"},
        "portfolio": None,
        "warnings": warnings,
        "provenance": [nav_source.to_dict(), estimate["source"], subscription["source"]],
        "chart": chart,
        "_history_rows": [point.to_dict() for point in rows],
    }


def make_report(config: dict[str, Any]) -> dict[str, Any]:
    client = HttpClient(timeout_seconds=22, retries=3)
    source = EastmoneyNavSource(client)
    funds: list[dict[str, Any]] = []
    warnings: list[str] = []
    for identity in config["fund_identities"]:
        try:
            item = collect_fund(identity, config, source)
        except (FundReportError, ValueError) as exc:
            item = failed_fund(identity, f"基金 {identity.code} 抓取/校验失败：{type(exc).__name__}: {exc}")
        funds.append(item)
        warnings.extend(item["warnings"])
    if not funds:
        raise ValueError("没有启用的基金配置")
    failed = sum(1 for fund in funds if fund["official_nav"]["status"] == "FETCH_FAILED")
    fallbacks = sum(1 for fund in funds if fund["official_nav"]["source"].get("is_fallback"))
    report_status = "FAILED" if failed == len(funds) else "DEGRADED" if failed or fallbacks else "OK"
    history_records: list[dict[str, Any]] = []
    for fund in funds:
        source_metadata = fund["official_nav"]["source"]
        for point in fund.pop("_history_rows", []):
            history_records.append(
                {
                    "fund_code": fund["identity"]["code"],
                    "data_type": "official_nav",
                    "data_date": point["nav_date"],
                    "source_name": source_metadata["source_name"],
                    "unit_nav": point["unit_nav"],
                    "accumulated_nav": point["accumulated_nav"],
                    "daily_return": point["official_daily_return"],
                    "fetched_at": source_metadata["fetched_at"],
                }
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "report_generated_at": now_iso(),
        "report_timezone": "Asia/Shanghai",
        "report_status": report_status,
        "data_quality": {
            "successful_fund_count": len(funds) - failed,
            "official_source_count": 0,
            "fallback_source_count": fallbacks,
            "fetch_failed_count": failed,
            "source_conflict_count": 0,
            "stale_data_count": sum(1 for fund in funds if fund["official_nav"].get("freshness_status") in {"POSSIBLY_STALE", "STALE"}),
        },
        "funds": funds,
        "market_news": config.get("ai_news", []),
        "market_reference": market_reference(config),
        "warnings": list(dict.fromkeys(warnings)),
        "_history_records": history_records,
    }


def persist(report: dict[str, Any], config: dict[str, Any]) -> Path:
    reports = BASE_DIR / "reports"
    data_dir = BASE_DIR / "data"
    report_path = reports / f"fund-report-{report['report_generated_at'][:10]}.html"
    history = report.pop("_history_records", [])
    atomic_write_json(data_dir / "latest.json", report)
    HistoryStore(data_dir / "history.json").upsert(history)
    atomic_write_text(report_path, render_html(report))
    return report_path


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a transparent public-data QDII fund report")
    parser.add_argument("--send", action="store_true", help="send a compact PushPlus summary")
    parser.add_argument("--dry-run", action="store_true", help="generate files but do not call PushPlus")
    parser.add_argument("--twice-per-day", action="store_true")
    parser.add_argument("--force-send", action="store_true")
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_FILE.relative_to(BASE_DIR)))
    args = parser.parse_args(argv)
    state_path = (BASE_DIR / args.state_file).resolve()
    slot = current_slot()
    state = load_state(state_path) if args.twice_per_day else {}
    if args.send and args.twice_per_day and not args.force_send and slot and state.get(slot, {}).get("date") == today().isoformat():
        print(f"skip=already_sent slot={slot} date={today().isoformat()}")
        return 0
    config = load_config(BASE_DIR)
    report = make_report(config)
    report_path = persist(report, config)
    quality = report["data_quality"]
    print(f"report={report_path}")
    print("quality=" + " ".join(f"{key}={value}" for key, value in quality.items()))
    if args.send and not args.dry_run:
        token = os.environ.get("PUSHPLUS_TOKEN") or config.get("pushplus_token")
        if not token:
            raise ValueError("未配置 PUSHPLUS_TOKEN；不会把 token 写入日志或报告")
        nav_dates = [fund["official_nav"].get("nav_date") for fund in report["funds"] if fund["official_nav"].get("nav_date")]
        nav_date = max(nav_dates) if nav_dates else "未知"
        status_name = {"OK": "数据正常", "DEGRADED": "数据降级", "FAILED": "数据异常"}[report["report_status"]]
        title = f"纳指基金日报 {today().isoformat()}｜净值截至{nav_date}｜{status_name}"
        result = send_pushplus(str(token), title, render_pushplus_html(report), config.get("pushplus_topic"))
        print(f"pushplus=sent code={result.get('code')}")
        if args.twice_per_day and slot and not args.force_send:
            state[slot] = {
                "date": today().isoformat(),
                "sent_at": now_iso(),
                "report_status": report["report_status"],
                "latest_nav_date": nav_date,
            }
            state["last_sent_at"] = state[slot]["sent_at"]
            state["schema_version"] = SCHEMA_VERSION
            atomic_write_json(state_path, state)
    return 0


def main() -> None:
    try:
        raise SystemExit(run())
    except (FundReportError, ValueError, OSError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

