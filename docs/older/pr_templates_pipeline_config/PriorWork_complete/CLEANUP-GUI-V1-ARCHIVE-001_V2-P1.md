# CLEANUP-GUI-V1-ARCHIVE-001_V2-P1 — Archive V1 / Hybrid GUI Shell

**Snapshot Baseline:** `StableNew-snapshot-20251128-144410.zip`  
**Inventory Baseline:** `docs/StableNew_V2_Inventory_V2-P1.md` + `repo_inventory.json`

> Phase-1 Objective Alignment:  
> - “Only V2 code survives. V1 is immediately archived so accidental imports cannot happen.”  
> - “Fix the V2 GUI scaffold once, clearly, deterministically.”

This PR removes the **old GUI shell and layout scaffolding** from the active import surface by moving them into an archive folder, while keeping the new **MainWindowV2 + LayoutManagerV2 + panels_v2** path untouched.

---

## 1. Goal & Scope

### Goal

- **Eliminate the V1 / hybrid GUI shell** from runtime so there is a single, unambiguous GUI stack:
  - `main.py` → `app_factory.build_v2_app` → `MainWindowV2` → `LayoutManagerV2` → `panels_v2/*`.
- **Prevent accidental regressions** where old layout files re-enter imports.
- Preserve the old files in `archive/gui_v1/` for reference only.

### In Scope

- `src/gui` V1 / hybrid layout and shell files that are **not** part of the current MainWindowV2 path.
- Root-level scratch / noise files that are not part of the repo contract.

### Out of Scope

- Any `_v2` / `panels_v2` / `theme_v2` modules.
- Any `gui_v2/*` adapter files (these are handled as “future subsystem” in a separate PR).
- Learning, queue, cluster, and AI subsystems.

---

## 2. Files to Move (Archive)

Create or reuse:

- `archive/gui_v1/`

Then **move** the following files using `git mv`, preserving relative structure:

### 2.1 V1 / Hybrid GUI Shell & Layout

From `src/gui/`:

1. `src/gui/main_window.py`  
   - The original `StableNewGUI` monolithic window, now superseded by `MainWindowV2`.
2. `src/gui/config_panel.py`
3. `src/gui/center_panel.py`
4. `src/gui/pipeline_controls_panel.py`
5. `src/gui/stage_chooser.py`
6. `src/gui/log_panel.py`
7. `src/gui/scrolling.py`
8. `src/gui/tooltip.py`

Move them to:

- `archive/gui_v1/main_window.py`
- `archive/gui_v1/config_panel.py`
- `archive/gui_v1/center_panel.py`
- `archive/gui_v1/pipeline_controls_panel.py`
- `archive/gui_v1/stage_chooser.py`
- `archive/gui_v1/log_panel.py`
- `archive/gui_v1/scrolling.py`
- `archive/gui_v1/tooltip.py`

### 2.2 Legacy Stage Cards

The original stage cards are superseded by the V2 cards in `src/gui/stage_cards_v2/`:

9. `src/gui/txt2img_stage_card.py`
10. `src/gui/img2img_stage_card.py`
11. `src/gui/upscale_stage_card.py`

Move them to:

- `archive/gui_v1/txt2img_stage_card.py`
- `archive/gui_v1/img2img_stage_card.py`
- `archive/gui_v1/upscale_stage_card.py`

### 2.3 Hybrid “AppLayoutV2” Bridge

12. `src/gui/app_layout_v2.py`  
   - Old hybrid layout that wired adapters + V1 shell.
   - Now superseded by `MainWindowV2` zone-map plus `LayoutManagerV2` and `panels_v2/*`.

Move to:

- `archive/gui_v1/app_layout_v2.py`

### 2.4 Legacy Theme Module

13. `src/gui/theme.py`  
   - Legacy theme helpers; `src/gui/theme_v2.py` is now the canonical V2 theme.
   - `theme.py` is only imported by legacy tests and `main_window.py` (which we are archiving).

Move to:

- `archive/gui_v1/theme.py`

> After this move, the only active theme entrypoint should be `src/gui/theme_v2.py`.

---

## 3. Root-Level Noise Cleanup

These are not part of the runtime contract and should not be in the main tree:

1. `_tmp_test.py`
2. `desktop.ini`

### Actions

- Remove `_tmp_test.py` from the repo (or move to `archive/dev_scratch/_tmp_test.py` if you prefer not to delete).
- Remove `desktop.ini` from the repo entirely.

---

## 4. Files Explicitly **Not** to Touch

To keep this PR surgical and Phase-1-safe:

- Do **not** modify or move:
  - `src/main.py`
  - `src/app_factory.py`
  - `src/controller/app_controller.py`
  - `src/gui/main_window_v2.py`
  - `src/gui/layout_v2.py`
  - `src/gui/theme_v2.py`
  - `src/gui/panels_v2/*`
  - `src/gui/pipeline_panel_v2.py`
  - `src/gui/preview_panel_v2.py`
  - `src/gui/adetailer_config_panel.py` (explicitly “maybe” – keep untouched)
  - `src/gui/advanced_prompt_editor.py`
  - `src/gui/api_status_panel.py`
  - `src/gui/engine_settings_dialog.py`
  - `src/gui/job_history_panel_v2.py`
  - `src/gui/learning_review_dialog_v2.py`
  - `src/gui/randomizer_panel_v2.py`
  - any files under `src/gui/stage_cards_v2/`
  - any files under `src/gui_v2/` (handled later as future subsystems)

---

## 5. Test Impact & Validation

### 5.1 Expected Test Changes

- All tests under `archive/tests_v1/gui_v1_legacy/` already target `main_window.py` & V1 layout; they remain in the archive and are **not** expected to pass in CI.
- No active `tests/gui_v2/*` should import these archived modules after this PR.

To verify:

- Run:

  ```bash
  rg "src\.gui\.main_window" .
  rg "StableNewGUI" .
  rg "src\.gui\.config_panel" .
  rg "src\.gui\.center_panel" .
  rg "src\.gui\.pipeline_controls_panel" .
  ```

- Outside of `archive/` and `tests/legacy/`, there should be **no matches**.

### 5.2 Runtime Sanity

- `python -m src.main` should:
  - Launch the V2 GUI (`MainWindowV2`).
  - Not attempt to import `src.gui.main_window` or `src.gui.theme`.

---

## 6. Definition of Done

This PR is complete when:

1. All listed V1/hybrid GUI files have been moved to `archive/gui_v1/`.
2. `_tmp_test.py` and `desktop.ini` no longer live at the repo root.
3. A search for V1 GUI modules (e.g., `src.gui.main_window`, `StableNewGUI`, `config_panel`, etc.) shows **no active imports** outside `archive/` and `tests/legacy/`.
4. `python -m src.main` still boots the GUI cleanly using `MainWindowV2`.
5. Existing Phase-1 GUI tests (`tests/gui_v2/test_gui_v2_layout_skeleton.py`, `tests/gui_v2/test_entrypoint_uses_v2_gui.py`, `tests/gui_v2/test_theme_v2.py`) still pass or fail only for known GUI issues unrelated to these archived files.
