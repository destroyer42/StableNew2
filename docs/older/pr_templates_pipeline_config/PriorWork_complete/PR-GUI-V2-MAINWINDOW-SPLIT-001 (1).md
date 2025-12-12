# PR-GUI-V2-MAINWINDOW-SPLIT-001: StableNewGUI Shell & Layout Extraction (V2-first)

## 1. Title

**PR-GUI-V2-MAINWINDOW-SPLIT-001: StableNewGUI Shell & Layout Extraction (V2-first)**

---

## 2. Summary

This PR is a **targeted refactor** of `src/gui/main_window.py` to start breaking up the monolithic `StableNewGUI` implementation into **smaller, well‑named modules**, while **preserving existing behavior and tests**.

We will:

- Introduce a **V2 application shell + layout module** that owns the new panel‑based GUI composition.
- Have `StableNewGUI` **delegate layout construction and panel wiring** to this module instead of inlining everything in `main_window.py`.
- Keep all public `StableNewGUI` APIs, wiring to the controller, and V2 tests **functionally unchanged**.
- Leave **V1 legacy GUI tests** and any V1 code untouched (they remain isolated under `tests/gui_v1_legacy/` and are still excluded from default collection).

This is explicitly a **structure‑only** change that **prepares** main_window for later UX and behavior work. It must not introduce new UX flows or alter pipeline execution.

---


## 3. Context & Motivation

### 3.1 Current state

- `src/gui/main_window.py` currently contains:
  - The `StableNewGUI` class (Tk root orchestration, menus, layout, callbacks, logging hooks, etc.).
  - V2 panel wiring (`PipelinePanelV2`, `RandomizerPanelV2`, `PreviewPanelV2`, `SidebarPanelV2`, `StatusBarV2`).
  - A mix of **V2‑era helper methods** (`_apply_pipeline_panel_overrides`, `_wire_progress_callbacks`, randomizer wiring, V2 layout helpers) and older V1‑style UI helpers.

- V2 tests already rely on:
  - `StableNewGUI` as the **main entrypoint**.
  - Exposed attributes like:
    - `sidebar_panel_v2`
    - `pipeline_panel_v2`
    - `randomizer_panel_v2`
    - `preview_panel_v2`
    - `status_bar_v2`
    - `run_button`
  - The fact that **V2 layout is panel‑oriented**, but they do *not* care where the layout code lives internally.

- We have **begun the V1 → V2 migration**:
  - Legacy GUI tests were moved to `tests/gui_v1_legacy/` and excluded via `norecursedirs`.
  - New V2 layout, pipeline, randomizer, status, learning, and adapter tests now define the **forward path**.

### 3.2 Why this PR now

- `main_window.py` is still the **heaviest** file in the GUI and mixes:
  - App lifecycle and root/window orchestration.
  - Layout and composition.
  - Controller and pipeline wiring.
  - Validation, progress/ETA, and learning hooks.

- Continuing to add V2 features without first separating concerns will:
  - Make it harder to reason about the GUI.
  - Increase the likelihood of regressions.
  - Make future V2 UX work (like the center‑panel controls, learning runs, AI suggestions) more fragile.

This PR is the **first structural slice**:

- Extract a focused **“App Layout V2”** helper module.
- Keep `StableNewGUI` as a **thin orchestrator** that:
  - Owns the Tk root and high‑level lifecycle.
  - Delegates panel creation and layout to the new helper.
  - Continues to expose the same V2 attributes that tests depend on.

---

## 4. Goals and Non‑Goals

### 4.1 Goals

1. **Split layout responsibilities** out of `main_window.py` into a new module:
   - A dedicated **V2 layout helper** that:
     - Knows how to build the shell (root frames, paned windows, sidebar, center, right panel, status bar).
     - Instantiates and returns the V2 panels.
     - Registers V2 panels onto `StableNewGUI` so existing tests still see the same attributes.

2. **Preserve StableNewGUI’s public contract**:
   - Constructor signature remains unchanged.
   - Attributes used by tests (`run_button`, `status_bar_v2`, `pipeline_panel_v2`, etc.) still exist and behave the same.
   - Existing controller/pipeline wiring remains in `main_window.py` (only layout/panel creation moves).

3. **Keep V1 GUI isolated**:
   - No changes to `tests/gui_v1_legacy/` or any V1‑specific modules.
   - No attempt to re‑enable V1 tests.

