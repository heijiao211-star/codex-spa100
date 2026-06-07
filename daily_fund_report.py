import argparse
import datetime as dt
import html
import json
import math
import os
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
REPORT_DIR = BASE_DIR / "reports"
CONFIG_CANDIDATES = [BASE_DIR / "config.local.json", BASE_DIR / "config.json"]
HISTORY_URL = "https://fundf10.eastmoney.com/F10DataApi.aspx"
ESTIMATE_URL = "https://fundgz.1234567.com.cn/js/{code}.js"
PUSHPLUS_URL = "https://www.pushplus.plus/send"


def load_config():
    for path in CONFIG_CANDIDATES:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                config = json.load(f)
            config["_path"] = str(path)
            return config
    raise FileNotFoundError("Missing config.local.json or config.json")


def http_get(url, timeout=20, encoding="utf-8", retries=3):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
        ),
        "Referer": "https://fund.eastmoney.com/",
    }
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            return raw.decode(encoding, errors="ignore")
        except Exception as exc:
            last_error = exc
            if attempt == retries:
                break
            time.sleep(0.8 * attempt)
    raise last_error


def http_post_json(url, payload, timeout=20):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json;charset=utf-8",
            "User-Agent": "CodexFundReport/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def clean_cell(value):
    value = re.sub(r"<.*?>", "", value, flags=re.S)
    value = html.unescape(value)
    return value.strip()


