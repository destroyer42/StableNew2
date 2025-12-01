<#
.SYNOPSIS
    Run journey tests, including shutdown/no-leak coverage, with configurable modes.

.DESCRIPTION
    Wrapper script that configures environment variables (auto-exit, attempts, timeout),
    optionally activates a venv, and runs one or more pytest journeys depending on the
    chosen mode.
>
param(
    [ValidateSet("all", "shutdown", "core", "legacy")]
    [string]$Mode = "all",
    [int]$Attempts = 3,
    [double]$UptimeSeconds = 3,
    [double]$TimeoutBuffer = 5
)

$env:STABLENEW_SHUTDOWN_LEAK_ATTEMPTS = "$Attempts"
$env:STABLENEW_AUTO_EXIT_SECONDS = "$UptimeSeconds"
$env:STABLENEW_SHUTDOWN_LEAK_TIMEOUT_BUFFER = "$TimeoutBuffer"
$env:STABLENEW_DEBUG_SHUTDOWN = "1"

# Optional: activate your Python virtualenv for journey tests
# . "$PSScriptRoot\..\venv\Scripts\Activate.ps1"

function RunShutdownJourney {
    python -m pytest tests/journeys/test_shutdown_no_leaks.py -q
}

function RunCoreJourneys {
    python -m pytest tests/journeys -q
}

function RunLegacyJourney {
    python -m pytest tests/legacy/test_pipeline_journey.py -q
}

switch ($Mode) {
    "shutdown" {
        RunShutdownJourney
        break
    }
    "core" {
        RunCoreJourneys
        break
    }
    "legacy" {
        RunLegacyJourney
        break
    }
    default {
        RunCoreJourneys
        RunShutdownJourney
        RunLegacyJourney
        break
    }
}
