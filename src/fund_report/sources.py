from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from .errors import ParseError, SourceUnavailableError
from .models import Estimate, FundIdentity, NavPoint, SourceHealth, SourceMetadata, Subscription, SubscriptionStatus

CHINA_TZ = ZoneInfo("Asia/Shanghai")
EASTMONEY_HISTORY_URL = "https://api.fund.eastmoney.com/f10/lsjz"
EASTMONEY_ESTIMATE_URL = "https://fundgz.1234567.com.cn/js/{code}.js"


def now_iso() -> str:
    return dt.datetime.now(CHINA_TZ).isoformat(timespec="seconds")


class HttpClient:
    """Small, bounded HTTP client that never records credentials in errors."""

    def __init__(self, timeout_seconds: int = 20, retries: int = 3, min_interval_seconds: float = 0.08):
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.min_interval_seconds = min_interval_seconds
        self._last_request = 0.0

    def get_text(self, url: str, *, referer: str, expected_content_type: str | None = None) -> str:
        delay = self.min_interval_seconds - (time.monotonic() - self._last_request)
        if delay > 0:
            time.sleep(delay)
        headers = {
            "User-Agent": "codex-spa100-public-fund-report/2.0",
            "Accept": "application/json,text/plain,text/html,*/*",
            "Referer": referer,
        }
        error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    status = getattr(response, "status", response.getcode())
                    content_type = response.headers.get("Content-Type", "")
                    if not 200 <= status < 300:
                        raise SourceUnavailableError(f"HTTP {status}")
                    raw = response.read()
                self._last_request = time.monotonic()
                text = raw.decode("utf-8-sig", errors="strict")
                if expected_content_type and content_type and expected_content_type not in content_type.lower():
                    # Some public endpoints return application/octet-stream; validate the payload too.
                    if expected_content_type == "json" and not text.lstrip().startswith(("{", "[")):
                        raise ParseError(f"unexpected content type {content_type}")
                return text
            except (
                urllib.error.HTTPError,
                urllib.error.URLError,
                TimeoutError,
                UnicodeDecodeError,
                ParseError,
                SourceUnavailableError,
            ) as exc:
                error = exc
                if attempt < self.retries:
                    time.sleep(min(4.0, 0.5 * (2 ** (attempt - 1))))
        raise SourceUnavailableError(f"source unavailable after {self.retries} attempts: {type(error).__name__}: {error}")


def decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", "--", "---", "null", "None"}:
        return None
    try:
        return Decimal(text.rstrip("%"))
    except InvalidOperation:
        return None


def parse_amount(value: Any) -> Decimal | None:
    """Parse a disclosed amount without converting unknown values to zero."""
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", "--", "不限额", "无限额", "不限制"}:
        return None
    if "暂停申购" in text or "暂停定投" in text:
        return Decimal("0")
    multiplier = Decimal("1")
    if "万美元" in text:
        multiplier = Decimal("10000")
    elif "万元" in text:
        multiplier = Decimal("10000")
    elif "亿" in text:
        multiplier = Decimal("100000000")
    number = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not number:
        return None
    try:
        return Decimal(number.group()) * multiplier
    except InvalidOperation:
        return None


@dataclass
class EastmoneyNavSource:
    client: HttpClient
    parser_version: str = "eastmoney-lsjz-json-v2"

    def _meta(self, url: str, latest_date: str | None = None, *, estimate: bool = False) -> SourceMetadata:
        return SourceMetadata(
            source_name="东方财富基金公开接口",
            source_type="third_party_public_api",
            source_level=3,
            source_url=url,
            fetched_at=now_iso(),
            data_date=latest_date,
            is_official=False,
            is_estimate=estimate,
            is_fallback=True,
            freshness_status="NORMAL",
            parser_version=self.parser_version,
            health=SourceHealth.DEGRADED.value,
        )

    def parse_history_response(self, fund_code: str, text: str) -> tuple[list[NavPoint], int]:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ParseError("Eastmoney history payload is not JSON") from exc
        if payload.get("ErrCode") not in (None, 0):
            raise SourceUnavailableError(f"Eastmoney error: {payload.get('ErrMsg') or payload.get('ErrCode')}")
        records = (payload.get("Data") or {}).get("LSJZList")
        if not isinstance(records, list):
            raise ParseError("Eastmoney history field Data.LSJZList is missing")
        rows: list[NavPoint] = []
        for record in records:
            try:
                nav_date = dt.date.fromisoformat(str(record.get("FSRQ", "")))
            except ValueError:
                continue
            unit_nav = decimal_or_none(record.get("DWJZ"))
            if unit_nav is None or unit_nav <= 0:
                continue
            daily_percent = decimal_or_none(record.get("JZZZL"))
            rows.append(
                NavPoint(
                    fund_code=fund_code,
                    nav_date=nav_date,
                    unit_nav=unit_nav,
                    accumulated_nav=decimal_or_none(record.get("LJJZ")),
                    official_daily_return=float(daily_percent / Decimal("100")) if daily_percent is not None else None,
                    subscription_status=str(record.get("SGZT") or "") or None,
                )
            )
        total = int(payload.get("TotalCount") or 0)
        return rows, total

    def fetch_nav_history(self, identity: FundIdentity, start: dt.date, end: dt.date) -> tuple[list[NavPoint], SourceMetadata]:
        page_size = 100
        page = 1
        total: int | None = None
        received: dict[dt.date, NavPoint] = {}
        final_url = ""
        while total is None or (page - 1) * page_size < total:
            query = urllib.parse.urlencode(
                {
                    "fundCode": identity.code,
                    "pageIndex": page,
                    "pageSize": page_size,
                    "startDate": start.isoformat(),
                    "endDate": end.isoformat(),
                }
            )
            final_url = f"{EASTMONEY_HISTORY_URL}?{query}"
            text = self.client.get_text(final_url, referer="https://fundf10.eastmoney.com/", expected_content_type="json")
            page_rows, total = self.parse_history_response(identity.code, text)
            if not page_rows:
                break
            for point in page_rows:
                previous = received.get(point.nav_date)
                if previous and previous != point:
                    raise ParseError(f"duplicate conflicting NAV date {point.nav_date} for {identity.code}")
                received[point.nav_date] = point
            page += 1
        rows = [received[item] for item in sorted(received)]
        if not rows:
            raise SourceUnavailableError(f"Eastmoney returned no NAV records for {identity.code}")
        return rows, self._meta(final_url, rows[-1].nav_date.isoformat())

    def fetch_estimate(self, identity: FundIdentity) -> Estimate:
        url = EASTMONEY_ESTIMATE_URL.format(code=identity.code)
        text = self.client.get_text(url, referer="https://fund.eastmoney.com/", expected_content_type=None)
        match = re.search(r"jsonpgz\((.*)\);?", text, flags=re.S)
        if not match:
            raise ParseError("Eastmoney estimate wrapper is missing")
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise ParseError("Eastmoney estimate payload is not JSON") from exc
        growth = decimal_or_none(payload.get("gszzl"))
        return Estimate(
            estimated_nav_date=str(payload.get("jzrq") or "") or None,
            estimated_unit_nav=decimal_or_none(payload.get("gsz")),
            estimated_return=float(growth / Decimal("100")) if growth is not None else None,
            estimate_generated_at=str(payload.get("gztime") or "") or None,
            estimate_model_version="third-party-estimate-v1",
            estimate_confidence="LOW",
            estimate_error_band=None,
            source=self._meta(url, str(payload.get("jzrq") or "") or None, estimate=True),
        )


