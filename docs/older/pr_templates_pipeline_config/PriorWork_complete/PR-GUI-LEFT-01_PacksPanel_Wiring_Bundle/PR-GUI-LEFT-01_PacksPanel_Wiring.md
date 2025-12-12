PR-GUI-LEFT-01: Packs/Presets Panel Wiring (LeftZone v2)
=======================================================

1. Title
--------
Port Packs/Presets loading to the v2 LeftZone and wire Load/Edit Pack actions through the controller (PR-GUI-LEFT-01).

2. Summary
----------
In the current v2 GUI:

- The LeftZone shows a Pack card with **Load Pack**, **Edit Pack** buttons, an empty list, and a **Preset** combobox.
- These controls are **stubbed only**:
  - Buttons log messages like `[controller] Load Pack clicked (stub).`
  - The list and preset dropdown are not populated from disk.

Meanwhile, the real Pack discovery and config logic still lives in the **legacy GUI / utility path** (e.g., older PromptPackPanel + file_io helpers).

This PR connects the dots for the v2 architecture:

- Introduce a small, non-GUI pack service that can:
  - Discover packs from the existing `packs/` directory.
  - Provide a simple list of pack descriptors (name, path, maybe description).
- Extend `AppController` with pack-related methods that:
  - Load pack metadata at startup and push it into the LeftZone panel.
  - Handle **Load Pack** / **Edit Pack** requests for the selected pack.
- Update the v2 LeftZone panel so that:
  - The pack list is populated from the service.
  - Clicking **Load Pack** / **Edit Pack** calls into `AppController` instead of stub log-only handlers.

Behavior remains simple and safe. Any advanced pack editing UI can be implemented in a later PR; for now, we focus on correctly wiring Pack discovery and basic selection/activation.

3. Problem Statement
--------------------
Right now, the v2 GUI LeftZone is halfway there:

- Visually, there is a Pack card with buttons and placeholders.
- Functionally, everything is stubbed:
  - No real pack discovery.
  - No real pack selection/activation.
  - No preset list tied to packs.

The **legacy GUI still owns the only real Pack logic**, which conflicts with Architecture_v2’s goals:

- GUI must be UI-only.
- Controller should own app-level behavior.
- Pack discovery should be in a separate, non-GUI module.

We need to move the **Pack behavior** onto the v2 path without pulling legacy GUI code forward.

4. Goals
--------
- Create or refine a **pack service module** that:
  - Loads pack metadata from the `packs/` directory (using existing helpers if available, e.g., in `src/utils/file_io.py`).
  - Returns a simple list of descriptors: `[{"name": ..., "path": ..., "preset_name": ...}, ...]` (exact shape can be small and pragmatic).
- Extend `AppController` to:
  - Load pack metadata on startup (or on first demand).
  - Hold the “selected pack” in controller state.
  - Expose controller methods for:
    - `on_load_pack_clicked()`
    - `on_edit_pack_clicked()`
    - `on_pack_selected(name_or_index)`
- Update the v2 LeftZone panel implementation to:
  - Display the list of packs.
  - Notify the controller when selection changes.
  - Invoke controller methods when Load/Edit Pack buttons are pressed.
- Add tests to protect pack service + controller behavior.

5. Non-goals
------------
- Do not build a full Pack editor UI.
- Do not change the pipeline behavior yet (pipeline can still ignore the active pack in this PR).
- Do not modify legacy GUI files.
- Do not change theme or non-LeftZone layout.
- Do not add new configuration persistence; we can keep pack selection in memory for now.

6. Allowed Files
----------------
This PR may modify or create only the following files:

- `src/utils/prompt_packs.py` (new or existing)  
  or, if that module already exists and has the right responsibilities, extend it there.
- `src/controller/app_controller.py` (add pack-related controller methods and state).
- `src/gui/main_window_v2.py` and/or `src/gui/left_zone.py` (if a LeftZone helper exists or is introduced) to wire GUI events to `AppController`.

If the repo already has a dedicated Pack-related module (e.g., `src/gui/prompt_pack_panel.py` or similar), you may **read** it for reference but should not expand its responsibilities in this PR. The focus is on the v2 path only.

7. Forbidden Files
------------------
Do **not** modify in this PR:

- Any modules under `src/pipeline/`
- Any modules under `src/api/`
- Legacy GUI files (e.g., `src/gui/main_window.py`, old panels)
- Theme module: `src/gui/theme.py`
- Entry point: `src/main.py`
- Test configuration / CI files

If something seems to require changes in any forbidden file, stop and request a new PR design instead of expanding this one.

8. Step-by-step Implementation Plan
-----------------------------------

### Step 1 – Introduce / extend Pack service (`prompt_packs.py`)
- If `src/utils/prompt_packs.py` does not exist, create it; if it does, extend it carefully.
- Implement functions like:

  - `discover_packs(packs_dir: Path | str) -> list[PackInfo]`
    - Uses existing file I/O helpers when possible (for example, call into `file_io` utilities instead of duplicating logic).
    - Returns a list of simple dataclass/NamedTuple/dict structures with minimally needed fields:
      - `name`: display name.
      - `path`: underlying file or folder.
      - Optional `preset_name` or `default_preset` field if available.

- Add a small, pure function to derive a display name from a pack’s filename/path if needed.

No GUI imports, no controller imports—this module must stay **pure logic / I/O**.

### Step 2 – Extend `AppController` with Pack state and methods
In `src/controller/app_controller.py`:

- Add controller state:

  - A list of pack descriptors (from the pack service).
  - A current pack selection (name or index).

- Add initialization logic:

  - On controller init, or on a dedicated `load_packs_if_needed()` method, call into the pack service to discover packs.
  - After discovery, send the pack list to the GUI LeftZone via a method on the window, e.g.:
    - `self.window.update_pack_list(display_names)`

