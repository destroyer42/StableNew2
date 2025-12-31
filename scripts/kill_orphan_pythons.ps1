# Kill orphaned Python processes from previous StableNew/WebUI sessions
# Run this manually if you see high memory usage before starting StableNew

Write-Host "Scanning for orphaned Python processes..." -ForegroundColor Cyan

$pythonProcs = Get-Process python -ErrorAction SilentlyContinue
if (-not $pythonProcs) {
    Write-Host "No Python processes found." -ForegroundColor Green
    exit 0
}

$now = Get-Date
$orphans = @()

foreach ($proc in $pythonProcs) {
    $age = ($now - $proc.StartTime).TotalHours
    $ramGB = [math]::Round($proc.WorkingSet64 / 1GB, 2)
    
    # Flag as orphan if:
    # - Older than 1 hour
    # - Using more than 10GB RAM (likely a stuck WebUI)
    if ($age -gt 1.0 -or $ramGB -gt 10.0) {
        $orphans += [PSCustomObject]@{
            PID = $proc.Id
            RAM_GB = $ramGB
            Age_Hours = [math]::Round($age, 1)
            StartTime = $proc.StartTime
        }
    }
}

if ($orphans.Count -eq 0) {
    Write-Host "No orphans found." -ForegroundColor Green
    exit 0
}

Write-Host "`nFound $($orphans.Count) potential orphan(s):" -ForegroundColor Yellow
$orphans | Format-Table -AutoSize

$response = Read-Host "`nKill these processes? (y/N)"
if ($response -eq 'y' -or $response -eq 'Y') {
    foreach ($orphan in $orphans) {
        try {
            Stop-Process -Id $orphan.PID -Force -ErrorAction Stop
            Write-Host "✓ Killed PID $($orphan.PID) ($($orphan.RAM_GB)GB)" -ForegroundColor Green
        } catch {
            Write-Host "✗ Failed to kill PID $($orphan.PID): $_" -ForegroundColor Red
        }
    }
    Write-Host "`nCleanup complete!" -ForegroundColor Cyan
} else {
    Write-Host "Cancelled." -ForegroundColor Gray
}
