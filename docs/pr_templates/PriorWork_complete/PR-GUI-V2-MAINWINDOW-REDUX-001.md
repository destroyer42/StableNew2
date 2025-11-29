
# PR-GUI-V2-MAINWINDOW-REDUX-001  
**Title:** StableNewGUI main_window.py redux (structure, not visuals)  

---

## 1. Intent & Scope

This PR is a **structural refactor** of `src/gui/main_window.py` for the V2 architecture.  
The goal is to make `StableNewGUI` smaller, clearer, and more maintainable **without changing user‑visible behavior** or any pipeline semantics.

This PR:

- Keeps the **existing V2 layout and panels** (PipelinePanelV2, RandomizerPanelV2, advanced stage cards, StatusBarV2, SidebarPanelV2, PreviewPanelV2) exactly as they are visually.
- Keeps all **adapters**, **stage sequencer**, **learning hooks**, and **AI settings generator** behavior unchanged.
- Focuses purely on **responsibility separation, grouping, and readability** inside `main_window.py` plus wiring into the existing `app_layout_v2` / `panels_v2` stack.

No behavior changes are allowed except where explicitly called out as **minor internal cleanup** (e.g., dead code removal, log message clarification) and covered by tests.

---

## 2. Current Context (What You Can Rely On)

Assume the repo state is the authoritative snapshot with the following in place:

- **V2 panels + layout:**
  - `src/gui/pipeline_panel_v2.py` (with advanced stage cards)
  - `src/gui/advanced_txt2img_stage_card_v2.py`
  - `src/gui/advanced_img2img_stage_card_v2.py`
  - `src/gui/advanced_upscale_stage_card_v2.py`
  - `src/gui/randomizer_panel_v2.py` (enhanced UX, risk banner, preview list)
  - `src/gui/preview_panel_v2.py`
  - `src/gui/sidebar_panel_v2.py`
  - `src/gui/status_bar_v2.py`
  - `src/gui/app_layout_v2.py` (AppLayoutV2 which composes panels and attaches run button)
  - `src/gui/panels_v2/__init__.py` re-exports these.

- **Adapters & controllers:**
  - `src/gui_v2/pipeline_adapter_v2.py`
  - `src/gui_v2/randomizer_adapter_v2.py`
  - `src/gui_v2/status_adapter_v2.py`
  - `src/gui_v2/learning_adapter_v2.py`
  - `src/learning/*` and `src/learning_v2/*` foundations (learning records, execution, metadata, feedback).
  - `src/controller/pipeline_controller.py`
  - `src/controller/learning_execution_controller.py`
  - `src/controller/settings_suggestion_controller.py`
  - `src/ai/settings_generator_*` contracts and stubs.

- **Pipeline:**
  - `src/pipeline/stage_sequencer.py` (StageType includes TXT2IMG, IMG2IMG, ADETAILER, UPSCALE).
  - `src/pipeline/pipeline_runner.py` (returns PipelineRunResult, emits learning metadata/hooks).
  - `src/pipeline/__init__.py` exporting sequencer types.
  - `src/pipeline/executor.py` has **not yet been changed for stage events**; those are staged in a separate PR (executor stage-events).

- **Tests:**
  - GUI v2 tests under `tests/gui_v2/` (layout, stage cards, validation, randomizer UX, status, AI button guards).
  - Learning/learning_v2 tests.
  - Pipeline IO contracts, stage sequencer, and runner/controller tests.
  - Safety tests guaranteeing no Tk imports in AI/learning/adapter layers.
  - Two expected XFAILs for upscale hang diagnostics remain until the executor stage-event PR is applied.

Treat all of the above as **fixed contracts** for this PR.

---

## 3. High-Level Goals for This PR

1. **Shrink `StableNewGUI`** into clearly separated concerns:
   - Window/bootstrap and lifecycle.
   - Layout and panel composition (delegated to `AppLayoutV2`).
   - Controller wiring (pipeline, learning, AI settings generator).
   - Status/progress/ETA wiring.
   - Randomizer wiring.
   - Learning hooks / AI-settings hooks.

2. **Codify an internal “MVC-ish” split:**
   - `StableNewGUI` acts as the view + thin orchestration shell.
   - Adapters + controllers handle “model/controller” work.
   - `AppLayoutV2` is the home for layout composition, not `StableNewGUI`.

3. **Make future GUI work easier:**
   - New panels/features can be added by touching predictable, smaller sections (or modules), **not** the giant monolith.
   - Future PRs for the editor, preset manager, and advanced learning UIs should have obvious extension points.

