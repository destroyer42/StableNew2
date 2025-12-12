
# PR-GUI-THEME-FIX-001: Restore ASWF Theme Constants and Theme Class

## 1. Title

**PR-GUI-THEME-FIX-001: Restore ASWF Theme Constants and Theme Class**

---

## 2. Summary

GUI tests are currently failing during import because `src.gui.theme` no longer exposes the expected **ASWF theme constants** and the **Theme** class used throughout the GUI (e.g., `AdvancedPromptEditor`, `PromptPackPanel`, `StageChooser`, and `test_theme_baseline`).

This PR restores the **minimal but complete theme surface** required by the existing GUI code and tests:

- Reintroduces or defines the ASWF color + font constants:
  - `ASWF_BLACK`, `ASWF_GOLD`, `ASWF_DARK_GREY`, `ASWF_MED_GREY`, `ASWF_LIGHT_GREY`
  - `ASWF_ERROR_RED`, `ASWF_OK_GREEN`
  - `FONT_FAMILY`, `FONT_SIZE_BASE`, `FONT_SIZE_LABEL`, `FONT_SIZE_BUTTON`, `FONT_SIZE_HEADING`
- Provides a `Theme` class with methods used by the GUI and exercised in tests, implemented in a **Tk-safe, headless-safe** way (using `try/except` around widget `.configure()` calls).
- Ensures `tests/gui/*` can import `src.gui.theme` without `ImportError` and that `test_theme_baseline` passes.

This PR is **GUI-only** and does not touch controller, pipeline, API, or utils layers.

---

## 3. Problem Statement

### 3.1 Current Failure

Running GUI tests yields:

- `ImportError: cannot import name 'ASWF_BLACK' from 'src.gui.theme'`
- `ImportError: cannot import name 'Theme' from 'src.gui.theme'`

Affected modules/tests include:

- `src.gui.advanced_prompt_editor` (imports ASWF_* + Theme)
- `src.gui.prompt_pack_panel` (imports ASWF_BLACK, ASWF_DARK_GREY, ASWF_GOLD)
- `src.gui.stage_chooser` (imports Theme)
- `tests/gui/test_theme_baseline.py` (imports ASWF_* and Theme)
- Many other GUI tests that transitively import `main_window` → `advanced_prompt_editor` → `theme`.

### 3.2 Impact

Because `src.gui.theme` does not define the expected names, **the entire GUI test suite fails during import**, even before any behavioral assertions run. This blocks:

- GUI regression testing
- Integration work on lifecycle and pipeline behavior that relies on a stable GUI

### 3.3 Why This PR Exists

We need a **small, well-scoped GUI PR** that:

- Restores the ASWF theme constants to their intended values (from the Figma/ASWF style guide).
- Reintroduces a `Theme` class with the methods expected by tests and GUI modules.
- Leaves the rest of the architecture untouched.

---

## 4. Goals

1. **Fix ImportError for ASWF_* and Theme** in `src.gui.theme`.
2. Ensure `tests/gui/test_theme_baseline.py` passes (and any other theme-related tests).
3. Allow other GUI tests to import `StableNewGUI`, `AdvancedPromptEditor`, `PromptPackPanel`, etc., without theme-related crashes.
4. Keep the implementation simple, headless-safe, and aligned with the ASWF dark theme (per `GUI_FIGMA_LAYOUT_GUIDE.md`).

---

## 5. Non-goals

- No changes to controller behavior or lifecycle.
- No changes to pipeline or randomizer behavior.
- No layout changes in GUI modules (no widget rearrangement).
- No new visual theming features beyond restoring the baseline constants and Theme methods.
- No changes to utils, API, or logging.

---

## 6. Allowed Files

Codex may modify **only** the following files in this PR:

- `src/gui/theme.py`
- `tests/gui/test_theme_baseline.py` (only if minor adjustments are required to align with the restored Theme API)

If `src/gui/theme.py` does not exist or is empty, Codex should create/populate it according to this spec.

---

## 7. Forbidden Files

Do **NOT** modify any of the following in this PR:

- Any other file under `src/gui/` (e.g., `main_window.py`, `advanced_prompt_editor.py`, `prompt_pack_panel.py`, `stage_chooser.py`)
- Any file under `src/controller/`
- Any file under `src/pipeline/`
- Any file under `src/utils/`
- Any file under `src/api/`
- Any non-theme tests (outside `tests/gui/test_theme_baseline.py`)

If it appears necessary to modify these files, **STOP and request a separate PR**.

---

## 8. Step-by-step Implementation

### 8.1 Restore ASWF Theme Constants in `src/gui/theme.py`

Add or restore the following constants with values aligned to the ASWF style guide and prior usage:

```python
ASWF_BLACK = "#221F20"
ASWF_GOLD = "#FFC805"

ASWF_DARK_GREY = "#2B2A2C"
ASWF_MED_GREY = "#3A393D"
ASWF_LIGHT_GREY = "#4A4950"

ASWF_ERROR_RED = "#CC3344"
ASWF_OK_GREEN = "#44AA55"

FONT_FAMILY = "Calibri"
FONT_SIZE_BASE = 11
FONT_SIZE_LABEL = 11
FONT_SIZE_BUTTON = 11
FONT_SIZE_HEADING = 13
```

