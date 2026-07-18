from __future__ import annotations

import calendar
import datetime as dt
import math
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from .errors import ParseError
from .models import NavPoint


def _subtract_months(value: dt.date, months: int) -> dt.date:
    month = value.month - months
    year = value.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return dt.date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _subtract_years(value: dt.date, years: int) -> dt.date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:  # leap day
        return value.replace(year=value.year - years, day=28)


def validate_nav_history(rows: Iterable[NavPoint], today: dt.date) -> list[NavPoint]:
    ordered = sorted(rows, key=lambda point: point.nav_date)
    if not ordered:
        raise ParseError("NAV history is empty")
    seen: set[dt.date] = set()
    for point in ordered:
        if point.nav_date in seen:
            raise ParseError(f"duplicate NAV date: {point.nav_date}")
        seen.add(point.nav_date)
        if point.unit_nav <= 0:
            raise ParseError(f"non-positive NAV on {point.nav_date}")
        if point.nav_date > today:
            raise ParseError(f"future NAV date: {point.nav_date}")
    return ordered


@dataclass(frozen=True)
class Window:
    name: str
    target_date: dt.date
    start: NavPoint | None
    end: NavPoint
    points: tuple[NavPoint, ...]
    complete: bool


def window_for(rows: list[NavPoint], name: str, *, months: int | None = None, years: int | None = None) -> Window:
    if months is None and years is None:
        raise ValueError("months or years is required")
    latest = rows[-1]
    target = _subtract_months(latest.nav_date, months) if months is not None else _subtract_years(latest.nav_date, years or 0)
    candidates = [point for point in rows if point.nav_date <= target]
    start = candidates[-1] if candidates else None
    points = tuple(point for point in rows if start is not None and point.nav_date >= start.nav_date)
    return Window(name=name, target_date=target, start=start, end=latest, points=points, complete=start is not None)


def adjusted_return(window: Window) -> float | None:
    if not window.complete or window.start is None:
        return None
    start_nav = window.start.adjusted_nav
    end_nav = window.end.adjusted_nav
    if start_nav is None or end_nav is None or start_nav <= 0:
        return None
    return float(end_nav / start_nav - Decimal("1"))


def seven_nav_day_return(rows: list[NavPoint]) -> float | None:
    # Seven return observations require eight confirmed NAV points.
    if len(rows) < 8:
        return None
    start, end = rows[-8], rows[-1]
    if start.adjusted_nav is None or end.adjusted_nav is None or start.adjusted_nav <= 0:
        return None
    return float(end.adjusted_nav / start.adjusted_nav - Decimal("1"))


def daily_returns(rows: list[NavPoint]) -> list[float]:
    result: list[float] = []
    previous: NavPoint | None = None
    for point in rows:
        value = point.official_daily_return
        if value is None and previous and previous.adjusted_nav and point.adjusted_nav:
            value = float(point.adjusted_nav / previous.adjusted_nav - Decimal("1"))
        if value is not None:
            result.append(value)
        previous = point
    return result


def annualized_volatility(rows: list[NavPoint]) -> float | None:
    values = daily_returns(rows)
    if len(values) < 20:
        return None
    return statistics.stdev(values) * math.sqrt(252)


def max_drawdown(rows: list[NavPoint]) -> dict[str, object] | None:
    usable = [point for point in rows if point.adjusted_nav is not None]
    if len(usable) < 2:
        return None
    peak = usable[0]
    trough = usable[0]
    worst = 0.0
    recovery: dt.date | None = None
    for point in usable:
        if point.adjusted_nav is not None and peak.adjusted_nav is not None and point.adjusted_nav > peak.adjusted_nav:
            peak = point
        drawdown = float(point.adjusted_nav / peak.adjusted_nav - Decimal("1"))  # type: ignore[operator]
        if drawdown < worst:
            worst = drawdown
            trough = point
            recovery = None
        if (
            trough.nav_date <= point.nav_date
            and point.adjusted_nav is not None
            and peak.adjusted_nav is not None
            and point.adjusted_nav >= peak.adjusted_nav
        ):
            recovery = point.nav_date
    return {
        "value": worst,
        "peak_date": peak.nav_date.isoformat(),
        "trough_date": trough.nav_date.isoformat(),
        "recovery_date": recovery.isoformat() if recovery else None,
        "recovered": recovery is not None,
        "recovery_days": (recovery - trough.nav_date).days if recovery else None,
        "observation_count": len(usable),
        "start_date": usable[0].nav_date.isoformat(),
        "end_date": usable[-1].nav_date.isoformat(),
    }


def cagr(window: Window) -> float | None:
    result = adjusted_return(window)
    if result is None or window.start is None:
        return None
    days = (window.end.nav_date - window.start.nav_date).days
    if days <= 0:
        return None
    return (1 + result) ** (365.2425 / days) - 1


def performance_summary(rows: list[NavPoint]) -> dict[str, object]:
    windows = {
        "1m": window_for(rows, "近1个月", months=1),
        "3m": window_for(rows, "近3个月", months=3),
        "6m": window_for(rows, "近6个月", months=6),
        "1y": window_for(rows, "近1年", years=1),
        "3y": window_for(rows, "近3年", years=3),
        "5y": window_for(rows, "近5年", years=5),
    }
    latest = rows[-1]
    previous_year = [point for point in rows if point.nav_date.year < latest.nav_date.year]
    ytd_start = previous_year[-1] if previous_year else None
    ytd = None
    if ytd_start and ytd_start.adjusted_nav and latest.adjusted_nav:
        ytd = float(latest.adjusted_nav / ytd_start.adjusted_nav - Decimal("1"))
    return {
        "latest_nav_date": latest.nav_date.isoformat(),
        "latest_official_daily_return": latest.official_daily_return,
        "return_7_nav_days": seven_nav_day_return(rows),
        "ytd": ytd,
        "periods": {
            name: {
                "return": adjusted_return(window),
                "cagr": cagr(window) if name in {"3y", "5y"} else None,
                "target_date": window.target_date.isoformat(),
                "start_date": window.start.nav_date.isoformat() if window.start else None,
                "end_date": window.end.nav_date.isoformat(),
                "complete": window.complete,
                "observation_count": len(window.points),
            }
            for name, window in windows.items()
        },
        "risk": {
            "1y_max_drawdown": max_drawdown(list(windows["1y"].points)) if windows["1y"].complete else None,
            "3y_max_drawdown": max_drawdown(list(windows["3y"].points)) if windows["3y"].complete else None,
            "since_inception_max_drawdown": max_drawdown(rows),
            "1y_annualized_volatility": annualized_volatility(list(windows["1y"].points)) if windows["1y"].complete else None,
            "volatility_formula": "样本标准差(ddof=1) × sqrt(252)，使用正式日收益率",
        },
    }

