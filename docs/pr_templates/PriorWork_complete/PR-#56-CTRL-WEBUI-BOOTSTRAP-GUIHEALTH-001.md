PR-#56-CTRL-WEBUI-BOOTSTRAP-GUIHEALTH-001: Non-blocking WebUI Bootstrap + GUI Connection Health & Gating
1. Title

Non-blocking WebUI Bootstrap + GUI Connection Health & Run Gating

2. Summary

This PR changes WebUI startup/health behavior so that:

The GUI always launches, even if WebUI is down or slow.

WebUI connectivity is handled by a controller-level connection workflow instead of blocking main.py.

The GUI shows explicit WebUI status (Ready / Connecting / Error / Disabled).

The Run pathway is gated on WebUI being healthy (no more “run into a dead API”).

There is a Reconnect / Restart WebUI button in the GUI that runs the full connection workflow.

Timeouts and retry behavior are configurable via app_config.

Default behavior:

python -m src.main never exits due to WebUI health; bootstrap_webui becomes best-effort and non-fatal.

When the user attempts to run the pipeline, or when they click “Reconnect”:

Try a fast “already-running” probe.

If that fails and autostart is enabled, start WebUI and:

Wait ~10 seconds.

Retry every 1s up to 10 times (~20s total).

If still unhealthy: show an Error state in the GUI and do not run the pipeline.

This is fully controller/GUI driven and keeps pipeline/pipeline-runner untouched.

3. Problem Statement
3.1 Current behavior

src/main.py calls bootstrap_webui(_load_webui_config()) on startup.

bootstrap_webui calls wait_for_webui_ready synchronously.

If WebUI is not running or slow, wait_for_webui_ready raises WebUIHealthCheckTimeout.

Result: StableNew exits before the GUI appears, and the user has no way to:

See the error state in-UI.

Retry connection.

Relaunch WebUI from the GUI.

This creates a hard dependency on WebUI availability for application launch, which is unfriendly for both dev and normal usage.

3.2 Desired behavior

The GUI should start independently of WebUI.

WebUI health should be visible and controllable inside the GUI, not as a fatal pre-check.

Pipeline runs must be blocked if WebUI is not healthy, with a clear explanation to the user.

There should be a single, explicit controller for “ensure WebUI is ready,” with configurable timeout and retry logic.

4. Goals

Make GUI startup independent of WebUI connectivity (non-blocking bootstrap).

Introduce a WebUI connection controller with:

Initial fast probe.

Optional autostart via WebUIProcessManager.

Configurable wait/retry loop (~20 seconds by default).

Wire WebUI status into the GUI API status panel (or equivalent).

Gate pipeline Run on WebUI status == READY.

Provide a Reconnect / Restart button that runs the connection workflow.

Add tests for:

Connection workflow logic.

Pipeline gating logic.

GUI status & Run button enable/disable behavior.

5. Non-goals

This PR does not:

Change wait_for_webui_ready semantics (HTTP endpoint, error types).

Modify pipeline stages, queue/cluster logic, or learning components.

Change where outputs are written or how models are selected (that’s already handled by PR-50–55 and earlier work).

6. Allowed Files

Codex may modify or create:

Entry point + config

src/main.py

src/config/app_config.py

Controller / connection orchestration

src/controller/pipeline_controller.py (only for WebUI gating and wiring)

src/controller/webui_connection_controller.py (new)

API helpers (light touch)

src/api/healthcheck.py (only to add small helpers/aliases if needed)

src/api/webui_process_manager.py (only to add small helpers/aliases if needed)

GUI

src/gui/api_status_panel.py or src/gui/api_status_panel_v2.py (whichever exists)

src/gui/app_layout_v2.py

src/gui/main_window.py

Any specific V2 run-control widget file only to wire enable/disable callbacks (no feature changes).

Tests

tests/controller/test_webui_connection_controller.py (new)

tests/controller/test_pipeline_controller_webui_gating.py (new)

tests/gui_v2/test_api_status_panel_webui_states_v2.py (new or extend existing)

Docs

docs/codex_context/PIPELINE_RULES.md

docs/codex_context/ARCHITECTURE_v2_COMBINED.md

docs/codex_context/ROLLING_SUMMARY.md

7. Forbidden Files

Do not modify:

