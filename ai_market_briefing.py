"""Market context and guarded DeepSeek commentary for the daily report."""

import datetime as dt
import html
import json
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


DEEPSEEK_CHAT_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-v4-flash"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search?{query}"

MARKET_SYMBOLS = (
    ("QQQ", "纳指100 ETF（QQQ）", "ETF 代理"),
    ("^TNX", "美国10年期国债收益率", "利率"),
    ("CNY=X", "美元兑人民币", "汇率"),
)


def _pct_change(first, last):
    if first in (None, 0) or last is None:
        return None
    return (last / first - 1) * 100


def _fmt_pct(value):
    if value is None:
        return "--"
    return f"{value:+.2f}%"


def _http_get_json(url, timeout=18):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 CodexFundReport/4.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_get_text(url, timeout=18):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 CodexFundReport/4.0",
            "Accept": "application/rss+xml,application/xml,text/xml,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _post_deepseek(payload, api_key, timeout=28):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        DEEPSEEK_CHAT_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "CodexFundReport/4.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_market_symbol(symbol, label, category):
    try:
        params = urllib.parse.urlencode({"range": "1mo", "interval": "1d", "events": "history"})
        payload = _http_get_json(YAHOO_CHART_URL.format(symbol=urllib.parse.quote(symbol, safe="")) + "?" + params)
        result = (payload.get("chart", {}).get("result") or [None])[0]
        if not result:
            return None
        closes = [value for value in result.get("indicators", {}).get("quote", [{}])[0].get("close", []) if value is not None]
        if len(closes) < 2:
            return None
        latest = closes[-1]
        return {
            "label": label,
            "category": category,
            "latest": round(latest, 4),
            "one_day": round(_pct_change(closes[-2], latest), 2),
            "five_day": round(_pct_change(closes[max(0, len(closes) - 6)], latest), 2),
            "source": "Yahoo Finance",
        }
    except Exception:
        return None


def fetch_market_snapshot():
    return [item for item in (_fetch_market_symbol(*symbol) for symbol in MARKET_SYMBOLS) if item]


def fetch_news(limit=5):
    query = urllib.parse.urlencode(
        {
            "q": "(Nasdaq 100 OR US technology stocks OR Federal Reserve) when:1d",
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
        }
    )
    try:
        root = ET.fromstring(_http_get_text(GOOGLE_NEWS_RSS_URL.format(query=query)))
    except Exception:
        return []

    news = []
    for item in root.findall("./channel/item")[:limit]:
        source = item.find("source")
        link = (item.findtext("link") or "").strip()
        title = (item.findtext("title") or "").strip()
        published = (item.findtext("pubDate") or "").strip()
        if not title:
            continue
        news.append(
            {
                "title": title,
                "source": (source.text or "新闻聚合").strip() if source is not None else "新闻聚合",
                "published": published,
                "url": link,
            }
        )
    return news


def fund_snapshot(items):
    result = []
    for item in items:
        summary = item["summary"]
        result.append(
            {
                "name": item["fund"].get("label") or item["fund"]["code"],
                "code": str(item["fund"]["code"]),
                "latest_nav_date": summary.get("latest_date"),
                "daily_change_pct": summary.get("daily_change"),
                "daily_change_label": summary.get("daily_change_label"),
                "return_7d_pct": summary.get("return_7d"),
                "return_30d_pct": summary.get("return_30d"),
                "return_1y_pct": summary.get("return_1y"),
                "drawdown_1y_pct": summary.get("drawdown_1y"),
                "drawdown_3y_pct": summary.get("drawdown_3y"),
                "volatility_1y_pct": summary.get("vol_1y"),
                "above_ma20": bool(summary.get("ma20") and summary.get("latest_trend_nav") and summary["latest_trend_nav"] >= summary["ma20"]),
                "above_ma60": bool(summary.get("ma60") and summary.get("latest_trend_nav") and summary["latest_trend_nav"] >= summary["ma60"]),
            }
        )
    return result


def _rule_based_brief(funds, market, reason=None):
    fund = funds[0] if funds else {}
    daily = fund.get("daily_change_pct")
    r7 = fund.get("return_7d_pct")
    r30 = fund.get("return_30d_pct")
    qqq = next((item for item in market if item["label"].startswith("纳指100")), None)

    if daily is not None and daily <= -1.5:
        headline = "短线波动放大，先看数据而非情绪"
    elif r30 is not None and r30 >= 6:
        headline = "近月表现偏强，估值与事件风险仍需同步观察"
    elif r7 is not None and r7 <= -3:
        headline = "近周回撤扩大，市场正在重新定价风险"
    else:
        headline = "市场暂无极端信号，聚焦基本面与长期节奏"

    overview_parts = []
    if daily is not None:
        overview_parts.append(f"基金{fund.get('daily_change_label') or '当日涨跌'}为{_fmt_pct(daily)}")
    if r7 is not None:
        overview_parts.append(f"近7个净值日{_fmt_pct(r7)}")
    if qqq and qqq.get("one_day") is not None:
        overview_parts.append(f"QQQ最近一个交易日{_fmt_pct(qqq['one_day'])}")
    overview = "；".join(overview_parts) or "基金与外部市场数据暂不完整，先以净值口径为准。"
    return {
        "headline": headline,
        "overview": overview + "。",
        "tailwinds": [],
        "risks": [],
        "takeaway": "未给出机械买卖提示；后续重点关注持续的趋势和重要事件。",
        "sources": [{"name": item["source"], "url": ""} for item in market[:2]],
        "mode": "规则化摘要",
        "fallback_reason": reason,
    }


