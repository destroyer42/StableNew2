<#
.SYNOPSIS
Canonical one-command Windows launcher for StableNew (PR-DEVEX-LAUNCH-180).

.DESCRIPTION
Resolves the repository from this script's own location, makes sure the supported repository .venv exists, and
starts the application with exactly that venv's interpreter:

    <repo>\.venv\Scripts\python.exe -m src.main [arguments]

* A missing .venv is created once through scripts/bootstrap_windows.ps1 (-SkipSvdReadiness), the existing
  bootstrap authority. System Python is used only there, as the source for creating the venv.
* A healthy .venv is reused: one read-only check (interpreter policy + exact pins through
  tools/runtime/check_launch_environment.py), no pip, no install, no venv creation.
* An incomplete, unsupported or drifted .venv stops with an actionable message. It is never deleted,
  recreated or repaired here, and the application is never started with another Python.
* The launcher does not start, stop or select A1111, Forge, Comfy or SVD; the application owns those.

Every argument is forwarded to src.main and the application's exit code is returned. Launcher failures exit with
10 (bootstrap failed), 11 (environment unusable) or 12 (not a StableNew checkout).
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExitBootstrapFailed = 10
$ExitEnvironmentUnusable = 11
$ExitNotACheckout = 12

function Stop-Launch {
    param(
        [Parameter(Mandatory = $true)][int]$Code,
        [Parameter(Mandatory = $true)][string[]]$Lines
    )

    Write-Host ""
    Write-Host "StableNew was not started." -ForegroundColor Red
    foreach ($line in $Lines) {
        Write-Host $line
    }
    exit $Code
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    # Native stderr must be collected, not turned into a terminating error by $ErrorActionPreference.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $Executable @Arguments 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    return [pscustomobject]@{ ExitCode = $code; Output = @($output) }
}

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$VenvPath = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"
$Bootstrap = Join-Path $PSScriptRoot "bootstrap_windows.ps1"
$EnvironmentCheck = Join-Path $RepoRoot "tools\runtime\check_launch_environment.py"
$BootstrapCheckCommand = ".\scripts\bootstrap_windows.ps1 -CheckOnly -SkipSvdReadiness"

if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot "src\main.py") -PathType Leaf)) {
    Stop-Launch $ExitNotACheckout @(
        "'$RepoRoot' is not a StableNew checkout (src\main.py is missing).",
        "Run this launcher from the StableNew repository's scripts folder."
    )
}

if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    if (Test-Path -LiteralPath $VenvPath) {
        $existing = @(Get-ChildItem -LiteralPath $VenvPath -Force)
        if ($existing.Count -gt 0) {
            Stop-Launch $ExitEnvironmentUnusable @(
                "The existing .venv at '$VenvPath' is incomplete (no Scripts\python.exe).",
                "It was left untouched. Inspect it, or deliberately rebuild this dedicated venv with:",
                "  .\scripts\bootstrap_windows.ps1 -Recreate -SkipSvdReadiness"
            )
        }
    }

    Write-Host "StableNew: no .venv found; creating the supported environment (this installs packages once)."
    $shell = (Get-Process -Id $PID).Path
    & $shell -NoProfile -ExecutionPolicy Bypass -File $Bootstrap -SkipSvdReadiness
    if ($LASTEXITCODE -ne 0) {
        Stop-Launch $ExitBootstrapFailed @(
            "Environment bootstrap failed (exit code $LASTEXITCODE); see the messages above.",
            "Fix the reported problem (for example install official standard-GIL Python 3.14) and launch again.",
            "Details: docs\runbooks\windows_runtime_bootstrap.md"
        )
    }
    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        Stop-Launch $ExitBootstrapFailed @(
            "Environment bootstrap finished but '$VenvPython' does not exist.",
            "Details: docs\runbooks\windows_runtime_bootstrap.md"
        )
    }
}

# Healthy .venv: one read-only check with the venv's own interpreter (no pip, no install, no venv creation).
$check = Invoke-Native -Executable $VenvPython -Arguments @($EnvironmentCheck)
if ($check.ExitCode -ne 0) {
    $lines = @("The .venv at '$VenvPath' is not a supported StableNew environment:")
    $lines += $check.Output | ForEach-Object { "  $_" }
    $lines += @(
        "It was left untouched and no other Python was tried. To diagnose:",
        "  $BootstrapCheckCommand",
        "To rebuild this dedicated venv deliberately:",
        "  .\scripts\bootstrap_windows.ps1 -Recreate -SkipSvdReadiness"
    )
    Stop-Launch $ExitEnvironmentUnusable $lines
}

Push-Location -LiteralPath $RepoRoot
try {
    & $VenvPython -m src.main @args
    $applicationExit = $LASTEXITCODE
} catch {
    Pop-Location
    Stop-Launch $ExitEnvironmentUnusable @("Could not start '$VenvPython': $($_.Exception.Message)")
}
Pop-Location
exit $applicationExit
