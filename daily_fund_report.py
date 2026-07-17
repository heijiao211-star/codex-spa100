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
from zoneinfo import ZoneInfo

from ai_market_briefing import build_market_briefing, render_market_briefing_html

BASE_DIR = Path(__file__).resolve().parent
REPORT_DIR = BASE_DIR / "reports"
CONFIG_CANDIDATES = [BASE_DIR / "config.local.json", BASE_DIR / "config.json"]
FUND_HISTORY_URL = "https://fundf10.eastmoney.com/F10DataApi.aspx"
FUND_HISTORY_API_URL = "https://api.fund.eastmoney.com/f10/lsjz"
ESTIMATE_URL = "https://fundgz.1234567.com.cn/js/{code}.js"
INDEX_HISTORY_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
PUSHPLUS_URL = "https://www.pushplus.plus/send"
QUICKCHART_CREATE_URL = "https://quickchart.io/chart/create"
DEFAULT_HISTORY_DAYS = 1200
CHINA_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_STATE_FILE = BASE_DIR / ".github" / "fund-report-state.json"
DEFAULT_BENCHMARKS = [
    {"type": "fund", "code": "513300", "label": "参考基准：纳斯达克100ETF", "color": "#7c3aed"},
]


def china_now():
    return dt.datetime.now(CHINA_TZ)


def resolve_path(path_value):
    path = Path(path_value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def load_config():
    for path in CONFIG_CANDIDATES:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                config = json.load(f)
            config["_path"] = str(path)
            config.setdefault("history_days", DEFAULT_HISTORY_DAYS)
            config.setdefault(
                "source_note",
                "主数据固定使用支付宝可购买的基金代码 270042（广发纳斯达克100ETF联接A）净值口径；基准图只作参考，不把美股纳斯达克指数当作你的持仓数据。",
            )
            if "benchmarks" not in config:
                config["benchmarks"] = [dict(item) for item in DEFAULT_BENCHMARKS]
            return config
    raise FileNotFoundError("Missing config.local.json or config.json")


def http_get(url, timeout=25, encoding="utf-8", retries=4, referer="https://fund.eastmoney.com/"):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
        ),
        "Referer": referer,
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
            time.sleep(1.2 * attempt)
    raise last_error


def http_post_json(url, payload, timeout=30, retries=4):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json;charset=utf-8",
        "User-Agent": "CodexFundReport/3.0",
    }
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except Exception as exc:
            last_error = exc
            if attempt == retries:
                break
            time.sleep(1.2 * attempt)
    raise last_error


def quickchart_url(chart_config, width=760, height=380):
    payload = {
        "chart": chart_config,
        "width": width,
        "height": height,
        "format": "png",
        "backgroundColor": "white",
    }
    result = http_post_json(QUICKCHART_CREATE_URL, payload, timeout=35, retries=3)
    data = json.loads(result)
    if not data.get("success") or not data.get("url"):
        raise RuntimeError(f"QuickChart 生成失败: {result}")
    return data["url"]


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


def parse_fund_history(text):
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", text, flags=re.S | re.I):
        cells = [clean_cell(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S | re.I)]
        if len(cells) < 4 or not re.match(r"\d{4}-\d{2}-\d{2}", cells[0]):
            continue
        nav = to_float(cells[1])
        if nav is None:
            continue
        rows.append(
            {
                "date": cells[0],
                "nav": nav,
                "acc_nav": to_float(cells[2]),
                "growth": to_float(cells[3]),
                "buy_status": cells[4] if len(cells) > 4 else "",
                "sell_status": cells[5] if len(cells) > 5 else "",
            }
        )
    return sorted(rows, key=lambda x: x["date"])


def fetch_history_legacy(code, days=DEFAULT_HISTORY_DAYS):
    end = china_now().date()
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
        url = FUND_HISTORY_URL + "?" + urllib.parse.urlencode(params)
        text = http_get(url)
        if pages is None:
            match = re.search(r"pages:(\d+)", text)
            pages = int(match.group(1)) if match else 1
        page_rows = parse_fund_history(text)
        if not page_rows:
            break
        for row in page_rows:
            if row["date"] not in seen_dates:
                rows.append(row)
                seen_dates.add(row["date"])
        page += 1
        time.sleep(0.06)
    if not rows:
        raise RuntimeError(f"未取得基金 {code} 的历史净值")
    return sorted(rows, key=lambda x: x["date"])


def parse_fund_history_api(text):
    """Parse the Eastmoney JSON historical-NAV response."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("fund history API returned invalid JSON") from exc

    if payload.get("ErrCode") not in (None, 0):
        message = payload.get("ErrMsg") or payload.get("ErrCode")
        raise RuntimeError(f"fund history API error: {message}")

    records = (payload.get("Data") or {}).get("LSJZList") or []
    rows = []
    for record in records:
        date = str(record.get("FSRQ") or "")
        nav = to_float(record.get("DWJZ"))
        if nav is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            continue
        rows.append(
            {
                "date": date,
                "nav": nav,
                "acc_nav": to_float(record.get("LJJZ")),
                "growth": to_float(record.get("JZZZL")),
                "buy_status": str(record.get("SGZT") or ""),
                "sell_status": str(record.get("SHZT") or ""),
            }
        )
    return sorted(rows, key=lambda x: x["date"]), int(payload.get("TotalCount") or 0)


def fetch_history_api(code, days=DEFAULT_HISTORY_DAYS):
    """Fetch history from Eastmoney's current JSON API."""
    end = china_now().date()
    start = end - dt.timedelta(days=days)
    rows = []
    seen_dates = set()
    page = 1
    page_size = 100
    total_count = None
    while total_count is None or (page - 1) * page_size < total_count:
        params = {
            "fundCode": code,
            "pageIndex": str(page),
            "pageSize": str(page_size),
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
        }
        url = FUND_HISTORY_API_URL + "?" + urllib.parse.urlencode(params)
        text = http_get(url, referer="https://fundf10.eastmoney.com/")
        page_rows, reported_total = parse_fund_history_api(text)
        total_count = reported_total or total_count
        if not page_rows:
            break
        for row in page_rows:
            if row["date"] not in seen_dates:
                rows.append(row)
                seen_dates.add(row["date"])
        page += 1
        time.sleep(0.06)
    if not rows:
        raise RuntimeError("fund history JSON API returned no records")
    return sorted(rows, key=lambda x: x["date"])