---

## 4. Allowed Files to Modify

You MAY edit:

- `src/gui/main_window.py`
- `src/gui/app_layout_v2.py`
- `src/gui/panels_v2/__init__.py`
- `docs/ROADMAP_v2.md`
- `docs/CHANGELOG.md`
- GUI v2 tests in `tests/gui_v2/` as needed to reflect moved methods/imports, **without** loosening assertions.

You may also add small helper modules under:

- `src/gui/` (for GUI-only helpers, if strictly necessary)
- `src/gui/panels_v2/` (for minor panel wiring helpers, not full re-implementations)

You MUST NOT:

- Change behavior in `src/pipeline/*` or `src/controller/*` in this PR.
- Change `src/learning*` or `src/ai*` modules.
- Change legacy GUI v1 files under `tests/gui_v1_legacy/` or any legacy GUI modules.

If you feel something outside this list must change, stop and leave a note in the PR body instead of editing it.

---

## 5. Concrete Refactor Plan

Implement the following **in order**.

### 5.1. Introduce internal sections in StableNewGUI

Inside `src/gui/main_window.py`, reorganize `StableNewGUI` methods into logical sections:

- Section 1: constructor and core fields  
  Initialize only simple flags, references, and store provided collaborators.

- Section 2: lifecycle helpers  
  Examples: startup, shutdown, “on close”, window geometry persistence, menu/menubar wiring.

- Section 3: layout and panels  
  All panel creation and layout **must** defer to `AppLayoutV2`.  
  `StableNewGUI` should no longer individually assemble all panels.

- Section 4: controller wiring  
  PipelineController, learning execution controller, AI settings controller, etc.

- Section 5: callbacks and event handlers  
  Run button handler, stop/cancel handler, config-changed callbacks, validation triggers, AI settings trigger.

- Section 6: progress/status hooks  
  Progress callbacks, ETA updates, status bar transitions.

- Section 7: randomizer and variant plan wiring  
  Interaction with randomizer panel V2 and its adapter.

- Section 8: learning / telemetry hooks  
  Hooks that connect to learning record/metadata / learning execution.

You do **not** need to name the regions explicitly in the code comments, but ensure logically grouped methods are contiguous and easy to navigate.

No logic changes are allowed in this step beyond moving code around and updating references.

---

### 5.2. Delegate layout to AppLayoutV2

Ensure `AppLayoutV2` is the **sole owner** of V2 layout composition:

- It should receive:
  - the `StableNewGUI` instance (for wiring events),
  - the root window/frame,
  - the panel classes (PipelinePanelV2, RandomizerPanelV2, SidebarPanelV2, PreviewPanelV2, StatusBarV2),
  - plus any additional configuration needed.

- It should:
  - Instantiate all V2 panels.
  - Attach them to the main frames.
  - Expose final panel instances back on `StableNewGUI` via attributes (e.g. `self.pipeline_panel_v2`, `self.randomizer_panel_v2`, etc.).
  - Wire the Run button reference so tests can still access `self.run_button`.

`StableNewGUI` should **not** manually grid/place individual V2 panels any more. It should call a single method on `AppLayoutV2` (for example: `AppLayoutV2(self).build(self.root)` or a comparable pattern) and then rely on the provided attributes.

Make sure existing GUI V2 tests that rely on:

- `StableNewGUI().pipeline_panel_v2`
- `run_button`
- status bar attributes

still pass.

---

### 5.3. Extract controller wiring into small helpers

Still inside `main_window.py`, create private helper methods such as (names can vary, but keep the intent):

- `_create_controllers()`
- `_wire_pipeline_callbacks()`
- `_wire_learning_execution_callbacks()`
- `_wire_ai_settings_callbacks()`
- `_wire_randomizer_callbacks()`

These should:

- Construct the relevant controllers (or retrieve them) using the existing configuration.
- Register callbacks with adapters/panels and the controller instances.
- Not change any observable behavior (no new log messages that tests depend on, no changed exception types).

The public `StableNewGUI` constructor should become a **high-level script**:

- initialize state
- build UI
- delegate to layout helper
- create controllers
- wire callbacks
- perform initial validation/status refresh

---

### 5.4. Clarify run/stop lifecycle (no behavior change)

Refactor only for clarity:

- Ensure the path from:
  - clicking “Run Full Pipeline” → validation → building effective config → building stage plan → invoking controller → wiring progress/status
  is readable and uses intermediate private helpers.

