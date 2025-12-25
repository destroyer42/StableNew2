# EMERGENCY: Zombie Process Recovery

**⚠️ CRITICAL SYSTEM RECOVERY PROCEDURE**

Use this runbook when StableNew has spawned zombie processes that are:
- Consuming excessive memory (multiple GB)
- Respawning when killed
- Visible as 10+ Python or 3+ CMD processes in Task Manager

---

## Quick Diagnosis

**Symptoms:**
- Task Manager shows 10+ `python.exe` processes
- Task Manager shows 3+ `cmd.exe` processes
- System memory usage abnormally high (8+ GB for StableNew)
- Processes instantly respawn when killed
- StableNew GUI may be frozen or unresponsive

**Verification:**
```powershell
# Count Python processes
(Get-Process python -ErrorAction SilentlyContinue).Count

# Count CMD processes
(Get-Process cmd -ErrorAction SilentlyContinue).Count
```

**Thresholds:**
- **NORMAL:** 1-3 Python, 0-1 CMD
- **WARNING:** 5-10 Python, 2 CMD
- **CRITICAL:** 10+ Python, 3+ CMD → **USE THIS RUNBOOK**

---

## Emergency Cleanup (Step-by-Step)

### Step 1: List All Zombie Processes

```powershell
# List all Python processes with details
Get-Process python -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, StartTime, @{Name='CommandLine';Expression={(Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)").CommandLine}} | Format-Table -AutoSize
```

**Look for:**
- Processes with `launch.py` in command line
- Processes with working directory matching WebUI path
- Multiple processes all started within seconds of each other

### Step 2: Find Parent CMD Processes

```powershell
# Find CMD parents of Python zombies
$zombies = Get-Process python -ErrorAction SilentlyContinue
$cmdParents = $zombies | ForEach-Object {
    $parentId = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)").ParentProcessId
    Get-Process -Id $parentId -ErrorAction SilentlyContinue | Where-Object {$_.ProcessName -eq 'cmd'}
} | Select-Object -Unique Id, ProcessName

$cmdParents | Format-Table
```

**Expected:** Multiple CMD.exe processes, all parents of Python processes.

### Step 3: Kill CMD Parents FIRST

**CRITICAL:** Must kill CMD parents before Python children, otherwise they respawn!

```powershell
# Extract CMD parent PIDs
$cmdPids = ($cmdParents | Select-Object -ExpandProperty Id)

# Kill all CMD parents forcefully
$cmdPids | ForEach-Object {
    Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
    Write-Host "Killed CMD parent PID $_"
}
```

### Step 4: Kill Remaining Python Processes

```powershell
# Kill all Python processes
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
```

### Step 5: Verify Cleanup

```powershell
# Wait 3 seconds for processes to exit
Start-Sleep -Seconds 3

# Count remaining processes
$pythonCount = (Get-Process python -ErrorAction SilentlyContinue).Count
$cmdCount = (Get-Process cmd -ErrorAction SilentlyContinue).Count

Write-Host "Remaining Python processes: $pythonCount"
Write-Host "Remaining CMD processes: $cmdCount"

if ($pythonCount -eq 0) {
    Write-Host "✅ SUCCESS: All zombies eliminated!" -ForegroundColor Green
} else {
    Write-Host "⚠️ WARNING: $pythonCount Python processes remain" -ForegroundColor Yellow
}
```

### Step 6: Verify No Respawning

```powershell
# Wait 5 more seconds and recheck
Start-Sleep -Seconds 5
$respawnCount = (Get-Process python -ErrorAction SilentlyContinue).Count

if ($respawnCount -eq 0) {
    Write-Host "✅ Confirmed: No respawning detected" -ForegroundColor Green
} else {
    Write-Host "❌ CRITICAL: Processes respawned! ($respawnCount found)" -ForegroundColor Red
    Write-Host "There may be additional parent processes. See Advanced Recovery below."
}
```

---

## Advanced Recovery (If Basic Cleanup Fails)

### Find Hidden Parent Processes

If processes keep respawning, there may be grandparent processes:

```powershell
# Recursively find all parents
function Get-ProcessTree($ProcessId) {
    $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (!$proc) { return }
    
    $parent = (Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId").ParentProcessId
    if ($parent -and $parent -ne 0) {
        Write-Host "PID $ProcessId ($($proc.Name)) -> Parent PID $parent"
        Get-ProcessTree $parent
    }
}

# Trace each Python process to its root
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "`n=== Tracing PID $($_.Id) ==="
    Get-ProcessTree $_.Id
}
```

**Look for:**
- PowerShell.exe parents (if launched via script)
- Explorer.exe parents (if launched via double-click)
- Service host parents (if WebUI registered as service)

### Nuclear Option: Kill All WebUI-Related Processes

**⚠️ WARNING:** This kills ALL processes matching WebUI patterns. Use only if normal cleanup fails.

```powershell
# Kill everything related to WebUI
Get-Process | Where-Object {
    $cmdline = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)").CommandLine
    $cmdline -like "*webui*" -or 
    $cmdline -like "*launch*" -or 
    $cmdline -like "*stable-diffusion*" -or
    $_.ProcessName -eq "python" -or 
    $_.ProcessName -eq "cmd"
} | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host "Nuclear cleanup complete. Check Task Manager."
```

---

## Post-Recovery Steps

### 1. Check StableNew Logs

```powershell
# Open recent log file
Get-ChildItem "logs\stablenew.log.jsonl" | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | notepad
```

**Look for:**
- `WebUI restart requested`
- `WebUI connection timeout`
- `Auto-restart triggered`
- `Process spawn` or `subprocess.Popen`

### 2. Check WebUI Logs

```powershell
# List recent WebUI logs
Get-ChildItem "logs\webui\*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 5
```

### 3. Document the Incident

Create entry in `reports/ZOMBIE_INCIDENTS_LOG.md`:

```markdown
## Incident: [Date]

**Severity:** [Critical/High/Medium]
**Zombie Count:** [X Python + Y CMD processes]
**Trigger:** [What caused the spawning? Connection loss? Crash? Restart loop?]
**Cleanup Method:** [Basic/Advanced/Nuclear]
**Root Cause:** [If identifiable]
**Prevention:** [What code change would prevent recurrence?]
```

### 4. Test StableNew Restart

```powershell
# Restart StableNew from clean state
cd C:\Users\rob\projects\StableNew
python -m src.main
```

**Verify:**
- GUI starts normally
- WebUI connects successfully
- Process count stays normal (1-3 Python)
- No zombies after 10 minutes

---

## Prevention Checklist

After cleanup, ensure fixes are in place:

- [ ] `PROCESS_LIFECYCLE_MANAGEMENT_v2.6.md` read and understood
- [ ] PR-PROC-001A implemented (CMD parent tracking)
- [ ] PR-PROC-001B implemented (runaway detection)
- [ ] PR-PROC-001C implemented (shutdown enhancement)
- [ ] Tests added for process lifecycle
- [ ] Monitoring/alerts configured

---

## When to Escalate

Contact development team if:
- Zombies respawn after nuclear cleanup
- Root cause not identifiable
- Happens repeatedly (3+ times per week)
- Memory leak exceeds 16 GB
- System becomes unbootable

---

## Reference Commands

```powershell
# Quick zombie check
(Get-Process python -ErrorAction SilentlyContinue).Count

# Quick CMD parent check
Get-Process cmd | Where-Object {(Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)").CommandLine -like "*webui*"}

# Emergency kill all
Get-Process python, cmd -ErrorAction SilentlyContinue | Stop-Process -Force

# Memory usage check
Get-Process python -ErrorAction SilentlyContinue | Measure-Object WorkingSet -Sum | Select-Object @{Name="TotalMemoryMB";Expression={[math]::Round($_.Sum / 1MB, 2)}}
```

---

## Appendix: Why CMD Parents Matter

**Windows Process Hierarchy:**
```
User Action
└─> StableNew (python.exe)
    └─> subprocess.Popen() spawns...
        └─> cmd.exe (INVISIBLE SHELL)
            └─> launch.py (python.exe)
                └─> WebUI worker 1 (python.exe)
                └─> WebUI worker 2 (python.exe)
                └─> WebUI worker N (python.exe)
```

**The Problem:**
- StableNew tracks only the first `python.exe` PID
- When `stop_webui()` called, kills Python processes
- **CMD.exe parent remains alive**
- CMD.exe continues spawning new Python children
- Each restart creates NEW CMD without killing old one
- Exponential growth: 1 → 2 → 4 → 8 → 16 CMD parents

**The Fix:**
- Track CMD parent PID when process spawned
- Kill CMD parent BEFORE killing Python children
- Scan for orphaned CMD.exe processes
- Verify no respawning after cleanup

**See:** `docs/PROCESS_LIFECYCLE_MANAGEMENT_v2.6.md` for comprehensive fix strategy.

---

**END OF RUNBOOK**

**Last Updated:** 2025-12-25  
**Version:** 1.0  
**Maintainer:** StableNew Development Team