def fetch_history(code, days=DEFAULT_HISTORY_DAYS):
    """Use the JSON API first and fall back to the legacy HTML endpoint."""
    errors = []
    for name, fetcher in (("JSON", fetch_history_api), ("legacy", fetch_history_legacy)):
        try:
            return fetcher(code, days)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            print(f"WARN: fund history source {name} failed for {code}: {exc}", file=sys.stderr)
    raise RuntimeError("unable to fetch fund history for " + str(code) + ": " + "; ".join(errors))

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


def fetch_index_history(secid, days=DEFAULT_HISTORY_DAYS):
    end = china_now().date()
    start = end - dt.timedelta(days=days)
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "klt": "101",
        "fqt": "0",
        "beg": start.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
    }
    url = INDEX_HISTORY_URL + "?" + urllib.parse.urlencode(params)
    text = http_get(url, referer="https://quote.eastmoney.com/")
    payload = json.loads(text)
    data = payload.get("data") or {}
    rows = []
    prev_nav = None
    for line in data.get("klines") or []:
        parts = line.split(",")
        if len(parts) < 3 or not re.match(r"\d{4}-\d{2}-\d{2}", parts[0]):
            continue
        nav = to_float(parts[2])
        if nav is None:
            continue
        rows.append(
            {
                "date": parts[0],
                "nav": nav,
                "acc_nav": nav,
                "growth": pct_change(prev_nav, nav) if prev_nav not in (None, 0) else None,
            }
        )
        prev_nav = nav
    if not rows:
        raise RuntimeError(f"未取得基准 {secid} 的历史数据")
    return {"label": data.get("name") or secid, "rows": rows}


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


def required_history_days(config):
    return max(int(config.get("history_days", DEFAULT_HISTORY_DAYS)), DEFAULT_HISTORY_DAYS)


def build_drawdown_points(rows, use_trend_value=True):
    points = []
    peak = None
    for row in rows:
        value = trend_value(row) if use_trend_value else row["nav"]
        if peak is None or value > peak:
            peak = value
        drawdown = (value / peak - 1) * 100 if peak else 0
        points.append({"date": row["date"], "value": drawdown})
    return points


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


def direction_text(value):
    if value is None:
        return "暂无涨跌数据"
    if value > 0:
        return "上涨"
    if value < 0:
        return "下跌"
    return "持平"


def sample_rows(rows, max_points):
    if len(rows) <= max_points:
        return rows
    indexes = {round(i * (len(rows) - 1) / (max_points - 1)) for i in range(max_points)}
    return [row for idx, row in enumerate(rows) if idx in indexes]


def sample_points(points, max_points):
    if len(points) <= max_points:
        return points
    indexes = {round(i * (len(points) - 1) / (max_points - 1)) for i in range(max_points)}
    return [point for idx, point in enumerate(points) if idx in indexes]


def format_axis_value(value, value_kind):
    if value_kind == "pct":
        return f"{value:.0f}%"
    return f"{value:.2f}"


def svg_line(rows, width=760, height=220, color="#2563eb", fill_id="g", full_dates=False, max_points=None):
    if not rows:
        return ""
    if max_points:
        rows = sample_rows(rows, max_points)
    pad_l, pad_r, pad_t, pad_b = 58, 18, 20, 36
    vals = [trend_value(r) for r in rows]
    v_min, v_max = min(vals), max(vals)
    if v_min == v_max:
        span = abs(v_min) * 0.03 or 1
        v_min -= span
        v_max += span
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    def xy(i, v):
        x = pad_l + (plot_w * i / max(1, len(rows) - 1))
        y = pad_t + (v_max - v) / (v_max - v_min) * plot_h
        return x, y

    points = [xy(i, trend_value(r)) for i, r in enumerate(rows)]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area = f"{pad_l:.1f},{height - pad_b:.1f} " + poly + f" {width - pad_r:.1f},{height - pad_b:.1f}"
    grid = []
    labels = []
    for step in range(5):
        y = pad_t + plot_h * step / 4
        value = v_max - (v_max - v_min) * step / 4
        grid.append(f"<line x1='{pad_l}' y1='{y:.1f}' x2='{width - pad_r}' y2='{y:.1f}' />")
        labels.append(f"<text x='{pad_l - 8}' y='{y + 4:.1f}' text-anchor='end'>{value:.2f}</text>")
    first_date = rows[0]["date"] if full_dates else rows[0]["date"][5:]
    last_date = rows[-1]["date"] if full_dates else rows[-1]["date"][5:]
    return f"""
<svg viewBox="0 0 {width} {height}" class="chart" role="img">
  <defs>
    <linearGradient id="{fill_id}" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0%" stop-color="{color}" stop-opacity="0.26"/>
      <stop offset="100%" stop-color="{color}" stop-opacity="0.03"/>
    </linearGradient>
  </defs>
  <g class="grid">{''.join(grid)}</g>
  <g class="axis-label">{''.join(labels)}</g>
  <polygon points="{area}" fill="url(#{fill_id})"/>
  <polyline points="{poly}" fill="none" stroke="{color}" stroke-width="4"
    stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="{points[-1][0]:.1f}" cy="{points[-1][1]:.1f}" r="5" fill="{color}"/>
  <text x="{pad_l}" y="{height - 10}" class="date-label">{first_date}</text>
  <text x="{width - pad_r}" y="{height - 10}" text-anchor="end" class="date-label">{last_date}</text>
</svg>"""


