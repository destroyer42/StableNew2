# Creates (or confirms) the desktop shortcut to the canonical StableNew launcher, launch_stablenew.bat
# (PR-DEVEX-LAUNCH-180). Kept for existing habits; it forwards to the idempotent, reversible manager
# (LAUNCH-AUTOSTART-440), which also handles autostart at sign-in and removal:
#   .\scripts\manage_stablenew_shortcuts.ps1 [-Desktop] [-Autostart] [-Remove] [-Status]

& (Join-Path $PSScriptRoot "manage_stablenew_shortcuts.ps1") -Desktop @args
exit $LASTEXITCODE
