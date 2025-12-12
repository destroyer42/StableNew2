Codex Execution Guide for PR-GUI-LEFT-01: Packs/Presets Panel Wiring
====================================================================

Purpose
-------
You are implementing PR-GUI-LEFT-01, which connects the v2 LeftZone Pack card to real pack discovery logic and controller behavior. The goal is:

- Discover packs from the existing `packs/` directory via a non-GUI service.
- Have `AppController` load and manage pack metadata + selection.
- Wire the v2 LeftZone widgets (list, Load Pack, Edit Pack) to these controller methods.

Scope
-----
You may only modify or create:

- `src/utils/prompt_packs.py`
- `src/controller/app_controller.py`
- `src/gui/main_window_v2.py` and/or `src/gui/left_zone.py` (if a small helper is used)

You must **not** modify pipeline, API, theme, entrypoint, legacy GUI, or test configuration files.

Implementation Steps
--------------------

1. Read `PR-GUI-LEFT-01_PacksPanel_Wiring.md` fully and summarize your plan before editing any code.

2. Pack service (`src/utils/prompt_packs.py`):
   - If the file exists, open it and reuse existing functions where appropriate.
   - If it does not exist, create it.
   - Implement a function like `discover_packs(packs_dir: Path | str)` that:
     - Looks at the `packs/` directory (path can be parameterized; the controller can supply the actual path).
     - Uses existing helper functions from other utils (e.g., `file_io`) if available; do not duplicate logic unnecessarily.
     - Returns a simple list of structures (dicts, dataclasses, or NamedTuples) with at least fields for `name` and `path`.
   - Keep this module free of any Tk or controller imports.

3. Controller (`src/controller/app_controller.py`):
   - Add attributes for:
     - `self.packs` (list of pack descriptors).
     - `self.selected_pack` (or index).
   - Add a method to load packs from the service, e.g. `load_packs()`:
     - Determine the packs directory (e.g., a `packs` folder relative to the repo root or config; use existing configuration if available).
     - Call `discover_packs(...)`.
     - Store results in `self.packs`.
     - Call a method on the GUI window to update the pack list, e.g.:
       - `self.window.update_pack_list([p.name for p in self.packs])`
   - Add event methods:
     - `on_pack_selected(index_or_name)`:
       - Update `self.selected_pack` to reference the chosen pack.
       - Optionally log the selection.
     - `on_load_pack_clicked()`:
       - If no pack selected, log a warning and return.
       - For now, just log that the selected pack is being “loaded” and mark it as active in controller state; do not integrate with pipeline yet.
     - `on_edit_pack_clicked()`:
       - If no pack selected, log a warning and return.
       - For now, either log a stub with the pack path or, if acceptable and easy, open the pack file in the default editor (OS-specific) guarded by try/except and logs.

4. GUI wiring (`src/gui/main_window_v2.py` / LeftZone helper):
   - Ensure the LeftZone Pack card has a Listbox (or similar) for packs and buttons for Load/Edit.
   - Implement a method on the window like `update_pack_list(list[str])` that:
     - Clears the listbox.
     - Inserts the new pack names.
   - Bind the list selection event to notify the controller:
     - On `<<ListboxSelect>>`, compute the selected index and call `self.controller.on_pack_selected(index)`.
   - Set Load/Edit Pack button commands to call the controller methods:
     - `command=self.controller.on_load_pack_clicked`
     - `command=self.controller.on_edit_pack_clicked`
   - Remove or replace previous stub commands that only logged controller messages without using pack state.

5. Tests:
   - Add `tests/utils/test_prompt_packs.py`:
     - Use a temporary directory (e.g., `tmp_path` fixture) with fake pack files or folders.
     - Call `discover_packs(tmp_path)` and assert that you get the expected pack names and paths.
   - Add `tests/controller/test_app_controller_packs.py`:
     - Use a fake window object with an `update_pack_list` method to avoid real Tk usage.
     - Stub or monkeypatch `discover_packs` to return a fixed list.
     - Assert that:
       - `load_packs()` calls the service and updates the window with the expected names.
       - `on_pack_selected(...)` updates the controller’s selected pack.
       - `on_load_pack_clicked()` / `on_edit_pack_clicked()` behave correctly when a pack is selected vs not selected (e.g., logging, no crash).

6. Run tests:
   - Run pack-related tests:
     - `pytest tests/utils/test_prompt_packs.py -v`
     - `pytest tests/controller/test_app_controller_packs.py -v`
   - Run existing controller tests to ensure no regressions:
     - `pytest tests/controller/test_app_controller_pipeline_flow_pr0.py -v`
   - Show full output.

7. Manual smoke test (human):
   - After reporting green tests, instruct the human to:
     - Run `python -m src.main`.
     - Confirm that:
       - The LeftZone pack list is populated with real pack names from the `packs` directory.
       - Selecting a pack and clicking Load/Edit Pack logs non-stub behavior referencing the selected pack.
       - Run/Stop and other parts of the GUI still behave exactly as before.

What You Must NOT Do
--------------------
- Do not modify any files outside the allowed list.
- Do not integrate packs with the actual pipeline in this PR.
- Do not add GUI logic into the service module.
- Do not change existing theme, entrypoint, or legacy GUI behavior.
- Do not rename or remove existing controller methods unrelated to packs.

Completion Checklist
--------------------
You are done when:

- `src/utils/prompt_packs.py` can discover packs from a directory.
- `AppController` loads packs, tracks selection, and handles Load/Edit clicks.
- v2 LeftZone widgets are driven by the controller instead of stub handlers.
- New tests for pack discovery and controller behavior pass.
- All pre-existing tests remain green.
