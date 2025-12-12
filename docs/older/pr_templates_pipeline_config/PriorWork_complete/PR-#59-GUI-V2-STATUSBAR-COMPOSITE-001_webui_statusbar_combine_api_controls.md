# PR-#59-GUI-V2-STATUSBAR-COMPOSITE-001: Combine StatusBarV2 + WebUI API controls into a single composite bar

**Created:** 2025-11-23T19:21:44 (local repo time)

---

## 1. Summary / What’s new

This PR finishes the WebUI GUI integration work by implementing **Option C** from our design discussion:

> Create a combined bar (StatusBarV2 + API/WebUI buttons) so the user has a single, consolidated status surface.

Concretely, this PR:

- Refactors the V2 status bar so that:
  - Existing StatusBarV2 fields (general status text, maybe job/queue hints, etc.) remain intact.
  - WebUI connection state and buttons (**Launch WebUI**, **Retry Connection**) live in the **same horizontal bar**, sharing layout.
- Ensures the **composite status bar** is the one actually used in V2 layouts and visible in the running GUI.
- Wires the composite bar to `WebUIConnectionController` so that:
  - It reflects connection state (`Disconnected`, `Connecting`, `Ready`, `Error`).
  - Buttons invoke `ensure_connected(autostart=True/False)` as appropriate.
- Aligns run/queue control enabling with the same readiness signal that drives the status bar display, so the UI and controller are consistent.
- Updates tests to verify the composite bar behavior and its callbacks.
- Adds a short PR-59 entry to the rolling summary.

This PR assumes PR-56/57/58 are in place:
- WebUIConfig + detection live in `app_config` and `webui_process_manager`.
- `WebUIConnectionController` exists and is used by `main.py` entrypoint per PR-58.
- A V2 API/WebUI status panel class and tests already exist (e.g., `APIStatusPanelV2` and `tests/gui_v2/test_api_status_panel_webui_states_v2.py`).

---

## 2. Problem statement

After PR-56/57/58:

- The **WebUI connection logic** is implemented and tested via:
  - `WebUIConnectionController` (controller, health, autostart)
  - `webui_process_manager` (process config + launch)
  - Controller gating tests & API status panel tests
- But the **actual GUI layout** still doesn’t present these controls as a single coherent surface:
  - `StatusBarV2` is still the main status bar for the app.
  - The API/WebUI panel with Launch/Retry exists and is tested, but may not be integrated into the active layout, or may be rendered separately where users don’t see/use it.
- From the user’s perspective:
  - There is one obvious status bar (StatusBarV2), but no clear WebUI buttons in that area.
  - WebUI status and actions feel “disconnected” from the rest of the GUI footer.

We want to converge on a **single V2 composite status bar** that:

- Retains existing StatusBarV2 UX.
- Adds WebUI connection state + controls in the same row.
- Is clearly visible and always present in the main V2 window.

---

## 3. Goals

1. **Composite status bar:**  
   Merge the existing StatusBarV2 content and the WebUI/API status controls into one horizontal bar.

2. **Single source of truth for status:**  
   Ensure the composite bar is the one used in `AppLayoutV2` / main window for V2 GUI.

3. **WebUI controls on the bar:**  
   - Show WebUI connection state (Disconnected, Connecting, Ready, Error).  
   - Provide Launch/Retry buttons that call into `WebUIConnectionController`.

4. **Consistent gating signals:**  
   - The same WebUI readiness state that gates pipeline runs must drive:
     - Run/Queue button enablement.
     - WebUI state display on the composite bar.

5. **Minimal, surgical changes:**  
   - Do not redesign the overall GUI.
   - Do not touch pipeline/queue/learning/assembler behavior.
   - Keep scope limited to layout and wiring.

---

## 4. Non-goals

- No changes to WebUI connection semantics (timeouts, retries, detection) beyond what PR-57/58 already specify.
- No changes to queue/job panels or job history panels.
- No changes to prompt/core config/negative prompt panels.
- No major styling overhaul; only layout adjustments necessary to house both StatusBarV2 fields and WebUI controls.

---

## 5. Context & references

- PR-56: Initial WebUI gating controller + basic status panel V2 tests.
- PR-57: Config + detection-based WebUI autostart, Launch/Retry in API status panel, gating tests.
- PR-58: Aligned `main.py` startup with `WebUIConnectionController` and ensured V2 status panel is the intended surface.

Key files (names may vary slightly in your tree):

- `src/gui/status_bar_v2.py` (or similar: StatusBarV2 implementation)
- `src/gui/api_status_panel.py` / `src/gui/api_status_panel_v2.py`
- `src/gui/app_layout_v2.py`
- `src/gui/main_window.py`
- `src/controller/webui_connection_controller.py`
- `src/controller/pipeline_controller.py` (for readiness gating and run/queue enablement)

---

## 6. Allowed files

