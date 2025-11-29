PR-022-CONTROLLER-WEBUI-LIFECYCLE-AUTO-LAUNCH-V2-P1
1. Title

PR-022-CONTROLLER-WEBUI-LIFECYCLE-AUTO-LAUNCH-V2-P1 — Deterministic WebUI Launch / Retry & UX Cleanup

2. Summary

Make the WebUI lifecycle predictable and observable from the V2 GUI:

“Launch WebUI” starts or attaches to the local WebUI process deterministically, with clear logging and state transitions.

“Retry” attempts a health check with retries (3-second interval, 4–5 attempts) and updates status accordingly.

If WebUI is already running, the system attaches instead of spawning a duplicate, and connects to the configured base URL.

Duplicate launch/retry buttons in the bottom-right area are removed so there is a single, reliable control pair in the status bar.

Tests are extended to cover the lifecycle state machine and the UX conditions.

3. Problem Statement

Current behavior (as you’re seeing):

Clicking Launch WebUI sometimes just opens the Stable Diffusion web page in a browser, but:

The terminal/API process isn’t clearly started or attached.

There's no visible sense of “WebUI is starting / ready / errored” in the app.

The Retry behavior is opaque:

No clear retry loop with spacing (3 seconds × 4–5 attempts).

Little to no status/log feedback when WebUI is down or not reachable.

The bottom-right area shows multiple Launch/Retry buttons, where:

One set actually works (wired through PR-019’s UX).

Another set is inert / legacy and confuses the user.

Existing tests (test_webui_lifecycle_ux_v2, test_status_bar_webui_controls_v2) cover basic state transitions, but:

They do not enforce retry behavior.

They do not assert that there is only one actionable Launch/Retry pair.

Result: the WebUI lifecycle feels flaky and opaque, and the GUI is cluttered with duplicate controls.

4. Goals

Deterministic WebUI launch path

When the user clicks “Launch WebUI”:

If WebUI is already healthy → attach and report READY.

If WebUI is not healthy → start process via WebUIProcessManager and perform a bounded health wait.

All steps log to the configured logger (and thus to the GUI log handler).

Reliable retry behavior

“Retry” performs a health check with retries:

Poll every ~3 seconds.

Up to 4–5 attempts (about 12–15 seconds total).

On success → state moves to READY.

On failure → state moves to ERROR and logs the reason.

Single, clean Launch/Retry UX

Bottom-right GUI shows exactly one Launch WebUI button and one Retry button, both functional.

Any legacy/inert buttons are removed or rewired, then removed as soon as StatusBarV2/APIStatusPanel own the UX.

Stronger tests

Extend existing lifecycle tests to:

Verify controller calls into WebUIProcessManager with the expected sequence.

Verify the UX only exposes the single control pair in StatusBarV2/APIStatusPanel.

5. Non-goals

No changes to:

Pipeline execution or Journey tests beyond WebUI gating.

Prompt/Pipeline/Learning tab layout (that’s PR-021).

Engine settings dialog behavior or config persistence (PR-015).

No new browser-launch semantics beyond what existing helpers (webui_launcher, etc.) already provide.

No changes to src/main.py or entrypoint selection (that’s already pointing at V2).

6. Allowed Files

Only these files should be modified in this PR:

Core behavior

src/api/webui_process_manager.py

src/controller/app_controller.py

src/controller/webui_connection_controller.py (light touch if needed for state mapping only)

GUI UX / buttons

src/gui/status_bar_v2.py

src/gui/api_status_panel.py

src/gui/main_window_v2.py (only for removing duplicate bottom-right WebUI buttons / wiring them to StatusBarV2)

Tests

tests/api/test_webui_process_manager.py

tests/controller/test_webui_lifecycle_ux_v2.py

tests/controller/test_webui_connection_controller.py (if needed)

tests/gui_v2/test_status_bar_webui_controls_v2.py

tests/app/test_bootstrap_webui_autostart.py (if present and relevant)

If Codex finds it “needs” any additional files, it should stop and report rather than editing them.

7. Forbidden Files

These must not be modified in this PR:

src/main.py

src/gui/theme_v2.py

src/gui/app_state_v2.py (read-only for state names; no structural changes)