def to_float(value):
    if value is None:
        return None
    value = str(value).replace(",", "").replace("%", "").strip()
    if value in {"", "--", "---"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_history(js_text):
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", js_text, flags=re.S | re.I):
        cells = [clean_cell(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S | re.I)]
        if len(cells) < 4 or not re.match(r"\d{4}-\d{2}-\d{2}", cells[0]):
            continue
        nav = to_float(cells[1])
        growth = to_float(cells[3])
        if nav is None:
            continue
        rows.append(
            {
                "date": cells[0],
                "nav": nav,
                "acc_nav": to_float(cells[2]),
                "growth": growth,
                "buy_status": cells[4] if len(cells) > 4 else "",
                "sell_status": cells[5] if len(cells) > 5 else "",
            }
        )
    return sorted(rows, key=lambda x: x["date"])


def fetch_history(code, days=420):
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    rows = []
    seen_dates = set()
    page = 1
    pages = None
    while pages is None or page <= pages:
        params = {
            "type": "lsjz",
            "code": code,
            "page": str(page),
            "per": "20",
            "sdate": start.isoformat(),
            "edate": end.isoformat(),
        }
        url = HISTORY_URL + "?" + urllib.parse.urlencode(params)
        text = http_get(url)
        if pages is None:
            match = re.search(r"pages:(\d+)", text)
            pages = int(match.group(1)) if match else 1
        page_rows = parse_history(text)
        if not page_rows:
            break
        for row in page_rows:
            if row["date"] not in seen_dates:
                rows.append(row)
                seen_dates.add(row["date"])
        page += 1
        time.sleep(0.08)
    if not rows:
        raise RuntimeError(f"未取得基金 {code} 的历史净值")
    return sorted(rows, key=lambda x: x["date"])


def fetch_estimate(code):
    try:
        text = http_get(ESTIMATE_URL.format(code=code))
    except Exception:
        return None
    match = re.search(r"jsonpgz\((.*)\);?", text, flags=re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return {
        "name": data.get("name", ""),
        "date": data.get("jzrq", ""),
        "nav": to_float(data.get("dwjz")),
        "estimate_nav": to_float(data.get("gsz")),
        "estimate_growth": to_float(data.get("gszzl")),
        "estimate_time": data.get("gztime", ""),
    }


def pct_change(first, last):
    if first in (None, 0) or last is None:
        return None
    return (last / first - 1) * 100


def trend_value(row):
    return row.get("acc_nav") or row["nav"]


def moving_average(values, window):
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def max_drawdown(values):
    peak = None
    worst = 0
    for value in values:
        if peak is None or value > peak:
            peak = value
        if peak:
            worst = min(worst, value / peak - 1)
    return worst * 100


def annualized_volatility(rows):
    returns = [row["growth"] / 100 for row in rows if row.get("growth") is not None]
    if len(returns) < 20:
        return None
    return statistics.pstdev(returns) * math.sqrt(252) * 100


def rows_since_calendar_days(rows, days):
    latest = dt.date.fromisoformat(rows[-1]["date"])
    cutoff = latest - dt.timedelta(days=days)
    selected = [row for row in rows if dt.date.fromisoformat(row["date"]) >= cutoff]
    return selected if selected else rows[-1:]


def summarize(rows, estimate):
    latest = rows[-1]
    trend_values = [trend_value(x) for x in rows]
    latest_growth = latest.get("growth")
    estimate_growth = estimate.get("estimate_growth") if estimate else None
    one_year_rows = rows_since_calendar_days(rows, 365)
    thirty_day_rows = rows_since_calendar_days(rows, 30)
    ma20 = moving_average(trend_values, 20)
    ma60 = moving_average(trend_values, 60)
    summary = {
        "latest_date": latest["date"],
        "latest_nav": latest["nav"],
        "latest_trend_nav": trend_value(latest),
        "latest_growth": latest_growth,
        "estimate_growth": estimate_growth,
        "estimate_time": estimate.get("estimate_time", "") if estimate else "",
        "return_7d": pct_change(trend_value(rows[-7]), trend_value(latest)) if len(rows) >= 7 else None,
        "return_30d": pct_change(trend_value(thirty_day_rows[0]), trend_value(latest)) if len(thirty_day_rows) > 1 else None,
        "return_1y": pct_change(trend_value(one_year_rows[0]), trend_value(latest)) if len(one_year_rows) > 1 else None,
        "drawdown_1y": max_drawdown([trend_value(x) for x in one_year_rows]),
        "vol_1y": annualized_volatility(one_year_rows),
        "ma20": ma20,
        "ma60": ma60,
    }
    summary["signal"] = make_signal(summary, latest["nav"])
    return summary


def make_signal(summary, latest_nav):
    growth = summary.get("estimate_growth")
    if growth is None:
        growth = summary.get("latest_growth")
    r7 = summary.get("return_7d")
    r30 = summary.get("return_30d")
    ma20 = summary.get("ma20")
    ma60 = summary.get("ma60")

    if growth is not None and growth <= -2.0:
        return ("可小额加仓", "单日回撤较深，若原计划定投不变，可考虑把加仓拆成 2-3 笔。")
    if r7 is not None and r7 <= -4.0:
        return ("偏左侧机会", "近七个净值日回撤明显，适合用定投资金慢慢承接，避免一次打满。")
    if r30 is not None and r30 >= 8.0 and growth is not None and growth > 0:
        return ("控制追高", "短期涨幅偏快，新增资金宜按原定投节奏，不建议情绪化加码。")
    if ma20 and ma60 and latest_nav > ma20 > ma60:
        return ("趋势偏强", "中短期均线向上，持仓可继续跟随，新增资金保持纪律。")
    if ma20 and latest_nav < ma20:
        return ("等待确认", "净值低于 20 日均线，短线偏弱，适合分批而不是单笔重仓。")
    return ("保持定投", "没有出现极端涨跌，按计划投入比择时更重要。")


def fmt_pct(value, signed=True):
    if value is None:
        return "--"
    prefix = "+" if signed and value > 0 else ""
    return f"{prefix}{value:.2f}%"


def fmt_num(value, digits=4):
    if value is None:
        return "--"
    return f"{value:.{digits}f}"


def color_for(value):
    if value is None:
        return "#667085"
    return "#d92d20" if value >= 0 else "#039855"


def sample_rows(rows, max_points):
    if len(rows) <= max_points:
        return rows
    indexes = {
        round(i * (len(rows) - 1) / (max_points - 1))
        for i in range(max_points)
    }
    return [row for idx, row in enumerate(rows) if idx in indexes]


def svg_line(rows, width=760, height=220, color="#2563eb", fill_id="g", full_dates=False, max_points=None):
    if not rows:
        return ""
    if max_points:
        rows = sample_rows(rows, max_points)
    pad_l, pad_r, pad_t, pad_b = 54, 18, 20, 34
    vals = [trend_value(r) for r in rows]
    v_min, v_max = min(vals), max(vals)
    if v_min == v_max:
        v_min *= 0.98
        v_max *= 1.02
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    def xy(i, v):
        x = pad_l + (plot_w * i / max(1, len(rows) - 1))
        y = pad_t + (v_max - v) / (v_max - v_min) * plot_h
        return x, y

    points = [xy(i, trend_value(r)) for i, r in enumerate(rows)]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area = (
        f"{pad_l:.1f},{height - pad_b:.1f} "
        + poly
        + f" {width - pad_r:.1f},{height - pad_b:.1f}"
    )
    grid = []
    labels = []
    for step in range(5):
        y = pad_t + plot_h * step / 4
        value = v_max - (v_max - v_min) * step / 4
        grid.append(f"<line x1='{pad_l}' y1='{y:.1f}' x2='{width-pad_r}' y2='{y:.1f}' />")
        labels.append(
            f"<text x='{pad_l - 8}' y='{y + 4:.1f}' text-anchor='end'>{value:.2f}</text>"
        )
    first_date = rows[0]["date"] if full_dates else rows[0]["date"][5:]
    last_date = rows[-1]["date"] if full_dates else rows[-1]["date"][5:]
    return f"""
<svg viewBox="0 0 {width} {height}" class="chart" role="img">
  <defs>
    <linearGradient id="{fill_id}" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0%" stop-color="{color}" stop-opacity="0.24"/>
      <stop offset="100%" stop-color="{color}" stop-opacity="0.02"/>
    </linearGradient>
  </defs>
  <g class="grid">{''.join(grid)}</g>
  <g class="axis-label">{''.join(labels)}</g>
  <polygon points="{area}" fill="url(#{fill_id})"/>
  <polyline points="{poly}" fill="none" stroke="{color}" stroke-width="3.2"
    stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="{points[-1][0]:.1f}" cy="{points[-1][1]:.1f}" r="4.4" fill="{color}"/>
  <text x="{pad_l}" y="{height - 9}" class="date-label">{first_date}</text>
  <text x="{width - pad_r}" y="{height - 9}" text-anchor="end" class="date-label">{last_date}</text>
</svg>"""


def svg_bars(rows, width=760, height=190):
    rows = rows[-7:]
    pad_l, pad_r, pad_t, pad_b = 40, 18, 22, 36
    vals = [r["growth"] if r.get("growth") is not None else 0 for r in rows]
    limit = max(1.0, max(abs(v) for v in vals) * 1.25)
    zero_y = pad_t + (limit / (2 * limit)) * (height - pad_t - pad_b)
    bar_w = (width - pad_l - pad_r) / max(1, len(rows)) * 0.56
    gap = (width - pad_l - pad_r) / max(1, len(rows))
    bars = []
    for i, (row, val) in enumerate(zip(rows, vals)):
        x = pad_l + i * gap + (gap - bar_w) / 2
        y = pad_t + (limit - val) / (2 * limit) * (height - pad_t - pad_b)
        h = abs(y - zero_y)
        top = min(y, zero_y)
        color = color_for(val)
        bars.append(
            f"<rect x='{x:.1f}' y='{top:.1f}' width='{bar_w:.1f}' height='{max(h, 2):.1f}' "
            f"rx='5' fill='{color}'/>"
            f"<text x='{x + bar_w/2:.1f}' y='{top - 7 if val >= 0 else top + h + 15:.1f}' "
            f"text-anchor='middle' class='bar-value'>{fmt_pct(val)}</text>"
            f"<text x='{x + bar_w/2:.1f}' y='{height - 11}' text-anchor='middle' "
            f"class='date-label'>{row['date'][5:]}</text>"
        )
    return f"""
<svg viewBox="0 0 {width} {height}" class="chart bars" role="img">
  <line x1="{pad_l}" y1="{zero_y:.1f}" x2="{width-pad_r}" y2="{zero_y:.1f}" class="zero-line"/>
  {''.join(bars)}
</svg>"""


def build_card(item, index):
    fund = item["fund"]
    rows = item["rows"]
    summary = item["summary"]
    estimate = item["estimate"] or {}
    signal, advice = summary["signal"]
    latest_color = color_for(summary.get("estimate_growth", summary.get("latest_growth")))
    name = fund.get("label") or estimate.get("name") or fund["code"]
    source_note = (
        f"估算 {fmt_pct(summary['estimate_growth'])} · {summary['estimate_time']}"
        if summary.get("estimate_growth") is not None
        else f"最新净值日涨跌 {fmt_pct(summary['latest_growth'])}"
    )
    return f"""
<section class="fund-card">
  <div class="fund-head">
    <div>
      <div class="fund-kicker">{html.escape(fund['code'])}</div>
      <h2>{html.escape(name)}</h2>
      <p>{html.escape(source_note)}</p>
    </div>
    <div class="today-pill" style="color:{latest_color};border-color:{latest_color}33;background:{latest_color}12">
      {fmt_pct(summary.get('estimate_growth', summary.get('latest_growth')))}
    </div>
  </div>
  <div class="metrics">
    <div><span>最新净值</span><strong>{fmt_num(summary['latest_nav'])}</strong></div>
    <div><span>净值日期</span><strong>{summary['latest_date']}</strong></div>
    <div><span>近7日</span><strong style="color:{color_for(summary['return_7d'])}">{fmt_pct(summary['return_7d'])}</strong></div>
    <div><span>近30日</span><strong style="color:{color_for(summary['return_30d'])}">{fmt_pct(summary['return_30d'])}</strong></div>
    <div><span>近1年</span><strong style="color:{color_for(summary['return_1y'])}">{fmt_pct(summary['return_1y'])}</strong></div>
    <div><span>1年回撤</span><strong>{fmt_pct(summary['drawdown_1y'], signed=False)}</strong></div>
    <div><span>1年波动率</span><strong>{fmt_pct(summary['vol_1y'], signed=False)}</strong></div>
    <div><span>操作提示</span><strong>{html.escape(signal)}</strong></div>
  </div>
  <div class="advice">{html.escape(advice)}</div>
  <h3>近七个净值日趋势</h3>
  {svg_line(rows[-7:], height=190, color=fund.get("color", "#2563eb"), fill_id=f"fill7{index}")}
  <h3>近七个净值日涨跌</h3>
  {svg_bars(rows)}
  <h3>近一年净值趋势</h3>
  {svg_line(rows_since_calendar_days(rows, 365), color=fund.get("color", "#2563eb"), fill_id=f"fill{index}", full_dates=True, max_points=72)}
</section>"""


def market_temperature(items):
    scores = []
    for item in items:
        s = item["summary"]
        r30 = s.get("return_30d") or 0
        r7 = s.get("return_7d") or 0
        dd = abs(s.get("drawdown_1y") or 0)
        score = 50 + r30 * 2 + r7 * 1.2 - max(0, dd - 10) * 0.7
        scores.append(max(0, min(100, score)))
    if not scores:
        return 50
    return round(sum(scores) / len(scores))


def build_report(items, config):
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    temp = market_temperature(items)
    if temp >= 68:
        temp_text = "偏热，新增资金宜克制追涨"
    elif temp <= 38:
        temp_text = "偏冷，定投资金可更从容分批"
    else:
        temp_text = "中性，按计划执行优先"
    title = config.get("title", "美股指数基金定投日报")
    cards = "\n".join(build_card(item, idx) for idx, item in enumerate(items))
    data_rows = []
    for item in items:
        fund = item["fund"]
        summary = item["summary"]
        name = fund.get("label") or (item["estimate"] or {}).get("name") or fund["code"]
        data_rows.append(
            f"<tr><td>{html.escape(name)}</td><td>{summary['latest_date']}</td>"
            f"<td>{fmt_num(summary['latest_nav'])}</td>"
            f"<td>{fmt_pct(summary.get('estimate_growth', summary.get('latest_growth')))}</td>"
            f"<td>{fmt_pct(summary['return_7d'])}</td><td>{fmt_pct(summary['return_1y'])}</td>"
            f"<td>{html.escape(summary['signal'][0])}</td></tr>"
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
  body {{
    margin: 0;
    background: #f4f7fb;
    color: #101828;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
      "Microsoft YaHei", Arial, sans-serif;
  }}
  .wrap {{ max-width: 920px; margin: 0 auto; padding: 24px 14px 34px; }}
  .hero {{
    padding: 26px 24px;
    border-radius: 8px;
    background: linear-gradient(135deg, #111827, #243b53 58%, #0f766e);
    color: #fff;
  }}
  .hero h1 {{ margin: 0 0 8px; font-size: 28px; letter-spacing: 0; }}
  .hero p {{ margin: 0; color: #d9e8f2; line-height: 1.65; }}
  .temp {{
    display: inline-block;
    margin-top: 16px;
    padding: 9px 12px;
    border: 1px solid rgba(255,255,255,.24);
    border-radius: 6px;
    background: rgba(255,255,255,.12);
    font-weight: 700;
  }}
  .fund-card {{
    margin-top: 18px;
    padding: 22px;
    border: 1px solid #e4e7ec;
    border-radius: 8px;
    background: #fff;
    box-shadow: 0 12px 30px rgba(16, 24, 40, .06);
  }}
  .fund-head {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }}
  .fund-kicker {{ color: #667085; font-size: 13px; font-weight: 700; }}
  h2 {{ margin: 4px 0 4px; font-size: 22px; line-height: 1.25; }}
  h3 {{ margin: 22px 0 8px; font-size: 16px; color: #344054; }}
  .fund-head p {{ margin: 0; color: #667085; font-size: 13px; }}
  .today-pill {{
    min-width: 82px;
    padding: 8px 10px;
    border: 1px solid;
    border-radius: 8px;
    text-align: center;
    font-size: 22px;
    font-weight: 800;
  }}
  .metrics {{
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 10px;
    margin-top: 18px;
  }}
  .metrics div {{
    padding: 12px;
    background: #f8fafc;
    border: 1px solid #edf2f7;
    border-radius: 8px;
  }}
  .metrics span {{ display: block; color: #667085; font-size: 12px; margin-bottom: 5px; }}
  .metrics strong {{ font-size: 16px; }}
  .advice {{
    margin-top: 12px;
    padding: 12px 14px;
    border-left: 4px solid #0f766e;
    background: #ecfdf3;
    color: #184e44;
    line-height: 1.7;
    border-radius: 6px;
  }}
  .chart {{ width: 100%; height: auto; display: block; overflow: visible; }}
  .grid line {{ stroke: #e5e7eb; stroke-width: 1; }}
  .axis-label text, .date-label, .bar-value {{ fill: #667085; font-size: 12px; }}
  .zero-line {{ stroke: #98a2b3; stroke-width: 1.2; stroke-dasharray: 4 4; }}
  table {{
    width: 100%;
    margin-top: 18px;
    border-collapse: collapse;
    background: #fff;
    border-radius: 8px;
    overflow: hidden;
  }}
  th, td {{ padding: 11px 9px; border-bottom: 1px solid #eaecf0; font-size: 13px; text-align: left; }}
  th {{ background: #111827; color: #fff; }}
  .note {{ margin-top: 16px; color: #667085; line-height: 1.7; font-size: 13px; }}
  @media (max-width: 680px) {{
    .fund-head {{ display: block; }}
    .today-pill {{ margin-top: 12px; width: fit-content; }}
    .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    h2 {{ font-size: 19px; }}
  }}
</style>
</head>
<body>
<main class="wrap">
  <section class="hero">
    <h1>{html.escape(title)}</h1>
    <p>生成时间：{now}。口径采用支付宝常见 QDII 指数基金的历史净值与天天基金估算，净值披露通常滞后一个交易日。</p>
    <div class="temp">市场温度 {temp}/100 · {temp_text}</div>
  </section>
  {cards}
  <table>
    <thead><tr><th>基金</th><th>净值日</th><th>净值</th><th>当日</th><th>近7日</th><th>近1年</th><th>提示</th></tr></thead>
    <tbody>{''.join(data_rows)}</tbody>
  </table>
  <p class="note">说明：红色代表上涨，绿色代表下跌；QDII 基金受海外市场、汇率、基金估算模型和净值披露时差影响，和纳斯达克/标普500现货指数不会完全同步。本简报用于定投节奏参考，不构成个性化投资建议。</p>
</main>
</body>
</html>"""


def collect_items(config):
    items = []
    for fund in config.get("funds", []):
        code = str(fund["code"]).strip()
        rows = fetch_history(code, days=config.get("history_days", 420))
        estimate = fetch_estimate(code)
        summary = summarize(rows, estimate)
        items.append({"fund": fund, "rows": rows, "estimate": estimate, "summary": summary})
        time.sleep(0.2)
    return items


def send_pushplus(config, title, content):
    token = os.environ.get("PUSHPLUS_TOKEN") or config.get("pushplus_token")
    if not token:
        raise RuntimeError("未配置 PushPlus token")
    payload = {
        "token": token,
        "title": title,
        "content": content,
        "template": "html",
    }
    topic = config.get("pushplus_topic")
    if topic:
        payload["topic"] = topic
    return http_post_json(PUSHPLUS_URL, payload)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true", help="send report to PushPlus")
    parser.add_argument("--dry-run", action="store_true", help="generate report without sending")
    args = parser.parse_args()

    config = load_config()
    if not config.get("funds"):
        raise RuntimeError("配置里没有 funds")

    REPORT_DIR.mkdir(exist_ok=True)
    items = collect_items(config)
    report = build_report(items, config)
    today = dt.date.today().isoformat()
    out_path = REPORT_DIR / f"fund-report-{today}.html"
    out_path.write_text(report, encoding="utf-8")

    title = f"{config.get('title', '美股指数基金定投日报')} {today}"
    print(f"report={out_path}")
    if args.send and not args.dry_run:
        result = send_pushplus(config, title, report)
        print(result)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