4. **Keep behavior identical**:
   - No visual redesign, no new widgets.
   - No pipeline behavior changes.
   - All current V2 tests must keep passing without modification, except for import path tweaks if they reference moved symbols.

### 4.2 Non‑Goals

- No changes to:
  - `src/pipeline/*`
  - `src/controller/*` (beyond trivial import updates if needed).
  - `src/learning/*`
  - AI settings generator.
- No new V2 panels or UX features.
- No attempt to shrink or re‑design the sidebar or central panel controls.
- No performance tuning.

---

## 5. Scope and Allowed Files

### 5.1 Allowed to change

- `src/gui/main_window.py`
- New file(s) under `src/gui/`:
  - `src/gui/app_layout_v2.py` (primary new module; name is fixed for this PR).
- V2 GUI tests for imports and layout assertions:
  - `tests/gui_v2/conftest.py`
  - `tests/gui_v2/test_gui_v2_layout_skeleton.py`
  - `tests/gui_v2/test_gui_v2_startup.py`
  - `tests/gui_v2/test_gui_v2_pipeline_button_wiring.py`
  - Any other `tests/gui_v2/*` that needs **import path** adjustments only.
- Documentation:
  - `docs/history/StableNew_history_summary.md`
  - `docs/CHANGELOG.md`
  - `docs/ROADMAP_v2.md`
  - `docs/pr_templates/PR-GUI-V2-MAINWINDOW-SPLIT-001.md` (this file).

### 5.2 Explicitly out of scope (must not be changed)

- `src/pipeline/executor.py`
- Any files under `tests/gui_v1_legacy/`
- Any safety tests not mentioned above.
- `pyproject.toml` test configuration (no changes to `testpaths`, `norecursedirs` for this PR).
- Randomizer/learning adapters and contracts.

If any change outside the **allowed list** looks necessary, stop and update the PR spec before proceeding.

---

## 6. Design Overview

### 6.1 New AppLayoutV2 helper

Introduce `src/gui/app_layout_v2.py` with a single public entrypoint:

- A class `AppLayoutV2` (or similar) that:

  - Is initialized with:
    - A reference to the `StableNewGUI` instance (the “owner”).
    - The theme utilities as currently used in `main_window.py`.
  - Exposes a method (name fixed for this PR):
    - `build_layout(root_frame) -> None`  
      - Creates the top‑level layout (paned windows, frames).
      - Instantiates V2 panels.
      - Registers resulting panel objects back on the owner (e.g. `owner.pipeline_panel_v2`, etc.).
      - Associates the `run_button` on the owner, exactly as previously done in `main_window.py`.

The helper:

- Does **not** know about:
  - PipelineRunner, PipelineController.
  - Learning contracts, AI settings generator.
- Only knows about:
  - Tk/Ttk widgets.
  - Theme constants and styles.
  - V2 panel classes (`PipelinePanelV2`, `RandomizerPanelV2`, `PreviewPanelV2`, `SidebarPanelV2`, `StatusBarV2`).

### 6.2 StableNewGUI after the split

`StableNewGUI` stays in `src/gui/main_window.py` and continues to:

- Own the root (Tk) window.
- Own controller/config/learning wiring.
- Own run/stop handlers, validation, progress callbacks, and learning hooks.
- Call into `AppLayoutV2.build_layout` from its `_build_ui` (or equivalent) method to construct the layout.

After this PR:

- `_build_ui` becomes primarily:
  - Root frame creation.
  - Instantiating `AppLayoutV2(self, theme=...)`.
  - Calling `layout.build_layout(root_frame)`.

- All of the **detailed panel composition code** that used to live inside `_build_ui` (and tightly around it) is moved into `AppLayoutV2`.

---

## 7. Detailed Implementation Plan

### 7.1 Preparation

1. Confirm the working baseline:
   - Pull latest main branch with all prior V2 work.
   - Ensure tests are green at baseline:
     - `pytest tests/gui_v2 -v`
     - `pytest tests/learning -v`
     - `pytest tests/learning_v2 -v`
     - `pytest tests/pipeline -v` (with the known XFAILs in `test_upscale_hang_diag.py`)
     - `pytest -v`

2. Open `src/gui/main_window.py` and identify:
   - The block where:
     - The root frame / paned windows are created.
     - Sidebar, center, right, and status bar are composed.
     - The V2 panels are instantiated and attached to `self`.
   - All references to:
     - `sidebar_panel_v2`
     - `pipeline_panel_v2`
     - `randomizer_panel_v2`
     - `preview_panel_v2`
     - `status_bar_v2`
     - `run_button`