def svg_bars(rows, width=760, height=230):
    rows = rows[-7:]
    if not rows:
        return ""
    pad_l, pad_r, pad_t, pad_b = 46, 18, 28, 42
    vals = [row["growth"] if row.get("growth") is not None else 0 for row in rows]
    limit = max(0.25, max(abs(v) for v in vals) * 1.35)
    plot_h = height - pad_t - pad_b
    zero_y = pad_t + plot_h / 2
    bar_w = (width - pad_l - pad_r) / max(1, len(rows)) * 0.62
    gap = (width - pad_l - pad_r) / max(1, len(rows))
    bars = []
    for i, (row, val) in enumerate(zip(rows, vals)):
        x = pad_l + i * gap + (gap - bar_w) / 2
        y = pad_t + (limit - val) / (2 * limit) * plot_h
        h = abs(y - zero_y)
        top = min(y, zero_y)
        bar_color = color_for(val)
        label_y = max(14, top - 8) if val >= 0 else min(height - 24, top + h + 18)
        bars.append(
            f"<rect x='{x:.1f}' y='{top:.1f}' width='{bar_w:.1f}' height='{max(h, 4):.1f}' "
            f"rx='6' fill='{bar_color}'/>"
            f"<text x='{x + bar_w / 2:.1f}' y='{label_y:.1f}' text-anchor='middle' "
            f"class='bar-value' fill='{bar_color}'>{fmt_pct(val)}</text>"
            f"<text x='{x + bar_w / 2:.1f}' y='{height - 13}' text-anchor='middle' class='date-label'>{row['date'][5:]}</text>"
        )
    return f"""
<svg viewBox="0 0 {width} {height}" class="chart" role="img">
  <line x1="{pad_l}" y1="{pad_t}" x2="{width - pad_r}" y2="{pad_t}" class="guide-line"/>
  <line x1="{pad_l}" y1="{zero_y:.1f}" x2="{width - pad_r}" y2="{zero_y:.1f}" class="zero-line"/>
  <line x1="{pad_l}" y1="{height - pad_b}" x2="{width - pad_r}" y2="{height - pad_b}" class="guide-line"/>
  <text x="{pad_l - 8}" y="{pad_t + 4}" text-anchor="end" class="date-label">+{limit:.2f}%</text>
  <text x="{pad_l - 8}" y="{zero_y + 4:.1f}" text-anchor="end" class="date-label">0</text>
  <text x="{pad_l - 8}" y="{height - pad_b + 4}" text-anchor="end" class="date-label">-{limit:.2f}%</text>
  {''.join(bars)}
</svg>"""


def svg_multi_line(series_list, width=760, height=270, value_kind="number", max_points=96, strong=False):
    prepared = []
    for series in series_list:
        points = [point for point in series.get("points", []) if point.get("value") is not None]
        if not points:
            continue
        prepared.append({"label": series["label"], "color": series["color"], "points": sample_points(points, max_points)})
    if not prepared:
        return ""

    pad_l, pad_r, pad_t, pad_b = 58, 18, 28, 40
    all_dates = [dt.date.fromisoformat(point["date"]).toordinal() for series in prepared for point in series["points"]]
    all_values = [point["value"] for series in prepared for point in series["points"]]
    d_min, d_max = min(all_dates), max(all_dates)
    v_min, v_max = min(all_values), max(all_values)
    if value_kind == "pct":
        v_max = max(v_max, 0)
    if d_min == d_max:
        d_max += 1
    if v_min == v_max:
        span = abs(v_min) * 0.08 or 1
        v_min -= span
        v_max += span
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    def xy(point):
        day = dt.date.fromisoformat(point["date"]).toordinal()
        x = pad_l + (day - d_min) / (d_max - d_min) * plot_w
        y = pad_t + (v_max - point["value"]) / (v_max - v_min) * plot_h
        return x, y

    grid = []
    labels = []
    for step in range(5):
        y = pad_t + plot_h * step / 4
        value = v_max - (v_max - v_min) * step / 4
        grid.append(f"<line x1='{pad_l}' y1='{y:.1f}' x2='{width - pad_r}' y2='{y:.1f}' />")
        labels.append(f"<text x='{pad_l - 8}' y='{y + 4:.1f}' text-anchor='end'>{format_axis_value(value, value_kind)}</text>")

    if v_min < 0 < v_max:
        zero_y = pad_t + (v_max / (v_max - v_min)) * plot_h
        grid.append(f"<line x1='{pad_l}' y1='{zero_y:.1f}' x2='{width - pad_r}' y2='{zero_y:.1f}' class='zero-line' />")

    polylines = []
    legends = []
    stroke_width = "4.4" if strong else "3.4"
    radius = "5" if strong else "4"
    for idx, series in enumerate(prepared):
        points = [xy(point) for point in series["points"]]
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        polylines.append(
            f"<polyline points='{poly}' fill='none' stroke='{series['color']}' stroke-width='{stroke_width}' "
            f"stroke-linecap='round' stroke-linejoin='round'/>"
            f"<circle cx='{points[-1][0]:.1f}' cy='{points[-1][1]:.1f}' r='{radius}' fill='{series['color']}'/>"
        )
        legend_x = pad_l + idx * 190
        legends.append(
            f"<rect x='{legend_x}' y='5' width='12' height='12' rx='3' fill='{series['color']}'/>"
            f"<text x='{legend_x + 18}' y='15' fill='#475467' font-size='12'>{html.escape(series['label'])}</text>"
        )

    first_date = dt.date.fromordinal(d_min).isoformat()
    last_date = dt.date.fromordinal(d_max).isoformat()
    return f"""
<svg viewBox="0 0 {width} {height}" class="chart" role="img">
  <g class="legend">{''.join(legends)}</g>
  <g class="grid">{''.join(grid)}</g>
  <g class="axis-label">{''.join(labels)}</g>
  {''.join(polylines)}
  <text x="{pad_l}" y="{height - 11}" class="date-label">{first_date}</text>
  <text x="{width - pad_r}" y="{height - 11}" text-anchor="end" class="date-label">{last_date}</text>
</svg>"""


def rows_to_series(rows, label, color, days=None, normalize=False, use_trend=True):
    selected = rows_since_calendar_days(rows, days) if days else rows
    points = []
    base = None
    for row in selected:
        value = trend_value(row) if use_trend else row["nav"]
        if base is None:
            base = value
        if normalize and base not in (None, 0):
            value = (value / base - 1) * 100
        points.append({"date": row["date"], "value": value})
    return {"label": label, "color": color, "points": points}


def points_to_series(points, label, color):
    return {"label": label, "color": color, "points": points}


def sample_chart_points(points, max_points):
    sampled = sample_points(points, max_points)
    return [point for point in sampled if point.get("value") is not None]


def quickchart_tick_options(y_suffix="", min_value=None, max_value=None):
    ticks = {"fontColor": "#667085", "fontSize": 11, "padding": 6}
    if min_value is not None:
        ticks["min"] = min_value
    if max_value is not None:
        ticks["max"] = max_value
    if y_suffix == "%":
        ticks["callback"] = "function(value) { return value + '%'; }"
    return ticks


