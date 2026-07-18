# GitHub Actions 配置

工作流 `.github/workflows/daily-fund-report.yml` 每天北京时间 11:07、16:17 运行，也支持手动 `workflow_dispatch`。

## 必需 Secret

- `PUSHPLUS_TOKEN`：PushPlus 用户 token。

不要配置或提交支付宝 Cookie、登录信息、个人持仓、订单截图、费率优惠或 Token。当前项目没有支付宝授权接口，也不会尝试绕过登录、验证码或风控。

## 工作流门禁

执行顺序：安装锁定工具 → Ruff → Mypy → Pytest → 公开数据抓取与校验 → JSON Schema 校验 → PushPlus → 保存公开历史与时段状态。

如果抓取失败，报告会标为 `FAILED`；若只能使用第三方公开净值源，报告会标为 `DEGRADED`。PushPlus 标题会携带状态，不会把异常数据写成正常收益日报。

## 持久化内容

工作流只提交 `data/latest.json`、`data/history.json` 和 `.github/fund-report-state.json`。完整 HTML 通过 Actions Artifact 保存。`history.json` 以基金代码、数据类型、数据日期与来源名称作为唯一键，重复运行不会重复追加。

## 手动发送

Actions 页选择 **Daily fund report** → **Run workflow** → `force_send=true`。该选项只跳过同一时段去重，不会篡改正式时段状态。