These are the segments we will move to `AppLayoutV2`.

### 7.2 Create `src/gui/app_layout_v2.py`

3. Create `src/gui/app_layout_v2.py`:

   - Add a small module docstring explaining:
     - This is the “V2 application layout builder” for StableNewGUI.
     - It is responsible purely for Tk layout and V2 panel assembly.

   - Define `class AppLayoutV2:` with:
     - `__init__(self, owner, theme)` or similar, where:
       - `owner` is the `StableNewGUI` instance.
       - `theme` is whatever the existing main_window currently uses when configuring styles.
     - `build_layout(self, root_frame)` method where:
       - All layout logic that currently lives in `StableNewGUI._build_ui` around panel construction is moved.

4. In `build_layout`:

   - Set up:
     - The main frames / paned windows (mirroring the existing layout).
     - The sidebar region and attach `SidebarPanelV2`, registering it as `owner.sidebar_panel_v2`.
     - The center pipeline region and attach `PipelinePanelV2`, registering it as `owner.pipeline_panel_v2`.
     - The right panel region and attach `RandomizerPanelV2` and `PreviewPanelV2` as appropriate, registering as `owner.randomizer_panel_v2`, `owner.preview_panel_v2`.
     - The status bar at the bottom, registering `owner.status_bar_v2`.
     - Create the primary `Run Full Pipeline` button and register it as `owner.run_button`, wiring its command back to `owner._on_run_full_pipeline_clicked` (or the existing handler).

   - Preserve:
     - Any existing **grid/pack configuration** that V2 tests assert (e.g., that panels are present and correctly attached).
     - Any style names that tests rely on.

### 7.3 Refactor `StableNewGUI` to use AppLayoutV2

5. In `src/gui/main_window.py`:

   - Import the helper:
     - `from src.gui.app_layout_v2 import AppLayoutV2`

   - In `_build_ui` (or equivalent method):

     - Retain:
       - Root and top‑level frame creation.
       - Menu setup.
       - Any pre‑layout state initialization (variables, config_manager, etc.).

     - Replace the inline panel layout code with:

       - Instantiate the layout helper with `self` and the theme utilities.
       - Call `layout.build_layout(root_frame)`.

   - Ensure:
     - All references to `self.sidebar_panel_v2`, `self.pipeline_panel_v2`, etc., still work.
     - Controller and validation wire‑ups that reference these attributes remain unchanged.

6. Remove now‑redundant layout code from `main_window.py` after it has been fully moved to `app_layout_v2.py`, but do not change:

   - Any handlers or callbacks.
   - Any logic related to:
     - Validation.
     - Progress/ETA.
     - Learning or AI settings generator hooks.
     - Pipeline execution and controller interactions.

### 7.4 Update tests (imports only)

7. Review `tests/gui_v2/*` for any direct imports from `main_window.py` that:

   - Assume layout helper functions live there.
   - If any test imports layout‑specific helpers that you moved to `AppLayoutV2`, update the import path to `src.gui.app_layout_v2` instead.

8. Do **not** change test assertions around:

   - The existence and type of `StableNewGUI`.
   - The presence of panel attributes on the instance.
   - The behavior of the Run button or randomizer/status wiring.

---

## 8. Testing Plan

### 8.1 Target test commands

Run at least the following:

1. GUI V2 suite:

   - `pytest tests/gui_v2 -v`

2. Learning & AI suites (regression check only, no expected changes):

   - `pytest tests/learning -v`
   - `pytest tests/learning_v2 -v`
   - `pytest tests/ai_v2 -v`

3. Pipeline suite (regression check only, no expected changes):

   - `pytest tests/pipeline -v`  
     - Two tests in `tests/pipeline/test_upscale_hang_diag.py` remain `xfail` by design.

4. Full suite:

   - `pytest -v`

### 8.2 Expectations

- All tests that were previously passing must remain passing.
- The only expected non‑passing outcomes are:
  - The known `xfail` entries in `tests/pipeline/test_upscale_hang_diag.py` (reason unchanged).
  - Any pre‑existing Tk/Tcl skips in GUI V2 tests when Tk is not fully available.

If any previously passing test fails due to this refactor, update the PR spec before making behavioral changes.

---

## 9. Risk, Rollback, and Safety

### 9.1 Risks

- Inadvertently changing layout or widget wiring when moving code:
  - Panels might not be attached where tests expect them.
  - `run_button` might not be wired to the correct handler.
  - `status_bar_v2` might not receive callbacks correctly if attributes are not registered on the owner.

