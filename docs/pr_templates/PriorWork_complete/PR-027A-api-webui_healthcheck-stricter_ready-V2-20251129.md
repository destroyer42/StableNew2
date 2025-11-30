PR-027@a-api-webui_healthcheck-stricter_ready-V2-202511291. Title

PR-027@a-api-webui_healthcheck-stricter_ready-V2-20251129 — Fix Premature WebUI READY & Harden Healthcheck

2. Summary

This PR fixes the core WebUI healthcheck so that:

wait_for_webui_ready only returns READY when the WebUI API is actually usable, not just when /sdapi/v1/progress responds.

The healthcheck uses model/options endpoints (e.g., /sdapi/v1/sd-models or /sdapi/v1/options) as the primary readiness signal, with /progress as a secondary “server up but not ready” probe.

WebUIConnectionController.ensure_connected and bootstrap_webui automatically benefit from the stricter semantics through the existing wait_for_webui_ready calls.

New tests cover:

“API server up but models not loaded yet” (should NOT report READY).

“API fully ready and models list returns” (should report READY).

Timeout and error paths.

This is a backend-only change: no GUI layout changes, no dropdown wiring in this PR. The goal is to stop lying about “READY” and give the later dropdown/resource PR something trustworthy to hook into.

3. Problem Statement

Currently, wait_for_webui_ready in src/api/healthcheck.py probes only:

GET {base_url}/sdapi/v1/progress

This endpoint frequently returns 200 OK before the SD backend has finished loading models and initializing pipelines. In your logs we see:

Healthcheck reporting “WebUI API ready at: …/progress” within milliseconds of process start.

Only after that do we see “Loading weights …” and model config logs.

Because WebUIConnectionController.ensure_connected and bootstrap_webui both rely on wait_for_webui_ready, the entire system is getting a false positive:

Controller marks the state as READY.

The status bar shows WebUI: Ready.

The WebUI resource fetch / dropdown wiring (next PR) has nothing reliable to latch onto.

From the user’s perspective, nothing works yet: dropdowns are empty, generate actions fail, and the UI appears to be lying.

We need the healthcheck to mean:

“The WebUI API is responsive and the core resources (models/options) can be queried successfully.”

4. Goals

Tighten readiness signal

wait_for_webui_ready returns True only if at least one “heavy” API endpoint (models/options) responds successfully within the timeout window.

Keep the function signature stable

No caller changes required; all existing uses (main/bootstrap, controller, discovery) should “just get better behavior.”

Preserve configurability via app_config

Respect existing timeouts, retry intervals, and total timeout semantics from app_config / controller.

Improve logging for observability

Log which endpoint succeeded (/sd-models, /options, /progress fallback).

Log when the API is reachable but NOT fully ready (e.g., /progress works but /sd-models fails).

Add focused tests

Simulate success/failure/timeouts via monkeypatched requests.get.

Confirm the controller’s “initial fast probe” uses the stricter healthcheck semantics.

5. Non-goals

No GUI changes (status bar duplication, logging panel visibility, etc. are separate PRs).

No dropdown/resource wiring in this PR (that will be the follow-on PR-028).

No modifications to WebUIProcessManager process launch behavior.

No changes to app configuration schema (env vars / config keys remain the same).

6. Allowed Files

Only these files may be modified:

src/api/healthcheck.py

src/controller/webui_connection_controller.py (only to leverage stricter semantics / logging, not to change public API)

src/utils/webui_discovery.py (if needed to stay consistent with the new readiness semantics)

Tests:

tests/api/test_healthcheck_v2.py (new)

tests/controller/test_webui_connection_controller_health_v2.py (new or extensions to an existing controller test file)

If Codex believes any other file must be edited, it should stop and surface that as a separate PR request.

7. Forbidden Files

Must not be modified in this PR:

src/gui/main_window_v2.py

src/gui/status_bar_v2.py

src/gui/api_status_panel.py

