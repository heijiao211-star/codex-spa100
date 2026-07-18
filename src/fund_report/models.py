from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any


class SubscriptionStatus(str, Enum):
    OPEN = "OPEN"
    LIMITED = "LIMITED"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"
    FETCH_FAILED = "FETCH_FAILED"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"


class FreshnessStatus(str, Enum):
    NORMAL = "NORMAL"
    NORMAL_DELAYED = "NORMAL_DELAYED"
    POSSIBLY_STALE = "POSSIBLY_STALE"
    STALE = "STALE"
    FETCH_FAILED = "FETCH_FAILED"


class SourceHealth(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    SCHEMA_CHANGED = "SCHEMA_CHANGED"


@dataclass(frozen=True)
class SourceMetadata:
    source_name: str
    source_type: str
    source_level: int
    source_url: str | None
    fetched_at: str
    published_at: str | None = None
    effective_date: str | None = None
    data_date: str | None = None
    is_official: bool = False
    is_estimate: bool = False
    is_fallback: bool = False
    freshness_status: str = FreshnessStatus.NORMAL.value
    parser_version: str = "1"
    health: str = SourceHealth.HEALTHY.value

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class FundIdentity:
    code: str
    official_name: str
    display_name: str
    manager: str | None
    share_class: str | None
    currency: str
    fund_type: str
    target_index: str | None
    target_etf: str | None
    official_benchmark: str | None
    official_product_url: str | None
    official_announcement_url: str | None
    platform: str
    invested: bool
    enabled: bool
    reference_fund: bool = False
    reference_only: bool = False

    @classmethod
    def from_mapping(cls, item: dict[str, Any]) -> FundIdentity:
        code = str(item.get("code", "")).strip()
        if not code.isdigit() or len(code) != 6:
            raise ValueError(f"基金代码必须是 6 位数字: {code!r}")
        return cls(
            code=code,
            official_name=str(item.get("official_name") or item.get("label") or code),
            display_name=str(item.get("display_name") or item.get("label") or code),
            manager=item.get("manager"),
            share_class=item.get("share_class"),
            currency=str(item.get("currency") or "CNY"),
            fund_type=str(item.get("fund_type") or "QDII 公募基金"),
            target_index=item.get("target_index"),
            target_etf=item.get("target_etf"),
            official_benchmark=item.get("official_benchmark"),
            official_product_url=item.get("official_product_url"),
            official_announcement_url=item.get("official_announcement_url"),
            platform=str(item.get("platform") or "支付宝（购买渠道）"),
            invested=bool(item.get("invested", False)),
            enabled=bool(item.get("enabled", True)),
            reference_fund=bool(item.get("reference_fund", False)),
            reference_only=bool(item.get("reference_only", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class NavPoint:
    fund_code: str
    nav_date: date
    unit_nav: Decimal
    accumulated_nav: Decimal | None
    official_daily_return: float | None
    subscription_status: str | None = None

    @property
    def adjusted_nav(self) -> Decimal | None:
        """Accumulated NAV is the only default used for long-period performance."""
        return self.accumulated_nav

    def to_dict(self) -> dict[str, Any]:
        return {
            "fund_code": self.fund_code,
            "nav_date": self.nav_date.isoformat(),
            "unit_nav": str(self.unit_nav),
            "accumulated_nav": str(self.accumulated_nav) if self.accumulated_nav is not None else None,
            "official_daily_return": self.official_daily_return,
            "subscription_status": self.subscription_status,
        }


@dataclass(frozen=True)
class Estimate:
    estimated_nav_date: str | None
    estimated_unit_nav: Decimal | None
    estimated_return: float | None
    estimate_generated_at: str | None
    estimate_model_version: str
    estimate_confidence: str
    estimate_error_band: float | None
    source: SourceMetadata

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_nav_date": self.estimated_nav_date,
            "estimated_nav": str(self.estimated_unit_nav) if self.estimated_unit_nav is not None else None,
            "estimated_return": self.estimated_return,
            "estimate_generated_at": self.estimate_generated_at,
            "estimate_model_version": self.estimate_model_version,
            "confidence": self.estimate_confidence,
            "error_band": self.estimate_error_band,
            "is_official": False,
            "source": self.source.to_dict(),
        }


@dataclass(frozen=True)
class Subscription:
    official_account_limit: Decimal | None
    public_channel_reference_limit: Decimal | None
    alipay_verified_limit: Decimal | None
    user_planned_amount: Decimal | None
    actual_order_amount: Decimal | None
    remaining_planned_amount: Decimal | None
    status: SubscriptionStatus
    announcement_date: str | None
    effective_date: str | None
    expiry_date: str | None
    share_class: str | None
    business_scope: str | None
    source: SourceMetadata
    alipay_verification_status: str

    def to_dict(self) -> dict[str, Any]:
        def amount(value: Decimal | None) -> str | None:
            return str(value) if value is not None else None

        return {
            "official_account_limit": amount(self.official_account_limit),
            "public_channel_reference_limit": amount(self.public_channel_reference_limit),
            "alipay_verified_limit": amount(self.alipay_verified_limit),
            "user_planned_amount": amount(self.user_planned_amount),
            "actual_order_amount": amount(self.actual_order_amount),
            "remaining_planned_amount": amount(self.remaining_planned_amount),
            "status": self.status.value,
            "announcement_date": self.announcement_date,
            "effective_date": self.effective_date,
            "expiry_date": self.expiry_date,
            "share_class": self.share_class,
            "business_scope": self.business_scope,
            "source": self.source.to_dict(),
            "alipay_verification_status": self.alipay_verification_status,
        }

