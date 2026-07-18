from __future__ import annotations

import html
from decimal import Decimal
from typing import Any

PUBLIC_NOTICE = "公开基金数据，适用于支付宝购买的同代码基金；支付宝渠道限额、费率和实际持仓以支付宝页面为准。"
INVESTMENT_NOTICE = "本报告仅作公开信息整理与数据质量提示，不构成买入、卖出或暂停定投建议。"


def pct(value: float | None, *, signed: bool = True) -> str:
    if value is None:
        return "数据不足"
    prefix = "+" if signed and value > 0 else ""
    return f"{prefix}{value * 100:.2f}%"


def number(value: str | Decimal | None, digits: int = 4) -> str:
    if value is None:
        return "—"
    try:
        return f"{Decimal(str(value)):.{digits}f}"
    except Exception:
        return str(value)


def amount(value: str | None, currency: str = "CNY") -> str:
    if value is None:
        return "未提供"
    return f"{value} {currency}"


def tone(value: float | None) -> tuple[str, str]:
    if value is None:
        return "#667085", "数据不足"
    if value > 0:
        return "#c62828", "上涨"
    if value < 0:
        return "#138a36", "下跌"
    return "#667085", "持平"


def source_line(source: dict[str, Any] | None) -> str:
    if not source:
        return "来源未提供"
    title = html.escape(str(source.get("source_name") or "未知来源"))
    date = html.escape(str(source.get("data_date") or "日期未提供"))
    fetched = html.escape(str(source.get("fetched_at") or ""))
    url = source.get("source_url")
    link = f' · <a href="{html.escape(str(url), quote=True)}">查看来源</a>' if url else ""
    fallback = " · 官方来源获取失败，当前使用第三方备用数据。" if source.get("is_fallback") else ""
    return f"来源：{title} · 数据日期：{date} · 核验：{fetched}{link}{fallback}"


def card(title: str, body: str, note: str = "") -> str:
    return f"<section class='card'><h2>{html.escape(title)}</h2>{body}<p class='source'>{note}</p></section>"


def sparkline(fund: dict[str, Any]) -> str:
    chart = fund.get("chart")
    if not chart or not chart.get("points"):
        return "<p class='muted'>近1年正式净值数据不足，不绘制图表。</p>"
    points = chart["points"]
    values = [float(item["value"]) for item in points]
    low, high = min(values), max(values)
    scale = high - low or 1.0
    width, height, pad = 680, 190, 18
    line = []
    for index, value in enumerate(values):
        x = pad + index * (width - pad * 2) / max(1, len(values) - 1)
        y = height - pad - (value - low) / scale * (height - pad * 2)
        line.append(f"{x:.1f},{y:.1f}")
    meta = (
        f"基金 {html.escape(fund['identity']['code'])} · 计算区间 {html.escape(chart['start_date'])} 至 {html.escape(chart['end_date'])}"
        f" · {chart['point_count']} 个数据点 · {html.escape(chart['source_name'])} · 非官方数据"
    )
    return (
        f"<div class='chart-meta'>{meta}</div>"
        f"<svg class='chart' viewBox='0 0 {width} {height}' role='img' aria-label='近一年净值趋势'>"
        "<line x1='18' y1='172' x2='662' y2='172' stroke='#d0d5dd'/>"
        f"<polyline fill='none' stroke='#2563eb' stroke-width='3' points='{' '.join(line)}'/></svg>"
    )


