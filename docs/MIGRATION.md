# 旧版到 schema 2.0 的字段迁移

| 旧字段/展示 | 新字段 | 迁移规则 |
| --- | --- | --- |
| `daily_change` | `official_nav.daily_return` | 仅正式 NAV 日涨跌 |
| `estimated_growth` | `estimate.estimated_return` | 永远单独展示且 `is_official=false` |
| `latest_nav` | `official_nav.unit_nav` | 保存为字符串，避免金额/净值浮点误差 |
| `return_1y` / `return_3y` | `performance.periods.*.return` | 仅日期完整覆盖时有值，否则 null |
| `drawdown_3y` | `performance.risk.*_max_drawdown` | 包含峰值、低点、恢复、区间与样本数 |
| `subscription_amount` | `subscription.*_limit` | 拆分公告限额、公开参考、支付宝核验和个人金额 |
| `history.csv append` | `data/history.json` | 用四字段唯一键更新，并原子写入 |
| 单一主基金 | `funds[]` | 每个基金独立抓取和计算，270042 不再代表其他基金 |

旧报告里任何以 `270042` 代替其他基金、把估算写成当日正式收益、把未知申购金额写为零的下游消费代码，都应停止读取旧字段。


