# 美股指数基金定投日报

每天生成一份面向支付宝基金口径的纳斯达克100和标普500指数基金简报，并通过 PushPlus 推送到微信。

## 运行

```powershell
.\run_report.ps1
```

只生成本地报告、不推送：

```powershell
& "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" .\daily_fund_report.py --dry-run
```

报告会保存到 `reports/` 目录。

## 更换基金

编辑 `config.local.json` 里的 `funds`，把 `code` 改成你在支付宝实际定投的基金代码即可。当前默认：

- `270042`：广发纳斯达克100ETF联接人民币(QDII)A
- `050025`：博时标普500ETF联接A

## 数据口径

- 历史净值：东方财富基金 F10 历史净值
- 当日估算：天天基金估算接口，有估算则显示估算涨跌，没有估算则回退到最新公布净值涨跌

QDII 基金通常存在净值披露延迟，报告中的“当天”更准确地说是“当前可取得的最新净值/估算时间”。

## 云端定时推送

如果使用 GitHub Actions，把本目录提交到 GitHub 仓库，然后在仓库设置里添加 Secret：

- `PUSHPLUS_TOKEN`：你的 PushPlus token

`.github/workflows/daily-fund-report.yml` 已配置为每天北京时间 08:30 推送，也支持在 Actions 页面手动点击 `Run workflow` 发送测试。