def _clean_text(value, limit):
    text = " ".join(str(value or "").split())
    return text[:limit]


def _clean_points(value, known_sources):
    points = []
    if not isinstance(value, list):
        return points
    for point in value[:2]:
        if not isinstance(point, dict):
            continue
        text = _clean_text(point.get("text"), 90)
        source = _clean_text(point.get("source"), 60)
        if text:
            points.append(
                {
                    "text": text,
                    "source": source if source in known_sources else "",
                    "published": _clean_text(point.get("published"), 48),
                }
            )
    return points


def _parse_ai_brief(raw_content, fallback, news):
    content = raw_content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    data = json.loads(content)
    known_sources = {item["source"] for item in news} | {
        item.get("name") or item.get("source") for item in fallback["sources"]
    }
    headline = _clean_text(data.get("headline"), 45)
    overview = _clean_text(data.get("overview"), 150)
    takeaway = _clean_text(data.get("takeaway"), 80)
    if not headline or not overview or not takeaway:
        raise ValueError("AI response missing required briefing fields")
    return {
        "headline": headline,
        "overview": overview,
        "tailwinds": _clean_points(data.get("tailwinds"), known_sources),
        "risks": _clean_points(data.get("risks"), known_sources),
        "takeaway": takeaway,
        "sources": fallback["sources"],
        "mode": "AI 市场解读",
        "fallback_reason": None,
    }


def build_market_briefing(items, config):
    settings = config.get("ai_briefing") or {}
    funds = fund_snapshot(items)
    market = fetch_market_snapshot()
    news = fetch_news(limit=max(1, min(int(settings.get("max_news", 5)), 8)))
    fallback = _rule_based_brief(funds, market)
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if settings.get("enabled", True) is False or not api_key:
        return fallback

    payload = {
        "model": settings.get("model") or DEFAULT_MODEL,
        "thinking": {"type": "disabled"},
        "temperature": 0.2,
        "max_tokens": 800,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是面向长期定投者的纳斯达克100 QDII 市场简报编辑。"
                    "只能依据用户提供的数据和新闻标题写中文摘要，绝不能编造事实、数字、新闻或来源。"
                    "不预测涨跌，不使用买入、卖出、加仓、减仓、等待确认等指令性表述。"
                    "新闻标题只是线索，若无法直接支持结论，请不要引用。"
                    "必须只返回一个合法 JSON 对象，不要 Markdown。"
                    "JSON 格式：{headline:string,overview:string,tailwinds:[{text:string,source:string,published:string}],"
                    "risks:[{text:string,source:string,published:string}],takeaway:string}。"
                    "headline不超过45字；overview不超过150字；tailwinds和risks各不超过2项；"
                    "takeaway不超过80字。source只能使用给定新闻source或Yahoo Finance。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "report_time": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
                        "fund_snapshot": funds,
                        "market_snapshot": market,
                        "news_leads": news,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }
    try:
        timeout = max(10, min(int(settings.get("timeout_seconds", 28)), 50))
        last_error = None
        # JSON Output can occasionally be empty; one retry avoids losing a useful
        # briefing while keeping the scheduled job bounded and inexpensive.
        for _ in range(2):
            response = _post_deepseek(payload, api_key, timeout=timeout)
            content = response["choices"][0]["message"].get("content") or ""
            try:
                return _parse_ai_brief(content, fallback, news)
            except Exception as exc:
                last_error = exc
        raise last_error or RuntimeError("AI response was empty")
    except Exception:
        fallback["fallback_reason"] = "AI 服务暂不可用，已自动使用规则化摘要。"
        return fallback


def render_market_briefing_html(briefing, compact=False):
    def points(title, entries, css_class):
        if not entries:
            return ""
        rows = []
        for entry in entries:
            source_text = " · ".join(part for part in (entry.get("source"), entry.get("published")) if part)
            source = f" <small>来源：{html.escape(source_text)}</small>" if source_text else ""
            rows.append(f"<li>{html.escape(entry['text'])}{source}</li>")
        return f"<div class='{css_class}'><b>{title}</b><ul>{''.join(rows)}</ul></div>"

    sections = [
        "<section class='market-briefing'>",
        f"<div class='briefing-kicker'>{html.escape(briefing.get('mode') or '市场观察')}</div>",
        f"<h2>{html.escape(briefing.get('headline') or '市场观察')}</h2>",
        f"<p>{html.escape(briefing.get('overview') or '')}</p>",
        points("积极线索", briefing.get("tailwinds") or [], "briefing-tailwinds"),
        points("风险与变量", briefing.get("risks") or [], "briefing-risks"),
        f"<div class='briefing-takeaway'><b>定投视角</b><span>{html.escape(briefing.get('takeaway') or '')}</span></div>",
    ]
    if briefing.get("fallback_reason"):
        sections.append(f"<small class='briefing-fallback'>{html.escape(briefing['fallback_reason'])}</small>")
    if not compact:
        sections.append("<small class='briefing-disclaimer'>市场信息仅供参考，不构成个性化投资建议。</small>")
    sections.append("</section>")
    return "".join(sections)