- Add event handlers:

  - `on_pack_selected(index_or_name)`:
    - Update internal `selected_pack` state.
    - Optionally log the selection.

  - `on_load_pack_clicked()`:
    - If no `selected_pack`, log a warning and return.
    - For now, log or set “active pack” within controller state/config.
    - (Actual pipeline integration will come in a later PR.)

  - `on_edit_pack_clicked()`:
    - If no `selected_pack`, log a warning and return.
    - For now, either:
      - Log a stub message with the pack path, or
      - Optionally open the pack file with `os.startfile` on Windows (guarded + logged), depending on what’s already in the repo and what’s acceptable in your environment.

- Ensure these controller methods are used by the v2 GUI instead of the previous stub log-only code.

### Step 3 – Wire LeftZone GUI to controller
In `src/gui/main_window_v2.py` (or a LeftZone helper module if present/introduced):

- Ensure the Pack card has:
  - A list or listbox widget for packs.
  - Buttons for Load Pack / Edit Pack.
  - A Preset combobox (even if its data is still stubbed for now).

- For pack list:

  - Add a method on the GUI class, e.g. `update_pack_list(names: list[str])`, that:
    - Clears the listbox.
    - Inserts each pack name.

  - Bind a selection event (e.g., `<<ListboxSelect>>`) that calls a method on the window, which then calls the controller, e.g.:
    - `self.controller.on_pack_selected(selected_index)`

- For buttons:

  - Update Load Pack button’s command to call `self.controller.on_load_pack_clicked()`.
  - Update Edit Pack button’s command to call `self.controller.on_edit_pack_clicked()`.

- Remove or replace the previous stub-only commands that just logged messages.

### Step 4 – Tests (TDD as much as feasible)
Add tests to validate pack service and controller behavior. Suggested minimums:

- **Pack service test** (e.g., `tests/utils/test_prompt_packs.py`):
  - Use a temporary directory with a couple of fake pack files or folders.
  - Call `discover_packs(...)` and assert that:
    - It returns the expected number of packs.
    - Display names match expected values.

- **Controller test** (e.g., `tests/controller/test_app_controller_packs.py`):
  - Use a fake/frozen pack service (e.g., monkeypatch or stub) that returns a known list.
  - Use a fake GUI window object exposing `update_pack_list(...)` and no real Tk dependencies.
  - Test that:
    - Controller loads packs and calls `window.update_pack_list` with the right names.
    - `on_pack_selected` updates controller state.
    - `on_load_pack_clicked` and `on_edit_pack_clicked` behave as expected when a pack is selected vs not selected (e.g., logging a warning).

These tests should be deterministic and not depend on actual pack files in the working directory.

### Step 5 – Manual smoke test
After tests are green:

1. Run `python -m src.main`.
2. Confirm:
   - The LeftZone pack list populates with pack names from your real `packs/` directory.
   - Selecting an item updates controller state (you should see logs).
   - Clicking **Load Pack** / **Edit Pack** calls the new controller behavior instead of stub logs.
3. Verify that Run/Stop and other parts of the GUI still behave as before.

9. Required Tests
-----------------
- New tests for pack service and controller pack behavior, at minimum:
  - `tests/utils/test_prompt_packs.py`
  - `tests/controller/test_app_controller_packs.py`

- Existing tests must remain green, especially:
  - `tests/controller/test_app_controller_pipeline_flow_pr0.py`

10. Acceptance Criteria
-----------------------
This PR is complete when:

- Pack discovery is implemented in a non-GUI service module.
- AppController:
  - Loads pack metadata and updates the GUI list when the app starts (or on first demand).
  - Tracks the selected pack.
  - Handles Load/Edit Pack clicks appropriately.
- The v2 LeftZone:
  - Shows real pack names from the `packs/` directory.
  - Notifies the controller when a pack is selected.
  - Uses controller methods for Load/Edit Pack.
- New tests for pack service + controller pass.
- All existing tests remain green.
- No forbidden files were modified.

11. Rollback Plan
-----------------
- Revert changes to:
  - `src/utils/prompt_packs.py`
  - `src/controller/app_controller.py`
  - `src/gui/main_window_v2.py` / `src/gui/left_zone.py` (if created/modified)
  - Any new tests related to packs.
- Since no persistent state or schema changes are introduced, rollback is code-only.

12. Codex Execution Constraints
-------------------------------
For Codex (implementer):

- Do not modify any files outside the Allowed Files list.
- Do not change pipeline behavior; treat pack integration with the pipeline as a future PR.
- Do not move GUI logic into the pack service or controller; preserve layer boundaries:
  - Pack service = pure discovery / data.
  - Controller = orchestration and state.
  - GUI = presentation + event forwarding.
- Keep the diff small and focused on Packs/Presets in the LeftZone.
- After implementation, always run:
  - `pytest tests/controller/test_app_controller_pipeline_flow_pr0.py -v`
  - The new pack-related tests.
- Show full test output.
- If you believe other modules must be modified, stop and request a new PR design instead of expanding this one.

13. Smoke Test Checklist
------------------------
- [ ] Run `pytest tests/utils/test_prompt_packs.py -v`.
- [ ] Run `pytest tests/controller/test_app_controller_packs.py -v`.
- [ ] Run `pytest tests/controller/test_app_controller_pipeline_flow_pr0.py -v`.
- [ ] Launch `python -m src.main`:
      - LeftZone shows pack names from `packs/`.
      - Changing selection emits controller logs reflecting the selected pack.
      - Load/Edit Pack buttons trigger controller behavior without errors.
      - Run/Stop behavior remains unchanged.
