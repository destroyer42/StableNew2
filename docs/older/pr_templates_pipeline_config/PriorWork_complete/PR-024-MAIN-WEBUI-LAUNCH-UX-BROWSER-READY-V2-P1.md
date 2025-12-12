PR-024-MAIN-WEBUI-LAUNCH-UX-BROWSER-READY-V2-P1
1. Title

PR-024-MAIN-WEBUI-LAUNCH-UX-BROWSER-READY-V2-P1 — WebUI Launch Button Opens Browser & Uses Connection Controller READY State

2. Summary

This PR fixes the WebUI launch UX so that:

Clicking Launch WebUI in the V2 status bar:

Uses the WebUIConnectionController to ensure the WebUI API is actually reachable (READY), and

Opens the WebUI in the default browser at the configured base URL.

The status bar’s WebUI indicator is driven by the same WebUIConnectionState that the controller uses (DISCONNECTED, CONNECTING, READY, ERROR), so status changes are visible and consistent with actual health.

This PR does not yet guarantee that model/VAE/sampler/scheduler dropdowns are repopulated from WebUI resources — that will be handled in a focused follow-on PR that hooks WebUI resources into the pipeline config panels. This PR’s job is to make the “WebUI is up and I can see it” part deterministic and observable.

3. Problem Statement

Current behavior (from logs and manual testing):

webui-user.bat does start from WebUIProcessManager (logs show venv, model loading, ADetailer init).

The healthcheck hits http://127.0.0.1:7860/sdapi/v1/progress and reports WebUI API ready.

The new WebUIConnectionController sees state transitions, and logs:

WebUI status update: state = WebUIConnectionState.DISCONNECTED
...
WebUI status update: state = WebUIConnectionState.READY


But from the GUI user’s perspective:

No browser window/tab is opened when WebUI hits READY.

The status panel often appears stuck on “disconnected” until you manually click Retry, because the async bootstrap and the connection controller are loosely coupled and the status label is subtle.

There’s no clear, single “success moment” where:

The user sees WebUI in the browser, and

The status bar clearly flips to READY.

Additionally, although dropdowns in the advanced stage cards are designed to be fed from WebUI resources (get_available_models, get_available_samplers, etc.), that wiring is not complete yet — so even when the API is healthy, the user does not see their model/VAE/sampler dropdowns update. That makes it hard to trust that WebUI connectivity is truly working.

We need a small, surgical fix that makes the Launch button obviously “do the right thing” and exposes a clean READY signal that future dropdown-refresh logic can hook into.

4. Goals

Launch button → ensure connection → open browser

When the user clicks Launch WebUI:

Use WebUIConnectionController.ensure_connected(autostart=True) as the single source of truth for connection/health.

If the resulting state is WebUIConnectionState.READY, open the WebUI base URL in the default browser (new tab/window).

Use the controller’s base URL instead of hardcoding

Expose a simple get_base_url() on WebUIConnectionController so UI code doesn’t guess the URL.

Log the full lifecycle

Log “Launch WebUI button clicked”, “Opening WebUI browser at …”, and state changes (DISCONNECTED → CONNECTING → READY/ERROR) in a consistent way for debugging.

Set up a clean hook for future dropdown refresh

Ensure that WebUIConnectionState.READY is clearly available in _update_window_webui_manager, so a future PR can subscribe and trigger “refresh WebUI resources → repopulate model/VAE/sampler/scheduler dropdowns” after READY.

5. Non-goals

No changes to:

How WebUIProcessManager starts the process (still runs webui-user.bat under the same console; we’re not toggling CREATE_NEW_CONSOLE here).

The pipeline execution path or Journey tests.

The actual dropdown-population logic for models/VAEs/samplers/schedulers (that will be a separate PR specifically for “WebUI resources → pipeline config dropdowns”).

No new modules; only small additions to existing files.

No changes to the V2 GUI layout (tabs/columns) — that’s already handled in previous PRs.

6. Allowed Files