You may modify:

- GUI layout and panels:
  - `src/gui/status_bar_v2.py` (or the actual module/class implementing StatusBarV2)
  - `src/gui/api_status_panel.py` / `src/gui/api_status_panel_v2.py`
  - `src/gui/app_layout_v2.py`
  - `src/gui/main_window.py`
- Controller (only for exposing clean readiness signals):
  - `src/controller/webui_connection_controller.py` (if you need a clearer state callback / enum type)
  - `src/controller/pipeline_controller.py` (only for read-only WebUI readiness + run/queue gating surface)
- Tests:
  - `tests/gui_v2/test_api_status_panel_webui_states_v2.py`
  - `tests/gui_v2/test_status_bar_v2_composite.py` (new)
  - `tests/gui_v2/test_main_window_webui_integration.py` (update as needed)
- Docs:
  - `docs/codex_context/ROLLING_SUMMARY.md`

If specific filenames differ in your repo, adapt accordingly but keep scope equivalently narrow.

---

## 7. Forbidden files

Do **not** modify:

- `src/pipeline/*`
- `src/learning/*`
- `src/queue/*`, `src/controller/cluster_controller.py`
- `src/utils/structured_logger.py` or other logging primitives
- `docs/codex_context/ARCHITECTURE_v2_COMBINED.md`
- `docs/codex_context/PIPELINE_RULES.md`

This PR focuses solely on GUI composite status bar wiring and WebUI control exposure, not core engine behavior.

---

## 8. Step-by-step implementation

### 8.1 Introduce a composite status bar API

1. In `src/gui/api_status_panel.py` (or the actual WebUI API status panel module):

   - Extract/confirm a clear **WebUI state widget** interface, e.g. a small frame or group of widgets that show:
     - A label bound to connection state (e.g., “WebUI: Ready / Connecting / Disconnected / Error”).
     - Two buttons: Launch / Retry.

   - Ensure this widget exposes methods or attributes such as:
     - `set_webui_state(state_enum)`
     - `set_launch_callback(callback: Callable[[], None])`
     - `set_retry_callback(callback: Callable[[], None])`

2. In `src/gui/status_bar_v2.py` (or the current StatusBarV2 implementation):

   - Create a **composite layout** that embeds both:
     - The original StatusBarV2 status label(s).
     - The WebUI state widget from step 1.
   - Layout guideline for Option C:
     - Left side: existing StatusBarV2 text (e.g., general app status, job hints).  
     - Right side: WebUI section: `[WebUI: <STATE>] [Launch] [Retry]`.

   - If necessary, add a small container frame inside StatusBarV2 for the WebUI controls, but keep it all within the same bar.

3. Expose high-level methods on StatusBarV2 (or on the composite class) such as:

   - `set_webui_state(state_enum)`
   - `set_webui_launch_callback(cb)`
   - `set_webui_retry_callback(cb)`

   These should delegate to the embedded WebUI widget.

### 8.2 Wire composite bar into AppLayoutV2

4. In `src/gui/app_layout_v2.py`:

   - Ensure that the footer/status area used in the V2 layout is the **composite bar**:

     - Replace any separate instantiation of a pure API status panel at the bottom with the composite StatusBarV2 that now includes WebUI controls.

   - Make sure the `owner` (MainWindow or the layout host) gets a handle on the composite bar, e.g.:

     - `owner.status_bar_v2 = StatusBarV2(...)`

   - Provide a way for `MainWindow` to call:

     - `status_bar_v2.set_webui_state(state_enum)`
     - `status_bar_v2.set_webui_launch_callback(cb)`
     - `status_bar_v2.set_webui_retry_callback(cb)`

### 8.3 Connect composite bar to WebUIConnectionController in MainWindow

5. In `src/gui/main_window.py`:

   - After constructing the controller stack and layout:

     - Retrieve `webui_connection_controller` (already used in PR-58 for autostart).

     - Register callbacks so that when WebUI connection state changes, the controller informs the GUI. If this already exists, just reuse it; if not, add a simple observer pattern or polling hook that:

       - On state change, calls `status_bar_v2.set_webui_state(...)` with the appropriate enum.

   - Wire button callbacks:

     - Launch:

       - `status_bar_v2.set_webui_launch_callback(lambda: webui_connection_controller.ensure_connected(autostart=True))`

     - Retry:

       - `status_bar_v2.set_webui_retry_callback(lambda: webui_connection_controller.ensure_connected(autostart=False))`

6. Ensure that the **Run/Queue** button enabling still aligns with WebUI readiness:

   - If PR-56/57/58 already expose a `is_webui_ready()` or similar on the controller, continue to use it.
   - Make sure run/queue buttons are disabled when WebUI is not `Ready`, and that this is in sync with the state shown on the composite bar.

### 8.4 Tests