def chart_line_config(title, series_list, y_suffix="", max_points=90, strong=False, min_value=None, max_value=None):
    labels = []
    datasets = []
    for series in series_list:
        points = sample_chart_points(series.get("points", []), max_points)
        if not points:
            continue
        if not labels:
            labels = [point["date"] for point in points]
        values = align_series_to_labels(points, labels)
        datasets.append(
            {
                "label": series["label"],
                "data": values,
                "borderColor": series["color"],
                "backgroundColor": series["color"],
                "borderWidth": 3.8 if strong else 2.8,
                "pointRadius": 0,
                "fill": False,
                "tension": 0.15,
                "lineTension": 0.15,
            }
        )
    return {
        "type": "line",
        "data": {"labels": labels, "datasets": datasets},
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "layout": {"padding": {"left": 10, "right": 14, "top": 12, "bottom": 8}},
            "title": {"display": True, "text": title, "fontSize": 18, "fontColor": "#111827", "fontStyle": "600", "padding": 16},
            "legend": {"display": len(datasets) > 1, "position": "bottom", "labels": {"boxWidth": 10, "fontColor": "#475467", "padding": 14}},
            "scales": {
                "xAxes": [{"gridLines": {"display": False, "drawBorder": False}, "ticks": {"maxTicksLimit": 6, "fontColor": "#667085", "fontSize": 10}}],
                "yAxes": [{"gridLines": {"color": "#eef2f6", "drawBorder": False}, "ticks": quickchart_tick_options(y_suffix, min_value, max_value)}],
            },
        },
    }


def chart_bar_config(title, rows):
    rows = rows[-7:]
    vals = [row["growth"] if row.get("growth") is not None else 0 for row in rows]
    limit = max(0.25, max(abs(v) for v in vals) * 1.35) if vals else 1
    return {
        "type": "bar",
        "data": {
            "labels": [row["date"][5:] for row in rows],
            "datasets": [
                {
                    "label": "日涨跌",
                    "data": vals,
                    "backgroundColor": ["#d92d20" if val >= 0 else "#039855" for val in vals],
                    "barPercentage": 0.72,
                    "categoryPercentage": 0.72,
                }
            ],
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "layout": {"padding": {"left": 10, "right": 14, "top": 12, "bottom": 8}},
            "title": {"display": True, "text": title, "fontSize": 18, "fontColor": "#111827", "fontStyle": "600", "padding": 16},
            "legend": {"display": False},
            "scales": {
                "xAxes": [{"gridLines": {"display": False, "drawBorder": False}, "ticks": {"fontColor": "#667085", "fontSize": 11}}],
                "yAxes": [{"gridLines": {"color": "#eef2f6", "drawBorder": False, "zeroLineColor": "#98a2b3"}, "ticks": quickchart_tick_options("%", -limit, limit)}],
            },
        },
    }


def align_series_to_labels(points, labels):
    by_date = {point["date"]: point["value"] for point in points}
    ordered = sorted(points, key=lambda point: point["date"])
    values = []
    cursor = 0
    last_value = None
    for label in labels:
        if label in by_date:
            last_value = by_date[label]
            values.append(last_value)
            continue
        while cursor < len(ordered) and ordered[cursor]["date"] <= label:
            last_value = ordered[cursor]["value"]
            cursor += 1
        values.append(last_value)
    return values


def image_html(url, alt):
    return (
        f"<div class='chart-card'><img src='{html.escape(url)}' alt='{html.escape(alt)}' "
        "style='width:100%;max-width:760px;display:block;border:0;border-radius:8px;'/></div>"
    )


def pushplus_chart_images(item, benchmarks):
    fund = item["fund"]
    rows = item["rows"]
    estimate = item["estimate"] or {}
    name = fund.get("label") or estimate.get("name") or fund["code"]
    color = fund.get("color", "#2563eb")
    seven_rows = rows[-7:]
    one_month_rows = rows_since_calendar_days(rows, 30)
    one_year_rows = rows_since_calendar_days(rows, 365)
    three_year_rows = rows_since_calendar_days(rows, 365 * 3)
    drawdown_points = build_drawdown_points(three_year_rows)
    min_drawdown = min((point["value"] for point in drawdown_points), default=-1)

    chart_specs = [
        (f"{name} 近7个净值日趋势", chart_line_config(f"{name} 近7个净值日趋势", [rows_to_series(seven_rows, "净值", color, use_trend=True)], max_points=7, strong=True)),
        (f"{name} 近7个净值日涨跌", chart_bar_config(f"{name} 近7个净值日涨跌", rows)),
        (f"{name} 近1个月净值趋势", chart_line_config(f"{name} 近1个月净值趋势", [rows_to_series(one_month_rows, "净值", color, use_trend=True)], max_points=42, strong=True)),
        (f"{name} 近1年净值趋势", chart_line_config(f"{name} 近1年净值趋势", [rows_to_series(one_year_rows, "净值", color, use_trend=True)], max_points=90, strong=True)),
        (f"{name} 近3年净值趋势", chart_line_config(f"{name} 近3年净值趋势", [rows_to_series(three_year_rows, "净值", color, use_trend=True)], max_points=110, strong=True)),
        (
            f"{name} 回撤曲线",
            chart_line_config(
                f"{name} 回撤曲线",
                [points_to_series(drawdown_points, "回撤", "#b42318")],
                y_suffix="%",
                max_points=110,
                strong=True,
                min_value=math.floor(min_drawdown),
                max_value=0,
            ),
        ),
    ]

    compare_series = [rows_to_series(three_year_rows, name, color, normalize=True, use_trend=True)]
    for benchmark in benchmarks:
        compare_series.append(
            rows_to_series(
                benchmark["rows"],
                benchmark["label"],
                benchmark["color"],
                days=365 * 3,
                normalize=True,
                use_trend=benchmark.get("use_trend", False),
            )
        )
    if len(compare_series) > 1:
        chart_specs.append((f"{name} vs 参考基准", chart_line_config(f"{name} vs 参考基准", compare_series, y_suffix="%", max_points=110)))

    images = []
    for alt, config in chart_specs:
        try:
            images.append(image_html(quickchart_url(config), alt))
            time.sleep(0.12)
        except Exception as exc:
            print(f"WARN: chart failed {alt}: {exc}", file=sys.stderr)
            images.append(f"<p class='note'>图表生成失败：{html.escape(alt)}。文字数据仍已正常生成。</p>")
    return "".join(images)