These values are consistent with the Figma layout guide (ASWF black/gold) and provide a stable baseline for tests and widgets using the theme.

If additional constants are referenced by `test_theme_baseline.py` (e.g., `COLOR_BG`, `COLOR_SURFACE`, `COLOR_SURFACE_ALT`, `COLOR_TEXT`, `COLOR_ACCENT`), define them sensibly in terms of the ASWF palette above, for example:

```python
COLOR_BG = ASWF_BLACK
COLOR_SURFACE = ASWF_DARK_GREY
COLOR_SURFACE_ALT = ASWF_MED_GREY
COLOR_TEXT = ASWF_LIGHT_GREY
COLOR_ACCENT = ASWF_GOLD
```

### 8.2 Implement the `Theme` Class

Implement a minimal but complete `Theme` class that exposes methods used by the GUI code and tests, such as:

- `apply_root(root)`
- `apply_ttk_styles(style)`
- `style_listbox(widget)`
- `style_button_primary(button)`
- `style_button_danger(button)`
- `style_frame(frame)`
- `style_label(label)`
- `style_label_heading(label)`
- `style_entry(entry)`
- `style_text(widget)`
- `style_scrollbar(scrollbar)`

Implementation guidance:

- Each method should configure widget colors/fonts using the constants above.
- To keep the tests stable in headless environments, **wrap widget `.configure()` calls in `try/except Exception`** so missing attributes or dummy widgets in tests do not cause crashes.

Example pattern (do not rely on this exact code, but keep the structure):

```python
class Theme:
    def apply_root(self, root):
        try:
            root.configure(bg=COLOR_BG)
        except Exception:
            pass

    def apply_ttk_styles(self, style):
        # For now, simply return the style; more advanced Ttk theming can be added later.
        return style

    def style_button_primary(self, button):
        try:
            button.configure(
                bg=ASWF_GOLD,
                fg=ASWF_BLACK,
                relief="flat",
                borderwidth=0,
                font=(FONT_FAMILY, FONT_SIZE_BUTTON, "bold"),
            )
        except Exception:
            pass

    # ... similarly for other style_* methods ...
```

Ensure that all methods used in `StageChooser`, `PromptPackPanel`, and any tests under `tests/gui/test_theme_baseline.py` are present.

### 8.3 Align `test_theme_baseline.py` (if needed)

Open `tests/gui/test_theme_baseline.py` and confirm that:

- It imports the expected constants and `Theme` from `src.gui.theme`.
- It asserts any specific hex values / basic behavior that should still hold.

If the test expectations differ slightly (e.g., different constant names), adjust the **test** minimally to reference the restored theme API, but do not weaken the intent (ASWF-themed dark mode, consistent font sizes, etc.).

Changes to tests should be **minimal** and only made if necessary.

---

## 9. Required Tests

After implementing the above, run:

```bash
pytest tests/gui/test_theme_baseline.py -v
pytest tests/gui -v
```

Initially, you may run only `test_theme_baseline.py` while iterating. Once it passes, run the full GUI suite to ensure there are no remaining theme-related import errors.

If some GUI tests are skipped due to Tk/Tcl issues (e.g., missing `init.tcl`), that is acceptable as long as:

- They skip with the existing skip messages.
- They do not fail due to theme imports.

---

## 10. Acceptance Criteria

This PR is complete when:

1. `src.gui.theme` defines:
   - `ASWF_BLACK`, `ASWF_GOLD`, `ASWF_DARK_GREY`, `ASWF_MED_GREY`, `ASWF_LIGHT_GREY`, `ASWF_ERROR_RED`, `ASWF_OK_GREEN`
   - `FONT_FAMILY`, `FONT_SIZE_BASE`, `FONT_SIZE_LABEL`, `FONT_SIZE_BUTTON`, `FONT_SIZE_HEADING`
   - `Theme` class with the methods required by GUI code and tests.
2. `tests/gui/test_theme_baseline.py` passes.
3. `pytest tests/gui -v` no longer fails due to `ImportError` from `src.gui.theme`. (Other skips due to Tk/Tcl are acceptable.)
4. No other GUI modules were modified.
5. No non-GUI layers (controller, pipeline, utils, API) were modified.

---

## 11. Rollback Plan

If issues or regressions are discovered:

1. Revert `src/gui/theme.py` to its previous version.
2. Revert any changes made to `tests/gui/test_theme_baseline.py`.
3. Re-run:

   ```bash
   pytest tests/gui -v
   ```

   to ensure the suite returns to its prior behavior (even if that includes the original ImportErrors).

Because this PR is limited to a single GUI module and one test file, rollback is straightforward.

---

## 12. Codex Execution Constraints

**For Codex (Implementer):**

- Open and follow this PR spec at:
  - `docs/codex/prs/PR-GUI-THEME-FIX-001_restore_theme_constants_and_theme_class.md`

Constraints:

1. Modify only `src/gui/theme.py` and, if needed, `tests/gui/test_theme_baseline.py`.
2. Do not refactor or “clean up” any other part of the GUI.
3. Use the ASWF colors (`#221F20` black, `#FFC805` gold) as canonical.
4. Keep all widget styling wrapped in `try/except` blocks to remain headless-safe in tests.
5. Run `pytest tests/gui/test_theme_baseline.py -v` and then `pytest tests/gui -v` and paste the results when executing this PR.
