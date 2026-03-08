# StableNew Logging Configuration

## Overview

StableNew has a sophisticated dual-output logging system:

1. **Console Terminal** - Controlled by `STABLENEW_LOG_LEVEL` environment variable (default: WARNING)
2. **GUI Log Panel** - Always captures DEBUG and above, with built-in filtering

**Recent Changes (v2.6):** All routine startup, resource loading, and internal state messages have been moved to DEBUG level. With the default WARNING console level, you'll only see actual warnings and errors in the terminal—no more cluttered console output!

## GUI Log Panel (Recommended for Debugging)

The GUI has a built-in **"Details"** log panel with powerful features:

### Features:
- **Level Filters**: `ALL`, `DEBUG+`, `INFO+`, `WARN+`, `ERROR`
- **Subsystem Filter**: Filter by component (e.g., "api", "pipeline", "gui")
- **Job ID Filter**: Filter by specific job ID
- **Auto-scroll**: Automatically scroll to latest logs
- **Crash Bundle**: Generate diagnostic bundle with last 500 log entries

### Usage:
1. Click the **"Details ▼"** button in the GUI to expand the log panel
2. Select your desired log level from the dropdown:
   - `DEBUG+` - See everything including internal state changes
   - `INFO+` - Normal operations plus warnings/errors
   - `WARN+` - Only warnings and errors (default)
   - `ERROR` - Only errors
3. Use subsystem or job filters to narrow down specific components
4. Enable "Auto-scroll" to follow logs in real-time

**💡 Tip:** Use the GUI log panel instead of console output for debugging. It has better filtering and doesn't clutter your terminal!

## Console Log Levels (Terminal Output)

Set the `STABLENEW_LOG_LEVEL` environment variable to control **console** verbosity:

- **WARNING** (default) - Only warnings and errors (recommended for normal use)
- **INFO** - Informational messages plus warnings/errors (moderate verbosity)
- **DEBUG** - Very detailed diagnostic information including UI state changes, job building steps, and internal operations (very verbose)
- **ERROR** - Only error messages (minimal)

**Note:** The GUI log panel always captures DEBUG and above regardless of this setting. This environment variable only controls what appears in the console/terminal.

## Environment Variables

### STABLENEW_LOG_LEVEL

Controls the verbosity of console output.

**Windows PowerShell:**
```powershell
$env:STABLENEW_LOG_LEVEL = "WARNING"
python -m src.main
```

**Windows Command Prompt:**
```cmd
set STABLENEW_LOG_LEVEL=WARNING
python -m src.main
```

**Linux/macOS:**
```bash
export STABLENEW_LOG_LEVEL=WARNING
python -m src.main
```

### STABLENEW_LOG_FILE

Redirect logs to a file instead of (or in addition to) console output.

**Example:**
```powershell
$env:STABLENEW_LOG_FILE = "logs/stablenew.log"
```

### STABLENEW_DEBUG_SHUTDOWN

Enable detailed shutdown diagnostics (automatically creates a timestamped log file).

**Example:**
```powershell
$env:STABLENEW_DEBUG_SHUTDOWN = "1"
```

### STABLENEW_FILE_ACCESS_LOG

Enable detailed file access tracing (for debugging file I/O issues).

**Example:**
```powershell
$env:STABLENEW_FILE_ACCESS_LOG = "1"
```

## Common Scenarios

### Quiet Mode (Recommended)

```powershell
# Default - shows only warnings and errors
python -m src.main
```

### Verbose Mode (For Debugging)

```powershell
$env:STABLENEW_LOG_LEVEL = "INFO"
python -m src.main
```

### Very Verbose Mode (For Deep Debugging)

```powershell
$env:STABLENEW_LOG_LEVEL = "DEBUG"
python -m src.main
```

### Save Logs to File

```powershell
$env:STABLENEW_LOG_LEVEL = "INFO"
$env:STABLENEW_LOG_FILE = "logs/debug.log"
python -m src.main
```

## Notes

- The default log level is now **WARNING** to reduce console clutter
- Log level changes take effect on the next application startup
- File logging is optional and can be combined with any log level
- Debug-level logging can impact performance and should only be used when diagnosing issues