def summarize(rows, estimate):
    latest = rows[-1]
    trend_values = [trend_value(x) for x in rows]
    latest_growth = latest.get("growth")
    estimate_growth = estimate.get("estimate_growth") if estimate else None
    seven_rows = rows[-7:]
    one_year_rows = rows_since_calendar_days(rows, 365)
    thirty_day_rows = rows_since_calendar_days(rows, 30)
    three_year_rows = rows_since_calendar_days(rows, 365 * 3)
    ma20 = moving_average(trend_values, 20)
    ma60 = moving_average(trend_values, 60)
    summary = {
        "latest_date": latest["date"],
        "latest_nav": latest["nav"],
        "latest_trend_nav": trend_value(latest),
        "latest_growth": latest_growth,
        "daily_change": estimate_growth if estimate_growth is not None else latest_growth,
        "daily_change_label": "估算涨跌" if estimate_growth is not None else "净值日涨跌",
        "estimate_growth": estimate_growth,
        "estimate_time": estimate.get("estimate_time", "") if estimate else "",
        "return_7d": pct_change(trend_value(seven_rows[0]), trend_value(latest)) if len(seven_rows) > 1 else None,
        "return_30d": pct_change(trend_value(thirty_day_rows[0]), trend_value(latest)) if len(thirty_day_rows) > 1 else None,
        "return_1y": pct_change(trend_value(one_year_rows[0]), trend_value(latest)) if len(one_year_rows) > 1 else None,
        "return_3y": pct_change(trend_value(three_year_rows[0]), trend_value(latest)) if len(three_year_rows) > 1 else None,
        "drawdown_1y": max_drawdown([trend_value(x) for x in one_year_rows]),
        "drawdown_3y": max_drawdown([trend_value(x) for x in three_year_rows]),
        "vol_1y": annualized_volatility(one_year_rows),
        "vol_3y": annualized_volatility(three_year_rows),
        "ma20": ma20,
        "ma60": ma60,
    }
    return summary


def metric_cell(label, value, color=None):
    style = f" style='color:{color}'" if color else ""
    return f"<div><span>{html.escape(label)}</span><strong{style}>{value}</strong></div>"


def change_panel(summary):
    value = summary.get("daily_change")
    color = color_for(value)
    label = summary.get("daily_change_label") or "涨跌"
    source = summary.get("estimate_time") if summary.get("estimate_growth") is not None else summary.get("latest_date")
    return f"""
  <div class="change-panel" style="border-color:{color}55;background:{color}10;">
    <div>
      <span>{html.escape(label)}</span>
      <b style="color:{color};">{direction_text(value)}</b>
      <small>{html.escape(source or '最新可得数据')}</small>
    </div>
    <strong style="color:{color};">{fmt_pct(value)}</strong>
  </div>"""


def build_compare_series(item, benchmarks, days=365 * 3):
    fund = item["fund"]
    rows = item["rows"]
    estimate = item["estimate"] or {}
    name = fund.get("label") or estimate.get("name") or fund["code"]
    series = [rows_to_series(rows_since_calendar_days(rows, days), name, fund.get("color", "#2563eb"), normalize=True, use_trend=True)]
    for benchmark in benchmarks:
        series.append(rows_to_series(benchmark["rows"], benchmark["label"], benchmark["color"], days=days, normalize=True, use_trend=benchmark.get("use_trend", False)))
    return series


def build_card(item, benchmarks, index):
    fund = item["fund"]
    rows = item["rows"]
    summary = item["summary"]
    estimate = item["estimate"] or {}
    name = fund.get("label") or estimate.get("name") or fund["code"]
    color = fund.get("color", "#2563eb")
    source_note = (
        f"估算 {fmt_pct(summary['estimate_growth'])} · {summary['estimate_time']}"
        if summary.get("estimate_growth") is not None
        else f"最新净值日涨跌 {fmt_pct(summary['latest_growth'])}"
    )

    metrics = [
        metric_cell("最新净值", fmt_num(summary["latest_nav"])),
        metric_cell("净值日期", summary["latest_date"]),
        metric_cell("近7净值日", fmt_pct(summary["return_7d"]), color_for(summary["return_7d"])),
        metric_cell("近1个月", fmt_pct(summary["return_30d"]), color_for(summary["return_30d"])),
        metric_cell("近1年", fmt_pct(summary["return_1y"]), color_for(summary["return_1y"])),
        metric_cell("近3年", fmt_pct(summary["return_3y"]), color_for(summary["return_3y"])),
        metric_cell("近1年回撤", fmt_pct(summary["drawdown_1y"], signed=False)),
        metric_cell("近3年最大回撤", fmt_pct(summary["drawdown_3y"], signed=False)),
        metric_cell("年化波动率", fmt_pct(summary["vol_3y"], signed=False)),
    ]

    seven_rows = rows[-7:]
    one_month_rows = rows_since_calendar_days(rows, 30)
    one_year_rows = rows_since_calendar_days(rows, 365)
    three_year_rows = rows_since_calendar_days(rows, 365 * 3)
    compare_series = build_compare_series(item, benchmarks)

    return f"""
<section class="fund-card">
  <div class="fund-head">
    <div>
      <div class="fund-kicker">{html.escape(fund['code'])} · 支付宝基金口径</div>
      <h2>{html.escape(name)}</h2>
      <p>{html.escape(source_note)}</p>
    </div>
  </div>
  {change_panel(summary)}
  <div class="metrics">{''.join(metrics)}</div>
  <h3>近7个净值日趋势</h3>
  {svg_line(seven_rows, height=200, color=color, fill_id=f"fill7{index}")}
  <h3>近7个净值日涨跌</h3>
  {svg_bars(rows)}
  <h3>近1个月净值趋势图</h3>
  {svg_line(one_month_rows, color=color, fill_id=f"fill1m{index}", full_dates=True, max_points=42)}
  <h3>近1年净值趋势图</h3>
  {svg_line(one_year_rows, color=color, fill_id=f"fill1y{index}", full_dates=True, max_points=96)}
  <h3>近3年净值趋势图</h3>
  {svg_line(three_year_rows, color=color, fill_id=f"fill3y{index}", full_dates=True, max_points=110)}
  <h3>回撤曲线</h3>
  {svg_multi_line([points_to_series(build_drawdown_points(three_year_rows), "回撤", "#b42318")], value_kind="pct", strong=True)}
  <h3>基金 vs 参考基准对比图</h3>
  {svg_multi_line(compare_series, value_kind="pct") if len(compare_series) > 1 else '<p class="note">未配置参考基准。</p>'}
</section>"""