def _status(value: Any) -> SubscriptionStatus:
    text = str(value or "UNKNOWN").upper()
    try:
        return SubscriptionStatus(text)
    except ValueError:
        return SubscriptionStatus.UNKNOWN


def resolve_subscription(identity: FundIdentity, config: dict[str, Any], report_date: dt.date) -> Subscription:
    """Resolve a configured official-announcement state machine.

    The repository ships with no fabricated announcement limits.  When a user
    provides verified announcement records, the latest active matching record is
    selected by effective date; otherwise every monetary field stays null.
    """
    records = []
    for item in config.get("subscription_announcements", []):
        if str(item.get("fund_code") or item.get("code") or "") != identity.code:
            continue
        if item.get("share_class") and item.get("share_class") != identity.share_class:
            continue
        if item.get("currency") and item.get("currency") != identity.currency:
            continue
        effective = str(item.get("effective_date") or "")
        expiry = str(item.get("expiry_date") or "")
        if effective and effective > report_date.isoformat():
            continue
        if expiry and expiry < report_date.isoformat():
            continue
        records.append(item)
    latest = (
        sorted(records, key=lambda item: str(item.get("effective_date") or ""))[-1]
        if records
        else None
    )
    manual = (config.get("manual_alipay") or {}).get(identity.code, {})
    verified_limit = parse_amount(manual.get("alipay_verified_limit"))
    source = SourceMetadata(
        source_name="基金公告配置" if records else "未配置的基金公告/支付宝账户数据",
        source_type="official_announcement" if records else "not_available",
        source_level=1 if records else 0,
        source_url=(latest.get("source_url") if latest else None),
        fetched_at=now_iso(),
        effective_date=(latest.get("effective_date") if latest else None),
        data_date=report_date.isoformat(),
        is_official=bool(records),
        is_fallback=False,
        freshness_status="NORMAL" if records else "FETCH_FAILED",
        parser_version="announcement-state-machine-v1",
        health=SourceHealth.HEALTHY.value if records else SourceHealth.DEGRADED.value,
    )
    if records:
        assert latest is not None
        status = _status(latest.get("status"))
        limit = parse_amount(latest.get("official_account_limit"))
        if status in {SubscriptionStatus.PAUSED, SubscriptionStatus.CLOSED} and limit is None:
            limit = Decimal("0")
        return Subscription(
            official_account_limit=limit,
            public_channel_reference_limit=parse_amount(latest.get("public_channel_reference_limit")),
            alipay_verified_limit=verified_limit,
            user_planned_amount=parse_amount(manual.get("user_planned_amount")),
            actual_order_amount=parse_amount(manual.get("actual_order_amount")),
            remaining_planned_amount=None,
            status=status,
            announcement_date=latest.get("announcement_date"),
            effective_date=latest.get("effective_date"),
            expiry_date=latest.get("expiry_date"),
            share_class=latest.get("share_class") or identity.share_class,
            business_scope=latest.get("business_scope"),
            source=source,
            alipay_verification_status="VERIFIED_MANUAL" if verified_limit is not None else "NOT_VERIFIED",
        )
    planned = parse_amount(manual.get("user_planned_amount"))
    actual = parse_amount(manual.get("actual_order_amount"))
    remaining = planned - actual if planned is not None and actual is not None else planned
    return Subscription(
        official_account_limit=None,
        public_channel_reference_limit=None,
        alipay_verified_limit=verified_limit,
        user_planned_amount=planned,
        actual_order_amount=actual,
        remaining_planned_amount=remaining,
        status=SubscriptionStatus.UNKNOWN,
        announcement_date=None,
        effective_date=None,
        expiry_date=None,
        share_class=identity.share_class,
        business_scope=None,
        source=source,
        alipay_verification_status="VERIFIED_MANUAL" if verified_limit is not None else "MANUAL_REQUIRED",
    )

