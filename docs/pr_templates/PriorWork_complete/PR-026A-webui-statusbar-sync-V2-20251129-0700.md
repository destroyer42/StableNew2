PR-026A-webui-statusbar-sync-V2-20251129-0700.md

2. Summary

Unify the WebUI status bar so there is one clear connection state, ensure the Launch/Retry buttons use the same lifecycle path that the smoketest exercises, and make sure the UI gets updated consistently when WebUI transitions between DISCONNECTED / CONNECTING / READY / ERROR.

3. Problem Statement

Current behavior (from snapshot 2025-11-29-065214):

Status bar shows three conflicting indicators:

A progress bar on the far left,

A separate text label hard-coded to disconnected,

An API status panel that says WebUI: Ready.

_update_window_webui_manager drives the API status panel directly via webui_panel.set_webui_state, but never calls StatusBarV2.update_webui_state, leaving _webui_state_label stale.

StatusBarV2 itself also wires the WebUI buttons to AppController.on_launch_webui_clicked / on_retry_webui_clicked, but _update_window_webui_manager overwrites the callbacks with a separate WebUIConnectionController’s handlers.

The smoketest only validates the panel + browser launch path, so it passes while the visible status bar looks wrong.

This makes it hard to trust the UI and to reason about whether WebUI is actually connected.

4. Goals

Single source of truth for WebUI state in the status bar.

Launch/Retry buttons use a single, predictable lifecycle path.

StatusBarV2.update_webui_state is actually used when state changes.

Keep the changes surgical and V2-only; no architectural rework.

5. Non-goals

No changes to pipeline execution, dropdown population, or WebUIResourceService (that’s the next PR you already asked for).

No redesign of the entire status bar layout beyond what’s needed to remove conflicting labels.

No behavior changes to the underlying healthcheck or WebUIProcessManager.

6. Allowed Files

src/main.py

src/gui/status_bar_v2.py

src/gui/api_status_panel.py (if needed for small label tweaks)

tests/app/test_webui_launch_opens_browser_v2.py

7. Forbidden Files

(All others, especially:)

src/gui/main_window_v2.py

src/controller/app_controller.py

src/controller/pipeline_controller.py

src/api/webui_process_manager.py

src/api/webui_resources.py

Unless explicitly unlocked later.

8. Step-by-step Implementation

StatusBarV2: remove the duplicate “disconnected” label or sync it

In StatusBarV2.__init__ (src/gui/status_bar_v2.py):

Either:

Option A (simpler, recommended): remove _webui_state_label entirely and rely solely on APIStatusPanel.status_label to show WebUI state. The left “Status” label remains for pipeline run status (“Idle/Running/Error”), and the right WebUI panel shows “WebUI: Disconnected/Ready/...”.

Option B: keep _webui_state_label, but have update_webui_state(...) update both _webui_state_var and the panel so they always match (no raw "disconnected" string).

Ensure update_webui_state(state):

Accepts a WebUIConnectionState enum (or string) and:

Normalizes it to an enum where possible.

Calls self.webui_panel.set_webui_state(enum_state) for visuals.

Updates _webui_state_var to a human-friendly string like "Disconnected" / "Connecting..." / "Ready" / "Error" if the label is kept.

Use StatusBarV2 as the single UI update path

In _update_window_webui_manager(window, webui_manager) (src/main.py):

After window.webui_process_manager = webui_manager, and after you build connection_controller:

Replace any direct webui_panel.set_webui_state(state) calls with window.status_bar_v2.update_webui_state(state) (guarded by hasattr / getattr).

This ensures that whenever the connection controller decides the state, both the panel and any status label are updated together.

Avoid double-wiring Launch/Retry

Confirm current wiring:

StatusBarV2.__init__ sets:

webui_panel.set_launch_callback(self.controller.on_launch_webui_clicked) (if controller has it).

_update_window_webui_manager then calls webui_panel.set_launch_callback(launch_callback) (overwriting).

Decision for this PR (minimal change):

Leave the StatusBar’s initial wiring as a fallback when no connection controller is installed.

In _update_window_webui_manager, continue to override with the WebUIConnectionController-backed launch_callback / retry_callback, but:

Ensure those callbacks always call window.status_bar_v2.update_webui_state(new_state) after ensure_connected / check_health.

Ensure they log a clear message when invoked ("Launch WebUI button clicked" and "Retry WebUI button clicked"), so you can see them in your terminal logs.

Tighten the smoketest to match reality

In tests/app/test_webui_launch_opens_browser_v2.py:

After calling panel.launch_callback(), assert that:

window.status_bar_v2.webui_panel.state_history[-1] is WebUIConnectionState.READY.

If you keep _webui_state_label, assert its text var is "Ready" (or whatever friendly string you choose).

This ensures the test now mirrors the real wiring: controller → _update_window_webui_manager → StatusBarV2.update_webui_state(...) → APIStatusPanel.

Visual sanity

While touching StatusBarV2, make minor adjustments so the WebUI panel area reads clearly as a single block:

Something like: [WebUI: Ready] [Launch WebUI] [Retry] without the orphan disconnected text.

No theme changes beyond simple label removal/rename.

9. Required Tests (failing first)

Update/extend tests so they initially fail under the old wiring, then pass with the new behavior:

tests/app/test_webui_launch_opens_browser_v2.py

New assertions tied to StatusBarV2.update_webui_state and the panel’s state_history.

Optional/manual:

Run pytest tests/app/test_webui_launch_opens_browser_v2.py -q in CI.

Manual GUI check (see Smoke Test Checklist).

10. Acceptance Criteria

In the running GUI:

With WebUI not running:

Status bar clearly shows something like WebUI: Disconnected.

After clicking Launch WebUI:

webui-user.bat starts in the SD WebUI directory (as now).

Once API is healthy, status bar shows a single, consistent WebUI: Ready state (no stray disconnected text).

Browser tab opens to http://127.0.0.1:7860.

After closing WebUI and clicking Retry:

Status transitions through Connecting back to Ready (or Error if it truly can’t connect).

Terminal logs show:

Launch WebUI button clicked and Retry WebUI button clicked when you press the buttons.

At least one WebUI status update: state = ... log line when state moves from DISCONNECTED → READY.

11. Rollback Plan

Revert changes to:

src/main.py

src/gui/status_bar_v2.py

src/gui/api_status_panel.py (if touched)

tests/app/test_webui_launch_opens_browser_v2.py

Because this PR is UI + wiring only, rollback is low-risk: the worst case is returning to the current confusing-but-working status bar.

12. Codex Execution Constraints

Do not modify any files outside the Allowed Files list.

Keep diffs surgical; no refactors or renames.

Preserve the existing WebUI detection, process launch, and healthcheck logic; only adjust which functions call update_webui_state and how the labels are wired.

Respect existing public method signatures on StatusBarV2 and APIStatusPanel; only extend them in backwards-compatible ways.

13. Smoke Test Checklist (for you to run locally)

python -m src.main

Verify initial status bar:

Progress bar empty.

WebUI status clearly indicates “Disconnected” (in a single place).

Click Launch WebUI:

Confirm webui-user.bat window opens and SD WebUI starts.

Confirm browser opens http://127.0.0.1:7860.

Watch status bar: it should transition to “Connecting…” and then “WebUI: Ready” without any leftover “disconnected” text.

With WebUI still running, close StableNew and restart:

Status should quickly resolve to “WebUI: Ready” after healthcheck.

Optional: run a trivial txt2img job and confirm no WebUI connection errors are logged.