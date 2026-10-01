<#
.SYNOPSIS
    Run the opt-in shutdown/no-leak process test with diagnostics logging enabled.

.DESCRIPTION
    Enables debug shutdown logging plus file-access tracing, then executes the
    shutdown/no-leak test. Useful for reproducing failures outside pytest or for
    collecting additional artifacts.
>
param(
    [int]$Attempts = 3,
    [double]$UptimeSeconds = 5,
    [double]$TimeoutBufferSeconds = 5
)

$env:STABLENEW_RUN_SHUTDOWN_LEAK_TEST = "1"
$env:STABLENEW_DEBUG_SHUTDOWN = "1"
$env:STABLENEW_FILE_ACCESS_LOG = "1"
$env:STABLENEW_SHUTDOWN_LEAK_ATTEMPTS = "$Attempts"
$env:STABLENEW_AUTO_EXIT_SECONDS = "$UptimeSeconds"
$env:STABLENEW_SHUTDOWN_LEAK_TIMEOUT_BUFFER = "$TimeoutBufferSeconds"

python -m pytest tests/system/test_shutdown_no_leaks.py -q
