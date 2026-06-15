import html
import math
import sys
import time

import daily_fund_report as report


# QuickChart receives pure JSON, so JavaScript callback strings are rendered as
# plain strings and cause the English "is not a function" chart error. Keep the
# axis numeric and put the percent sign in chart titles / labels instead.
def fixed_tick_options(y_suffix="", min_value=None, max_value=None):
    ticks = {"fontColor": "#667085", "fontSize": 11, "padding": 6}
    if min_value is not None:
        ticks["min"] = min_value
    if max_value is not None:
        ticks["max"] = max_value
    if y_suffix == "%":
        ticks["maxTicksLimit"] = 7
    return ticks


def fixed_chart_line_config(title, series_list, y_suffix="", max_points=90, strong=False, min_value=None, max_value=None):
    config = report.chart_line_config(title, series_list, y_suffix, max_points, strong, min_value, max_value)
    y_axis = config["options"]["scales"]["yAxes"][0]
    y_axis["ticks"] = fixed_tick_options(y_suffix, min_value, max_value)
    if y_suffix == "%":
        y_axis["scaleLabel"] = {
            "display": True,
            "labelString": "比例（%）",
            "fontColor": "#667085",
            "fontSize": 11,
        }
    return config


def fixed_chart_bar_config(title, rows):
    rows = rows[-7:]
    vals = [row["growth"] if row.get("growth") is not None else 0 for row in rows]
    limit = max(0.25, max(abs(v) for v in vals) * 1.45) if vals else 1
    nice_limit = math.ceil(limit * 10) / 10
    return {
        "type": "bar",
        "data": {
            "labels": [row["date"][5:] for row in rows],
            "datasets": [
                {
                    "label": "日涨跌（%）",
                    "data": vals,
                    "backgroundColor": ["#d92d20" if val >= 0 else "#039855" for val in vals],
                    "barPercentage": 0.82,
                    "categoryPercentage": 0.78,
                }
            ],
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "layout": {"padding": {"left": 10, "right": 14, "top": 12, "bottom": 8}},
            "title": {
                "display": True,
                "text": f"{title}（纵轴：涨跌幅%）",
                "fontSize": 18,
                "fontColor": "#111827",
                "fontStyle": "600",
                "padding": 16,
            },
            "legend": {"display": False},
            "scales": {
                "xAxes": [
                    {
                        "gridLines": {"display": False, "drawBorder": False},
                        "ticks": {"fontColor": "#667085", "fontSize": 11},
                    }
                ],
                "yAxes": [
                    {
                        "gridLines": {
                            "color": "#eef2f6",
                            "drawBorder": False,
                            "zeroLineColor": "#98a2b3",
                            "zeroLineWidth": 1.5,
                        },
                        "ticks": fixed_tick_options("%", -nice_limit, nice_limit),
                        "scaleLabel": {
                            "display": True,
                            "labelString": "涨跌幅（%）",
                            "fontColor": "#667085",
                            "fontSize": 11,
                        },
                    }
                ],
            },
        },
    }


def change_detail_table(rows):
    rows = rows[-7:]
    cells = []
    for row in rows:
        val = row.get("growth")
        color = report.color_for(val)
        cells.append(
            "<td style='padding:7px 6px;border:1px solid #eaecf0;text-align:center;'>"
            f"<div style='color:#667085;font-size:12px;'>{html.escape(row['date'][5:])}</div>"
            f"<div style='color:{color};font-weight:700;font-size:14px;'>{report.fmt_pct(val)}</div>"
            "</td>"
        )
    return (
        "<table style='width:100%;border-collapse:collapse;margin-top:8px;background:#fff;'>"
        "<tbody><tr>" + "".join(cells) + "</tr></tbody></table>"
    )


def fixed_pushplus_chart_images(item, benchmarks):
    fund = item["fund"]
    rows = item["rows"]
    estimate = item["estimate"] or {}
    name = fund.get("label") or estimate.get("name") or fund["code"]
    color = fund.get("color", "#2563eb")
    seven_rows = rows[-7:]
    one_month_rows = report.rows_since_calendar_days(rows, 30)
    one_year_rows = report.rows_since_calendar_days(rows, 365)
    three_year_rows = report.rows_since_calendar_days(rows, 365 * 3)
    drawdown_points = report.build_drawdown_points(three_year_rows)
    min_drawdown = min((point["value"] for point in drawdown_points), default=-1)
    drawdown_floor = min(-1, math.floor(min_drawdown) - 1)

    chart_specs = [
        (
            f"{name} 近7个净值日趋势",
            fixed_chart_line_config(
                f"{name} 近7个净值日趋势",
                [report.rows_to_series(seven_rows, "净值", color, use_trend=True)],
                max_points=7,
                strong=True,
            ),
            "",
        ),
        (
            f"{name} 近7个净值日涨跌",
            fixed_chart_bar_config(f"{name} 近7个净值日涨跌", rows),
            change_detail_table(rows),
        ),
        (
            f"{name} 近1个月净值趋势",
            fixed_chart_line_config(
                f"{name} 近1个月净值趋势",
                [report.rows_to_series(one_month_rows, "净值", color, use_trend=True)],
                max_points=42,
                strong=True,
            ),
            "",
        ),
        (
            f"{name} 近1年净值趋势",
            fixed_chart_line_config(
                f"{name} 近1年净值趋势",
                [report.rows_to_series(one_year_rows, "净值", color, use_trend=True)],
                max_points=90,
                strong=True,
            ),
            "",
        ),
        (
            f"{name} 近3年净值趋势",
            fixed_chart_line_config(
                f"{name} 近3年净值趋势",
                [report.rows_to_series(three_year_rows, "净值", color, use_trend=True)],
                max_points=110,
                strong=True,
            ),
            "",
        ),
        (
            f"{name} 回撤曲线",
            fixed_chart_line_config(
                f"{name} 回撤曲线（纵轴：回撤%）",
                [report.points_to_series(drawdown_points, "回撤", "#b42318")],
                y_suffix="%",
                max_points=140,
                strong=True,
                min_value=drawdown_floor,
                max_value=0,
            ),
            f"<p class='note'>回撤区间：{report.fmt_pct(min_drawdown, signed=False)} 至 0%，纵轴已按实际回撤范围放大。</p>",
        ),
    ]

    compare_series = [report.rows_to_series(three_year_rows, name, color, normalize=True, use_trend=True)]
    for benchmark in benchmarks:
        compare_series.append(
            report.rows_to_series(
                benchmark["rows"],
                benchmark["label"],
                benchmark["color"],
                days=365 * 3,
                normalize=True,
                use_trend=benchmark.get("use_trend", False),
            )
        )
    if len(compare_series) > 1:
        chart_specs.append(
            (
                f"{name} vs 参考基准",
                fixed_chart_line_config(f"{name} vs 参考基准（收益率%）", compare_series, y_suffix="%", max_points=110),
                "",
            )
        )

    images = []
    for alt, config, extra_html in chart_specs:
        try:
            images.append(report.image_html(report.quickchart_url(config), alt))
            if extra_html:
                images.append(extra_html)
            time.sleep(0.12)
        except Exception as exc:
            print(f"WARN: chart failed {alt}: {exc}", file=sys.stderr)
            images.append(f"<p class='note'>图表生成失败：{html.escape(alt)}。文字数据仍已正常生成。</p>")
    return "".join(images)


report.quickchart_tick_options = fixed_tick_options
report.chart_line_config = fixed_chart_line_config
report.chart_bar_config = fixed_chart_bar_config
report.pushplus_chart_images = fixed_pushplus_chart_images


if __name__ == "__main__":
    report.main()
