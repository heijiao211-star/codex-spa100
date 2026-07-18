"""Compatibility note for the retired unverified AI-news fetcher.

Market commentary is now rendered only from explicitly configured, attributable
items with title, publication time, event date and original source URL.  This
avoids presenting search snippets or model speculation as verified facts.
"""

from __future__ import annotations

DISCLAIMER = "本段为信息整理和市场解释，不构成买入、卖出或暂停定投建议。"


def build_market_briefing(_items, config):
    return {"items": config.get("ai_news", []), "disclaimer": DISCLAIMER}


def render_market_briefing_html(_briefing, compact=False):
    return ""

