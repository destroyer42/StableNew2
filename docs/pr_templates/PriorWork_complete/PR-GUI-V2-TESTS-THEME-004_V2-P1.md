# PR-GUI-V2-TESTS-THEME-004_V2-P1 — Make GUI V2 Tests Use MainWindowV2 and Retire legacy theme.py

**Snapshot Baseline:** `StableNew-snapshot-20251128-154233.zip`  
**Inventory Baseline:** `repo_inventory.json` in the same snapshot

> Phase-1 Alignment  
> - “Stop relying on AppLayoutV2 / StableNewGUI for V2 tests.”  
> - “V2 GUI entrypoint = MainWindowV2.”  
> - “Move any needed elements from theme.py to theme_v2.py and retire theme.py to the archive bin.”

This PR does two tightly-related things:

1. **Updates GUI V2 tests to construct and exercise `MainWindowV2` directly** (through the V2 app factory), instead of the legacy `StableNewGUI + AppLayoutV2` stack.
2. **Migrates the last remaining V2 theming dependencies from `src/gui/theme.py` into `src/gui/theme_v2.py`,** updates callers, and archives `theme.py` so V2 has a single canonical theme implementation.

No pipeline, controller, or WebUI contracts are changed.

---

## 1. Goal & Scope

### Goals

1. **Tests:**  
   - `tests/gui_v2` fixtures should build **MainWindowV2** via `build_v2_app`, not `StableNewGUI` or `_build_ui_v2()` from `src/gui/main_window.py`.
   - GUI V2 tests must not go through `AppLayoutV2` or legacy theming (`theme.py`).

2. **Theming:**
   - All V2 widgets and panels must import styling constants and styles from **`theme_v2.py` only**.
   - `theme.py` becomes a pure legacy artifact and is moved to the archive.

### In Scope

- `tests/gui_v2/conftest.py`
- `src/gui/theme_v2.py`
- `src/gui/theme.py` (archive only; no behavior changes to new code paths)
- V2 panels that currently import `src.gui.theme`:
  - `src/gui/job_history_panel_v2.py`
  - `src/gui/negative_prompt_panel_v2.py`
  - `src/gui/resolution_panel_v2.py`

### Out of Scope

- Any changes to:
  - `src/main.py`
  - `src/app_factory.py`
  - `src/controller/app_controller.py`
  - `src/gui/main_window_v2.py`
  - `src/gui/layout_v2.py`
  - Any `src/gui/panels_v2/*` modules not listed above
- Any test moves/archival (handled by `CLEANUP-GUI-TEST-QUARANTINE-002_V2-P1`).

---

## 2. Tests: Stop Using StableNewGUI / AppLayoutV2

### 2.1 Update `tests/gui_v2/conftest.py` to build MainWindowV2

**File to edit:**

- `tests/gui_v2/conftest.py`

**Current behavior (simplified):**

- Imports from `src.gui.main_window`:

  - `StableNewGUI`
  - `enable_gui_test_mode`
  - `reset_gui_test_mode`

- `gui_app_factory` fixture builds a `StableNewGUI` instance directly:

  - Creates temporary `packs`, `presets`, `lists`, and `output` directories in `tmp_path`.
  - Instantiates `StableNewGUI(root=tk_root, config_manager=ConfigManager(...), preferences=PreferencesManager(...), ...)`.
  - Sets `config_service`, `structured_logger.output_dir`, and fake `api_connected`.
  - Calls `enable_gui_test_mode()` at fixture entry and `reset_gui_test_mode()` at fixture teardown.

This drives the legacy `StableNewGUI` + `AppLayoutV2` path and ultimately hits the `theme` kwarg issue.

**Desired behavior:**

- `gui_app_factory` should build the **V2 app stack** via `build_v2_app`:

  - `from src.app_factory import build_v2_app`
  - Call `build_v2_app(root=tk_root, pipeline_runner=None, webui_manager=None, threaded=False)` to construct:
    - `root` (Tk)
    - `app_state` (`AppStateV2`)
    - `app_controller` (`AppController`)
    - `window` (`MainWindowV2`)
  - Return the `window` as the `app` for GUI tests.

**Concrete edits:**

1. **Imports:**

   - Remove imports from `src.gui.main_window`:

     ```python
     from src.gui.main_window import (
         StableNewGUI,
         enable_gui_test_mode,
         reset_gui_test_mode,
     )
     ```

   - Add import from app factory:

     ```python
     from src.app_factory import build_v2_app
     ```

   - Leave `ConfigManager`, `PreferencesManager`, and `ConfigService` imports as-is if they’re still used for configuration of the V2 stack (or remove them if unused after refactor).