7. Update `tests/gui_v2/test_api_status_panel_webui_states_v2.py`:

   - Ensure tests still validate state → label mapping for WebUI status widget.
   - Add assertions (if not present) that Launch/Retry call the wired callbacks.

8. Add a new test file, e.g. `tests/gui_v2/test_status_bar_v2_composite.py`:

   - Create a `StatusBarV2` instance in a test Tk root (withdrawn).
   - Inject test callbacks for Launch/Retry:
     - Simulate button clicks; assert that callbacks were invoked.
   - Call `set_webui_state(...)` and assert that the right label text or style is updated.
   - Ensure that the original StatusBarV2 label remains present and can be updated without breaking the WebUI region.

9. Update `tests/gui_v2/test_main_window_webui_integration.py` (if present from PR-58) to assert:

   - On startup with autostart disabled:
     - The composite bar exists and shows a “Disconnected” or equivalent state.
     - Launch/Retry callbacks are wired (e.g., clicking them results in `ensure_connected` calls on the mocked controller).
   - On state change to `Ready`:
     - The composite bar reflects the new state.
     - Run/Queue controls become enabled.

### 8.5 Rolling summary

10. Update `docs/codex_context/ROLLING_SUMMARY.md`:

    - Add a PR-59 entry with 2–4 bullets describing:
      - Composite StatusBarV2 + WebUI controls.
      - Visible Launch/Retry on the main status bar.
      - Continued gating of pipeline runs on WebUI readiness.

---

## 9. Behavioral changes

After this PR, the user experience should be:

- The **bottom status bar** in V2 GUI displays both:
  - General app status (existing StatusBarV2 behavior), and
  - WebUI status + controls in the same horizontal bar.

- WebUI portion shows:
  - Current connection state (Disconnected, Connecting, Ready, Error).
  - Two buttons: **Launch WebUI** and **Retry Connection**.

- Clicking **Launch WebUI**:
  - Calls `WebUIConnectionController.ensure_connected(autostart=True)`.
  - Uses detection + config (from PR-57) to start WebUI if not already running.

- Clicking **Retry Connection**:
  - Calls `ensure_connected(autostart=False)` to re-probe an existing WebUI instance.

- Run/Queue buttons are active only when WebUI is `Ready`. If it’s not ready:
  - The status bar makes it obvious why (state text).
  - The run controls are disabled or clearly blocked.

---

## 10. Tests to run

At minimum:

- `pytest tests/gui_v2/test_api_status_panel_webui_states_v2.py -v`
- `pytest tests/gui_v2/test_status_bar_v2_composite.py -v` (new)
- `pytest tests/gui_v2/test_main_window_webui_integration.py -v` (if present)
- `pytest tests/gui_v2 -v`
- `pytest tests/controller/test_webui_connection_controller.py -v`
- `pytest tests/controller/test_pipeline_controller_webui_gating.py -v`
- `pytest -v`

Paste the full output into the PR notes.

---

## 11. Acceptance criteria

This PR is complete when:

1. The V2 GUI’s visible bottom bar is a **single composite status bar** that includes WebUI state and Launch/Retry buttons.

2. WebUI state is clearly shown and updated as the connection progresses (Disconnected → Connecting → Ready / Error).

3. Launch/Retry buttons on the bar reliably call into `WebUIConnectionController.ensure_connected` with the correct flags.

4. Run/Queue controls in the GUI are disabled when WebUI is not `Ready` and enabled once it becomes `Ready`.

5. All tests listed in §10 pass (aside from any existing Tk-related skips).

6. `ROLLING_SUMMARY.md` has an entry for PR-59 describing the composite bar and visible WebUI controls.

---

## 12. Rollback plan

If this PR causes regressions:

1. Revert changes to:
   - `src/gui/status_bar_v2.py`
   - `src/gui/api_status_panel.py` / `src/gui/api_status_panel_v2.py`
   - `src/gui/app_layout_v2.py`
   - `src/gui/main_window.py`
   - Any tests added or modified
   - `docs/codex_context/ROLLING_SUMMARY.md` (remove the PR-59 entry)

2. Re-run:
   - `pytest tests/gui_v2 -v`
   - `pytest tests/controller -v`
   - `pytest -v`

3. Confirm that behavior returns to the PR-58 baseline (status bar without integrated WebUI controls, but no crashes or gating regressions).

---

## 13. Codex execution prompt (for GPT-4.1)

> Implement PR-#59-GUI-V2-STATUSBAR-COMPOSITE-001 as described in the spec.  
> Focus on:
> - Building a composite StatusBarV2 that embeds WebUI state + Launch/Retry buttons.
> - Ensuring AppLayoutV2 and MainWindow use this composite bar and wire it to WebUIConnectionController.
> - Keeping run/queue controls aligned with WebUI readiness.  
> Only modify files listed under “Allowed files”. After implementation, run the tests listed in §10 and paste the full output and a short diff summary.