def fund_card(fund: dict[str, Any], market: dict[str, Any]) -> str:
    identity = fund["identity"]
    nav = fund["official_nav"]
    performance = fund["performance"]
    subscription = fund["subscription"]
    estimate = fund["estimate"]
    color, word = tone(nav.get("daily_return"))
    periods = performance.get("periods", {})
    p1y = periods.get("1y", {})
    p3y = periods.get("3y", {})
    nav_body = f"""
      <div class='identity'><span>{html.escape(identity["code"])}</span><b>{html.escape(identity["display_name"])}</b></div>
      <div class='nav-grid'>
        <div><small>最新已确认净值</small><strong>{number(nav.get("unit_nav"))}</strong></div>
        <div><small>正式净值日期</small><strong class='nowrap'>{html.escape(str(nav.get("nav_date") or "—"))}</strong></div>
        <div><small>正式日涨跌</small><strong style='color:{color}'>{word} {pct(nav.get("daily_return"))}</strong></div>
        <div><small>净值状态</small><strong>{html.escape(str(nav.get("freshness_status") or "FETCH_FAILED"))}</strong></div>
      </div>
      <p class='notice'>正式净值优先展示。{PUBLIC_NOTICE}</p>
    """
    source_note = source_line(nav.get("source"))
    estimate_body = "<p>本日不提供估算。</p>"
    if estimate.get("estimated_return") is not None:
        estimate_color, estimate_word = tone(estimate.get("estimated_return"))
        estimate_body = f"""
          <div class='nav-grid'>
            <div><small>估算目标净值日</small><strong class='nowrap'>{html.escape(str(estimate.get("target_nav_date") or "—"))}</strong></div>
            <div><small>估算净值</small><strong>{number(estimate.get("estimated_nav"))}</strong></div>
            <div><small>估算涨跌</small><strong style='color:{estimate_color}'>{estimate_word} {pct(estimate.get("estimated_return"))}</strong></div>
            <div><small>模型可信度</small><strong>{html.escape(str(estimate.get("confidence") or "LOW"))}</strong></div>
          </div>
          <p class='notice'>非官方数据；最终以基金公司及支付宝更新后的正式净值为准。</p>
        """
    performance_body = f"""
      <div class='metric-grid'>
        <div><small>最近7个正式日收益观察值</small><b>{pct(performance.get("return_7_nav_days"))}</b></div>
        <div><small>今年以来</small><b>{pct(performance.get("ytd"))}</b></div>
        <div><small>近1个月</small><b>{pct((periods.get("1m") or {}).get("return"))}</b></div>
        <div><small>近3个月</small><b>{pct((periods.get("3m") or {}).get("return"))}</b></div>
        <div><small>近1年</small><b>{pct(p1y.get("return"))}</b></div>
        <div><small>近3年累计收益</small><b>{pct(p3y.get("return"))}</b></div>
        <div><small>近3年年化收益（CAGR）</small><b>{pct(p3y.get("cagr"))}</b></div>
        <div><small>近5年累计收益</small><b>{pct((periods.get("5y") or {}).get("return"))}</b></div>
      </div>
      <p class='muted'>若覆盖不足完整区间，指标会显示“数据不足”，不会用最早记录冒充近1年或近3年。</p>
      <h3>近1年正式净值趋势</h3>{sparkline(fund)}
    """
    risk = performance.get("risk", {})
    draw = risk.get("1y_max_drawdown") or {}
    risk_body = f"""
      <div class='metric-grid'>
        <div><small>近1年最大回撤</small><b>{pct(draw.get("value"), signed=False) if draw else "数据不足"}</b></div>
        <div><small>峰值 → 低点</small><b class='nowrap'>{html.escape(str(draw.get("peak_date") or "—"))} → {html.escape(str(draw.get("trough_date") or "—"))}</b></div>
        <div><small>是否恢复 / 恢复日</small><b>{"已恢复" if draw.get("recovered") else "未恢复"} / {html.escape(str(draw.get("recovery_date") or "—"))}</b></div>
        <div><small>近1年年化波动率</small><b>{pct(risk.get("1y_annualized_volatility"), signed=False)}</b></div>
      </div>
      <p class='muted'>{html.escape(str(risk.get("volatility_formula") or ""))}</p>
    """
    subscription_body = f"""
      <div class='metric-grid'>
        <div><small>申购状态</small><b>{html.escape(subscription.get("status", "UNKNOWN"))}</b></div>
        <div><small>基金公司公告限额</small><b>{amount(subscription.get("official_account_limit"), identity.get("currency", "CNY"))}</b></div>
        <div><small>公开渠道参考限额</small><b>{amount(subscription.get("public_channel_reference_limit"), identity.get("currency", "CNY"))}</b></div>
        <div><small>支付宝限额核验状态</small><b>{html.escape(subscription.get("alipay_verification_status", "NOT_VERIFIED"))}</b></div>
        <div><small>我的计划申购金额</small><b>{amount(subscription.get("user_planned_amount"), identity.get("currency", "CNY"))}</b></div>
        <div><small>我的实际申购金额</small><b>{amount(subscription.get("actual_order_amount"), identity.get("currency", "CNY"))}</b></div>
      </div>
      <p class='muted'>公告日：{html.escape(str(subscription.get("announcement_date") or "未提供"))}；生效日：{html.escape(str(subscription.get("effective_date") or "未提供"))}；适用业务：{html.escape(str(subscription.get("business_scope") or "未提供"))}</p>
    """
    benchmark = fund.get("benchmark", {})
    benchmark_body = f"""
      <div class='metric-grid'>
        <div><small>官方业绩比较基准</small><b>{html.escape(str(benchmark.get("official_benchmark") or "未配置"))}</b></div>
        <div><small>目标ETF</small><b>{html.escape(str(benchmark.get("target_etf") or "未配置"))}</b></div>
        <div><small>目标指数</small><b>{html.escape(str(benchmark.get("target_index") or "未配置"))}</b></div>
      </div>
      <p class='muted'>NDX、XNDX、目标ETF、人民币参考基准和基金净值是不同对象；没有严格符合合同定义的序列时，本报告不会把参考曲线标为“官方基准”。</p>
      <div class='metric-grid'>
        <div><small>USD/CNY 参考变动</small><b>{pct(market.get('usd_cny_return'))}</b></div>
        <div><small>汇率数据日期</small><b>{html.escape(str(market.get('fx_date') or '未配置'))}</b></div>
        <div><small>美元资产参考变动</small><b>{pct(market.get('usd_asset_return'))}</b></div>
        <div><small>人民币市场参考计算</small><b>{pct(market.get('cny_reference_return'))}</b></div>
      </div>
      <p class='muted'>USD/CNY 上涨表示美元相对人民币升值。{html.escape(str(market.get('notice') or '未配置汇率参考数据。'))}</p>
    """
    return "".join(
        [
            card("最新已确认正式净值", nav_body, source_note),
            card("下一待公布净值估算", estimate_body, source_line(estimate.get("source"))),
            card("阶段收益与风险", performance_body),
            card("风险口径", risk_body),
            card("申购状态和额度", subscription_body, source_line(subscription.get("source"))),
            card("基准、汇率及市场解释", benchmark_body),
        ]
    )


