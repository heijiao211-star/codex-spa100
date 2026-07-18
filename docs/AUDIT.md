# 代码结构与数据审计

审计分支：`main`（合并修复后的版本）。完整日报的实际生成代码曾位于根目录 `daily_fund_report.py`；`daily_fund_report_runtime.py` 只覆写 QuickChart 配置。并不存在另一个截图日报生成器，因此没有修改 `scripts/monitor.py` 之类的旁支文件。

## 旧调用链（已废弃）

`daily_fund_report.py: main()` → 东方财富历史/估算接口 → 正则清洗 → `summarize()` → SVG / QuickChart → `build_report()` / `build_pushplus_report()` → PushPlus → `.github/fund-report-state.json`。

旧实现的主要问题是：

1. 将 `270042` 写死为“主数据”，容易被误认为能代表其他基金；
2. 用估算涨跌替换正式日涨跌；
3. 以接口返回条数而非日期覆盖判断近 1 年/近 3 年；
4. 指标在数据不足时仍可能显示；
5. 申购状态来自净值页面且失败路径不透明；
6. 抓取、计算、渲染、保存、推送堆在单文件；
7. 历史写入没有唯一键和原子替换；
8. AI 模块会把非固定来源的摘要混入事实陈述。

## 新调用链

`daily_fund_report.py` → `fund_report.main.run()` → `EastmoneyNavSource.fetch_nav_history()`（分页） → `validate_nav_history()` → `performance_summary()` / `resolve_subscription()` → `renderer.render_html()` → `notifications.send_pushplus()` → `HistoryStore.upsert()` / 原子状态写入。

源码结构：

| 模块 | 职责 |
| --- | --- |
| `src/fund_report/models.py` | FundIdentity、SourceMetadata、NAV、估算、申购状态模型 |
| `sources.py` | 有限重试 HTTP、东方财富备用数据、金额解析、公告状态机 |
| `metrics.py` | 日期锚定收益、最大回撤、样本年化波动、CAGR |
| `renderer.py` | 移动端 HTML 与 PushPlus 摘要 |
| `storage.py` | 原子 JSON 写入与幂等历史表 |
| `notifications.py` | PushPlus 超时、重试及响应校验 |
| `main.py` | 编排、质量摘要、按基金降级和推送门禁 |

## 字段来源映射

| 数据块 / 字段 | 当前来源 | 类型 / 级别 | 是否支付宝数据 | 日期与新鲜度 |
| --- | --- | --- | --- | --- |
| `official_nav.*` | 东方财富 `f10/lsjz` | 第三方公开备用 / 3 | 否 | `nav_date` 与 `fetched_at` 均输出 |
| `estimate.*` | 东方财富 `fundgz` | 模型/第三方估算 / 4 | 否 | `estimated_nav_date`、`estimate_generated_at` 输出 |
| `official_account_limit` | 已核验基金公司公告配置 | 官方 / 1；未配置则 null | 否 | 公告/生效/失效日期输出 |
| `public_channel_reference_limit` | 已核验公开渠道配置 | 公开渠道 / 2-3；未配置则 null | 否 | 来源链接和核验时间输出 |
| `alipay_verified_limit` | 用户手工输入或授权导入 | 手工/授权 | 仅该字段可能是 | `updated_at` 应由用户填写 |
| 个人持仓、成本、订单、费率 | 不抓取 | `NOT_AVAILABLE` | 否 | `MANUAL_REQUIRED` |
| 基准、目标 ETF、指数 | `config/funds.json` 的产品元数据 | 手工配置，待官方资料核验 | 否 | 无价格序列时不绘制“官方基准” |
| 市场信息 | `ai_news` 中带原始链接的手工核验项目 | 显式来源 | 否 | 需发布/事件日期 |
| USD/CNY / 美元资产参考 | 可选 `market_reference` 手工核验配置 | 市场参考，非官方净值 | 否 | 汇率日与美股交易日单独输出 |

当前默认没有基金管理人机器可读 NAV 接口、官方公告库、支付宝授权接口或受核验的汇率/指数序列。因此这些项目不会被捏造；报告以 `DEGRADED` 表示第三方 NAV 备用数据。

