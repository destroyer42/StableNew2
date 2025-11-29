PR-GUI-LEFT-01: Packs & Presets Panel (v2 LeftZone Functional Port)
===================================================================

1. Title
--------
Implement the Packs & Presets panel in the v2 LeftZone using a dedicated pack service and controller wiring (PR-GUI-LEFT-01).

2. Summary
----------
The v2 GUI now has a themed header, status bar, and a structural LeftZone card with stubbed buttons:

- `Load Pack`
- `Edit Pack`
- Pack list placeholder
- `Preset` label + combobox

However, all pack/preset functionality is still either in:
- The **legacy GUI** (`StableNewGUI` + old PromptPackPanel), or
- Lower-level file utilities.

PR-GUI-LEFT-01 ports the **core Packs/Presets behavior** into the v2 architecture, without touching the pipeline:

- Introduce a **PackService** (or similar) in `src/utils/` responsible for discovering, loading, and listing prompt packs.
- Wire `AppController` to own an instance of this service.
- Implement a v2-friendly Packs & Presets panel in the LeftZone that:
  - Displays the list of available packs.
  - Allows selecting a pack.
  - Populates the Preset combobox for the selected pack.
  - Calls controller callbacks for Load/Edit actions (still allowed to be stubbed or minimal in this PR).

This PR should **not** change how the pipeline runs or how prompts are actually applied yet; it is the GUI + service layer for Packs/Presets only.

3. Problem Statement
--------------------
Currently:

- LeftZone shows `Load Pack`, `Edit Pack`, a blank list, and a `Preset` combobox, but:
  - The list is empty.
  - The Preset combobox does not reflect real pack content.
  - Button clicks only log stub messages.

- Pack discovery and loading logic lives in legacy code (e.g., old PromptPackPanel + helper functions), which:
  - Violates GUI-only rules (file I/O inside GUI).
  - Is tightly coupled to the old GUI layout.
  - Is not usable by the v2 architecture.

We need a v2-aligned implementation that:

- Centralizes pack discovery/loading in a non-GUI module.
- Exposes a clean interface the controller can call.
- Lets the v2 LeftZone panel show truthful pack/preset lists and selection state.

4. Goals
--------
- Create a **PackService** (or similar) in `src/utils/prompt_packs.py` that:
  - Knows how to scan the `packs/` directory for valid packs (using existing file_io helpers when possible).
  - Returns a structured list of packs and their presets (names/IDs, not UI widgets).
  - Can reload/rescan on demand.

- Extend `AppController` to:
  - Own a PackService instance.
  - Provide methods like:
    - `refresh_packs()` (internal)
    - `on_load_pack_clicked()`
    - `on_edit_pack_clicked()`
    - `on_pack_selected(name)`
    - `on_preset_selected(name)`
  - Update the GUI (LeftZone panel) via explicit methods like:
    - `view.set_packs(list_of_names)`
    - `view.set_presets(list_of_names)`
    - `view.set_active_pack(name)`
    - `view.set_active_preset(name)`

- Implement a v2 LeftZone panel (inside `MainWindow_v2` or a small helper class) that:
  - Shows the packs list.
  - Shows presets for the currently selected pack.
  - Invokes controller callbacks on selection and button clicks.
  - Is visually consistent with existing theme and LeftZone card.

- Cover the new behavior with tests at the **service/controller** layers (not Tk render tests).

5. Non-goals
------------
- No changes to pipeline stages or prompt application logic.
- No editing of pack contents on disk (beyond simple read operations). Edit behavior can remain a stub that just logs for now.
- No changes to randomizer/matrix logic.
- No breaking changes to the legacy GUI (it may still exist as a fallback; we just won’t use it from `src/main.py`).

6. Allowed Files
----------------
This PR may create or modify only:

- `src/utils/prompt_packs.py` (new – PackService and related helpers)
- `src/controller/app_controller.py` (add pack-related controller logic)
- `src/gui/main_window_v2.py` (wire the LeftZone UI to controller)
- Optionally, a new GUI helper module if needed, e.g.:
  - `src/gui/packs_panel_v2.py`

Tests:

- `tests/utils/test_prompt_packs_service.py` (new)
- `tests/controller/test_app_controller_packs_integration.py` (new)

7. Forbidden Files
------------------
Do **not** modify in this PR:

- Any files under `src/pipeline/`
- Any files under `src/api/`
- `src/gui/theme.py`
- Legacy GUI modules (e.g., `src/gui/main_window.py`, legacy PromptPackPanel)
- `src/main.py`
- Existing tests (only the new test files listed above may be created)

If changes to forbidden files seem necessary, stop and request a new PR design.

8. Step-by-step Implementation Plan
-----------------------------------

### Step 1 – Introduce PackService in `src/utils/prompt_packs.py`
- Create a module with:
  - A small dataclass or namedtuple for pack metadata, e.g. `PromptPackInfo(name: str, path: Path, presets: list[str])`.
  - A `PackService` class (or similar) that:
    - Is initialized with a base directory (e.g., `packs/` from config or default).
    - Provides methods:
      - `list_packs() -> list[PromptPackInfo]`
      - `get_pack(name: str) -> PromptPackInfo | None`
    - Uses existing file I/O helpers from `src.utils.file_io` where applicable (for locating and parsing packs). Avoid duplicating that logic.
- Keep PackService **pure and synchronous**; no Tk or threading.