def market_briefing(news: list[dict[str, Any]]) -> str:
    valid = [item for item in news if all(item.get(field) for field in ("title", "published_at", "source_url", "event_date"))]
    if not valid:
        return card("市场信息整理", f"<p>今日无足够可靠的新事件，暂不生成市场归因。</p><p class='notice'>{INVESTMENT_NOTICE}</p>")
    rows = "".join(
        f"<li><a href='{html.escape(str(item['source_url']), quote=True)}'>{html.escape(str(item['title']))}</a>"
        f"（发布：{html.escape(str(item['published_at']))}；事件：{html.escape(str(item['event_date']))}；"
        f"关联：{html.escape(str(item.get('nasdaq100_relevance') or '未量化'))}；置信度：{html.escape(str(item.get('confidence') or 'LOW'))}）</li>"
        for item in valid
    )
    return card("市场信息整理", f"<ul>{rows}</ul><p class='notice'>{INVESTMENT_NOTICE}</p>")


def render_html(report: dict[str, Any]) -> str:
    status = report["report_status"]
    generated = report["report_generated_at"]
    market = report.get("market_reference") or {}
    funds = "".join(fund_card(fund, market) for fund in report["funds"])
    warnings = "".join(f"<li>{html.escape(str(item))}</li>" for item in report.get("warnings", [])) or "<li>无</li>"
    return f"""<!doctype html>
<html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>
<title>纳指基金日报</title><style>
body{{margin:0;background:#f4f7fb;color:#172033;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',Arial,sans-serif;line-height:1.55}}
.wrap{{max-width:780px;margin:auto;padding:14px 12px 30px}}.hero{{background:#12213d;color:#fff;padding:20px;border-radius:14px}}.hero h1{{font-size:24px;margin:0 0 6px}}.hero p{{margin:3px 0;color:#dbe7ff;font-size:13px}}
.card{{margin-top:14px;padding:16px;border-radius:12px;background:#fff;border:1px solid #e4e7ec;box-shadow:0 2px 10px #1018280a}}.card h2{{font-size:18px;margin:0 0 12px}}h3{{font-size:15px;margin:18px 0 8px}}
.identity{{display:grid;gap:3px;margin-bottom:13px}}.identity span{{color:#52627a;font-size:12px;font-weight:700}}.identity b{{font-size:18px}}.nav-grid,.metric-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}}.nav-grid div,.metric-grid div{{border-radius:9px;background:#f8fafc;padding:10px;min-width:0}}small{{display:block;color:#667085;font-size:12px}}strong,b{{display:block;overflow-wrap:anywhere}}.source,.muted{{color:#667085;font-size:12px}}.notice{{border-left:3px solid #2563eb;padding-left:9px;color:#475467;font-size:13px}}.nowrap{{white-space:nowrap;word-break:keep-all;overflow-wrap:normal}}.chart{{width:100%;height:auto;background:#fcfdff;border-radius:8px}}.chart-meta{{font-size:11px;color:#667085;white-space:nowrap;word-break:keep-all;overflow-x:auto;padding-bottom:6px}}a{{color:#175cd3}}
@media(min-width:650px){{.nav-grid{{grid-template-columns:repeat(4,minmax(0,1fr))}}.metric-grid{{grid-template-columns:repeat(4,minmax(0,1fr))}}}}
</style></head><body><main class='wrap'><section class='hero'><h1>纳指基金日报</h1><p>报告状态：{html.escape(status)} · 生成时间（北京时间）：{html.escape(generated)}</p><p>{PUBLIC_NOTICE}</p></section>
{market_briefing(report.get("market_news", []))}{funds}<section class='card'><h2>报告状态和数据新鲜度</h2><ul>{warnings}</ul><p class='notice'>{INVESTMENT_NOTICE}</p></section></main></body></html>"""


def render_pushplus_html(report: dict[str, Any]) -> str:
    """A bounded summary; full HTML remains in the repository/artifact."""
    chunks = [
        f"<h2>纳指基金日报｜{html.escape(report['report_generated_at'][:10])}</h2>",
        f"<p>数据状态：{html.escape(report['report_status'])}</p>",
    ]
    for fund in report["funds"]:
        nav = fund["official_nav"]
        chunks.append(
            f"<p><b>{html.escape(fund['identity']['code'])} {html.escape(fund['identity']['display_name'])}</b><br>"
            f"正式净值 {number(nav.get('unit_nav'))}（{html.escape(str(nav.get('nav_date') or '—'))}），正式日涨跌 {pct(nav.get('daily_return'))}</p>"
        )
    chunks.append(f"<p>{PUBLIC_NOTICE}</p><p>{INVESTMENT_NOTICE}</p>")
    content = "".join(chunks)
    return content[:15000]

