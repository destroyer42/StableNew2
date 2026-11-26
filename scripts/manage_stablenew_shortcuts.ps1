<#
.SYNOPSIS
Owner-run, idempotent and reversible StableNew desktop shortcut and per-user autostart at Windows sign-in
(LAUNCH-AUTOSTART-440).

.DESCRIPTION
Creates, removes or reports two per-user shortcuts to this checkout's canonical launcher
(<repo>\scripts\launch_stablenew.bat):

* Desktop:   <Desktop>\StableNew.lnk
* Autostart: <Startup>\StableNew.lnk, the current user's Startup folder
             (shell:startup, %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup).
             Windows starts it at every sign-in, including the first sign-in after a restart.

Nothing machine-wide is touched: no registry Run key, no Scheduled Task, no service, no admin rights. Task
Manager > Startup apps shows the autostart entry and can disable it without this script.

The script only ever writes or deletes files named StableNew.lnk in those two folders, and only when the
shortcut is StableNew's own: a shortcut whose target is a launch_stablenew.bat. A different file of that name is
reported and left untouched. Running Install twice changes nothing the second time.

The application has a single-instance lock, so an autostarted StableNew and a later manual launch cannot both
run; the second one reports that StableNew is already running.

.PARAMETER Desktop
Act on the desktop shortcut only.

.PARAMETER Autostart
Act on the sign-in autostart shortcut only. With neither -Desktop nor -Autostart, both are acted on.

.PARAMETER Remove
Remove StableNew's shortcut(s) instead of installing them.

.PARAMETER Status
Report what is installed and change nothing.

.PARAMETER DesktopDir
Folder used instead of the user's Desktop (for tests).

.PARAMETER StartupDir
Folder used instead of the user's Startup folder (for tests).

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\manage_stablenew_shortcuts.ps1
Installs (or confirms) both shortcuts for this checkout.

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\manage_stablenew_shortcuts.ps1 -Autostart -Remove
Stops StableNew starting at sign-in; the desktop shortcut stays.

Exit codes: 0 done (or nothing to do), 2 a foreign StableNew.lnk was left untouched, 12 not a StableNew checkout.
#>

[CmdletBinding()]
param(
    [switch]$Desktop,
    [switch]$Autostart,
    [switch]$Remove,
    [switch]$Status,
    [string]$DesktopDir = "",
    [string]$StartupDir = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExitForeignShortcut = 2
$ExitNotACheckout = 12
$ShortcutName = "StableNew.lnk"
$LauncherLeaf = "launch_stablenew.bat"

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$Launcher = Join-Path $RepoRoot "scripts\$LauncherLeaf"

if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot "src\main.py") -PathType Leaf) -or
    -not (Test-Path -LiteralPath $Launcher -PathType Leaf)) {
    Write-Host "'$RepoRoot' is not a StableNew checkout (src\main.py or scripts\$LauncherLeaf is missing)." -ForegroundColor Red
    exit $ExitNotACheckout
}

if ($Remove -and $Status) {
    Write-Host "Use either -Remove or -Status, not both." -ForegroundColor Red
    exit 1
}

if (-not $Desktop -and -not $Autostart) {
    $Desktop = $true
    $Autostart = $true
}

if (-not $DesktopDir) { $DesktopDir = [System.Environment]::GetFolderPath("Desktop") }
if (-not $StartupDir) { $StartupDir = [System.Environment]::GetFolderPath("Startup") }

$Shell = New-Object -ComObject WScript.Shell

# Desired shortcut properties. The autostart window opens minimized so a sign-in does not put a console in front.
$Targets = @()
if ($Desktop) {
    $Targets += [pscustomobject]@{ Label = "Desktop shortcut"; Folder = $DesktopDir; WindowStyle = 1; Description = "StableNew" }
}
if ($Autostart) {
    $Targets += [pscustomobject]@{ Label = "Autostart at sign-in"; Folder = $StartupDir; WindowStyle = 7; Description = "StableNew (starts at Windows sign-in)" }
}

function Get-ShortcutState {
    param([Parameter(Mandatory = $true)]$Target)

    $path = Join-Path $Target.Folder $ShortcutName
    if (-not (Test-Path -LiteralPath $path)) {
        return [pscustomobject]@{ Path = $path; Kind = "absent"; TargetPath = "" }
    }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        return [pscustomobject]@{ Path = $path; Kind = "foreign"; TargetPath = "" }
    }
    $link = $Shell.CreateShortcut($path)
    $current = [string]$link.TargetPath
    if ((Split-Path -Leaf $current) -ne $LauncherLeaf) {
        return [pscustomobject]@{ Path = $path; Kind = "foreign"; TargetPath = $current }
    }
    $same = ($current -eq $Launcher) -and
        ([string]$link.WorkingDirectory -eq $RepoRoot) -and
        ([int]$link.WindowStyle -eq $Target.WindowStyle) -and
        ([string]$link.Description -eq $Target.Description)
    if ($same) {
        return [pscustomobject]@{ Path = $path; Kind = "current"; TargetPath = $current }
    }
    return [pscustomobject]@{ Path = $path; Kind = "stale"; TargetPath = $current }
}

$foreign = $false
foreach ($target in $Targets) {
    $state = Get-ShortcutState $target

    if ($Status) {
        switch ($state.Kind) {
            "absent" { Write-Host "$($target.Label): not installed ($($state.Path))" }
            "current" { Write-Host "$($target.Label): installed -> $Launcher" }
            "stale" { Write-Host "$($target.Label): installed for another checkout or with old settings -> $($state.TargetPath)" }
            "foreign" { Write-Host "$($target.Label): $($state.Path) exists but is not StableNew's shortcut (target '$($state.TargetPath)')"; $foreign = $true }
        }
        continue
    }

    if ($state.Kind -eq "foreign") {
        Write-Host "$($target.Label): left untouched. '$($state.Path)' is not a StableNew launcher shortcut (target '$($state.TargetPath)')." -ForegroundColor Yellow
        $foreign = $true
        continue
    }

    if ($Remove) {
        if ($state.Kind -eq "absent") {
            Write-Host "$($target.Label): nothing to remove."
        } else {
            Remove-Item -LiteralPath $state.Path -Force
            Write-Host "$($target.Label): removed $($state.Path)"
        }
        continue
    }

    if ($state.Kind -eq "current") {
        Write-Host "$($target.Label): already installed -> $Launcher"
        continue
    }

    if (-not (Test-Path -LiteralPath $target.Folder -PathType Container)) {
        New-Item -ItemType Directory -Path $target.Folder | Out-Null
    }
    $link = $Shell.CreateShortcut($state.Path)
    $link.TargetPath = $Launcher
    $link.WorkingDirectory = $RepoRoot
    $link.Description = $target.Description
    $link.WindowStyle = $target.WindowStyle
    $link.IconLocation = "shell32.dll,2"
    $link.Save()
    if ($state.Kind -eq "stale") {
        Write-Host "$($target.Label): updated $($state.Path) -> $Launcher (was $($state.TargetPath))"
    } else {
        Write-Host "$($target.Label): created $($state.Path) -> $Launcher"
    }
}

if ($foreign) {
    exit $ExitForeignShortcut
}
exit 0
