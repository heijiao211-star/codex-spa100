$ErrorActionPreference = "Stop"

param(
    [Parameter(Mandatory = $true)]
    [string]$RemoteUrl
)

$repoRoot = $PSScriptRoot
Set-Location $repoRoot

function Require-Git {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "git 未安装，无法发布到 GitHub。"
    }
}

function Ensure-Repo {
    if (-not (Test-Path (Join-Path $repoRoot ".git"))) {
        git init | Out-Null
    }

    git branch -M main
}

function Ensure-Identity {
    $name = git config --get user.name
    $email = git config --get user.email

    if ([string]::IsNullOrWhiteSpace($name)) {
        git config user.name "Codex Local"
    }

    if ([string]::IsNullOrWhiteSpace($email)) {
        git config user.email "codex-local@example.invalid"
    }
}

function Configure-Remote {
    $hasOrigin = git remote get-url origin 2>$null
    if ($LASTEXITCODE -eq 0 -and $hasOrigin) {
        git remote set-url origin $RemoteUrl
        return
    }

    git remote add origin $RemoteUrl
}

Require-Git
Ensure-Repo
Ensure-Identity
Configure-Remote

git add .github/workflows/daily-fund-report.yml
git add daily_fund_report.py
git add run_report.ps1
git add config.json
git add config.example.json
git add README.md
git add GITHUB_ACTIONS_SETUP.md
git add publish_to_github.ps1
git add .gitignore

$status = git status --short
if (-not [string]::IsNullOrWhiteSpace($status)) {
    git commit -m "Set up daily fund report automation"
}

git push -u origin main
