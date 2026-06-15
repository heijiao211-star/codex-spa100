$ErrorActionPreference = "Stop"

$Python = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$Script = Join-Path $PSScriptRoot "daily_fund_report_runtime.py"

& $Python $Script --send