### 9.2 Mitigations

- Move code **mechanically** (copy → paste → adjust imports) rather than rewriting logic.
- Use the existing V2 tests as a **safety net**:
  - They validate panel presence, Run button behavior, pipeline config roundtrips, progress/ETA wiring, and randomizer integration.
- Keep the diff to:
  - One new module.
  - A focused edit in `main_window.py`.
  - Minor import path adjustments in tests.

### 9.3 Rollback plan

If something goes wrong:

- Revert `src/gui/app_layout_v2.py`.
- Revert changes in:
  - `src/gui/main_window.py`
  - `tests/gui_v2/*` touched by this PR.
- Re‑run:
  - `pytest tests/gui_v2 -v`
  - `pytest -v`

Until the previous green baseline is restored.

---

## 10. Acceptance Criteria

This PR is complete when:

1. `StableNewGUI`:
   - Still constructs without errors.
   - Still exposes:
     - `sidebar_panel_v2`
     - `pipeline_panel_v2`
     - `randomizer_panel_v2`
     - `preview_panel_v2`
     - `status_bar_v2`
     - `run_button`

2. V2 layout and pipeline tests:
   - `pytest tests/gui_v2 -v` are all green (modulo known Tk skips).

3. No new test failures appear in:
   - `pytest tests/learning* -v`
   - `pytest tests/ai_v2 -v`
   - `pytest tests/pipeline -v` other than the known `xfail`s.

4. The new module:
   - `src/gui/app_layout_v2.py` exists.
   - Has a clear docstring and single responsibility (layout & V2 panel assembly).

5. Docs:
   - `docs/CHANGELOG.md` and `docs/ROADMAP_v2.md` are updated with a brief note that the V2 GUI layout is now delegated to `AppLayoutV2`.

---

## 11. CODEX Run Sheet (Step‑by‑Step)

> Use this as the **exact** instruction block for CODEX. Do not improvise beyond these steps without updating this PR file.

1. **Baseline check**
   - Confirm you are on the branch that includes all previous V2 work.
   - Run:
     - `pytest tests/gui_v2 -v`
     - `pytest -v`
   - Ensure tests match the previously known status (GUI V2 green, known XFAILs in pipeline).

2. **Create the layout helper**
   - Add `src/gui/app_layout_v2.py`.
   - Implement `AppLayoutV2` with:
     - `__init__(self, owner, theme)` (or equivalent).
     - `build_layout(self, root_frame)` where you copy the V2 panel layout logic from `StableNewGUI._build_ui`.
   - Ensure this module:
     - Instantiates and attaches `SidebarPanelV2`, `PipelinePanelV2`, `RandomizerPanelV2`, `PreviewPanelV2`, and `StatusBarV2`.
     - Wires the Run button to the existing run handler and exposes it as `owner.run_button`.

3. **Refactor StableNewGUI to use the helper**
   - In `src/gui/main_window.py`:
     - Import `AppLayoutV2`.
     - In `_build_ui`, keep root/menu setup as‑is.
     - Replace inline panel layout + V2 panel instantiation with:
       - Creating `AppLayoutV2(self, theme=...)`.
       - Calling `layout.build_layout(root_frame)`.
   - Do not change:
     - Run/stop handlers.
     - Progress/ETA wiring.
     - Learning/AI hooks.
     - Controller or PipelineRunner interactions.

4. **Adjust tests only if necessary**
   - If any `tests/gui_v2/*` import layout‑specific helpers from `main_window.py` that you moved to `app_layout_v2.py`, update those imports.
   - Do not broaden test coverage in this PR; only keep them compiling and passing.

5. **Run tests**
   - Run:
     - `pytest tests/gui_v2 -v`
     - `pytest -v`
   - Confirm:
     - All V2 GUI tests pass.
     - No new failures in other suites.
     - Only the pre‑existing XFAILs and Tk skips remain.

6. **Update docs**
   - Append a short entry to:
     - `docs/CHANGELOG.md` noting this refactor.
     - `docs/ROADMAP_v2.md` under the V2 GUI section describing that panel layout is now owned by `AppLayoutV2`.

7. **Final verification**
   - Briefly manual‑launch the GUI (if your environment allows) to confirm:
     - Sidebar, pipeline panel, randomizer, preview, and status bar appear as before.
     - The Run button is present and wired.

If any step requires changes outside the allowed scope, stop and annotate the concern in this PR file before proceeding.

