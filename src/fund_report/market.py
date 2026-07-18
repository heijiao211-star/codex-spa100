from __future__ import annotations

from typing import Any


def reference_cny_return(usd_asset_return: float | None, usd_cny_return: float | None) -> float | None:
    """Combine USD asset and USD/CNY moves for a clearly labelled market reference.

    A positive USD/CNY return means USD appreciated against CNY. This is not a
    fund-NAV estimator: valuation FX, cash, fees and tracking difference can
    make actual QDII returns materially different.
    """
    if usd_asset_return is None or usd_cny_return is None:
        return None
    return (1 + usd_asset_return) * (1 + usd_cny_return) - 1


def market_reference(config: dict[str, Any]) -> dict[str, Any]:
    value = config.get("market_reference") or {}
    fx = value.get("usd_cny") or {}
    asset = value.get("usd_asset") or {}
    asset_return = asset.get("return")
    fx_return = fx.get("return")
    if not isinstance(asset_return, int | float):
        asset_return = None
    if not isinstance(fx_return, int | float):
        fx_return = None
    return {
        "usd_asset_return": asset_return,
        "usd_asset_session_date": asset.get("session_date"),
        "usd_asset_source": asset.get("source"),
        "usd_cny_return": fx_return,
        "fx_date": fx.get("data_date"),
        "fx_source": fx.get("source"),
        "cny_reference_return": reference_cny_return(asset_return, fx_return),
        "estimate_target_nav_date": value.get("estimate_target_nav_date"),
        "is_official": False,
        "notice": "仅为市场参考计算，不等于基金正式净值。",
    }

