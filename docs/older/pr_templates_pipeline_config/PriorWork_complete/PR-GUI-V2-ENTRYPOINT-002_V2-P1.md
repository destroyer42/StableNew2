
# PR-GUI-V2-ENTRYPOINT-002_V2-P1 — Flip Entrypoint to MainWindowV2 & Archive Legacy GUI

**Snapshot Baseline:** `StableNew-snapshot-20251128-111334.zip`  
**Inventory Baseline:** `repo_inventory_classified_v2_phase1.json` (Phase-1 classification)  

> Phase-1 Objective Alignment:  
> - **Single V2 GUI shell:** `MainWindowV2` is the only GUI entrypoint.  
> - **Legacy GUI archived:** `StableNewGUI` and the hybrid bridge (`AppLayoutV2`) are no longer used by runtime or active tests.  
> - **Tests align to V2:** Entrypoint tests and GUI V2 fixtures stop referencing `StableNewGUI`.

---

## 1. Goal & Scope

### High-Level Goal

Make **`MainWindowV2`** the **canonical GUI entrypoint** for StableNew and archive the old monolithic/ hybrid GUI:

- `src/gui/main_window.py` (StableNewGUI)
- `src/gui/app_layout_v2.py` (hybrid V2-inside-V1 bridge)
- `src/gui/theme.py`
- `src/gui/prompt_pack_panel.py`

This PR is focused on:

1. **Entrypoint contract** (`ENTRYPOINT_GUI_CLASS`) → now points to `MainWindowV2`.
2. **Tests** that previously assumed `StableNewGUI` → updated to use V2 or archived as V1.
3. **Archival move** of the legacy GUI implementation files into `archive/gui_v1/`.

> NOTE: This PR assumes the left-panel packs/presets port (`PR-GUI-V2-LEFTPANEL-001`) is either merged or in progress; it does **not** add new GUI features, only flips what is considered “the real GUI.”

---

## 2. Files to Modify (Allowed)

### Runtime / Entrypoint

- `src/main.py`
  - Export `ENTRYPOINT_GUI_CLASS` that points to `MainWindowV2` (via `app_factory` / `main_window_v2`).
  - This is needed for `tests/gui_v2/test_entrypoint_uses_v2_gui.py`.

- `src/gui/main_window_v2.py`
  - Export `ENTRYPOINT_GUI_CLASS = MainWindowV2` at module level.
  - This replaces the old implicit `StableNewGUI` contract for tests.

> **Do not change** the `main()` logic beyond adding `ENTRYPOINT_GUI_CLASS` and possibly a comment.  
> It already uses `build_v2_app()` and `MainWindowV2`, which is correct.

### Tests (V2-aligned)

- `tests/gui_v2/conftest.py`
  - Change `gui_app_factory` to build a **V2 app**, instead of `StableNewGUI`:
    - Import from `src.app_factory` (`build_v2_app`) and/or `src.gui.main_window_v2.MainWindowV2`.
    - Stop importing `StableNewGUI`, `enable_gui_test_mode`, `reset_gui_test_mode` from `src.gui.main_window`.
    - Create a `tk_root` and call `build_v2_app(root=tk_root, ...)` in test mode, returning `window` (which is a `MainWindowV2` instance).
    - Ensure heavy side effects (WebUI process, long-running checks) are disabled via monkeypatch or arguments (similar to how `enable_gui_test_mode` used to).

- `tests/gui_v2/test_entrypoint_uses_v2_gui.py`
  - Migrate expectations from `StableNewGUI` to `MainWindowV2`:
    - `from src.gui import main_window_v2 as main_window`
    - In `test_stablenewgui_exposes_v2_components` (rename if desired):
      - `app = gui_app_factory()`
      - Assert `center_notebook`, `pipeline_panel_v2`, `status_bar_v2` attributes still exist – but now on `MainWindowV2`.
    - In `test_entrypoint_targets_v2_gui`:
      - `import src.main as entrypoint`
      - `reload(entrypoint)`
      - `assert getattr(main_window, "ENTRYPOINT_GUI_CLASS", None) is main_window.MainWindowV2`
      - `assert getattr(entrypoint, "ENTRYPOINT_GUI_CLASS", None) is main_window.MainWindowV2`

- `tests/gui_v2/test_gui_v2_ai_settings_button_guarded.py`
  - This test currently imports `StableNewGUI`, `enable_gui_test_mode`, `disable_gui_test_mode` from `src.gui.main_window`.
  - For **this PR**, move it to the legacy tests archive, because:
    - The AI settings generator is not yet ported to V2.
    - We need to decouple GUI V2 tests from `StableNewGUI`.
  - Action:
    - Move file to `archive/tests_v1/gui_v1_legacy/test_gui_v2_ai_settings_button_guarded.py` (keeping its contents unchanged).
    - Optionally add a short module-level comment noting that AI settings will be reintroduced in V2 in a future PR.

- `tests/conftest.py`
  - If it imports `StableNewGUI` or `src.gui.main_window`, remove those references or gate them behind legacy/archived behaviors.
  - Ensure no common fixtures for non-legacy tests depend on the legacy GUI.

---

## 3. Files to Move/Archive (Legacy GUI)

Create a new directory (if it does not already exist):

- `archive/gui_v1/`

Then **move**, not copy:

- `src/gui/main_window.py` → `archive/gui_v1/main_window.py`
- `src/gui/app_layout_v2.py` → `archive/gui_v1/app_layout_v2.py`
- `src/gui/theme.py` → `archive/gui_v1/theme.py`
- `src/gui/prompt_pack_panel.py` → `archive/gui_v1/prompt_pack_panel.py`

And for tests:

- Create or reuse `archive/tests_v1/gui_v1_legacy/`:
  - Move:
    - `tests/gui_v2/test_gui_v2_ai_settings_button_guarded.py`
  - Ensure any other tests that reference `StableNewGUI` and are not rewritten for V2 are also moved here (e.g., if new ones are discovered when running `rg "StableNewGUI" tests`).

> **Important:** Because these are moves, not deletes, they are still available as reference if we need to consult them later, but they can no longer be imported from `src.*` or `tests.*` during normal runs.

---

## 4. Files Explicitly **Not** to Touch in This PR

To keep scope controlled and avoid unintended regressions:

- `src/pipeline/executor.py`
- `src/controller/app_controller.py`
- `src/gui/theme_v2.py`
- `src/gui/sidebar_panel_v2.py`
- `src/gui/pipeline_panel_v2.py`
- `src/gui/prompt_pack_panel_v2.py`
- `src/gui/status_bar_v2.py`
- `src/gui/preview_panel_v2.py`
- `src/gui/randomizer_panel_v2.py`
- `src/gui/stage_cards_v2/*`
- `src/gui/app_state_v2.py`
- `src/gui/adetailer_config_panel.py`  (**still “maybe” – keep, no edits**)
- Any files under `archive/` besides the new moves noted above.

---

## 5. Architectural & Contract Changes

### 5.1 Entrypoint Contract

**New contract:**

- In `src/gui/main_window_v2.py`:

  ```python
  class MainWindowV2(...):
      ...

  # Used by tests and entrypoint contract
  ENTRYPOINT_GUI_CLASS = MainWindowV2
  ```

- In `src/main.py`, near the top-level imports:

  ```python
  from src.gui.main_window_v2 import MainWindowV2, ENTRYPOINT_GUI_CLASS  # ENTRYPOINT_GUI_CLASS re-export
  ```

  or:

  ```python
  from src.gui.main_window_v2 import MainWindowV2

  ENTRYPOINT_GUI_CLASS = MainWindowV2
  ```

**Behavior:**

- Tests now rely on `ENTRYPOINT_GUI_CLASS` pointing to `MainWindowV2` in both:
  - `src.gui.main_window_v2`
  - `src.main`

The `main()` function logic remains unchanged (it already uses `build_v2_app`).

### 5.2 Testing Surface

- `gui_app_factory` now returns a **`MainWindowV2`** instance, not `StableNewGUI`.
- All GUI V2 tests that import the entrypoint class should now import from `src.gui.main_window_v2`.

---

## 6. Validation & Tests

### 6.1 Automated Tests

At minimum, these should pass:

- `pytest tests/gui_v2/test_entrypoint_uses_v2_gui.py -q`
- `pytest tests/gui_v2/test_gui_v2_layout_skeleton.py -q`
- `pytest tests/gui_v2 -q` (overall GUI V2 suite)
- `pytest -q` (full suite), with the understanding that:
  - Any failures referencing `StableNewGUI` should either:
    - Be updated to use `MainWindowV2`, **or**
    - Be moved to `archive/tests_v1` and documented as legacy.

### 6.2 Manual Smoke Check

- Run `python -m src.main`:
  - Confirm the V2 GUI opens (no black screen).
  - Confirm the window class is `MainWindowV2` (e.g., via logging or internal attribute).
- Confirm that no code paths import `src.gui.main_window` at runtime:
  - You can optionally use the `STABLENEW_FILE_ACCESS_LOG=1` feature to confirm only V2 GUI files are touched for the main window.

---

## 7. Definition of Done

This PR is complete when:

1. **Entrypoint contract flipped:**
   - `ENTRYPOINT_GUI_CLASS` points to `MainWindowV2` in both `src.gui.main_window_v2` and `src.main`.

2. **Legacy GUI archived:**
   - `src/gui/main_window.py`, `app_layout_v2.py`, `theme.py`, `prompt_pack_panel.py` have been moved to `archive/gui_v1/`.
   - `tests/gui_v2/test_gui_v2_ai_settings_button_guarded.py` (and any other `StableNewGUI`-only GUI tests not yet ported) have been moved to `archive/tests_v1/gui_v1_legacy/`.

3. **V2 tests aligned:**
   - `tests/gui_v2/conftest.py` builds a V2 GUI (`MainWindowV2`) via `build_v2_app` or equivalent; no imports from `src.gui.main_window`.
   - `tests/gui_v2/test_entrypoint_uses_v2_gui.py` asserts that `ENTRYPOINT_GUI_CLASS` is `MainWindowV2` in both `src.gui.main_window_v2` and `src.main`.

4. **No remaining V2 runtime imports of legacy GUI:**
   - A search for `StableNewGUI` in `src/` yields only:
     - Files under `archive/`, or
     - Comments / docstrings clearly marked as legacy reference (if any).

5. **Test suite stable:**
   - GUI V2 tests pass.
   - Any remaining failures due to `StableNewGUI` references have either:
     - Been updated to use `MainWindowV2`, or
     - Been consciously moved to the legacy test archive.
