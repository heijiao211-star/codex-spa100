# 纳斯达克100基金定投日报

每天生成一份面向支付宝基金口径的纳斯达克 100 QDII 基金简报，并通过 PushPlus 推送到微信。

## 运行

```powershell
.\run_report.ps1
```

只生成本地报告，不推送：

```powershell
& "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" .\daily_fund_report.py --dry-run
```

报告会保存到 `reports/` 目录。

## 现在支持的内容

- 近 1 个月收益率
- 近 3 年收益率
- 最大回撤
- 年化波动率
- 近 1 个月净值趋势图
- 近 3 年净值趋势图
- 回撤曲线
- 基金 vs 纳斯达克100ETF 对比图

## 修改基金代码

编辑 `config.json` 或 `config.local.json` 的 `funds`：

- `code`：基金代码
- `label`：展示名称
- `color`：图表颜色

当前默认：

- `270042`：纳斯达克100 · 广发纳指ETF联接A

## 基准配置

默认会拉取一个可投资基准代理：

- `513300`：纳斯达克100ETF

如需修改，编辑配置文件中的 `benchmarks`。

## 数据口径

- 基金历史净值：东方财富基金 F10 历史净值
- 当日估算：天天基金估算接口
- 基准对比：默认使用可投资 ETF / 联接基金代理；如需改成指数直连，可在 `benchmarks` 中改成 `type: "index"` + `secid`

QDII 基金通常存在净值披露延迟，简报中的“当日”更准确地说是“当前可取得的最新净值 / 估算时间”。

## 云端定时推送

如使用 GitHub Actions，把目录提交到 GitHub 仓库，然后在仓库设置中添加 Secret：

- `PUSHPLUS_TOKEN`：你的 PushPlus token

注意这里需要填 PushPlus 官网“发送消息”页面里的用户 token，不是 SecretKey。填错时脚本会明确报 `PushPlus 发送失败`，避免误以为发送成功。

`.github/workflows/daily-fund-report.yml` 已配置为每天北京时间 08:30 推送，也支持在 Actions 页面手动点击 `Run workflow` 测试。
