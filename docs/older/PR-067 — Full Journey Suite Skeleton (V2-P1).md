PR-067 — Full Journey Suite Skeleton (V2-P1).md

Unify existing journey tests + add OS-level shutdown journey under a single harness and automation entrypoints

Summary

In the current snapshot (StableNew-snapshot-20251130-075449.zip + repo_inventory.json), the real journey-related pieces are:

Docs / plans

docs/Journey_Test_Plan_2025-11-26_1115.md

docs/archive/schemas/journey_test_coverage_checklist.md

tests/Journey Test Suite – Comprehensive Plan.md

docs/pr_templates/Unknown Status/PR-08_V2_Journey_Test_Full_Pipeline.md

V2 journey tests already present

tests/journeys/fakes/fake_pipeline_runner.py

tests/journeys/test_jt01_prompt_pack_authoring.py

tests/journeys/test_jt02_lora_embedding_integration.py

tests/journeys/test_jt03_txt2img_pipeline_run.py

tests/journeys/test_jt04_img2img_adetailer_run.py

tests/journeys/test_jt05_upscale_stage_run.py

tests/journeys/test_v2_full_pipeline_journey.py

Legacy

tests/legacy/test_pipeline_journey.py (V1-era journey)

There is no shutdown/no-leaks journey in this snapshot yet; we will add:

tests/journeys/test_shutdown_no_leaks.py (NEW in this PR)

PR-067 does not introduce new business logic. It:

Creates a small journey harness helper for app-level subprocess-driven journeys.

Standardizes pytest markers and grouping for existing journey tests (JT-01…JT-05, V2 full pipeline, legacy pipeline).

Adds a new OS-level shutdown journey test_shutdown_no_leaks.py to the suite (assuming the implementation we’ve been iterating on).

Extends the automation hooks from PR-066 (scripts/run_journey_tests.ps1 + journeys workflow) to run:

“Core” V2 journeys

Shutdown/no-leaks journey

Legacy journey (opt-in)

This gives you a coherent journey-suite skeleton that Codex and your CI can target.

Goals

Make all V2 journey tests discoverable and runnable via a single script + workflow.

Introduce a reusable journey_harness module for subprocess-based journeys (like shutdown/no-leaks).

Add test_shutdown_no_leaks.py to the suite as the OS-level process-leak test.

Normalize markers: journey, slow, and legacy for strict pytest config.

Keep legacy V1 journey available but clearly flagged as such.

Scope & Risk Tier

Subsystems: Test suite, tooling, CI, pytest config.