src/gui/views/*_tab_frame_v2.py (layout covered by PR-021)

src/pipeline/executor.py

Any files under archive/ or legacy/ directories

Any docs outside docs/pr_templates/ (no doc changes needed for this PR)

8. Step-by-step Implementation
8.1 WebUIProcessManager — bounded auto-launch & health checks

File: src/api/webui_process_manager.py

Tighten ensure_running semantics

Keep the public signature:

def ensure_running(self) -> bool:


Behavior:

If self.is_running() and check_health() returns True → return True immediately (attach to an already-healthy WebUI).

If self.is_running() but health is False → treat as unhealthy:

Optionally log a warning.

Attempt a restart (stop() then start()), then health-check.

If no process is running:

Call start() (spawns the process).

Call check_health() (see below).

Return True if health passes, False otherwise.

All exceptions from start() or check_health() must be caught and cause ensure_running to return False (existing tests’ expectation).

Implement retry logic inside check_health

Keep the existing public method:

def check_health(self) -> bool:


Behavior (high-level):

Determine the base URL:

Priority: self._config.base_url (if set).

Else: STABLENEW_WEBUI_BASE_URL env var.

Else: default "http://127.0.0.1:7860".

Use the existing wait_for_webui_ready(url, timeout=..., poll_interval=...) from src.api.healthcheck.

Adjust defaults to reflect your requirement:

timeout ≈ 15.0 seconds.

poll_interval ≈ 3.0 seconds.

(This translates to ~5 attempts; exact values can be tuned.)

Example (micro-patch style):

def check_health(self) -> bool:
    if self._config.base_url:
        url = self._config.base_url
    else:
        url = os.environ.get("STABLENEW_WEBUI_BASE_URL", "http://127.0.0.1:7860")

    from src.api.healthcheck import wait_for_webui_ready

    try:
        return wait_for_webui_ready(url, timeout=15.0, poll_interval=3.0)
    except Exception:
        return False


This preserves the “single-call” contract from AppController tests (FakeWebUIManager sees only one check_health call) while giving the real manager a robust retry loop.

Optional: log context

Use LogContext(subsystem="api") and log_with_ctx around ensure_running and check_health to log:

“WebUI already running; checking health…”

“WebUI start requested…”

“WebUI health check succeeded/failed for URL …”

Do not change function signatures; tests depend on them.

8.2 WebUIConnectionController — ensure_connected & reconnect clarity (light touch)

File: src/controller/webui_connection_controller.py

Ensure ensure_connected(autostart: bool) leverages WebUIProcessManager.ensure_running() when autostart=True rather than manually reproducing spawn logic.

Ensure reconnect():

Sets state to DISCONNECTED.

Calls ensure_connected(autostart=True).

On success → state READY.

On failure or exception → state ERROR.

Keep the state enum (DISCONNECTED, CONNECTING, READY, ERROR) as the canonical state set.

8.3 AppController — lifecycle command methods

File: src/controller/app_controller.py

Confirm or implement:

def on_launch_webui_clicked(self) -> None:
    self._append_log("[webui] Launch requested by user.")
    ok = self._webui_process_manager.ensure_running()
    if ok:
        self._update_webui_state("connected")  # or via WebUIConnectionState.READY
    else:
        self._update_webui_state("error")


The semantics above must remain backward-compatible with FakeWebUIManager in test_webui_lifecycle_ux_v2.py:

ensure_running() is called once.

State is updated to “connected” on True, “error” on False.

Confirm or implement:

def on_retry_webui_clicked(self) -> None:
    self._append_log("[webui] Retry requested by user.")
    ok = self._webui_process_manager.check_health()
    if ok:
        self._update_webui_state("connected")
    else:
        self._update_webui_state("error")


Again, only one call to check_health() — the retries happen inside the real manager.

_update_webui_state must:

Map internal string/enum to WebUIConnectionState.

Update:

app_state.webui_state.

status_bar_v2.set_webui_state(...) (or equivalent).

Ensure state transitions drive the button enable/disable logic.

8.4 Status bar & API status panel — single control pair

Files:

src/gui/status_bar_v2.py

src/gui/api_status_panel.py

src/gui/main_window_v2.py (for duplicate button removal only)

APIStatusPanel owns the buttons

Ensure APIStatusPanel defines one Launch button and one Retry button:

Launch button command → calls a _on_launch_clicked, which invokes the _launch_callback.

Retry button command → _on_retry_clicked, invoking _retry_callback.

Confirm StatusBarV2 only instantiates APIStatusPanel once and passes:

APIStatusPanel(master=self, launch_callback=controller.on_launch_webui_clicked, retry_callback=controller.on_retry_webui_clicked, ...)


Ensure StatusBarV2.update_webui_state(...) or set_webui_state(...) drives the button states:

When CONNECTED/READY → Launch disabled, Retry enabled or context-appropriate.

When DISCONNECTED/ERROR → Launch enabled, Retry enabled.

Remove / de-duplicate extra buttons

Search src/gui/main_window_v2.py (and V2-only panels) for any additional ttk.Button with labels like:

“Launch WebUI”

“Retry Connection”

For any duplicates:

If they are inert → remove them outright.

If they are wired directly to controller methods:

Replace them with simple wrappers around StatusBarV2 or just delete them, relying solely on the status bar’s controls.

Goal: the only place the user sees Launch/Retry is in the status bar / APIStatusPanel.

Internal attributes for tests

StatusBarV2 already exposes _launch_button for tests (per test_status_bar_webui_controls_v2.py).

Make sure that:

There is only one _launch_button and one _retry_button attribute.

Tests that introspect these attributes still pass.

8.5 Tests
8.5.1 tests/controller/test_webui_lifecycle_ux_v2.py

Confirm existing tests:

test_on_launch_webui_updates_state:

FakeWebUIManager.ensure_running() called once.

State goes to “connected” on success.

test_on_launch_webui_handles_failure:

ensure_running() returns False → state “error”.

test_on_retry_webui_updates_state:

check_health() called once.

State “connected” on True.

If necessary, extend with:

def test_on_launch_webui_logs_and_calls_manager_once(...):
    # assert log + ensure_calls == 1


but avoid changing call-count expectations.

8.5.2 tests/api/test_webui_process_manager.py

Add tests to verify:

When is_running() returns True and check_health() is patched to True → ensure_running() returns True without calling start().

When not running:

ensure_running() calls start() and then check_health() once.

When check_health() returns False → ensure_running() returns False and does not raise.

Optionally, a test mocking wait_for_webui_ready to assert it is called with timeout≈15.0 and poll_interval≈3.0.

8.5.3 tests/gui_v2/test_status_bar_webui_controls_v2.py

Extend or add assertions:

Only one launch and one retry button exist.

update_webui_state("connected") disables Launch.

update_webui_state("error") re-enables Launch.

Keep the Tk skip behavior: this test must skip gracefully if Tk/auto.tcl is unavailable in Codex’s environment.

8.5.4 tests/controller/test_webui_connection_controller.py

If needed, assert that:

ensure_connected(autostart=True) calls WebUIProcessManager.ensure_running() at least once.

reconnect() moves through DISCONNECTED → (CONNECTING) → READY/ERROR appropriately.

9. Required Tests (Failing first)

Codex should follow this sequence:

Add/update tests first, then run:

pytest tests/controller/test_webui_lifecycle_ux_v2.py -q
pytest tests/api/test_webui_process_manager.py -q
pytest tests/gui_v2/test_status_bar_webui_controls_v2.py -q  # expected to skip if Tk not available


At least one test should fail on the baseline (pre-PR) to prove the PR is adding coverage for missing behavior.

Implement the code changes.

Re-run the above tests until they pass.

Run a broader subset:

pytest tests/controller/test_pipeline_controller_webui_gating.py -q
pytest tests/controller/test_webui_connection_controller.py -q
pytest tests/app/test_bootstrap_webui_autostart.py -q


to ensure no regressions in startup/gating.

10. Acceptance Criteria

Launch behavior

Clicking “Launch WebUI”:

If WebUI is already healthy → immediately updates state to READY/connected without spawning a new process.

If WebUI is not running → spawns process, waits up to ~15 seconds with internal retries, and sets state to connected on success or error on failure.

Retry behavior

Clicking “Retry” triggers a bounded health check with multiple attempts (via check_health()), and state is updated accordingly.

UX

Only one pair of Launch/Retry buttons is visible in the bottom-right status area.

Buttons enable/disable states clearly reflect WebUI connection state (e.g., Launch disabled when connected).

Logging

Logs clearly indicate:

Launch requested, process starting (or reusing running process).

Health check attempts and outcomes.

Error messages when unable to start or connect.

Tests

All updated tests pass:

tests/controller/test_webui_lifecycle_ux_v2.py

tests/api/test_webui_process_manager.py

tests/gui_v2/test_status_bar_webui_controls_v2.py (or is cleanly skipped in Tk-less environments)

Any related WebUI gating/startup tests.

11. Rollback Plan

If the PR introduces issues:

Revert changes to:

src/api/webui_process_manager.py

src/controller/app_controller.py

src/controller/webui_connection_controller.py

src/gui/status_bar_v2.py

src/gui/api_status_panel.py

src/gui/main_window_v2.py

Modified tests.

Re-run:

pytest tests/controller/test_webui_lifecycle_ux_v2.py \
       tests/api/test_webui_process_manager.py \
       tests/gui_v2/test_status_bar_webui_controls_v2.py -q


Confirm behavior matches the pre-PR snapshot (even if less robust).

Because this PR is constrained to a handful of lifecycle-related files, rollback is straightforward.

12. Codex Execution Constraints

When you hand this to Codex:

Explicitly list the Allowed Files and Forbidden Files as above.

Instructions to Codex:

“Do not change any public function names or signatures.”

“Preserve the single-call semantics of AppController.on_launch_webui_clicked and on_retry_webui_clicked; retries must occur inside the real WebUIProcessManager implementations.”

“Avoid introducing new modules or classes; keep diffs minimal and in-place.”

“Maintain skip guards for GUI tests so they skip gracefully when Tk is not available.”