Only the following files may be modified in this PR:

src/main.py

src/controller/webui_connection_controller.py

tests/app/test_bootstrap_webui_autostart.py (extend)
or (preferred) new test file:

tests/app/test_webui_launch_opens_browser_v2.py

If Codex believes any other file must be changed, it should stop and report instead of editing.

7. Forbidden Files

These files must not be modified in this PR:

src/pipeline/executor.py

src/pipeline/pipeline_runner.py

src/gui/main_window_v2.py

src/gui/status_bar_v2.py

src/gui/views/pipeline_config_panel_v2.py

src/gui/stage_cards_v2/*

src/api/webui_process_manager.py

src/api/webui_resources.py

Any files under archive/ or legacy/

Any documentation files (docs/*.md)

8. Step-by-step Implementation
8.1 Add base URL accessor to WebUIConnectionController

File: src/controller/webui_connection_controller.py

Add a simple getter to expose the current base URL:

class WebUIConnectionController:
    ...
    def get_base_url(self) -> str:
        """Return the current WebUI base URL used for health checks."""
        return self._base_url_provider()


Do not change the constructor signature or existing behavior.

get_base_url() should always return the same URL that ensure_connected will probe.

(Optional but nice) Add a tiny unit test to tests/controller/test_webui_connection_controller.py (if present):

Monkeypatch _base_url_provider to return a known URL.

Assert that get_base_url() returns that URL.

8.2 Wire Launch button → ensure_connected → open browser

File: src/main.py (inside _update_window_webui_manager)

We already create a WebUIConnectionController and configure callbacks for the status panel:

update_status(log_changes: bool = True)

launch_callback()

retry_callback()

webui_panel.set_launch_callback(launch_callback)

webui_panel.set_retry_callback(retry_callback)

window.after(1000, periodic_check) to drive periodic status checks.

Modify launch_callback() as follows:

Add import webbrowser at the top of src/main.py (standard library import).

Replace the body of launch_callback() with logic that:

def launch_callback() -> None:
    nonlocal consecutive_failures, error_logged, last_logged_state
    try:
        logging.info("Launch WebUI button clicked")
        # Ask the connection controller to ensure WebUI is reachable
        new_state = connection_controller.ensure_connected(autostart=True)
        webui_panel.set_webui_state(new_state)

        if new_state is WebUIConnectionState.READY:
            try:
                base_url = connection_controller.get_base_url()
                logging.info("Opening WebUI in browser at %s", base_url)
                import webbrowser  # if not already imported at top
                webbrowser.open_new_tab(base_url)
            except Exception as exc:
                logging.warning("Failed to open WebUI browser tab: %s", exc)

        # reset counters on successful launch/reconnect attempt
        consecutive_failures = 0
        error_logged = False
        last_logged_state = None
    except Exception as e:
        logging.warning("Failed to launch WebUI: %s", e)


Key points:

We do not change the semantics of ensure_connected — it still owns the logic for “check health → autostart if allowed → retry until READY/ERROR.”

If the state comes back READY, we:

fetch the effective base URL via connection_controller.get_base_url(), and

open a browser tab to that URL.

All errors in opening the browser are logged but don’t crash the GUI.

Keep retry_callback() as-is:

It should continue to call connection_controller.reconnect() and webui_panel.set_webui_state(new_state).

8.3 Keep periodic status monitoring intact

File: src/main.py

Do not change update_status() or the periodic_check() loop, except to ensure they still call:

state = connection_controller.get_state()

webui_panel.set_webui_state(state)

The periodic check should remain responsible for:

Logging state changes.

Attempting auto-reconnect after repeated DISCONNECTED states.

This PR’s only behavior change in update_status/periodic_check is that Launch now opens the browser once READY is confirmed.

9. Required Tests (Failing first)

Before implementing code changes, Codex should:

Add a new test (or extend an existing one) to enforce the desired behavior.

Preferred: new file tests/app/test_webui_launch_opens_browser_v2.py:

Arrange:

Build a small fake window structure with:

A fake status_bar_v2 containing a real or fake webui_panel that can accept set_launch_callback.

A fake webui_panel object that stores the launch callback in a test-accessible attribute.

Monkeypatch:

src.main.WebUIConnectionController to a fake controller where:

get_state() returns WebUIConnectionState.DISCONNECTED by default.

ensure_connected(autostart=True) returns WebUIConnectionState.READY.

get_base_url() returns "http://127.0.0.1:7860".

webbrowser.open_new_tab to a mock.

Act:

Call _update_window_webui_manager(window, fake_manager) to wire up the status bar.

Invoke the launch callback that webui_panel.set_launch_callback received.

Assert (baseline expected to fail before code change):

webbrowser.open_new_tab is called exactly once with "http://127.0.0.1:7860".

Run:

pytest tests/app/test_webui_launch_opens_browser_v2.py -q


It should fail on the baseline, since launch_callback does not currently open the browser.

Then implement the changes and re-run until the test passes.

10. Acceptance Criteria

Functionally, this PR is done when:

Launch button behavior

From a clean app start (python -m src.main):

Clicking Launch WebUI:

Logs “Launch WebUI button clicked”.

Calls WebUIConnectionController.ensure_connected(autostart=True).

If WebUI is reachable, logs “Opening WebUI in browser at http://127.0.0.1:7860”
 (or the configured URL).

Opens a browser tab to that URL.

If WebUI is already running, the same behavior occurs without spawning a second instance — ensure_connected succeeds quickly and we only open the browser.

Status indicator

The status area in the bottom-right shows WebUI state that matches WebUIConnectionController:

DISCONNECTED → initial state.

CONNECTING → while ensure_connected is probing.

READY → once ensure_connected/reconnect succeed.

ERROR → when WebUI cannot be reached.

Logs include “WebUI status update: state = WebUIConnectionState.READY” when Ready is reached.

Browser failure handling

If webbrowser.open_new_tab raises an exception, the app logs a warning but does not crash and the WebUI state still reflects READY correctly.

Tests

All new/updated tests pass:

pytest tests/app/test_webui_launch_opens_browser_v2.py -q

Existing WebUI bootstrap tests remain green:

pytest tests/app/test_bootstrap_webui_autostart.py -q

No other tests regress.

Dropdowns (forward-looking note)

While this PR does not fully wire model/VAE/sampler/scheduler dropdowns to WebUI resources, it establishes a reliable READY state and browser launch flow.

A future PR will hook into this READY state to trigger WebUI resource refresh and repopulate the dropdowns. At that point, your “true test” will indeed be:

WebUI launches and is visible, and

All related dropdowns update from the WebUI API.

11. Rollback Plan

If this PR causes regressions:

Revert changes in:

src/main.py

src/controller/webui_connection_controller.py

tests/app/test_webui_launch_opens_browser_v2.py (or any modifications to tests/app/test_bootstrap_webui_autostart.py)

Re-run:

pytest tests/app/test_bootstrap_webui_autostart.py -q
pytest tests/app/test_webui_launch_opens_browser_v2.py -q  # should be removed or skipped after revert


Confirm behavior is back to the prior state:

WebUI still autostarts in the background when configured.

Status panel still updates via the connection controller.

Launch button no longer tries to open the browser.

12. Codex Execution Constraints

When you hand this spec to Codex / an implementer agent, include the following constraints explicitly:

Do not modify any files outside the Allowed Files list.

Do not change public function signatures or class names in:

WebUIConnectionController

bootstrap_webui

_update_window_webui_manager

Use the existing WebUIConnectionController and WebUIConnectionState types:

No new enums or parallel state mechanisms.

Keep diffs minimal and surgical, focused only on:

Adding get_base_url() to the controller.

Updating the launch_callback in src/main.py.

Adding the new test.

If Codex believes another file must be changed, it should stop, explain why, and wait for human approval.