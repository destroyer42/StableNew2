# Creates a desktop shortcut to the canonical StableNew launcher (PR-DEVEX-LAUNCH-180).
# The repository is resolved from this script's own location; nothing is hard-coded.

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$Launcher = Join-Path $RepoRoot "scripts\launch_stablenew.bat"

$WshShell = New-Object -ComObject WScript.Shell
$Desktop = [System.Environment]::GetFolderPath('Desktop')
$Shortcut = $WshShell.CreateShortcut((Join-Path $Desktop "StableNew.lnk"))
$Shortcut.TargetPath = $Launcher
$Shortcut.WorkingDirectory = $RepoRoot
$Shortcut.Description = "StableNew"
$Shortcut.WindowStyle = 1
$Shortcut.IconLocation = "shell32.dll,2"
$Shortcut.Save()

Write-Host "Desktop shortcut created: $(Join-Path $Desktop 'StableNew.lnk') -> $Launcher"
