<#
.SYNOPSIS
Fast-forward the live StableNew checkout to an approved origin/main commit and relaunch the app (LAUNCH-UPDATE-1).

.DESCRIPTION
Started only by the running StableNew app (src/app/live_update.py), as a detached process, after its own preflight
passed and its queue finished the running job. The app then exits. This script:

1. Waits up to -ExitWaitSeconds for the old app process (-OldPid) to exit. It never stops or kills it; if the old app
   is still running, it reports old_app_did_not_exit and changes nothing.
2. Re-checks the checkout: branch main, upstream origin/main, no staged or modified tracked files, HEAD still -OldSha,
   origin/main still -TargetSha, and -OldSha an ancestor of -TargetSha.
3. Runs "git merge --ff-only <TargetSha>". Only tracked files that differ between the two commits change.
4. Starts scripts\launch_stablenew.ps1 minimized and waits up to -HealthSeconds for the new app's started marker.
   If the launch exits first (for example exit 11, an environment the launcher refuses), it moves local main back with
   "git reset --keep <OldSha>" (owner decision D7; origin is never touched) and relaunches the old code.
5. Writes <StateDir>\result.json for the app to report.

Whenever the old app has exited, the app is relaunched, so a refusal never leaves the PC without StableNew. Nothing is
installed, fetched, pushed or deleted here. Git is called with argument lists only; both SHAs are validated first.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$StateDir,
    [Parameter(Mandatory = $true)][int]$OldPid,
    [Parameter(Mandatory = $true)][string]$OldSha,
    [Parameter(Mandatory = $true)][string]$TargetSha,
    [int]$ExitWaitSeconds = 120,
    [int]$HealthSeconds = 180
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ResultPath = Join-Path $StateDir "result.json"
$IntentPath = Join-Path $StateDir "intent.json"
$MarkerPath = Join-Path $StateDir "started.json"
$Launcher = Join-Path $RepoRoot "scripts\launch_stablenew.ps1"
$Shell = (Get-Process -Id $PID).Path
$env:GIT_TERMINAL_PROMPT = "0"

$UpdateId = ""
try {
    $UpdateId = [string]((Get-Content -LiteralPath $IntentPath -Raw | ConvertFrom-Json).update_id)
} catch {
    $UpdateId = ""
}

function Write-Result {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [string]$Reason = "",
        [string]$NewSha = "",
        [string]$Detail = "",
        [string]$Health = ""
    )

    $payload = [ordered]@{
        update_id = $UpdateId
        status = $Status
        reason = $Reason
        old_sha = $OldSha
        new_sha = $NewSha
        health = $Health
        detail = $Detail
        finished_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    }
    $temporary = "$ResultPath.tmp"
    $payload | ConvertTo-Json -Compress | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $ResultPath -Force
}

function Invoke-Git {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & git -C $RepoRoot @Arguments 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    return [pscustomobject]@{ ExitCode = $code; Text = (@($output) -join "`n").Trim() }
}

function Start-App {
    # Launches the canonical launcher minimized; returns "confirmed", "exited:<code>" or "unconfirmed".
    $launchedAt = (Get-Date).ToUniversalTime()
    $process = Start-Process -FilePath $Shell -WindowStyle Minimized -PassThru -WorkingDirectory $RepoRoot `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$Launcher`"")
    $null = $process.Handle  # keeps the exit code readable after the process ends
    $deadline = (Get-Date).AddSeconds($HealthSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path -LiteralPath $MarkerPath -PathType Leaf) {
            $marker = Get-Item -LiteralPath $MarkerPath
            if ($marker.LastWriteTimeUtc -ge $launchedAt.AddSeconds(-1)) {
                try {
                    $markerId = [string]((Get-Content -LiteralPath $MarkerPath -Raw | ConvertFrom-Json).update_id)
                } catch {
                    $markerId = ""
                }
                if ($markerId -eq $UpdateId) {
                    return "confirmed"
                }
            }
        }
        if ($process.HasExited) {
            # A clean exit may still have written the marker just before it ended.
            Start-Sleep -Milliseconds 200
            if ((Test-Path -LiteralPath $MarkerPath -PathType Leaf) -and
                (Get-Item -LiteralPath $MarkerPath).LastWriteTimeUtc -ge $launchedAt.AddSeconds(-1)) {
                return "confirmed"
            }
            return "exited:$($process.ExitCode)"
        }
        Start-Sleep -Milliseconds 500
    }
    return "unconfirmed"
}