def build_report(items, benchmarks, config, market_briefing):
    now = china_now().strftime("%Y-%m-%d %H:%M")
    title = config.get("title", "纳斯达克100基金定投日报")
    cards = "\n".join(build_card(item, benchmarks, idx) for idx, item in enumerate(items))
    data_rows = []
    for item in items:
        fund = item["fund"]
        summary = item["summary"]
        name = fund.get("label") or (item["estimate"] or {}).get("name") or fund["code"]
        daily_color = color_for(summary.get("daily_change"))
        data_rows.append(
            f"<tr><td>{html.escape(name)}</td><td>{summary['latest_date']}</td>"
            f"<td>{fmt_num(summary['latest_nav'])}</td>"
            f"<td style='color:{daily_color};font-weight:700'>{fmt_pct(summary.get('daily_change'))}</td>"
            f"<td>{fmt_pct(summary['return_7d'])}</td>"
            f"<td>{fmt_pct(summary['return_30d'])}</td>"
            f"<td>{fmt_pct(summary['return_1y'])}</td>"
            f"<td>{fmt_pct(summary['return_3y'])}</td>"
            f"<td>{fmt_pct(summary['drawdown_3y'], signed=False)}</td></tr>"
        )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
  body {{ margin: 0; background: #f4f7fb; color: #101828; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Arial, sans-serif; }}
  .wrap {{ max-width: 920px; margin: 0 auto; padding: 24px 14px 34px; }}
  .hero {{ padding: 26px 24px; border-radius: 8px; background: linear-gradient(135deg, #111827, #243b53 58%, #0f766e); color: #fff; }}
  .hero h1 {{ margin: 0 0 8px; font-size: 28px; }}
  .hero p {{ margin: 0; color: #d9e8f2; line-height: 1.65; }}
  .market-briefing {{ margin-top: 16px; padding: 18px; border-radius: 8px; background: #fff; color: #1d2939; }}
  .market-briefing h2 {{ margin: 4px 0 8px; font-size: 20px; }}
  .market-briefing p {{ color: #475467; }}
  .briefing-kicker {{ color: #0f766e; font-weight: 700; font-size: 12px; }}
  .briefing-tailwinds, .briefing-risks {{ margin-top: 12px; padding: 10px 12px; border-radius: 6px; }}
  .briefing-tailwinds {{ background: #ecfdf3; }}
  .briefing-risks {{ background: #fffaeb; }}
  .market-briefing ul {{ margin: 6px 0 0; padding-left: 18px; color: #475467; line-height: 1.65; }}
  .market-briefing small {{ color: #667085; }}
  .briefing-takeaway {{ display: flex; gap: 10px; margin-top: 12px; padding: 11px 12px; border-left: 4px solid #0f766e; background: #f0fdf4; border-radius: 6px; line-height: 1.6; }}
  .briefing-disclaimer, .briefing-fallback {{ display: block; margin-top: 10px; }}
  .fund-card {{ margin-top: 18px; padding: 22px; border: 1px solid #e4e7ec; border-radius: 8px; background: #fff; box-shadow: 0 12px 30px rgba(16, 24, 40, .06); }}
  .fund-head {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }}
  .fund-kicker {{ color: #667085; font-size: 13px; font-weight: 700; }}
  h2 {{ margin: 4px 0 4px; font-size: 22px; line-height: 1.25; }}
  h3 {{ margin: 22px 0 8px; font-size: 16px; color: #344054; }}
  .fund-head p {{ margin: 0; color: #667085; font-size: 13px; }}
  .change-panel {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 16px; padding: 16px; border: 1px solid; border-radius: 8px; }}
  .change-panel span, .change-panel small {{ display: block; color: #667085; font-size: 12px; }}
  .change-panel b {{ display: block; margin: 4px 0 2px; font-size: 16px; }}
  .change-panel strong {{ font-size: 34px; line-height: 1; white-space: nowrap; }}
  .metrics {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; margin-top: 18px; }}
  .metrics div {{ padding: 12px; background: #f8fafc; border: 1px solid #edf2f7; border-radius: 8px; }}
  .metrics span {{ display: block; color: #667085; font-size: 12px; margin-bottom: 5px; }}
  .metrics strong {{ font-size: 16px; }}
  .chart {{ width: 100%; height: auto; display: block; overflow: visible; }}
  .grid line {{ stroke: #e5e7eb; stroke-width: 1; }}
  .axis-label text, .date-label, .bar-value {{ fill: #667085; font-size: 12px; font-weight: 700; }}
  .legend text {{ fill: #475467; font-size: 12px; }}
  .zero-line {{ stroke: #98a2b3; stroke-width: 1.4; stroke-dasharray: 4 4; }}
  .guide-line {{ stroke: #edf2f7; stroke-width: 1; }}
  table {{ width: 100%; margin-top: 18px; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; }}
  th, td {{ padding: 11px 9px; border-bottom: 1px solid #eaecf0; font-size: 13px; text-align: left; }}
  th {{ background: #111827; color: #fff; }}
  .note {{ margin-top: 16px; color: #667085; line-height: 1.7; font-size: 13px; }}
  @media (max-width: 680px) {{ .fund-head {{ display: block; }} .change-panel {{ align-items: flex-start; }} .change-panel strong {{ font-size: 28px; }} .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} h2 {{ font-size: 19px; }} }}
</style>
</head>
<body>
<main class="wrap">
  <section class="hero">
    <h1>{html.escape(title)}</h1>
    <p>生成时间：{now}。{html.escape(config.get('source_note', '主数据固定使用基金代码 270042。'))}</p>
  </section>
  {render_market_briefing_html(market_briefing)}
  {cards}
  <table>
    <thead><tr><th>基金</th><th>净值日</th><th>最新净值</th><th>当日涨跌</th><th>近7日</th><th>近1月</th><th>近1年</th><th>近3年</th><th>最大回撤</th></tr></thead>
    <tbody>{''.join(data_rows)}</tbody>
  </table>
  <p class="note">说明：红色代表上涨，绿色代表下跌。主数据固定为支付宝可购买基金代码 270042（广发纳斯达克100ETF联接A）的净值/估算口径；参考基准仅用于趋势对照，不代表你的支付宝持仓数据。本简报仅用于定投节奏参考，不构成个性化投资建议。</p>
</main>
</body>
</html>"""


def build_pushplus_report(items, benchmarks, config, market_briefing):
    now = china_now().strftime("%Y-%m-%d %H:%M")
    title = config.get("title", "纳斯达克100基金定投日报")
    rows = []
    cards = []
    for item in items:
        fund = item["fund"]
        summary = item["summary"]
        estimate = item["estimate"] or {}
        name = fund.get("label") or estimate.get("name") or fund["code"]
        daily = fmt_pct(summary.get("daily_change"))
        daily_color = color_for(summary.get("daily_change"))
        r7 = fmt_pct(summary["return_7d"])
        one_month = fmt_pct(summary["return_30d"])
        one_year = fmt_pct(summary["return_1y"])
        three_year = fmt_pct(summary["return_3y"])
        drawdown = fmt_pct(summary["drawdown_3y"], signed=False)
        vol = fmt_pct(summary["vol_3y"], signed=False)

        rows.append(
            "<tr>"
            f"<td>{html.escape(name)}</td>"
            f"<td>{summary['latest_date']}</td>"
            f"<td>{fmt_num(summary['latest_nav'])}</td>"
            f"<td style='color:{daily_color};font-weight:700'>{daily}</td>"
            f"<td>{r7}</td>"
            f"<td>{one_year}</td>"
            f"<td>{drawdown}</td>"
            "</tr>"
        )
        cards.append(
            f"""
<section class="fund-card">
  <div class="fund-top">
    <div>
      <div class="code">{html.escape(fund['code'])} · 支付宝基金口径</div>
      <h2>{html.escape(name)}</h2>
      <p class="sub">净值日 {summary['latest_date']}</p>
    </div>
  </div>
  <div class="daily-box" style="border-color:{daily_color}55;background:{daily_color}10;">
    <span>{html.escape(summary.get('daily_change_label') or '涨跌')}</span>
    <b style="color:{daily_color};">{direction_text(summary.get('daily_change'))}</b>
    <strong style="color:{daily_color};">{daily}</strong>
  </div>
  <div class="metric-grid">
    <div><span>最新净值</span><b>{fmt_num(summary['latest_nav'])}</b></div>
    <div><span>近7净值日</span><b style="color:{color_for(summary['return_7d'])};">{r7}</b></div>
    <div><span>近1个月</span><b style="color:{color_for(summary['return_30d'])};">{one_month}</b></div>
    <div><span>近1年</span><b style="color:{color_for(summary['return_1y'])};">{one_year}</b></div>
    <div><span>近3年</span><b style="color:{color_for(summary['return_3y'])};">{three_year}</b></div>
    <div><span>最大回撤</span><b>{drawdown}</b></div>
    <div><span>年化波动</span><b>{vol}</b></div>
  </div>
  {pushplus_chart_images(item, benchmarks)}
</section>"""
        )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
  body {{ margin: 0; background: #f5f7fb; color: #101828; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Arial, sans-serif; }}
  .wrap {{ max-width: 760px; margin: 0 auto; padding: 14px 12px 22px; }}
  .hero {{ padding: 20px 18px; border-radius: 8px; background: #111827; color: #fff; }}
  h1 {{ font-size: 22px; line-height: 1.25; margin: 0 0 8px; }}
  .hero p {{ margin: 0; color: #d0d5dd; font-size: 13px; line-height: 1.7; }}
  .market-briefing {{ margin-top: 14px; padding: 15px 14px; border-radius: 8px; background: #fff; color: #1d2939; }}
  .market-briefing h2 {{ font-size: 18px; margin: 4px 0 7px; }}
  .market-briefing p {{ color: #475467; font-size: 13px; line-height: 1.7; }}
  .briefing-kicker {{ color: #0f766e; font-size: 12px; font-weight: 700; }}
  .briefing-tailwinds, .briefing-risks {{ margin-top: 10px; padding: 9px 10px; border-radius: 6px; font-size: 13px; }}
  .briefing-tailwinds {{ background: #ecfdf3; }}
  .briefing-risks {{ background: #fffaeb; }}
  .market-briefing ul {{ margin: 5px 0 0; padding-left: 17px; color: #475467; line-height: 1.6; }}
  .briefing-takeaway {{ margin-top: 10px; padding: 10px; border-left: 4px solid #0f766e; background: #f0fdf4; border-radius: 6px; line-height: 1.65; font-size: 13px; }}
  .briefing-takeaway b {{ display: block; margin-bottom: 3px; }}
  .briefing-disclaimer, .briefing-fallback {{ display: block; margin-top: 8px; color: #667085; font-size: 11px; }}
  .fund-card {{ margin-top: 14px; padding: 16px 14px; border: 1px solid #e4e7ec; border-radius: 8px; background: #fff; }}
  .fund-top {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }}
  .code {{ color: #667085; font-size: 12px; font-weight: 700; }}
  h2 {{ font-size: 19px; line-height: 1.3; margin: 4px 0 4px; }}
  .sub {{ margin: 0; color: #667085; font-size: 12px; }}
  .daily-box {{ margin-top: 12px; padding: 13px 12px; border: 1px solid; border-radius: 8px; }}
  .daily-box span {{ display: block; color: #667085; font-size: 12px; }}
  .daily-box b {{ display: inline-block; margin-top: 4px; font-size: 15px; }}
  .daily-box strong {{ float: right; font-size: 28px; line-height: 1.1; }}
  .metric-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 14px; }}
  .metric-grid div {{ padding: 10px; border-radius: 8px; background: #f8fafc; border: 1px solid #edf2f7; }}
  .metric-grid span {{ display: block; color: #667085; font-size: 12px; margin-bottom: 4px; }}
  .metric-grid b {{ font-size: 16px; }}
  .chart-card {{ margin-top: 12px; padding: 8px; border-radius: 8px; border: 1px solid #e4e7ec; background: #fff; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 14px; background: #fff; }}
  th, td {{ border-bottom: 1px solid #eaecf0; padding: 8px 6px; font-size: 12px; text-align: left; }}
  th {{ background: #111827; color: #fff; }}
  .note {{ color: #667085; font-size: 12px; line-height: 1.7; }}
</style>
</head>
<body>
  <main class="wrap">
    <section class="hero">
      <h1>{html.escape(title)}</h1>
      <p>生成时间：{now}。{html.escape(config.get('source_note', '主数据固定使用基金代码 270042。'))}</p>
    </section>
    {render_market_briefing_html(market_briefing, compact=True)}
    {''.join(cards)}
    <table>
      <thead><tr><th>基金</th><th>净值日</th><th>净值</th><th>当日</th><th>近7日</th><th>近1年</th><th>最大回撤</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    <p class="note">主数据固定为支付宝可购买基金代码 270042（广发纳斯达克100ETF联接A）的净值/估算口径；参考基准只用于对照，不代表你的支付宝持仓。本简报仅用于定投节奏参考，不构成个性化投资建议。</p>
  </main>
</body>
</html>"""


def collect_items(config, days):
    items = []
    for fund in config.get("funds", []):
        code = str(fund["code"]).strip()
        rows = fetch_history(code, days=days)
        estimate = fetch_estimate(code)
        summary = summarize(rows, estimate)
        items.append({"fund": fund, "rows": rows, "estimate": estimate, "summary": summary})
        time.sleep(0.2)
    return items


def collect_benchmarks(config, days):
    benchmarks = []
    for benchmark in config.get("benchmarks", []):
        try:
            benchmark_type = (benchmark.get("type") or "index").strip().lower()
            if benchmark_type == "fund":
                code = str(benchmark.get("code", "")).strip()
                if not code:
                    continue
                rows = fetch_history(code, days=days)
                benchmarks.append({"label": benchmark.get("label") or code, "color": benchmark.get("color", "#98a2b3"), "rows": rows, "use_trend": True})
            else:
                secid = str(benchmark.get("secid", "")).strip()
                if not secid:
                    continue
                data = fetch_index_history(secid, days=days)
                benchmarks.append({"label": benchmark.get("label") or data["label"], "color": benchmark.get("color", "#98a2b3"), "rows": data["rows"], "use_trend": False})
        except Exception as exc:
            print(f"WARN: benchmark skipped {benchmark}: {exc}", file=sys.stderr)
        time.sleep(0.15)
    return benchmarks


def send_pushplus(config, title, content):
    token = os.environ.get("PUSHPLUS_TOKEN") or config.get("pushplus_token")
    if not token:
        raise RuntimeError("未配置 PushPlus token")
    payload = {"token": token, "title": title, "content": content, "template": "html"}
    topic = config.get("pushplus_topic")
    if topic:
        payload["topic"] = topic
    result = http_post_json(PUSHPLUS_URL, payload, timeout=35, retries=5)
    try:
        result_data = json.loads(result)
    except json.JSONDecodeError:
        raise RuntimeError(f"PushPlus 返回了无法解析的响应: {result}") from None
    if result_data.get("code") != 200:
        msg = result_data.get("msg") or result_data.get("data") or result
        raise RuntimeError(f"PushPlus 发送失败: code={result_data.get('code')} msg={msg}")
    return result


def load_state(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def current_beijing_slot():
    """Return the scheduled report slot for the current Beijing time.

    Morning slot: 05:00-12:59 (covers the 11:00 CST run).
    Afternoon slot: 13:00-20:59 (covers the 16:00 CST run).
    Outside these windows the function returns None; manual runs outside
    scheduled hours will not be blocked by the twice-per-day guard.
    """
    hour = china_now().hour
    if 5 <= hour < 13:
        return "morning"
    if 13 <= hour < 21:
        return "afternoon"
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true", help="send report to PushPlus")
    parser.add_argument("--dry-run", action="store_true", help="generate report without sending")
    parser.add_argument("--twice-per-day", action="store_true", help="skip scheduled send if the current morning/afternoon slot was already sent")
    parser.add_argument("--force-send", action="store_true", help="ignore twice-per-day state, useful for manual test runs")
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_FILE.relative_to(BASE_DIR)), help="state file used by --twice-per-day")
    args = parser.parse_args()

    config = load_config()
    if not config.get("funds"):
        raise RuntimeError("配置里没有 funds")

    state_path = resolve_path(args.state_file)
    today = china_now().date().isoformat()
    slot = current_beijing_slot()
    state = load_state(state_path) if args.twice_per_day else {}
    if args.send and args.twice_per_day and not args.force_send and slot:
        slot_state = state.get(slot, {})
        if slot_state.get("date") == today:
            print(f"skip=already_sent slot={slot} date={today} sent_at={slot_state.get('sent_at', '')}")
            return

    REPORT_DIR.mkdir(exist_ok=True)
    days = required_history_days(config)
    items = collect_items(config, days)
    benchmarks = collect_benchmarks(config, days)
    market_briefing = build_market_briefing(items, config)
    report = build_report(items, benchmarks, config, market_briefing)
    out_path = REPORT_DIR / f"fund-report-{today}.html"
    out_path.write_text(report, encoding="utf-8")

    title = f"{config.get('title', '纳斯达克100基金定投日报')} {today}"
    print(f"report={out_path}")
    if args.send and not args.dry_run:
        push_content = build_pushplus_report(items, benchmarks, config, market_briefing)
        print(f"pushplus_content_chars={len(push_content)}")
        result = send_pushplus(config, title, push_content)
        print(result)
        if args.twice_per_day and slot and not args.force_send:
            latest = items[0]["summary"] if items else {}
            slot_state = {
                "date": today,
                "sent_at": china_now().isoformat(timespec="seconds"),
                "latest_nav_date": latest.get("latest_date"),
                "latest_nav": latest.get("latest_nav"),
            }
            state[slot] = slot_state
            # Keep a top-level last-sent record for human readability.
            state.update(
                {
                    "last_sent_date": today,
                    "last_sent_at": slot_state["sent_at"],
                    "fund_codes": [str(fund.get("code")) for fund in config.get("funds", [])],
                }
            )
            save_state(state_path, state)
            print(f"state={state_path} slot={slot}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