2. **`gui_app_factory` fixture implementation:**

   - Replace the body that calls `StableNewGUI(...)` with a call to `build_v2_app`:

     - Keep the tmp directories (`packs_dir`, `presets_dir`, `lists_dir`, `output_dir`) creation exactly as now.
     - Inside the inner `_build(**kwargs)`:

       - Create a minimal stub `pipeline_runner` if needed:

         ```python
         def _stub_pipeline_runner(*_args, **_kwargs):
             # no-op; enough for layout tests
             return None
         ```

       - Call `root, app_state, app_controller, window = build_v2_app(
             root=tk_root,
             pipeline_runner=_stub_pipeline_runner,
             webui_manager=None,
             threaded=False,
         )`

       - If tests rely on `config_service` or `structured_logger.output_dir` on the window, configure them on `window` or `app_controller` in the same way the old fixture did, but **without** calling into legacy main_window scaffolding.

       - Return `window` from `_build`.

   - Remove calls to `enable_gui_test_mode()` and `reset_gui_test_mode()`; they are legacy helpers tied to `StableNewGUI`.

3. **Teardown:**

   - The fixture currently uses `yield _build` and calls `reset_gui_test_mode()` after `yield`.
   - After removing `reset_gui_test_mode()`, the teardown can be either a no-op or a simple `yield _build` with no extra cleanup (Tk cleanup is usually handled by the test harness).

**Result:**

- All GUI V2 tests that use `gui_app_factory()` will now be exercising **MainWindowV2** constructed through the canonical V2 app stack (AppController + AppStateV2), with no dependency on `AppLayoutV2` or `StableNewGUI`.

---

## 3. Theming: Migrate constants to theme_v2 and archive theme.py

### 3.1 Add missing constants to `src/gui/theme_v2.py`

**File to edit:**

- `src/gui/theme_v2.py`

Currently `theme_v2.py` defines:

- Color constants:

  - `BACKGROUND_DARK`, `BACKGROUND_ELEVATED`, `BORDER_SUBTLE`, `TEXT_PRIMARY`, `TEXT_MUTED`, `TEXT_DISABLED`, `ACCENT_GOLD`, `ACCENT_GOLD_HOVER`, etc.

- `Theme.apply_ttk_styles(...)` sets up key styles like:

  - `"Panel.TFrame"`, `"Surface.TFrame"`, `"StatusBar.TFrame"`, `"Pipeline.TFrame"`, `"PipelineHeading.TLabel"`, `"StatusStrong.TLabel"`, etc.

V2 widgets still expect a few legacy-style constants, currently provided only by `theme.py`:

- `PADDING_XS`
- `PADDING_SM`
- `PADDING_MD`
- `PADDING_LG`
- `STATUS_LABEL_STYLE`
- `STATUS_STRONG_LABEL_STYLE`
- `SURFACE_FRAME_STYLE`

**Edits:**

1. **Define padding constants at module level** (matching existing values from `theme.py`):

   ```python
   PADDING_XS = 2
   PADDING_SM = 4
   PADDING_MD = 8
   PADDING_LG = 12
   ```

2. **Define style name constants mapping into existing styles:**

   - For frame surfaces:

     ```python
     SURFACE_FRAME_STYLE = "Surface.TFrame"
     ```

   - For labels:

     ```python
     STATUS_LABEL_STYLE = "Status.TLabel"
     STATUS_STRONG_LABEL_STYLE = "StatusStrong.TLabel"
     ```

3. **Ensure `"Status.TLabel"` exists in `apply_ttk_styles`:**

   - In `Theme.apply_ttk_styles`, where other label styles are configured, add a configure call for `Status.TLabel`, e.g.:

     ```python
     style.configure(
         "Status.TLabel",
         foreground=TEXT_MUTED,
         background=BACKGROUND_ELEVATED,
     )
     ```

   - `"StatusStrong.TLabel"` is already configured; keep it as the “strong” variant.

4. **Optionally add `__all__`** (if not already present) to make it clear what `theme_v2` exports:

   ```python
   __all__ = [
       "Theme",
       "BACKGROUND_DARK",
       "BACKGROUND_ELEVATED",
       "BORDER_SUBTLE",
       "TEXT_PRIMARY",
       "TEXT_MUTED",
       "TEXT_DISABLED",
       "ACCENT_GOLD",
       "ACCENT_GOLD_HOVER",
       "ERROR_RED",
       "SUCCESS_GREEN",
       "INFO_BLUE",
       "PADDING_XS",
       "PADDING_SM",
       "PADDING_MD",
       "PADDING_LG",
       "SURFACE_FRAME_STYLE",
       "STATUS_LABEL_STYLE",
       "STATUS_STRONG_LABEL_STYLE",
   ]
   ```

   (If `__all__` already exists, just append the new names.)

### 3.2 Update V2 panels to import from `theme_v2` instead of `theme`