src/gui/views/*

src/main.py (no changes to the thin wrapper; it should continue to import wait_for_webui_ready from src.api.healthcheck)

src/api/webui_process_manager.py

src/api/webui_resources.py

src/pipeline/*

Anything under archive/ or clearly marked V1 / legacy.

GUI and pipeline work are explicitly out of scope for this PR.

8. Step-by-step Implementation
8.1 Strengthen wait_for_webui_ready

File: src/api/healthcheck.py

Current behavior (simplified):

Build probe_url = {base_url}/sdapi/v1/progress.

Loop until timeout:

requests.get(probe_url, timeout=min(timeout, 5.0))

If status 200 → log “WebUI API ready” and return True.

Proposed behavior:

Introduce endpoint constants near the top of the module

PROGRESS_PATH = "/sdapi/v1/progress"

MODELS_PATH = "/sdapi/v1/sd-models"

OPTIONS_PATH = "/sdapi/v1/options"

Change readiness semantics inside wait_for_webui_ready

Inside the function, compute:

progress_url = f"{base_url.rstrip('/')}{PROGRESS_PATH}"

models_url = f"{base_url.rstrip('/')}{MODELS_PATH}"

options_url = f"{base_url.rstrip('/')}{OPTIONS_PATH}"

Poll loop:

First, try models (preferred strong signal):

GET models_url

If status_code == 200 and the body is valid JSON (list or dict), log:

“WebUI API ready (models endpoint): {models_url}”

and return True.

If models fails (non-200 or exception):

Try options as a secondary strong signal:

GET options_url

If 200 and valid JSON, log:

“WebUI API ready (options endpoint): {options_url}”

and return True.

Only if both models and options fail:

Optionally ping progress as a weak signal:

GET progress_url

If 200:

Log:

“WebUI API reachable but models/options not ready yet: {progress_url}”

along with the last error from models/options, if available.

Do not return True yet. Continue polling until timeout.

Between iterations, sleep poll_delay as before.

On timeout:

Include the last error (from models/options) in the exception message, if available.

Raise WebUIHealthCheckTimeout exactly as before.

Logging

Ensure logs clearly differentiate between:

“Probing WebUI readiness at model/options endpoints.”

“WebUI API reachable (progress endpoint) but not ready for models/options yet.”

“WebUI did not become ready within allotted time.”

Reuse LogContext with subsystem "api" and add fields like {"endpoint": "/sdapi/v1/sd-models"} where useful.

Backward compatibility

Keep the function signature unchanged:

def wait_for_webui_ready(base_url: str, timeout: float = 30.0, poll_interval: float = 0.5) -> bool:

Callers do not need to pass any new parameters; they automatically benefit from the stricter semantics.

8.2 Adjust find_webui_port to align with new readiness semantics

File: src/api/healthcheck.py

The find_webui_port helper currently:

Iterates over candidate ports, constructing URLs.

Uses /sdapi/v1/progress as the probe.

Update:

Keep port scanning logic as-is, but for each candidate URL:

Probe using wait_for_webui_ready(candidate_url, timeout=short_timeout, poll_interval=1.0) instead of manually hitting /progress.

For performance:

Use a short timeout (e.g., 3–5 seconds) for each candidate in find_webui_port, to avoid a long stall when scanning multiple ports.

Preserve logging:

When a WebUI instance is found but API not enabled (e.g., web interface responds but models/options path fails), keep emitting the existing log that suggests starting WebUI with --api.

This keeps the semantics consistent: every “ready” result now means “models/options success,” no matter which port was detected.

8.3 Ensure WebUIConnectionController uses the stricter semantics correctly

File: src/controller/webui_connection_controller.py

The controller already uses wait_for_webui_ready multiple times:

Initial fast probe for an already-running WebUI.

After autostart, with a longer timeout.

When a different port is auto-detected via find_webui_port.

We don’t need to change the algorithm, but we should:

Update logging to reflect the new semantics

Where it currently logs “WebUI ready,” update messages to something like:

"WebUI models/options are ready at %s"

so log lines match the stricter semantics.

Ensure state transitions are correct

On a successful wait_for_webui_ready call:

Always set self._state = WebUIConnectionState.READY and return it.

On WebUIHealthCheckTimeout or other exceptions:

Maintain the existing behavior (stay DISCONNECTED or transition to ERROR).

No change to public API

Methods and signatures remain:

get_state()

ensure_connected(autostart: bool = True)

reconnect()

_set_base_url_from_env_or_config() etc.

8.4 Tests
8.4.1 Healthcheck tests

File: tests/api/test_healthcheck_v2.py (new)

Add tests using monkeypatching of requests.get to simulate different phases.

test_wait_for_webui_ready_succeeds_when_models_endpoint_ready

Arrange:

Base URL: "http://127.0.0.1:7860".

Monkeypatch healthcheck.requests.get so:

Calls to /sdapi/v1/sd-models return a fake Response with status_code=200 and a small JSON list.

No progress usage needed in this happy path.

Act:

Call wait_for_webui_ready(base_url, timeout=1.0, poll_interval=0.01).

Assert:

Returns True without raising.

test_wait_for_webui_ready_does_not_return_true_on_progress_only

Arrange:

requests.get returns:

For /sdapi/v1/sd-models → either 500 or raises requests.exceptions.ConnectionError.

For /sdapi/v1/options → same failure.

For /sdapi/v1/progress → 200 OK.

Act:

Call wait_for_webui_ready with a small timeout (e.g., 0.3–0.5 seconds).

Assert:

Raises WebUIHealthCheckTimeout.

Verify via captured logs (optional) that the function logs “API reachable but not ready” while never marking it as ready.

test_wait_for_webui_ready_uses_poll_interval_and_timeout

Optionally, assert that the number of calls to requests.get roughly matches timeout / poll_interval to ensure we aren’t busy-looping.

8.4.2 Controller tests

File: tests/controller/test_webui_connection_controller_health_v2.py

test_ensure_connected_uses_strict_healthcheck

Monkeypatch:

healthcheck.wait_for_webui_ready to:

First call → raise WebUIHealthCheckTimeout.

Second call → return True.

Assert:

ensure_connected(autostart=True):

Calls autostart (simulate via fake WebUIProcessManager).

Eventually sets state to READY only when healthcheck returns True.

test_ensure_connected_does_not_mark_ready_when_healthcheck_times_out

Monkeypatch wait_for_webui_ready to always raise WebUIHealthCheckTimeout.

Assert:

ensure_connected(autostart=False) returns DISCONNECTED or ERROR (whatever the current behavior is), but never sets READY.

9. Required Tests (Failing first)

Before implementing the new behavior, Codex should:

Add the new tests:

tests/api/test_healthcheck_v2.py

tests/controller/test_webui_connection_controller_health_v2.py

Run:

pytest tests/api/test_healthcheck_v2.py -q

pytest tests/controller/test_webui_connection_controller_health_v2.py -q

They should initially fail because the current implementation treats /progress as READY.

After implementing the stricter healthcheck:

All new tests must pass.

Existing tests that rely on wait_for_webui_ready or WebUIConnectionController must remain green.

10. Acceptance Criteria

This PR is complete when:

Readiness semantics are correct

wait_for_webui_ready only returns True if:

/sdapi/v1/sd-models or /sdapi/v1/options responds with 200 and valid JSON within the timeout.

If only /sdapi/v1/progress responds 200 but the other endpoints fail, the function logs this and eventually raises WebUIHealthCheckTimeout.

Controller behavior

WebUIConnectionController.ensure_connected uses the stricter healthcheck and:

Does not mark READY on progress-only responses.

Transitions to READY only after a successful models/options probe.

Logs reflect reality

When watching python -m src.main, you see:

“Probing WebUI readiness at models/options …”

“WebUI API ready (models/options endpoint): …” when fully ready.

Or “WebUI did not become ready within allotted time …” with last error details on timeout.

No regressions

The app still boots, WebUI still autostarts from StableNew, and once the A1111 backend is truly up:

Status eventually becomes READY (even if it now takes a little longer).

No new exceptions are raised in typical startup flows.

11. Rollback Plan

If this PR causes issues (e.g., too strict for certain custom WebUI builds):

Revert changes in:

src/api/healthcheck.py

src/controller/webui_connection_controller.py

src/utils/webui_discovery.py (if touched)

New tests under tests/api/ and tests/controller/ created for this PR.

Rerun:

pytest tests/api/test_healthcheck_v2.py tests/controller/test_webui_connection_controller_health_v2.py -q

Behavior will return to the current (looser) semantics: /sdapi/v1/progress ≈ READY.

12. Codex Execution Constraints

When you hand this to Codex, include:

“Only modify the Allowed Files; treat Forbidden Files as read-only.”

“Do not change any public APIs or function signatures.”

“Keep diffs minimal and surgically scoped to healthcheck semantics and related tests.”

“If you discover a need to modify GUI, pipeline, or process manager code, stop and surface that as a separate PR request.”

13. Smoke Test Checklist (for you to run manually)

After the PR is implemented and tests pass:

Start StableNew

cd C:\Users\rob\projects\StableNew
python -m src.main


Observe logs while WebUI is starting

You should not see “WebUI API ready …” until after the A1111 window has:

Logged model loading,

Finished initializing,

And the WebUI web page is actually responsive.

Watch for correct “READY” timing

If A1111 is slow to load models, healthcheck should keep polling and only declare READY after models/options succeed.

Negative test

Start StableNew with WebUI turned off / broken:

You should get clear log messages and an eventual timeout, not a false READY.

Once this lands, READY will finally mean READY, which sets us up for PR-028 to safely wire the model/VAE/sampler/scheduler dropdown population onto that state.