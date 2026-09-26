[CmdletBinding()]
param(
    [string[]]$TargetedTest = @(),
    [switch]$FullGate,
    [switch]$AllowMain
)

$ErrorActionPreference = "Stop"

$root = git rev-parse --show-toplevel 2>$null
if (-not $root) {
    throw "Not inside a Git repository."
}

Push-Location $root
try {
    $branch = git branch --show-current
    if (-not $AllowMain -and $branch -eq "main") {
        throw "Refusing agent preflight on main. Use a feature branch/worktree."
    }

    Write-Host "==> Git state"
    & "$PSScriptRoot\agent_context.ps1"

    Write-Host "==> Diff whitespace/conflict check"
    git diff --check
    if ($LASTEXITCODE -ne 0) {
        throw "git diff --check failed."
    }

    foreach ($test in $TargetedTest) {
        if ([string]::IsNullOrWhiteSpace($test)) { continue }
        Write-Host "==> Targeted pytest: $test"
        python -m pytest $test -q
        if ($LASTEXITCODE -ne 0) {
            throw "Targeted test failed: $test"
        }
    }

    if ($FullGate) {
        Write-Host "==> StableNew PR gate"
        python tools/ci/run_pr_gate.py
        if ($LASTEXITCODE -ne 0) {
            throw "StableNew PR gate failed."
        }
    }

    Write-Host "==> Final diff summary"
    git diff --stat
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to produce diff summary."
    }

    Write-Host "AGENT PREFLIGHT OK"
}
finally {
    Pop-Location
}