function Stop-Refused {
    param([Parameter(Mandatory = $true)][string]$Reason, [string]$Detail = "")

    # The old app has exited: relaunch the unchanged checkout before reporting.
    $health = Start-App
    Write-Result -Status "refused" -Reason $Reason -NewSha $OldSha -Detail $Detail -Health $health
    exit 0
}

# 1. Wait for the old app to exit (never stop it).
$deadline = (Get-Date).AddSeconds($ExitWaitSeconds)
while ((Get-Date) -lt $deadline) {
    if (-not (Get-Process -Id $OldPid -ErrorAction SilentlyContinue)) {
        break
    }
    Start-Sleep -Milliseconds 500
}
if (Get-Process -Id $OldPid -ErrorAction SilentlyContinue) {
    Write-Result -Status "refused" -Reason "old_app_did_not_exit" -NewSha $OldSha `
        -Detail "process $OldPid was still running after $ExitWaitSeconds s; nothing was changed"
    exit 0
}

# 2. Re-check everything the preflight checked that can change between then and now.
$shaPattern = "^[0-9a-f]{40}$"
if (($OldSha -cnotmatch $shaPattern) -or ($TargetSha -cnotmatch $shaPattern)) {
    Stop-Refused -Reason "invalid_request" -Detail "both SHAs must be 40 lowercase hexadecimal characters"
}

$branch = Invoke-Git @("rev-parse", "--abbrev-ref", "HEAD")
if ($branch.ExitCode -ne 0 -or $branch.Text -ne "main") {
    Stop-Refused -Reason "checkout_changed" -Detail "branch is '$($branch.Text)', not main"
}
$upstream = Invoke-Git @("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
if ($upstream.ExitCode -ne 0 -or $upstream.Text -ne "origin/main") {
    Stop-Refused -Reason "checkout_changed" -Detail "upstream is '$($upstream.Text)', not origin/main"
}
$status = Invoke-Git @("status", "--porcelain", "--untracked-files=no")
if ($status.ExitCode -ne 0 -or $status.Text) {
    Stop-Refused -Reason "checkout_changed" -Detail "tracked files changed since the preflight"
}
$head = Invoke-Git @("rev-parse", "HEAD")
if ($head.ExitCode -ne 0 -or $head.Text -ne $OldSha) {
    Stop-Refused -Reason "checkout_changed" -Detail "HEAD is $($head.Text), not $OldSha"
}
$remote = Invoke-Git @("rev-parse", "refs/remotes/origin/main")
if ($remote.ExitCode -ne 0 -or $remote.Text -ne $TargetSha) {
    Stop-Refused -Reason "target_moved" -Detail "origin/main is $($remote.Text), not $TargetSha"
}
$ancestor = Invoke-Git @("merge-base", "--is-ancestor", $OldSha, $TargetSha)
if ($ancestor.ExitCode -ne 0) {
    Stop-Refused -Reason "not_fast_forward" -Detail "$OldSha is not an ancestor of $TargetSha"
}

# 3. Fast-forward only.
$merge = Invoke-Git @("merge", "--ff-only", $TargetSha)
if ($merge.ExitCode -ne 0) {
    Stop-Refused -Reason "merge_failed" -Detail $merge.Text
}

# 4. Start the new build; roll back locally if it does not come up.
$health = Start-App
if ($health -like "exited:*") {
    $reset = Invoke-Git @("reset", "--keep", $OldSha)
    if ($reset.ExitCode -ne 0) {
        Write-Result -Status "refused" -Reason "rollback_failed" -NewSha $TargetSha `
            -Detail "new build $health; git reset --keep failed: $($reset.Text)"
        exit 0
    }
    $relaunch = Start-App
    Write-Result -Status "refused" -Reason "rolled_back" -NewSha $OldSha -Health $relaunch `
        -Detail "new build $TargetSha $health; local main moved back to $OldSha"
    exit 0
}

Write-Result -Status "applied" -NewSha $TargetSha -Health $health
exit 0
