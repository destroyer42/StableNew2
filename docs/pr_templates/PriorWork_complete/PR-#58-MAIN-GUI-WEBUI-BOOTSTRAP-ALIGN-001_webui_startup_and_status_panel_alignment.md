# PR-#58-MAIN-GUI-WEBUI-BOOTSTRAP-ALIGN-001: Align main.py startup with WebUIConnectionController + V2 status panel

**Created:** 2025-11-23T19:02:32 (local repo time)

---

## 1. Summary / What’s new

This PR fixes the remaining disconnect between:

- `main.py`’s legacy, env-var–driven WebUI bootstrap log/behavior, and  
- The new PR-56/57 WebUIConnectionController + V2 API/WebUI status panel + pipeline gating.

Concretely, it:

- Removes or updates the **“WebUI autostart is disabled; GUI will launch without waiting.”** log to reflect the new config/detection model.
- Ensures **main startup actually triggers WebUI connection / autostart** via `WebUIConnectionController` when configured, instead of silently doing nothing.
- Guarantees the **V2 API/WebUI status panel** (with Launch/Retry buttons) is what the GUI uses, so the user can see and use the controls implemented in PR-57.
- Ensures pipeline run controls (Run/Queue) are enabled/disabled based on *actual* WebUI readiness, not just controller-internal state.
- Keeps GUI startup non-blocking: the window appears immediately; WebUI probing/autostart happens in the background, with state reflected in the status panel.

This PR is deliberately small and surgical: it does **not** change the WebUIConnectionController semantics or the assembler/queue pipelines; it only ensures the entrypoint and layout are aligned with the already-implemented behaviors.

---

## 2. Problem statement

Post PR-57, Codex’s implementation is test-green but two UX problems remain:

1. **Startup log + behavior are still governed by main.py’s legacy env-var check**  
   - On launch you still see:  
     `WebUI autostart is disabled; GUI will launch without waiting.`  
   - This message is produced in `main.py`, which was **not** edited in PR-57.  
   - It still checks `STABLENEW_WEBUI_AUTOSTART` directly instead of using `app_config.get_webui_autostart_enabled()` / detection-based defaults.
   - As a result, even though WebUIConnectionController has detection + autostart logic, **nothing triggers it on startup**, so autostart appears “broken.”

2. **V2 API/WebUI status panel + buttons don’t show up in the live GUI**  
   - PR-57 added Launch/Retry buttons and state wiring to the V2 API/WebUI status panel and its tests, but:
     - The actual `AppLayoutV2`/`main_window` may still be instantiating an older panel.
     - Or the V2 panel is being constructed without the WebUI state/handlers from the controller.
   - From the user’s perspective:
     - No Launch/Retry buttons are visible.
     - There is no obvious WebUI status surface, even though tests say it exists.

Net effect: the architecture is correct on paper and in tests, but the **entrypoint + layout are still wired to the old world**, so the new functionality is effectively hidden.

We want to make the live app behave like the tested design:

- Startup uses the same WebUI config & detection APIs as the controller/tests.
- GUI uses the same V2 status panel that has Launch/Retry.
- Pipeline run controls reflect WebUI readiness the same way tests expect.

---

## 3. Goals

1. **Align `main.py` startup with PR-56/57 behavior**  
   - Use `app_config` + `WebUIConnectionController` for any autostart decisions.  
   - Remove hard-coded `STABLENEW_WEBUI_AUTOSTART` checks from `main.py`.

2. **Ensure the V2 API/WebUI status panel is actually used in the visible GUI**  
   - `AppLayoutV2` and `main_window` must instantiate the V2 panel that PR-57 updated and wire it to the WebUI connection controller.

3. **Trigger WebUI connection/autostart in a user-friendly way**  
   - On startup:
     - GUI appears immediately.
     - If autostart is enabled in app_config, `WebUIConnectionController.ensure_connected(autostart=True)` is invoked in a non-blocking way (thread or deferred call).  
   - If autostart is disabled, the status panel should clearly show “Disconnected” and present Launch/Retry buttons that call into the controller.

4. **Keep pipeline run gating intact and visible**  
   - Run button(s) should be disabled or guarded when WebUI is not `READY`.  
   - When runs are blocked due to WebUI not ready, the GUI should reflect that state (e.g., via disabled run button + tooltip, or a message surface already present in the V2 controls).

5. **No regressions to queue, learning, or assembler paths**  
   - The PR must not alter pipeline/queue behavior, only when and how runs are allowed to start.

---

## 4. Non-goals

- No redesign of the entire startup/CLI semantics. `python -m src.main` remains the entrypoint.
- No modifications to the underlying SD WebUI HTTP client.
- No new persistence mechanisms beyond what app_config already uses.
- No changes to randomizer/learning/queue infrastructure beyond what is necessary for UI gating signals.
- No introduction of OS-specific hacks beyond existing `os.name` checks already in the repo.

---

## 5. Allowed files

You may modify:

