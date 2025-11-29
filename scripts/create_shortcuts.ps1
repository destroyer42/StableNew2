# Enhanced StableNew Desktop Shortcut Creator
# Creates multiple shortcut options for StableNew

param(
    [string]$ShortcutType = "advanced"
)

function Create-Shortcut {
    param($Name, $Target, $Description, $IconIndex = 0)

    $WshShell = New-Object -comObject WScript.Shell
    $Desktop = [System.Environment]::GetFolderPath('Desktop')
    $Shortcut = $WshShell.CreateShortcut("$Desktop\$Name.lnk")

    $Shortcut.TargetPath = $Target
    $Shortcut.WorkingDirectory = "C:\Users\rober\projects\StableNew"
    $Shortcut.Description = $Description
    $Shortcut.WindowStyle = 1

    # Try different icon options
    $IconSet = $false

    # Try Python icon first
    $PythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
    if ($PythonPath -and (Test-Path $PythonPath)) {
        $Shortcut.IconLocation = "$PythonPath,0"
        $IconSet = $true
    }

    # Fallback to system icons
    if (-not $IconSet) {
        switch ($IconIndex) {
            0 { $Shortcut.IconLocation = "shell32.dll,2" }   # Default executable
            1 { $Shortcut.IconLocation = "shell32.dll,25" }  # Network/web icon
            2 { $Shortcut.IconLocation = "shell32.dll,137" } # Gear/settings icon
            3 { $Shortcut.IconLocation = "shell32.dll,238" } # Computer icon
        }
    }

    $Shortcut.Save()
    Write-Host "✅ Created: $Desktop\$Name.lnk" -ForegroundColor Green
}

Write-Host "🎯 StableNew Desktop Shortcut Creator" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# Create main shortcut
Create-Shortcut -Name "StableNew" -Target "C:\Users\rober\projects\StableNew\launch_stablenew_advanced.bat" -Description "StableNew - Stable Diffusion WebUI Automation" -IconIndex 0

# Create additional shortcuts
$CreateExtra = Read-Host "Create additional shortcuts? (CLI, Simple Launcher) [y/N]"
if ($CreateExtra -match "^[Yy]") {

    # CLI shortcut
    $CLITarget = "powershell.exe"
    $CLIArgs = "-NoExit -Command `"cd 'C:\Users\rober\projects\StableNew'; Write-Host 'StableNew CLI Ready - Example: python -m src.cli --help' -ForegroundColor Green`""

    $WshShell = New-Object -comObject WScript.Shell
    $Desktop = [System.Environment]::GetFolderPath('Desktop')
    $CLIShortcut = $WshShell.CreateShortcut("$Desktop\StableNew CLI.lnk")
    $CLIShortcut.TargetPath = $CLITarget
    $CLIShortcut.Arguments = $CLIArgs
    $CLIShortcut.WorkingDirectory = "C:\Users\rober\projects\StableNew"
    $CLIShortcut.Description = "StableNew CLI - Command Line Interface"
    $CLIShortcut.IconLocation = "powershell.exe,0"
    $CLIShortcut.Save()

    Write-Host "✅ Created: $Desktop\StableNew CLI.lnk" -ForegroundColor Green

    # Simple launcher shortcut
    Create-Shortcut -Name "StableNew Simple" -Target "C:\Users\rober\projects\StableNew\launch_stablenew.bat" -Description "StableNew - Simple Launcher" -IconIndex 1
}

Write-Host ""
Write-Host "🎉 Desktop shortcuts created successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Available shortcuts:" -ForegroundColor Yellow
Write-Host "  🖥️  StableNew          - Advanced launcher with auto-detection" -ForegroundColor White

if ($CreateExtra -match "^[Yy]") {
    Write-Host "  💻  StableNew CLI      - Command line interface" -ForegroundColor White
    Write-Host "  🚀  StableNew Simple   - Basic launcher" -ForegroundColor White
}

Write-Host ""
Write-Host "🎯 Double-click any StableNew icon on your desktop to launch!" -ForegroundColor Cyan
