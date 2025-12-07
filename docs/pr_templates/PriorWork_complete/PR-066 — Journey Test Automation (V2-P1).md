PR-066 — Journey Test Automation (V2-P1)
Summary

We now have a shutdown journey test (tests/journeys/test_shutdown_no_leaks.py) that validates:

The app launches via python -m src.main

Auto-exit triggers the real shutdown path (X/Exit equivalent)

StableNew and SD-WebUI processes are fully torn down

However:

Codex/Copilot cannot run this test in their sandbox environment (no GUI, no SD-WebUI, no Windows desktop).

There’s no single, canonical way for humans or CI to run this test.

This PR introduces Journey Test Automation:

A local one-command runner script: scripts/run_journey_tests.ps1.

A GitHub Actions workflow to run the shutdown journey on a self-hosted runner.

A small doc + comments so Codex always knows how to trigger the tests, even if it can’t run them itself.

The goal is to make journey testing repeatable, obvious, and integrated into your workflow.

Goals

Provide a single, easy command to run shutdown journey tests locally on your Windows machine.

Add a GitHub Actions workflow to run journey tests on a self-hosted Windows runner.

Document how to run journey tests so Codex & future humans can reference the same entrypoints.

Make it explicit that:

Humans/CI are responsible for actually running SD-WebUI + Tk-based journeys.

Codex is responsible for keeping the harness working and reading the results.

Scope & Risk Tier

Subsystems: Tooling, CI, and docs.

Risk tier: Low — no production behavior changes; only scripts, tests, and workflow config.

Allowed Files

scripts/run_journey_tests.ps1 (NEW)

.github/workflows/journeys_shutdown.yml (NEW)

docs/Testing_Journeys_V2-P1.md (NEW)

tests/journeys/test_shutdown_no_leaks.py (small header comment only)

Forbidden Files

Do not modify:

src/** production code (entrypoint, controllers, GUI, executor, WebUI manager, etc.)

Any existing test logic inside tests/journeys/test_shutdown_no_leaks.py beyond the header comment.

Any other workflows not directly related to journey tests.

Implementation Plan
1. Add local runner script: scripts/run_journey_tests.ps1

Create a PowerShell script that:

Sets the relevant environment variables for the journey test.

Optionally activates your Python venv (commented out).

Runs only the shutdown journey test with pytest.

Behavior:

Parameters (with defaults):

Attempts (int, default 3) → STABLENEW_SHUTDOWN_LEAK_ATTEMPTS

UptimeSeconds (float, default 3) → STABLENEW_AUTO_EXIT_SECONDS

TimeoutBuffer (float, default 5) → STABLENEW_SHUTDOWN_LEAK_TIMEOUT_BUFFER

Pseudo-code:

param(
    [int]$Attempts = 3,
    [double]$UptimeSeconds = 3,
    [double]$TimeoutBuffer = 5
)

$env:STABLENEW_SHUTDOWN_LEAK_ATTEMPTS = "$Attempts"
$env:STABLENEW_AUTO_EXIT_SECONDS = "$UptimeSeconds"
$env:STABLENEW_SHUTDOWN_LEAK_TIMEOUT_BUFFER = "$TimeoutBuffer"
$env:STABLENEW_DEBUG_SHUTDOWN = "1"

# Optional: activate venv if needed
# . "$PSScriptRoot\..\venv\Scripts\Activate.ps1"

python -m pytest tests/journeys/test_shutdown_no_leaks.py -q


Usage (local):

scripts\run_journey_tests.ps1
# or with overrides
scripts\run_journey_tests.ps1 -Attempts 5 -UptimeSeconds 4 -TimeoutBuffer 8


This becomes the canonical local entrypoint Codex will reference.

2. Add GitHub Actions workflow: .github/workflows/journeys_shutdown.yml

Add a new workflow that runs the shutdown journey tests on a self-hosted Windows runner (required because this test needs Tk + SD-WebUI + your environment).

Key points:

Name: Journey Tests (Shutdown / No-Leaks)

Trigger:

workflow_dispatch (manual)

Optional schedule (cron) for nightly runs

Runs on: runs-on: self-hosted (assumes you configure a Windows runner with SD-WebUI installed)

Example structure:

name: Journey Tests (Shutdown / No-Leaks)

on:
  workflow_dispatch: {}
  schedule:
    - cron: "0 8 * * *"  # Optional: daily at 08:00 UTC

jobs:
  shutdown-journey:
    runs-on: self-hosted
    env:
      STABLENEW_SHUTDOWN_LEAK_ATTEMPTS: "3"
      STABLENEW_AUTO_EXIT_SECONDS: "3"
      STABLENEW_SHUTDOWN_LEAK_TIMEOUT_BUFFER: "5"
      STABLENEW_DEBUG_SHUTDOWN: "1"
    steps:
      - name: Checkout StableNew
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.10"

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          if (Test-Path dev-requirements.txt) { pip install -r dev-requirements.txt }

      - name: Run shutdown journey tests
        run: |
          scripts\run_journey_tests.ps1


Notes / Assumptions:

The self-hosted runner:

Is Windows.

Has C:\Users\rob\stable-diffusion-webui or equivalent path configured.

Has required system dependencies for SD-WebUI.

If your SD-WebUI path differs on the runner, you can add environment overrides or a config file to point StableNew to the correct location.

3. Add doc: docs/Testing_Journeys_V2-P1.md

Create a small doc that explains:

What journey tests are (end-to-end behavior checks, including GUI + SD-WebUI).

How to run them locally:

# Windows / PowerShell
scripts\run_journey_tests.ps1


How to run them in CI:

From GitHub UI:

Actions → “Journey Tests (Shutdown / No-Leaks)” → Run workflow

What environment is required:

Self-hosted Windows runner

SD-WebUI installed and reachable

What Codex can and cannot do:

Can: edit tests, scripts, workflows, and interpret journey test results.

Cannot: actually run GUI/SD-WebUI in its sandbox — humans/CI must run them.

This doc is primarily for future-you and for agent instructions.

4. Add a header comment to tests/journeys/test_shutdown_no_leaks.py

At the top of the file, add a short comment block (no logic changes) to make the entrypoints self-documenting:

"""
Shutdown Journey Test: ensures StableNew + SD-WebUI fully exit with no leaked processes.

How to run locally (Windows/PowerShell):
    scripts\run_journey_tests.ps1

How to run in CI:
    GitHub Actions → "Journey Tests (Shutdown / No-Leaks)" workflow
"""


This ensures Codex always has a clear, in-repo reference for how to trigger the test.

Tests / Validation

This PR adds/changes no production code; validation is about making sure the harness works:

Local smoke test

From a PowerShell prompt:

scripts\run_journey_tests.ps1


Confirm:

It sets env vars.

It runs pytest tests/journeys/test_shutdown_no_leaks.py -q.

It surfaces pass/fail cleanly.

GitHub Actions smoke test

On your self-hosted runner:

Push PR-066.

From GitHub:

Go to Actions.

Trigger “Journey Tests (Shutdown / No-Leaks)” manually.

Confirm:

Workflow spins up on the self-hosted runner.

Dependencies install.

The PowerShell script runs journey tests.

Pass/fail is visible in the workflow logs.

No production impact

Confirm no src/** files changed.

Confirm existing unit/functional tests still pass.

Definition of Done

PR-066 is complete when:

scripts/run_journey_tests.ps1 exists and can run the shutdown journey test locally with a single command.

A GitHub Actions workflow Journey Tests (Shutdown / No-Leaks) exists and successfully runs the same script on a self-hosted Windows runner.

docs/Testing_Journeys_V2-P1.md clearly documents how to run these tests.

tests/journeys/test_shutdown_no_leaks.py has a header comment pointing to both the local script and the CI workflow.

No production (src/**) code behavior is changed.

Once merged, any future shutdown-related PR can simply say:

“After applying this change, run scripts\run_journey_tests.ps1 locally or the ‘Journey Tests (Shutdown / No-Leaks)’ Action to verify no process leaks remain.”