**Files to edit:**

1. `src/gui/job_history_panel_v2.py`
2. `src/gui/negative_prompt_panel_v2.py`
3. `src/gui/resolution_panel_v2.py`

**Current imports:**

Each of these files currently does:

```python
from src.gui import theme as theme_mod
```

and then uses attributes such as:

- `theme_mod.SURFACE_FRAME_STYLE`
- `theme_mod.PADDING_MD`
- `theme_mod.PADDING_SM`
- `theme_mod.STATUS_LABEL_STYLE`
- `theme_mod.STATUS_STRONG_LABEL_STYLE`

**Edits:**

- Change the import to:

  ```python
  from src.gui import theme_v2 as theme_mod
  ```

- Leave the rest of the code intact, since the attribute names are now provided by `theme_v2`:

  - `SURFACE_FRAME_STYLE`, `PADDING_MD`, `PADDING_SM`, `STATUS_LABEL_STYLE`, `STATUS_STRONG_LABEL_STYLE` will resolve against `theme_v2`.

**Result:**

- All V2 panels rely exclusively on `theme_v2` for styling constants.

### 3.3 Archive `src/gui/theme.py`

**File to move:**

- `src/gui/theme.py` → `archive/gui_v1/theme.py`

**Actions:**

1. Use `git mv` to move the file:

   - `git mv src/gui/theme.py archive/gui_v1/theme.py`

2. Optionally add a short header comment inside the archived file:

   ```python
   # Legacy theming module (V1 / hybrid).
   # Kept only for historical reference; V2 GUI uses src.gui.theme_v2 instead.
   ```

3. After the move, run a search in the repo to confirm no remaining imports:

   ```bash
   rg "from src\.gui import theme" .
   rg "import src\.gui\.theme" .
   rg "theme_mod = theme" -n
   ```

   - There should be **no matches outside `archive/`**.

---

## 4. Files Explicitly **Not** to Touch

To keep this PR surgical, **do not** change:

- `src/gui/main_window.py` (any reshaping of this file into a pure shim will be a separate PR).
- `src/gui/main_window_v2.py`
- `src/main.py`
- `src/app_factory.py`
- `src/controller/app_controller.py`
- Any modules under:
  - `src/gui/panels_v2/` (other than the three listed)
  - `src/gui/stage_cards_v2/`
  - `src/gui/widgets/scrollable_frame_v2.py` (already uses `theme_v2`)
- Any non-GUI tests.

---

## 5. Validation & Test Plan

### 5.1 GUI V2 Tests

Run the core GUI V2 tests:

```bash
pytest tests/gui_v2/test_gui_v2_layout_skeleton.py -q
pytest tests/gui_v2/test_entrypoint_uses_v2_gui.py -q
pytest tests/gui_v2/test_theme_v2.py -q
```

Expected:

- `test_gui_v2_layout_skeleton` now builds a `MainWindowV2` instance via `build_v2_app` (through `gui_app_factory`).
- No stack trace mentioning `AppLayoutV2`, `StableNewGUI`, or `_tkinter.TclError: unknown option "-theme"`.

### 5.2 Global Tests

Run:

```bash
pytest -q
```

Expected:

- No new failures introduced by:
  - Changing the fixture to use `build_v2_app`.
  - Migrating theme constants to `theme_v2`.
  - Archiving `src/gui/theme.py`.

### 5.3 Import Checks

After the changes:

```bash
rg "from src\.gui import theme" src tests
rg "import src\.gui\.theme" src tests
```

Expected:

- No matches outside `archive/gui_v1/theme.py`.

---

## 6. Definition of Done

This PR is complete when:

1. `tests/gui_v2/conftest.py` builds `MainWindowV2` via `build_v2_app` and no longer imports or calls:
   - `StableNewGUI`
   - `enable_gui_test_mode`
   - `reset_gui_test_mode`
   - `AppLayoutV2`
2. `src/gui/theme_v2.py` defines the padding and style constants used by V2 panels:
   - `PADDING_XS`, `PADDING_SM`, `PADDING_MD`, `PADDING_LG`
   - `SURFACE_FRAME_STYLE`, `STATUS_LABEL_STYLE`, `STATUS_STRONG_LABEL_STYLE`
   - and configures `Status.TLabel` as a distinct style.
3. `src/gui/job_history_panel_v2.py`, `negative_prompt_panel_v2.py`, and `resolution_panel_v2.py` import `theme_v2` instead of `theme`, and still render correctly.
4. `src/gui/theme.py` has been moved to `archive/gui_v1/theme.py`, and there are **no active imports** of `src.gui.theme` anywhere under `src/` or `tests/`.
5. All existing Phase-1 target tests pass, and there are no new GUI regressions when running `python -m src.main` (GUI boots and displays the V2 layout).