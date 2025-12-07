# StableNew Desktop Launchers

This directory contains several launcher options for StableNew to make it easy to run from your desktop.

## Available Launchers

### 🖥️ Desktop Shortcuts
Run `create_shortcuts.ps1` to create desktop shortcuts:
```powershell
powershell -ExecutionPolicy Bypass -File "create_shortcuts.ps1"
```

**Created Shortcuts:**
- **StableNew**: Advanced launcher with auto-detection and error checking
- **StableNew CLI** (optional): Opens PowerShell in StableNew directory for CLI commands
- **StableNew Simple** (optional): Basic batch launcher

### 🚀 Batch Launchers

#### `launch_stablenew_advanced.bat`
- **Auto-detection**: Finds StableNew installation automatically
- **Error checking**: Validates Python installation and paths
- **Robust**: Handles multiple installation locations
- **User-friendly**: Clear status messages and error handling

#### `launch_stablenew.bat`
- **Simple**: Direct launch from current directory
- **Fast**: Minimal overhead
- **Basic**: For when you know everything is set up correctly

## Usage

### Option 1: Desktop Shortcut (Recommended)
1. Run the shortcut creator: `powershell -ExecutionPolicy Bypass -File "create_shortcuts.ps1"`
2. Double-click the "StableNew" icon on your desktop
3. The GUI will launch automatically

### Option 2: Direct Batch File
1. Double-click `launch_stablenew_advanced.bat` in Windows Explorer
2. Or run from command line: `.\launch_stablenew_advanced.bat`

### Option 3: Command Line
```bash
# From StableNew directory
python -m src.main

# CLI mode with specific prompt
python -m src.cli --prompt "your prompt" --preset default
```

## Features

✅ **Auto-Path Detection**: Finds StableNew even if moved
✅ **Python Validation**: Checks Python installation
✅ **Error Handling**: Clear error messages if something goes wrong
✅ **Multiple Icons**: Uses Python icon when available
✅ **Clean Interface**: Professional launcher with status updates

## Troubleshooting

**"Could not find StableNew installation"**
- Ensure you're running from the StableNew directory
- Or update the path in the batch file to match your installation

**"Python not found"**
- Install Python from python.org
- Or add Python to your system PATH

**Desktop shortcut doesn't work**
- Right-click shortcut → Properties → Check target path
- Re-run `create_shortcuts.ps1` to recreate

## Customization

To change the installation path, edit these files:
- `launch_stablenew.bat`: Line 4 - `cd /d "C:\Users\rober\projects\StableNew"`
- `create_shortcuts.ps1`: Update path variables
- `launch_stablenew_advanced.bat`: Update search paths in the loop

The advanced launcher automatically searches these locations:
- Current directory (where the batch file is located)
- `C:\Users\%USERNAME%\projects\StableNew`
- `C:\StableNew`
- `D:\StableNew`
- `%USERPROFILE%\StableNew`
- `%USERPROFILE%\Documents\StableNew`