Risk: Low (test + tooling only; no src/** behavior changes).

Allowed Files

This PR may touch/add:

New helper

tools/test_helpers/journey_harness.py (NEW)

Existing V2 journey tests

tests/journeys/fakes/fake_pipeline_runner.py

tests/journeys/test_jt01_prompt_pack_authoring.py

tests/journeys/test_jt02_lora_embedding_integration.py

tests/journeys/test_jt03_txt2img_pipeline_run.py

tests/journeys/test_jt04_img2img_adetailer_run.py

tests/journeys/test_jt05_upscale_stage_run.py

tests/journeys/test_v2_full_pipeline_journey.py

New OS-level shutdown journey

tests/journeys/test_shutdown_no_leaks.py (NEW, formalizing the subprocess-based shutdown/no-leaks test we’ve been iterating on)

Legacy journey

tests/legacy/test_pipeline_journey.py (markers only)

Tooling / config

scripts/run_journey_tests.ps1 (from PR-066 — extend modes to include full suite)

.github/workflows/journeys_shutdown.yml (from PR-066 — add a “full suite” job)

docs/Testing_Journeys_V2-P1.md (from PR-066 — extend to cover the full suite)

pyproject.toml ([tool.pytest.ini_options] markers section)

Forbidden Files

Do not modify:

Any src/** production code (controllers, GUI, executor, WebUI manager, etc.).

Any non-journey tests outside the listed paths.

Implementation Plan
1. Add journey_harness helper for app-level journeys

File: tools/test_helpers/journey_harness.py (NEW)

Purpose: centralize subprocess-based app runs for journeys like shutdown/no-leaks (and future ones that exercise python -m src.main).

Suggested API:

import os
import subprocess
import sys
from typing import Mapping, Optional

def build_env(extra: Optional[Mapping[str, str]] = None) -> dict[str, str]:
    env = dict(os.environ)
    if extra:
        env.update(extra)
    return env

def run_app_once(
    *,
    auto_exit_seconds: float = 3.0,
    timeout_buffer: float = 5.0,
    extra_env: Optional[Mapping[str, str]] = None,
) -> subprocess.CompletedProcess:
    env = build_env(extra_env or {})
    env["STABLENEW_AUTO_EXIT_SECONDS"] = str(auto_exit_seconds)

    timeout = auto_exit_seconds + timeout_buffer

    proc = subprocess.Popen(
        [sys.executable, "-m", "src.main"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate(timeout=5)
        raise RuntimeError(
            f"StableNew app did not exit within {timeout} seconds; "
            f"returncode={proc.returncode}"
        )
    return subprocess.CompletedProcess(
        args=proc.args,
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr,
    )

def run_journey_mode(
    mode: str,
    *,
    auto_exit_seconds: float = 3.0,
    timeout_buffer: float = 5.0,
    extra_env: Optional[Mapping[str, str]] = None,
) -> subprocess.CompletedProcess:
    env = dict(extra_env or {})
    env["STABLENEW_JOURNEY_MODE"] = mode
    return run_app_once(
        auto_exit_seconds=auto_exit_seconds,
        timeout_buffer=timeout_buffer,
        extra_env=env,
    )


Notes:

STABLENEW_JOURNEY_MODE is forward-looking: current JT-01–05 tests run “in-process” and don’t need it yet, but this gives us a standard hook for future app-driven journeys.

test_shutdown_no_leaks.py should use run_app_once() rather than open-coding subprocess.Popen if practical.

2. Normalize pytest markers and config

File: pyproject.toml ([tool.pytest.ini_options])

Currently addopts uses --strict-markers and defines slow, gui, etc., but no journey or legacy markers.

Add to the markers list:

markers = [
    "integration: marks tests as integration tests (may require external services)",
    "slow: marks tests as slow (deselect with '-m \"not slow\"')",
    "gui: marks tests that require GUI/display (may not run in CI)",
    "timeout: marks tests that rely on pytest-timeout for execution limits",
    "journey: marks end-to-end journey tests",
    "legacy: marks legacy V1-era journey tests",
]


Then, for each journey test file:

tests/journeys/test_jt01_prompt_pack_authoring.py

tests/journeys/test_jt02_lora_embedding_integration.py

tests/journeys/test_jt03_txt2img_pipeline_run.py

tests/journeys/test_jt04_img2img_adetailer_run.py

tests/journeys/test_jt05_upscale_stage_run.py

tests/journeys/test_v2_full_pipeline_journey.py

tests/journeys/test_shutdown_no_leaks.py (NEW file in this PR)

Ensure each top-level test function has:

import pytest

@pytest.mark.journey
@pytest.mark.slow
def test_...():
    ...


For tests/legacy/test_pipeline_journey.py:

Add:

import pytest

@pytest.mark.journey
@pytest.mark.legacy
@pytest.mark.slow
def test_...():
    ...


Do not change its logic. It stays as a reference V1 journey and is already under norecursedirs = ["tests/legacy"] so it won’t be pulled into the main suite unless explicitly targeted.

3. Add / wire test_shutdown_no_leaks.py into the suite

File: tests/journeys/test_shutdown_no_leaks.py (NEW)

Purpose:

OS-level end-to-end shutdown journey that:

Launches StableNew via python -m src.main in a subprocess.

Uses STABLENEW_AUTO_EXIT_SECONDS (and related envs) to exercise the real clean shutdown path.

Uses the existing process-inspection helpers (from PR-060+) to assert that no StableNew/SD-WebUI Python processes remain after repeated cycles.

Key expectations (behavior, not code):

Marked with @pytest.mark.journey and @pytest.mark.slow.

Uses tools/test_helpers/journey_harness.run_app_once() for process handling.

Reads envs:

STABLENEW_SHUTDOWN_LEAK_ATTEMPTS → number of repetitions.

STABLENEW_AUTO_EXIT_SECONDS → uptime before auto-exit.

STABLENEW_SHUTDOWN_LEAK_TIMEOUT_BUFFER → additional time before treating as timeout.

After each run:

Calls assert_no_stable_new_processes() (from your process inspection helper) to confirm no lingering StableNew/SD-WebUI python.exe processes.

You already have the logic / shape from your failing test output; this PR just formalizes it into the repo as the canonical OS-level shutdown journey.

4. Extend scripts/run_journey_tests.ps1 to cover the full suite

File: scripts/run_journey_tests.ps1 (from PR-066)

Extend it to support multiple modes:

param(
    [string]$Mode = "all",  # all | shutdown | core | legacy
    [int]$Attempts = 3,
    [double]$UptimeSeconds = 3,
    [double]$TimeoutBuffer = 5
)

$env:STABLENEW_SHUTDOWN_LEAK_ATTEMPTS = "$Attempts"
$env:STABLENEW_AUTO_EXIT_SECONDS = "$UptimeSeconds"
$env:STABLENEW_SHUTDOWN_LEAK_TIMEOUT_BUFFER = "$TimeoutBuffer"
$env:STABLENEW_DEBUG_SHUTDOWN = "1"

# Optional venv activation:
# . "$PSScriptRoot\..\venv\Scripts\Activate.ps1"

if ($Mode -eq "shutdown") {
    python -m pytest tests/journeys/test_shutdown_no_leaks.py -q
}
elseif ($Mode -eq "core") {
    python -m pytest tests/journeys -q
}
elseif ($Mode -eq "legacy") {
    python -m pytest tests/legacy/test_pipeline_journey.py -q
}
else {
    # full suite: core V2 + OS-level shutdown + legacy
    python -m pytest tests/journeys -q
    python -m pytest tests/legacy/test_pipeline_journey.py -q
}


This gives you:

-Mode shutdown → only test_shutdown_no_leaks.py.

-Mode core → JT-01…JT-05 + test_v2_full_pipeline_journey.py.

-Mode legacy → V1 pipeline journey only.

Default (all) → everything (V2 + shutdown + legacy).

5. Extend GitHub Actions workflow for full suite

File: .github/workflows/journeys_shutdown.yml (from PR-066)

Keep the existing shutdown-only job (from PR-066), and add a second job for the full suite:

jobs:
  shutdown-journey:
    # existing job, runs Mode=shutdown

  full-journey-suite:
    runs-on: self-hosted
    env:
      STABLENEW_DEBUG_SHUTDOWN: "1"
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          if (Test-Path dev-requirements.txt) { pip install -r dev-requirements.txt }

      - name: Run full journey suite
        run: |
          scripts\run_journey_tests.ps1 -Mode all


That gives you:

A lightweight, repeatable “shutdown-only” sanity check.

A heavier “full journey suite” job you can run on demand or via schedule.

6. Update journey testing doc

File: docs/Testing_Journeys_V2-P1.md (introduced in PR-066)

Extend it to:

List the existing concrete journeys:

JT-01 – Prompt Pack Authoring & Randomization

JT-02 – LoRA/Embedding Integration

JT-03 – txt2img Pipeline Run

JT-04 – img2img / ADetailer Run

JT-05 – Upscale Stage Run

V2 Full Pipeline Journey (test_v2_full_pipeline_journey.py)

OS Shutdown / No-Leaks Journey (test_shutdown_no_leaks.py)

Legacy Pipeline Journey (V1)

Document how to run:

Locally (PowerShell)

# Shutdown only
scripts\run_journey_tests.ps1 -Mode shutdown

# Core V2 journeys
scripts\run_journey_tests.ps1 -Mode core

# Full suite (V2 + shutdown + legacy)
scripts\run_journey_tests.ps1 -Mode all


In CI (GitHub Actions)

“Journey Tests (Shutdown / No-Leaks)” → shutdown-only job

“full-journey-suite” job → full suite

Call out explicitly that:

Codex/Copilot cannot run these tests in their own sandbox.

They must edit tests + harness and then instruct:

“Run scripts\run_journey_tests.ps1 -Mode shutdown locally”

or “Trigger the ‘Journey Tests’ workflow in GitHub Actions.”

Tests / Validation

Local

Run:

scripts\run_journey_tests.ps1 -Mode core
scripts\run_journey_tests.ps1 -Mode shutdown
scripts\run_journey_tests.ps1 -Mode all


Confirm:

All journey tests execute.

No unknown-marker warnings (journey/legacy are now registered).

test_shutdown_no_leaks.py passes once the shutdown fixes land.

CI

Trigger the updated workflow.

Confirm:

Shutdown-only job behaves as expected.

Full-suite job runs both tests/journeys and tests/legacy/test_pipeline_journey.py.

No production impact

Verify no src/** code was modified.