### Step 2 – Extend AppController for packs
- In `src/controller/app_controller.py`:
  - Add a `self.pack_service` attribute, initialized with the appropriate packs directory.
  - On controller initialization, call a private method like `_refresh_packs_initial()` to:
    - Query `pack_service.list_packs()`.
    - Pass the pack names to the view via `view.set_packs([...])` (you will need to add or verify such a method on the view/LeftZone panel).
  - Implement public/GUI-facing methods, e.g.:
    - `on_load_pack_clicked()`
    - `on_edit_pack_clicked()`
    - `on_pack_selected(pack_name)`
    - `on_preset_selected(preset_name)`
  - For now, Load/Edit can log and/or set internal state; actual pack content application into pipeline config is out-of-scope for this PR.

### Step 3 – Implement LeftZone panel behavior in `MainWindow_v2`
- In `src/gui/main_window_v2.py` (or a new `packs_panel_v2.py` file imported into it):
  - Replace the stubbed pack list + Preset combobox with functioning widgets that:
    - Display the pack names provided by the controller (e.g., via `set_packs`).
    - Notify the controller when:
      - A pack is selected (e.g., listbox selection change → `controller.on_pack_selected(name)`).
      - A preset is selected (combobox selection change → `controller.on_preset_selected(name)`).
      - `Load Pack` / `Edit Pack` buttons are clicked (`controller.on_load_pack_clicked()` / `controller.on_edit_pack_clicked()`).
- Maintain strict GUI → controller communication:
  - GUI never touches PackService or file system directly.
  - GUI exposes simple methods for the controller to update visual state (list of pack names, list of preset names, selected indices, etc.).

### Step 4 – Write service tests
- In `tests/utils/test_prompt_packs_service.py`:
  - Use temporary directories and fake pack files to test PackService’s behavior.
  - Verify that:
    - Empty directory → empty packs list.
    - Multiple packs are discovered correctly (names, paths).
    - Presets are read and exposed as expected (within reason; may be superficial until full pack parsing is known).

### Step 5 – Write controller integration tests
- In `tests/controller/test_app_controller_packs_integration.py`:
  - Use a fake view object (no Tk) that records calls, e.g.:
    - `set_packs(...)`
    - `set_presets(...)`
  - Use a fake PackService that returns deterministic pack/preset data.
  - Verify that:
    - On initialization, controller calls PackService and updates the view with the correct pack list.
    - When `on_pack_selected` is called:
      - Controller queries PackService for that pack.
      - Controller calls `view.set_presets([...])` with the correct preset names.
    - When `on_load_pack_clicked` / `on_edit_pack_clicked` are called:
      - At minimum, appropriate log calls or state changes occur (even if full behavior is deferred).

### Step 6 – Manual GUI smoke test
After implementation and tests are green:

1. Run `python -m src.main` to launch v2 GUI.
2. Confirm that:
   - The LeftZone pack list is populated with actual pack names (from `packs/` dir).
   - Selecting a pack populates the Preset dropdown.
   - Clicking Load/Edit/Preview/Settings/Help logs relevant controller messages (even if some are still stubbed).
3. Confirm that pipeline Run behavior is unchanged (still uses stub runner and does not hang).

9. Required Tests
-----------------
New tests (to be added in this PR):

- `tests/utils/test_prompt_packs_service.py`
  - Covers pack discovery and basic preset listing behavior.

- `tests/controller/test_app_controller_packs_integration.py`
  - Covers how AppController integrates with PackService and updates a fake view.

Existing tests must continue to pass, especially:

- `tests/controller/test_app_controller_pipeline_flow_pr0.py`

10. Acceptance Criteria
-----------------------
PR-GUI-LEFT-01 is accepted when:

- PackService exists and can list packs from the `packs/` folder.
- AppController uses PackService to fetch pack/preset lists and updates the v2 view.
- LeftZone pack list and preset combobox show real data from disk.
- `Load Pack` / `Edit Pack` / pack selection / preset selection flows are wired to controller methods (even if some behaviors remain stubbed).
- New tests are present and passing, alongside all existing tests.
- No forbidden files are modified.

11. Rollback Plan
-----------------
To roll back:

- Remove `src/utils/prompt_packs.py`.
- Remove new pack-related logic from `src/controller/app_controller.py`.
- Restore `src/gui/main_window_v2.py` (and any new packs panel module) to previous version.
- Remove the new test files under `tests/utils/` and `tests/controller/`.

12. Codex Execution Constraints
-------------------------------
For Codex (implementer):

- Only touch the Allowed Files listed above.
- Follow TDD for the new behavior:
  - Write tests in `tests/utils/test_prompt_packs_service.py` and `tests/controller/test_app_controller_packs_integration.py` first.
  - Run them (expect failures), then implement minimal code to make them pass.
- Do not change pipeline, API, or theme modules.
- Do not refactor unrelated parts of `AppController` or `MainWindow_v2`.
- Keep the diff small and focused on Packs/Presets behavior.

13. Smoke Test Checklist
------------------------
- [ ] `pytest tests/utils/test_prompt_packs_service.py -v` passes.
- [ ] `pytest tests/controller/test_app_controller_packs_integration.py -v` passes.
- [ ] `pytest tests/controller/test_app_controller_pipeline_flow_pr0.py -v` passes.
- [ ] V2 GUI launches (`python -m src.main`).
- [ ] LeftZone shows pack names and presets from `packs/`.
- [ ] Pack selection updates Preset combobox.
- [ ] Load/Edit Pack buttons trigger controller methods without errors.
- [ ] Run button still executes stub pipeline twice without hanging.