- `src/main.py`
- `src/gui/app_layout_v2.py`
- `src/gui/main_window.py`
- `src/gui/api_status_panel_v2.py` (or the actual V2 status panel used in tests)
- `src/controller/webui_connection_controller.py` (only if a small adjustment is needed for callbacks)
- `src/controller/pipeline_controller.py` (only for exposing clear WebUI readiness to the GUI, not pipeline logic itself)

Tests:

- `tests/gui_v2/test_api_status_panel_webui_states_v2.py`
- `tests/gui_v2/test_main_window_webui_integration.py` (if exists; otherwise create a small new test file)
- `tests/controller/test_pipeline_controller_webui_gating.py` (update only if assertions need to be aligned with new GUI enablement behavior)

Docs:

- `docs/codex_context/ROLLING_SUMMARY.md` (append PR-58 entry only)

If some of these paths differ slightly in your tree, adapt accordingly but keep the scope equivalently narrow.

---

## 6. Forbidden files

Do **not** modify:

- `src/pipeline/*`
- `src/learning/*`
- `src/queue/*` and `src/controller/cluster_controller.py`
- `src/utils/structured_logger.py` and other logging primitives
- `docs/codex_context/ARCHITECTURE_v2_COMBINED.md` (beyond what PR-57 already changed)
- `docs/codex_context/PIPELINE_RULES.md`

We are aligning startup + GUI wiring only, not redefining architecture or pipeline rules.

---

## 7. Step-by-step implementation

### 7.1 main.py: replace legacy env-based autostart with controller-driven flow

1. Locate the startup section in `src/main.py` that currently:

   - Imports `wait_for_webui_ready` / WebUI-related pieces.
   - Logs: `WebUI autostart is disabled; GUI will launch without waiting.`
   - Makes decisions based directly on `os.getenv("STABLENEW_WEBUI_AUTOSTART", ...)`.

2. Refactor to:

   - Use `app_config.get_webui_autostart_enabled()` (from PR-57) as the **single source of truth** for whether autostart is desired.
   - Remove direct references to `STABLENEW_WEBUI_AUTOSTART` from `main.py`. Environment vars remain supported via app_config functions, not via the entrypoint.

3. After constructing the controller stack (including `WebUIConnectionController`) and before entering the Tk mainloop:

   - If `app_config.get_webui_autostart_enabled()` is `True`, schedule a **non-blocking** call to `webui_connection_controller.ensure_connected(autostart=True)`:

     - On Tkinter, this can be done via `root.after(0, ...)` with a lightweight callback that calls into the controller on a background thread if needed.
     - The GUI must not freeze until WebUI is ready; rely on the controller and healthcheck timeouts already in place.

4. Keep logging, but make it truthful and config-centric, e.g.:

   - When autostart enabled: `WebUI autostart enabled; attempting connection in background.`
   - When autostart disabled: `WebUI autostart disabled; use the GUI WebUI controls to connect.`

5. Do **not** alter the creation order of GUI vs controllers beyond what is necessary to obtain a reference to `WebUIConnectionController` at startup.

### 7.2 Ensure V2 API/WebUI status panel is used and wired

6. In `src/gui/app_layout_v2.py`:

   - Confirm that the API/WebUI status panel being instantiated is the **same class** updated in PR-57 and tested in `tests/gui_v2/test_api_status_panel_webui_states_v2.py`.

   - If there are multiple status panel variants (e.g., v1 and v2), ensure only the V2 variant is used in the V2 layout.

7. Ensure that `AppLayoutV2` exposes the necessary hooks for WebUI state + actions, for example:

   - `set_webui_state(connection_state: WebUIConnectionState)`
   - `on_launch_webui` / `on_retry_webui` callbacks, wired to the panel’s Launch/Retry buttons.

8. In `src/gui/main_window.py`:

   - Make sure the `MainWindow`:

     - Receives a `WebUIConnectionController` instance (or a thin facade) from the controller layer.
     - Subscribes to WebUI connection state updates (using whatever callback or polling pattern PR-57 established).
     - Passes state + callbacks into `AppLayoutV2` / the status panel instance.

   - Specifically, ensure the Launch/Retry buttons call:

     - `webui_connection_controller.ensure_connected(autostart=True)` for Launch.
     - `webui_connection_controller.ensure_connected(autostart=False)` for Retry-only behavior.

9. Verify that when WebUI state changes to `READY`, the run controls are enabled in the GUI; when it is not `READY`, run controls are disabled or otherwise blocked.

### 7.3 GUI enablement and controller gating alignment

10. Confirm that `PipelineController` still gates pipeline runs on WebUI readiness (per PR-56/57). If needed:

    - Provide a simple read-only property or method like `is_webui_ready()` that MainWindow can call to decide whether to enable the Run button.

11. In `MainWindow` (or the relevant GUI controller facade), use that read-only indicator to:

    - Disable/enable run controls appropriately.
    - Avoid a state where the button appears clickable but controller immediately rejects the run without feedback.

### 7.4 Tests

