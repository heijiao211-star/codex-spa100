from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import FundIdentity


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"配置必须是 JSON 对象: {path}")
    return value


def load_config(base_dir: Path) -> dict[str, Any]:
    config_path = base_dir / "config.local.json"
    if not config_path.exists():
        config_path = base_dir / "config.json"
    config = load_json(config_path)
    funds_file = config.get("funds_file")
    if funds_file:
        funds_path = (base_dir / str(funds_file)).resolve()
        funds_data = load_json(funds_path)
        funds = funds_data.get("funds", [])
    else:
        # Legacy inline funds remain readable but are normalized immediately.
        funds = config.get("funds", [])
    identities = [FundIdentity.from_mapping(item) for item in funds]
    config["fund_identities"] = [item for item in identities if item.enabled and not item.reference_only]
    config["references"] = [item for item in identities if item.enabled and item.reference_only]
    config.setdefault("history_days", 1900)
    config.setdefault("report_timezone", "Asia/Shanghai")
    config.setdefault("max_nav_lag_days", 6)
    config.setdefault("ai_news", [])
    config.setdefault("subscription_announcements", [])
    config.setdefault("manual_alipay", {})
    config["_path"] = str(config_path)
    return config

