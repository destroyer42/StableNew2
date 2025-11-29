# StableNew Desktop Shortcut Creator
# This script creates a desktop shortcut for StableNew

$WshShell = New-Object -comObject WScript.Shell
$Desktop = [System.Environment]::GetFolderPath('Desktop')
$Shortcut = $WshShell.CreateShortcut("$Desktop\StableNew.lnk")

# Set shortcut properties
$Shortcut.TargetPath = "C:\Users\rober\projects\StableNew\launch_stablenew.bat"
$Shortcut.WorkingDirectory = "C:\Users\rober\projects\StableNew"
$Shortcut.Description = "StableNew - Stable Diffusion WebUI Automation"
$Shortcut.WindowStyle = 1  # Normal window

# Try to use Python icon if available, otherwise use default
$PythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
if ($PythonPath) {
    $Shortcut.IconLocation = "$PythonPath,0"
} else {
    # Use default executable icon
    $Shortcut.IconLocation = "shell32.dll,2"
}

# Save the shortcut
$Shortcut.Save()

Write-Host "✅ Desktop shortcut created: $Desktop\StableNew.lnk"
Write-Host "🎯 Double-click the 'StableNew' icon on your desktop to launch the GUI!"