src/pipeline/*

src/queue/*

src/controller/job_execution_controller.py

src/controller/job_history_service.py

src/controller/cluster_controller.py

src/cluster/*

src/learning*

src/randomizer*

Any of the new V2 configuration/model panels’ internal behavior:

core_config_panel_v2.py

negative_prompt_panel_v2.py

resolution_panel_v2.py

output_settings_panel_v2.py

model_manager_panel_v2.py

prompt_pack_panel_v2.py

You may only touch those panels if you need to wire in a reference to connection state or a Run-enable callback, not to change their logic.

8. Step-by-step Implementation
8.1 Make bootstrap non-blocking (src/main.py)

Locate:

def main():
    setup_logging("INFO")

    bootstrap_webui(_load_webui_config())

    lock_sock = _acquire_single_instance_lock()
    ...


Change bootstrap_webui so that:

It never calls wait_for_webui_ready.

It:

Reads webui_autostart_enabled from config.

If enabled:

Creates a WebUIProcessManager with WebUIProcessConfig from config.

Calls start() and logs that WebUI autostart has been requested.

Swallows any process-level errors (logs warning, does not crash).

If disabled:

Logs that “WebUI autostart is disabled; GUI will launch without waiting.”

Keep _load_webui_config intact apart from any new config fields described next.

Result: python -m src.main never exits due to a WebUI health exception. At worst, it logs a warning that WebUI may not be running.

8.2 Add WebUI connection config knobs (src/config/app_config.py)

Add new config entries with getters/setters:

webui_autostart_enabled: bool
(may already exist; ensure there’s a clean, documented getter)

webui_health_initial_timeout_seconds: float

Default: 2.0

webui_health_retry_count: int

Default: 10

webui_health_retry_interval_seconds: float

Default: 1.0

webui_health_total_timeout_seconds: float

Default: 20.0 (approx; used to cap the whole workflow)

Environment overrides (suggested):

STABLENEW_WEBUI_HEALTH_INITIAL_TIMEOUT

STABLENEW_WEBUI_HEALTH_RETRY_COUNT

STABLENEW_WEBUI_HEALTH_RETRY_INTERVAL

STABLENEW_WEBUI_HEALTH_TOTAL_TIMEOUT

Ensure existing behavior for other configs is unaffected.

8.3 Introduce WebUIConnectionController (src/controller/webui_connection_controller.py)

Create a new controller class encapsulating the workflow:

Define an enum:

class WebUIConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    READY = "ready"
    ERROR = "error"
    DISABLED = "disabled"


Define controller:

class WebUIConnectionController:
    def __init__(self, app_config: AppConfig, logger: logging.Logger | None = None):
        ...

    def get_state(self) -> WebUIConnectionState:
        ...

    def ensure_connected(self, autostart: bool = True) -> WebUIConnectionState:
        """
        Fast probe → optional autostart → retries → update state → return state.
        """

    def reconnect(self) -> WebUIConnectionState:
        """
        Manual “Reconnect / Restart WebUI” workflow bound to GUI.
        """


Implementation:

ensure_connected:

Read timeouts and retry parameters from app_config.

Try wait_for_webui_ready with initial_timeout.

If success → set state READY → return.

If not healthy:

If autostart is False OR webui_autostart_enabled is False:

Set state ERROR or DISCONNECTED → return.

Else:

Start WebUI via WebUIProcessManager.

Sleep ~10 seconds (configurable or derived from total_timeout).

Loop up to retry_count times:

Call wait_for_webui_ready with retry_interval.

If success: state = READY → return.

If all retries fail:

Set state ERROR → return.

reconnect:

Typically just calls ensure_connected(autostart=True) and returns the resulting state.

Catch all exceptions, log, and set state ERROR.

All external exceptions should be logged, not propagated.

8.4 Integrate with PipelineController (src/controller/pipeline_controller.py)

Add a webui_connection_controller dependency:

Either pass it into PipelineController.__init__ (preferred) or obtain it from a factory.

Store as self._webui_connection.

At the beginning of the run path (before queue/runner logic):

In run_pipeline / run_full_pipeline (whatever your current entrypoint is):

state = self._webui_connection.ensure_connected(autostart=True)
if state is not WebUIConnectionState.READY:
    # Emit a user-facing error message and bail.
    self._emit_error("WebUI is not ready", details=f"State={state.value}")
    return


Do not enqueue or call the pipeline runner if state is not READY.

Optionally expose a query for the GUI:

def get_webui_connection_state(self) -> WebUIConnectionState:
    return self._webui_connection.get_state()


This ensures no pipeline run is attempted if WebUI is offline, slow, or misconfigured.

8.5 Wire WebUI status into API status panel (src/gui/api_status_panel*_v2.py)

Extend the API/WebUI status panel:

Add a label (or similar UI element) for WebUI state:

Display text like: “WebUI: Ready / Connecting / Error / Disabled”

Add a Reconnect / Restart button:

Clicking it calls a callback provided from main_window / controller layer:

e.g., on_webui_reconnect_clicked()

The panel should:

Support a method like set_webui_state(WebUIConnectionState) to update the label.

Invoke the reconnect callback when the button is pressed.

8.6 Layout & main window wiring (app_layout_v2.py, main_window.py)

In app_layout_v2.py:

When constructing the API/WebUI status panel, provide:

A setter for state updates (if needed).

A reconnect callback (bound to a method on the controller / main window).

In main_window.py:

Hold a reference to a WebUIConnectionController (via the main PipelineController).

Implement:

A method to fetch and push the current state into the status panel.

The reconnect callback:

Calls webui_connection_controller.reconnect().

Updates the status panel accordingly.

Consider using root.after(...) to periodically poll and refresh the displayed state (low frequency, e.g. 1–2s), or just refresh on key actions (app startup, reconnect completion, run attempts).

8.7 Gate the Run button

Wherever the main Run button is wired (likely in main_window.py / PipelinePanelV2):

Before actually invoking PipelineController.run_*, check:

If WebUIConnectionState is not READY:

Do not start the pipeline.

Instead:

Focus the API/WebUI status panel.

Optionally display a message (status bar or lightweight dialog):

“Cannot run pipeline: WebUI is not connected. Use ‘Reconnect’ to attempt a restart.”

When status is READY, the Run button should be enabled.

The status panel state and Run button enabled/disabled state should stay in sync.

8.8 Tests

Add or update:

tests/controller/test_webui_connection_controller.py:

test_ensure_connected_already_running:

Mock wait_for_webui_ready to succeed immediately.

Assert final state is READY and no process start.

test_ensure_connected_autostart_and_retries_to_ready:

First probe fails.

Autostart enabled.

Process start called.

Subsequent probes succeed after a few retries.

Final state READY; call ordering verified.

test_ensure_connected_times_out_sets_error:

All healthchecks fail.

Final state ERROR.

tests/controller/test_pipeline_controller_webui_gating.py:

test_run_blocked_when_webui_not_ready:

Inject a fake WebUIConnectionController that always returns ERROR.

Assert run method bails early and doesn’t reach the pipeline runner.

test_run_allowed_when_webui_ready:

Fake returns READY.

Assert run goes through to the runner.

tests/gui_v2/test_api_status_panel_webui_states_v2.py:

test_status_panel_updates_label_for_states:

Drive panel through READY / ERROR / DISCONNECTED (using a fake controller or direct method).

Assert label text changes as expected.

test_reconnect_button_calls_callback:

Inject a mock reconnect callback.

Simulate button click.

Assert callback called once.

Run suites:

pytest tests/controller/test_webui_connection_controller.py -v

pytest tests/controller/test_pipeline_controller_webui_gating.py -v

pytest tests/gui_v2/test_api_status_panel_webui_states_v2.py -v

pytest tests/controller -v

pytest tests/gui_v2 -v

pytest -v (if time permits)

Tk/Tcl-related skips are acceptable; don’t add broad new skips without cause.

9. Acceptance Criteria

This PR is done when:

python -m src.main never exits due to WebUI health; at worst, it logs warnings.

With WebUI stopped:

The GUI still launches.

The API/WebUI status panel shows a non-READY state (Disconnected/Error).

The Run button is disabled or produces a clear “cannot run; WebUI down” message instead of actually running.

Clicking Reconnect / Restart WebUI:

Triggers the controller workflow (probe → autostart → retries).

Within ~20 seconds, ends in either READY or ERROR state.

The GUI updates accordingly.

With WebUI up and healthy:

Status panel shows READY.

Run button is enabled and pipeline runs normally.

All tests in §8.8 pass, except for known Tk/Tcl skips.

10. Rollback Plan

If something goes sideways:

Revert changes to:

src/main.py

src/config/app_config.py

src/controller/webui_connection_controller.py

src/controller/pipeline_controller.py (WebUI-specific bits)

src/api/healthcheck.py / src/api/webui_process_manager.py (if touched)

GUI status panel and layout changes

New tests and docs

Re-run:

pytest tests/controller -v

pytest tests/gui_v2 -v

pytest -v

Confirm behavior matches pre-PR baseline (including the current blocking bootstrap behavior).