- Ensure the path from:
  - clicking “Stop/Cancel” → signaling the controller → updating UI state → status transitions
  is also clearly grouped.

Do **not** change any of the existing validation rules, state names, or event sequences. This PR is only allowed to:

- rename private helpers for clarity,
- group existing behavior,
- remove obviously dead/unreachable code.

Anything behavioral must be caught by existing tests; if tests start failing due to logic differences, back out the behavioral change.

---

### 5.5. Update docs: ROADMAP_v2 and CHANGELOG

Update:

- `docs/ROADMAP_v2.md`
  - Note that the main-window monolith has been partially decomposed.
  - Update or add a bullet under the GUI V2 section:  
    “StableNewGUI now delegates layout/composition to AppLayoutV2 and groups controller/adapter wiring for easier future work (editor, presets, AI, learning UIs).”

- `docs/CHANGELOG.md`
  - Add an entry under the latest section for:
    - Structural `main_window.py` refactor
    - No user-visible UI changes
    - All adapters and controllers unchanged.

Keep the style consistent with existing entries.

---

## 6. Tests & Validation

You MUST run at least:

- `pytest tests/gui_v2 -v`
- `pytest tests/safety -v`
- `pytest tests/pipeline -v`
- `pytest tests/learning -v`
- `pytest tests/learning_v2 -v`
- `pytest -v`

Expected known outcomes:

- GUI V2 suite: may have 1–2 pre-existing Tk skips depending on environment (do not introduce new ones).
- Pipeline tests: two XFAILs in `tests/pipeline/test_upscale_hang_diag.py` remain as-is (related to executor stage events).
- Safety tests: must remain green (no new Tk imports in adapters/learning/AI layers).

If any regression appears outside of the known XFAILs/skips, fix it or revert the change that caused it.

---

## 7. Acceptance Criteria

This PR is complete when:

1. `StableNewGUI` is **materially smaller and easier to read**, with clear sections and helper methods.
2. All V2 panels are fully composed through `AppLayoutV2`; `main_window.py` no longer owns low-level layout details.
3. Controller/adapter wiring is grouped into small helpers with no observable behavior change.
4. All existing tests (except the two known XFAILs and existing Tk skips) pass.
5. ROADMAP_v2 and CHANGELOG are updated to reflect this structural refactor.
6. No new dependencies are introduced for non-GUI layers; GUI V2 remains layered on top of adapters/controllers, not vice versa.

---

## 8. Codex Instruction Block (Copy/Paste into Codex)

Use the following instructions when you hand this PR to Codex (ChatGPT Codex 5.1 max or equivalent). Paste this **as-is** into the Codex chat before asking it to implement the PR.

PR instructions for Codex:

You are working on the StableNew repo, using the current authoritative snapshot (including GUI V2 panels, adapters, stage sequencer, learning, and AI settings groundwork). Implement the PR “PR-GUI-V2-MAINWINDOW-REDUX-001” exactly as described in the PR markdown file I provide. Do not speculate or diverge from the specification.

Key rules:
- Do NOT change behavior in src/pipeline/* or src/controller/* in this PR.
- Do NOT modify legacy GUI V1 files or tests.
- Your primary focus is refactoring src/gui/main_window.py so StableNewGUI is smaller and clearly organized into lifecycle, layout, controller wiring, callbacks, and progress/randomizer/learning hooks.
- Defer layout to AppLayoutV2: it should own the composition of V2 panels and run button wiring. StableNewGUI should call a single helper to build the layout and then use the exposed panel attributes.
- Extract controller wiring into small, private helper methods in main_window.py (pipeline, learning, AI settings, randomizer).
- Do not change validation logic, run/stop lifecycle semantics, or adapter/controller behavior.
- Keep the existing V2 tests passing; do not loosen assertions. Update imports/paths where necessary to reflect the new structure.
- Update docs/ROADMAP_v2.md and docs/CHANGELOG.md to describe the structural refactor. No marketing copy, just factual entries.

After implementing:
- Run: pytest tests/gui_v2 -v
- Run: pytest tests/safety -v
- Run: pytest tests/pipeline -v
- Run: pytest tests/learning -v
- Run: pytest tests/learning_v2 -v
- Run: pytest -v

If any test fails (other than the pre-existing Tk skips and the two XFAILs in tests/pipeline/test_upscale_hang_diag.py), fix the cause inside the allowed file set or revert the change. Summarize exactly what you changed and which tests you ran in your final message.
