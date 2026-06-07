# GitHub Actions Setup

This project is already prepared for scheduled delivery through GitHub Actions.

## What is already configured

- Workflow file: `.github/workflows/daily-fund-report.yml`
- Schedule: every day at `08:30` Asia/Shanghai
- Manual test trigger: `workflow_dispatch`
- PushPlus token source: GitHub Actions secret `PUSHPLUS_TOKEN`

## Files to push to GitHub

Push these files and folders:

- `.github/workflows/daily-fund-report.yml`
- `daily_fund_report.py`
- `config.json`
- `config.example.json`
- `README.md`

Do not push:

- `config.local.json`
- `reports/`

`config.local.json` is already ignored by `.gitignore` and should stay local because it contains your real PushPlus token.

## One-time setup

1. Create a new GitHub repository.
2. Push this project to that repository.
3. In GitHub, open `Settings > Secrets and variables > Actions`.
4. Create a new repository secret named `PUSHPLUS_TOKEN`.
5. Paste your real PushPlus token as the secret value.
6. Open the `Actions` tab and enable workflows if GitHub asks.
7. Run `Daily fund report` once with `Run workflow` to verify the first delivery.

## Fastest way to push

After you create an empty GitHub repository, run:

```powershell
.\publish_to_github.ps1 -RemoteUrl https://github.com/YOUR_NAME/YOUR_REPO.git
```

The script will:

- initialize a local git repository if needed
- create or update remote `origin`
- commit only the files needed for automation
- push branch `main`

## Fund configuration

The workflow reads fund definitions from `config.json`.

If you want to change the tracked funds, edit `config.json` before pushing:

- Nasdaq 100 QDII fund code
- S&P 500 QDII fund code
- labels and colors

Do not store the PushPlus token in `config.json`; GitHub Actions provides it through the `PUSHPLUS_TOKEN` secret.

## How it runs

GitHub Actions runs:

```yaml
python daily_fund_report.py --send
```

The script already supports this flow:

- load fund settings from `config.json`
- read `PUSHPLUS_TOKEN` from environment
- fetch latest fund history and estimate data
- generate the HTML report
- send the report through PushPlus

## If delivery stops later

Check these places first:

- `Actions > Daily fund report > latest run`
- secret `PUSHPLUS_TOKEN` still exists
- `config.json` still contains valid fund codes
- GitHub Actions is enabled for the repository
