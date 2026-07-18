# 支付宝可购买纳斯达克100场外基金日报

这是一个面向中国境内场外公募 QDII 基金的公开数据日报。它不会登录支付宝、不会读取支付宝账户，也不会把纳斯达克股票、美国 ETF 或指数当作用户直接持仓。

默认基金清单在 [`config/funds.json`](config/funds.json)：`270042`、`000834`、`019172`。每只基金以自己的代码独立抓取净值；`platform: 支付宝（购买渠道）` 只说明购买渠道，不代表数据由支付宝提供。

## 数据边界

- 正式净值：优先预留基金管理人官方源；当前默认实现使用东方财富公开接口作为第三方备用，报告会明确标记为降级数据。
- 下一待公布净值估算：与正式净值分开显示，且始终标记为非官方、低可信度。
- 支付宝限额、优惠费率、持仓、成本、待确认订单和实际收益：默认 `NOT_AVAILABLE` / `NOT_VERIFIED` / `MANUAL_REQUIRED`。只有用户手工填写或导入授权数据后才会显示。
- 申购公告：只读取 `subscription_announcements` 中有来源链接、日期、份额与币种的已核验记录；没有记录时金额为 `null`，绝不把未知写成 `0`。

完整审计、字段映射和迁移说明见 [`docs/AUDIT.md`](docs/AUDIT.md)、[`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) 与 [`docs/MIGRATION.md`](docs/MIGRATION.md)。

## 本地运行

```powershell
$env:PYTHONPATH = "src"
python .\daily_fund_report.py --dry-run
```

输出：

- `reports/fund-report-YYYY-MM-DD.html`：完整移动端 HTML；
- `data/latest.json`：版本化最新快照；
- `data/history.json`：按 `fund_code + data_type + data_date + source_name` 幂等保存的公开净值历史。

发送前请通过环境变量配置令牌，而不是提交到仓库：

```powershell
$env:PUSHPLUS_TOKEN = "..."
python .\daily_fund_report.py --send --force-send
```

## GitHub Actions

工作流在北京时间 11:07 和 16:17 运行。顺序是：依赖安装 → 静态检查 → 单元测试 → 抓取 → 数据验证 → 生成报告 → PushPlus → 保存公开历史。需要的唯一必需 Secret 是 `PUSHPLUS_TOKEN`。

手动运行时选择 `force_send=true` 可跳过时段去重。不要重跑旧版失败任务；它会使用旧提交。

## 配置个人支付宝数据

仅在私有的 `config.local.json` 里填入 `manual_alipay`。公开仓库不得提交持仓、订单、截图、费用优惠或 Token。没有经过授权的支付宝接口或用户导入文件时，页面不会伪装为“已同步支付宝账户”。


