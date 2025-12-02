# Journey Tests (Shutdown / No-Leaks)

This guide explains how to run the journey suite, ranging from the GUI-centric JT-01…JT-05 flows to the OS-level shutdown/no-leak verification and the archived legacy journey.

## What this test does

- Launches `python -m src.main` just like a normal Windows user.
- Enables `STABLENEW_AUTO_EXIT_SECONDS` to trigger the real close path (window-close / controller shutdown).
- Ensures no `python.exe` or WebUI processes remain after each run.
- Validates the behavior via `tests/journeys/test_shutdown_no_leaks.py`.

## Running locally (Windows / PowerShell)

The same `scripts\run_journey_tests.ps1` helper now supports multiple modes:

- **shutdown**: only `tests/journeys/test_shutdown_no_leaks.py`
- **core**: JT-01…JT-05 + `tests/journeys/test_v2_full_pipeline_journey.py`
- **legacy**: legacy V1 pipeline journey
- **all** (default): runs core + shutdown + legacy in order

Examples:

```powershell
scripts\run_journey_tests.ps1 -Mode shutdown
scripts\run_journey_tests.ps1 -Mode core
scripts\run_journey_tests.ps1 -Mode all
```

For deep diagnostics (shutdown inspector + file-access trace), use the specialized helper:

```powershell
scripts\run_shutdown_diag.ps1
```

The script still exposes the journey-specific environment variables (`STABLENEW_SHUTDOWN_LEAK_ATTEMPTS`, `STABLENEW_AUTO_EXIT_SECONDS`, `STABLENEW_SHUTDOWN_LEAK_TIMEOUT_BUFFER`) for fine-grained control. It also sets `STABLENEW_DEBUG_SHUTDOWN=1` automatically.

## Running in CI (self-hosted Windows runner)

The GitHub workflow `Journey Tests (Shutdown / No-Leaks)` now includes:

1. A **shutdown-only** job (`run_journey_tests.ps1 -Mode shutdown`)
2. A **full-journey-suite** job (`run_journey_tests.ps1 -Mode all`) that runs all Core V2 journeys, the POST shutdown verification, and the legacy V1 journey in sequence.

Human operators can trigger either job manually via the Actions tab. Both jobs assume the runner has:

- Windows + GUI/Tk support
- SD-WebUI checkout at the expected path (e.g., `C:\Users\rob\stable-diffusion-webui`)
- Python 3.10 (installed via `actions/setup-python@v5`)

When you edit journey-related code, re-run the script (or the workflow) to catch regressions.
Use the provided GitHub Actions workflow:

1. Navigate to **Actions > Journey Tests (Shutdown / No-Leaks)**.
2. Click **Run workflow** (optionally select a branch).
3. Let the job complete (it installs dependencies + runs `scripts\run_journey_tests.ps1`).

The job requires:

- A self-hosted Windows runner with access to SD-WebUI (typically `C:\Users\rob\stable-diffusion-webui`).
- Python 3.10 installed.
- The ability to launch GUI windows (since Tk / WebUI are involved).

## Journey harness note

- The subprocess-driven journeys (shutdown/no-leaks and any future headless modes) now rely on `tools/test_helpers/journey_harness.py`, which centralizes `python -m src.main` execution plus a forward-looking `STABLENEW_JOURNEY_MODE` hook.
- Journey tests are marked with `@pytest.mark.journey` (and `@pytest.mark.slow`), while the legacy V1 journey also bears `@pytest.mark.legacy`.
- Codex cannot run these GUI/SD-WebUI journeys in the sandbox; humans/CI must operate the harness and interpret the results. Always refer back to this doc when advising how to validate a shutdown-related change.