12. Update or add tests to validate the new wiring:

    - `tests/gui_v2/test_api_status_panel_webui_states_v2.py`:

      - Confirm that Launch/Retry callbacks are used as expected for different states.
      - If PR-57 already covers this fully, only adjust assertions if needed to reflect new labels/logs.

    - Add a small integration-style GUI V2 test, e.g. `tests/gui_v2/test_main_window_webui_integration.py`:

      - Create a `MainWindow` with a mocked `WebUIConnectionController` that tracks calls.
      - Simulate:
        - Startup autostart enabled path → assert `ensure_connected(autostart=True)` is called.
        - Clicking Launch/Retry → assert respective `ensure_connected` calls happen with correct flags.
        - State change to READY → assert run controls become enabled.

    - `tests/controller/test_pipeline_controller_webui_gating.py`:

      - Adjust expectations if needed to reflect how GUI enables/disables run controls, but do not weaken gating behavior.

13. Do **not** introduce real Tk windows popping up in tests; use the existing testing patterns (dummy root, withdraw, etc.).

### 7.5 Rolling summary

14. Append a short PR-58 section to `docs/codex_context/ROLLING_SUMMARY.md` summarizing:

    - Alignment of main.py startup with WebUIConnectionController.
    - Use of V2 API/WebUI status panel in the main layout.
    - Confirmation that pipeline runs remain gated on WebUI readiness, with visible GUI affordances (Launch/Retry buttons, run button enablement).

---

## 8. Behavioral changes

After this PR, from the user’s perspective:

- Running `python -m src.main`:

  - Always opens the StableNew GUI.
  - Shows a WebUI status surface (likely in the bottom status area) that reports `Disconnected`, `Connecting`, `Ready`, or `Error`.
  - If autostart is enabled in config:
    - A background connection attempt is made automatically.
    - Status will switch from `Disconnected` → `Connecting` → `Ready` (or `Error` if it fails).
  - If autostart is disabled:
    - The status panel clearly indicates that WebUI is not connected and offers Launch/Retry buttons.

- The WebUI status panel now clearly exposes:

  - **Launch WebUI**: starts `webui-user.bat` (or configured command) in the detected/configured working directory.
  - **Retry Connection**: re-probes WebUI without starting a new process (useful when WebUI is started manually).

- The Run/Queue buttons are only active when WebUI is `Ready`. If they are disabled, it’s obvious from both:

  - The disabled state of the controls.
  - The status panel messaging.

This matches the architecture and tests for PR-56/57 and makes the behavior discoverable and reliable.

---

## 9. Tests to run

At minimum:

- `pytest tests/controller/test_pipeline_controller_webui_gating.py -v`
- `pytest tests/gui_v2/test_api_status_panel_webui_states_v2.py -v`
- `pytest tests/gui_v2/test_main_window_webui_integration.py -v` (new)
- `pytest tests/controller -v`
- `pytest tests/gui_v2 -v`
- `pytest -v`

Paste the full output into the PR notes.

---

## 10. Acceptance criteria

This PR is complete when:

1. All tests listed above pass (modulo existing Tk skips).  
2. The legacy env-var-only autostart log/behavior is removed from `main.py` and replaced with config/controller-driven logic.  
3. On a real Windows system with WebUI at a path like `C:\Users\<user>\stable-diffusion-webui`:
   - `python -m src.main` opens the GUI.
   - WebUI status panel is visible and functional.
   - If autostart is enabled, WebUI is started and status becomes `Ready` within the configured timeout.
   - Launch/Retry buttons work as expected when autostart is disabled or WebUI is started manually.
4. Pipeline runs remain gated on WebUI readiness, with the GUI reflecting that gating state (no “mystery” rejections).

---

## 11. Rollback plan

If this PR causes any regressions:

1. Revert changes to:

   - `src/main.py`
   - `src/gui/app_layout_v2.py`
   - `src/gui/main_window.py`
   - `src/gui/api_status_panel_v2.py`
   - Any tests created/modified for this PR
   - `docs/codex_context/ROLLING_SUMMARY.md` (remove the PR-58 entry)

2. Re-run:

   - `pytest tests/controller -v`
   - `pytest tests/gui_v2 -v`
   - `pytest -v`

3. Confirm that behavior returns to the PR-57 baseline (controller + status panel logic exists and tests are green, but startup + layout may still exhibit the prior UX issues).

---

## 12. Codex execution prompt (for GPT-4.1)

> Implement PR-#58-MAIN-GUI-WEBUI-BOOTSTRAP-ALIGN-001 as described in the spec.  
> 
> Focus on:
> - Aligning main.py startup autostart messaging/behavior with app_config + WebUIConnectionController.
> - Ensuring the V2 API/WebUI status panel (with Launch/Retry) is actually used in AppLayoutV2/main_window and wired to the controller.
> - Making run controls reflect WebUI readiness.  
> 
> Only modify the files listed under “Allowed files”. Keep diffs focused and preserve existing pipeline/queue/learning behavior.  
> 
> After implementation, run the tests listed in §9 and paste the full output and a brief diff summary.
