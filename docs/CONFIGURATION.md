# 配置说明

`config/funds.json` 中每个基金都必须有独立 `code` 与身份字段。`official_product_url`、`official_announcement_url`、`target_etf` 和严格合同口径的 `official_benchmark` 未经核验时请保持 `null` 或写明“以基金合同为准”，不要填入推测值。

## 公告状态机

在私有 `config.local.json` 的 `subscription_announcements` 增加记录。解析器按基金代码、份额类别、币种和报告日过滤，再按生效日期选择最新有效记录。建议字段：

```json
{
  "fund_code": "270042",
  "share_class": "人民币A",
  "currency": "CNY",
  "status": "LIMITED",
  "official_account_limit": "10000元",
  "announcement_date": "2026-01-01",
  "effective_date": "2026-01-02",
  "expiry_date": null,
  "business_scope": "申购、定投",
  "source_url": "https://基金管理人公告链接"
}
```

状态只能为 `OPEN`、`LIMITED`、`PAUSED`、`CLOSED`、`UNKNOWN`、`FETCH_FAILED`、`SOURCE_CONFLICT`。抓取或核验失败不得填 `0`；仅正式暂停/关闭记录可以表现为 `0`。

## 支付宝手工数据

`manual_alipay` 只用于用户明确核验的私有数据。它不会自动访问支付宝，且不应被提交。支持：`alipay_verified_limit`、`user_planned_amount`、`actual_order_amount`、`updated_at`。个人份额、成本、订单、实际收益需要另行导入设计，当前统一为 `MANUAL_REQUIRED`。

金额内部使用 `Decimal`，支持 `10元`、`100.00元`、`2,000元`、`1万元`、`10万元`、`100万美元`、`不限额`、`暂停申购`。

## 汇率与美元资产参考

可选 `market_reference` 只接受已核验的手工输入，并要求分别填写美元资产交易日和汇率日期。人民币市场参考计算为 `(1 + 美元资产收益率) × (1 + USD/CNY 变动率) - 1`；`USD/CNY` 上涨表示美元相对人民币升值。它始终标为非官方市场参考，不等于基金正式净值，未配置时各字段均为 `null`。

