# PR-GUI-V2-ADAPTERS-001 – GUI v2 Adapters Consolidation

## 1. Title

GUI v2 adapters consolidation for pipeline, randomizer, status, and learning hooks

## 2. Summary

This PR extracts and formalizes the GUI v2 adapter layer between Tk-based widgets and the controller/pipeline/learning stack. It consolidates the existing ad‑hoc glue logic scattered in `StableNewGUI` and early v2 modules into a small set of explicit, testable, Tk‑free adapters.

The intent is to:
- Keep the GUI layer purely about layout, widgets, and user interactions.
- Make pipeline, randomizer, and learning wiring deterministic and easier to test.
- Prepare for future distributed/learning features without re‑entangling Tk with the pipeline.

No functional behavior change is expected from a user perspective. The PR only refactors data‑passing and callback wiring into a more explicit adapter layer, backed by tests.

## 3. Problem Statement

Current v2 work has improved structure (stage cards, StatusBarV2, RandomizerPanelV2, learning stubs, learning record hooks), but some responsibilities are still blurred:

- `StableNewGUI` directly merges configs, handles randomizer plans, and knows too much about controller/pipeline internals.
- Randomizer integration is split between `randomizer_panel_v2`, `randomizer_adapter`, and `main_window` without a single well‑defined contract.
- Learning hooks (learning runner, learning records) exist at the pipeline/controller level but have no clear GUI‑facing integration pattern yet.
- Status/progress/ETA wiring is correctly marshaled through `root.after`, but the logic still lives inside the main window instead of an explicit adapter that a headless test can exercise.

This makes it harder to:
- Add new flows (e.g., “learning runs”, “one‑click actions”) without touching Tk glue everywhere.
- Reuse randomizer and learning behaviors from non‑GUI surfaces (CLI, future API).
- Reason about which layer owns what, relative to `ARCHITECTURE_v2`.

## 4. Goals

1. Introduce a **clear GUI v2 adapter layer** that owns:
   - Pipeline run invocation and config preparation (txt2img/img2img/upscale stage cards → controller/pipeline runner).
   - Randomizer plan evaluation and variant preview counts (GUI panel → randomizer+planner).
   - Status/progress/ETA updates (controller callbacks → StatusBarV2).
   - Learning hooks scaffolding (learning runner + record hooks), but **without** fully enabling user‑visible learning behavior yet.

2. Ensure adapters are:
   - **Tk‑free** (pure Python, no direct widget imports).
   - **Config‑centric** (operate on dicts/dataclasses instead of widgets).
   - **Tested in isolation** with deterministic, pure tests (no Tk, no network).

3. Reduce responsibilities of `StableNewGUI`:
   - GUI constructs panels and passes simple callback handles & config snapshots into adapters.
   - Adapters call controller/runner methods and feed back status/records to the GUI through small interfaces.

4. Preserve all existing v2 tests:
   - `tests/gui_v2` remains green after the refactor.
   - Safety tests continue to confirm that adapters are Tk‑free and do not import GUI modules.

## 5. Non‑Goals

- No visible UX changes (layout, labels, colors, or widget positions).
- No new one‑click actions or learning workflows yet.
- No changes to the pipeline core semantics (how SD WebUI is called, how images are generated).
- No changes to legacy GUI v1 tests or files beyond what has already been migrated/isolated.
- No distributed pipeline / multi‑node execution changes.

## 6. Allowed Files

Adapters & GUI V2:

- `src/gui/main_window.py` (only adapter wiring / call‑site updates; no major layout changes).
- `src/gui/pipeline_panel_v2.py`
- `src/gui/txt2img_stage_card.py`
- `src/gui/img2img_stage_card.py`
- `src/gui/upscale_stage_card.py`
- `src/gui/randomizer_panel_v2.py`
- `src/gui/status_bar_v2.py`

New adapter modules (Tk‑free):

- `src/gui_v2/adapters/__init__.py` (new)
- `src/gui_v2/adapters/pipeline_adapter_v2.py` (new)
- `src/gui_v2/adapters/randomizer_adapter_v2.py` (may alias/extend existing `randomizer_adapter` if present)
- `src/gui_v2/adapters/status_adapter_v2.py` (new)
- `src/gui_v2/adapters/learning_adapter_v2.py` (new, thin wrapper over existing `src/learning` stubs)

Controller / learning surface (very light touch, if necessary for adapter hooks):

- `src/controller/pipeline_controller.py`
- `src/learning/learning_runner.py`
- `src/learning/learning_record.py`
- `src/learning/learning_adapter.py`

Tests:

- `tests/gui_v2/conftest.py`
- `tests/gui_v2/test_gui_v2_pipeline_adapter.py` (new)
- `tests/gui_v2/test_gui_v2_randomizer_adapter_integration.py` (new or extended from existing)
- `tests/gui_v2/test_gui_v2_status_adapter_progress_eta.py` (new)
- `tests/learning/test_learning_adapter_stub.py` (may extend)
- `tests/safety/test_no_gui_imports_in_utils.py`
- `tests/safety/test_randomizer_import_isolation.py`
- `tests/safety/test_gui_v2_adapters_no_tk_imports.py` (new)

## 7. Forbidden Files

- Any pipeline core beyond minor adapter hooks:
  - `src/pipeline/pipeline_runner.py` (except for small, explicit adapter hook points if absolutely needed).
- Legacy GUI v1 code:
  - `src/gui/config_panel.py`
  - Any `tests/gui` (v1 legacy tests).
- API and logger layers:
  - `src/api/*`
  - `src/utils/structured_logger.py`

If an edit outside the allowed list is truly necessary, stop and request an updated PR design before proceeding.

## 8. Step‑by‑Step Implementation Plan

1. **Introduce adapter package**
   - Create `src/gui_v2/adapters/__init__.py` as a simple namespace package.
   - Ensure there are **no Tk imports** in this package.

2. **PipelineAdapterV2**
   - New module: `src/gui_v2/adapters/pipeline_adapter_v2.py`.
   - Define a small dataclass or dict protocol (documented in code) that represents:
     - The base pipeline config (dict or existing config dataclass).
     - Per‑stage overrides from the v2 stage cards.
   - Provide a function/class method such as `build_effective_config(base_config, txt2img_overrides, img2img_overrides, upscale_overrides)` that returns the merged config dict.
   - Provide a method to invoke the controller’s run method:
     - Accepts a controller instance and effective config.
     - Returns whatever the controller currently returns, without altering semantics.
   - This module must be Tk‑free and safe to import in isolation.

3. **RandomizerAdapterV2**
   - If `src/gui_v2/randomizer_adapter.py` already exists, refactor logic into `RandomizerAdapterV2` under `src/gui_v2/adapters/randomizer_adapter_v2.py` while keeping legacy imports/backwards compatibility through a thin shim in the old location.
   - Responsibilities:
     - Accept normalized randomizer options from `RandomizerPanelV2` (mode, fanout, matrix dict, etc.).
     - Call into the existing randomizer planner (`build_variant_plan`, `apply_variant_to_config`) using the current base config.
     - Return a small `RandomizerPlanResult` structure (plan + per‑variant configs, or similar) that is already covered by tests in prior PRs.
   - Ensure import safety:
     - No Tk imports, no GUI imports, no direct access to widgets.

4. **StatusAdapterV2**
   - New module: `src/gui_v2/adapters/status_adapter_v2.py`.
   - Wrap `StatusBarV2` so controller callbacks can be wired without the controller knowing about Tk.
   - Provide methods such as:
     - `on_state_change(new_state)` → maps lifecycle states to `StatusBarV2` methods.
     - `on_progress(progress_dict)` → maps numeric progress to progressbar/ETA.
   - Adapter should be as thin as possible, but contain the mapping logic that currently lives in `StableNewGUI`.

5. **LearningAdapterV2**
   - New module: `src/gui_v2/adapters/learning_adapter_v2.py`.
   - Bridge between:
     - GUI “learning run” intent (later PRs) and
     - The existing learning stack (`learning_runner`, `learning_record`, `learning_plan`, etc.).
   - For this PR, only implement **non‑GUI** helper functions and test them:
     - Example: `create_learning_context(base_config, one_click_action, run_metadata)` returning a structure that the learning runner/record can understand.
   - Do **not** yet wire any visible GUI buttons or flows into learning behavior (that belongs to later PRs).

6. **Wire adapters into StableNewGUI**
   - In `src/gui/main_window.py`, replace direct config merging and randomizer integration with calls to the adapter modules.
   - The GUI should:
     - Collect base config + stage overrides from the v2 panels.
     - Call into `PipelineAdapterV2` to compute effective config.
     - Call into `RandomizerAdapterV2` to compute variant plans when needed.
     - Wire the controller’s progress/state callbacks through `StatusAdapterV2` methods.
   - Keep layout and widget creation logic as‑is; only move logic that “thinks” about pipeline or randomizer semantics into the adapters.

7. **Safety & import isolation**
   - Add/extend `tests/safety/test_gui_v2_adapters_no_tk_imports.py` to assert:
     - Importing each adapter module does **not** pull in `tkinter`, `ttk`, or `src.gui` modules.
   - Ensure existing safety tests remain green.

8. **Tests for adapters**
   - Add `tests/gui_v2/test_gui_v2_pipeline_adapter.py`:
     - Use dummy controllers and configs to validate that the adapter builds the expected effective config and calls the controller once.
   - Extend or add `tests/gui_v2/test_gui_v2_randomizer_adapter_integration.py`:
     - Confirm plan lengths match UI‑reported variant counts.
     - Confirm first variant config matches the previous v2 behavior.
   - Add `tests/gui_v2/test_gui_v2_status_adapter_progress_eta.py`:
     - Inject fake callbacks and validate the mapping from controller‑style events to StatusBarV2 method calls.

9. **Cleanup & review**
   - Remove any now‑dead helper methods from `StableNewGUI` that only duplicate adapter logic.
   - Ensure that docstrings and comments reference the new adapter locations instead of main_window glue.

## 9. Required Tests (Failing First)

Before implementing the adapters, add/extend tests that will **fail** against the current codebase:

1. `tests/gui_v2/test_gui_v2_pipeline_adapter.py`
   - Asserts that `PipelineAdapterV2.build_effective_config(...)` returns a merged config with stage overrides applied.
   - Asserts that calling the adapter’s run helper invokes a dummy controller’s run method exactly once with the merged config.

2. `tests/gui_v2/test_gui_v2_randomizer_adapter_integration.py`
   - Asserts that variant counts from `RandomizerAdapterV2` match the matrix/fanout UI expectations.
   - Asserts that the first variant config matches the previous v2 randomizer integration behavior.

3. `tests/gui_v2/test_gui_v2_status_adapter_progress_eta.py`
   - Asserts that simulated lifecycle and progress callbacks are mapped to the correct StatusBarV2 methods.

4. `tests/safety/test_gui_v2_adapters_no_tk_imports.py`
   - Fails if any adapter module imports `tkinter`, `ttk`, or `src.gui.*` directly.

Run:
- `pytest tests/gui_v2 -v`
- `pytest tests/safety -v`

Expect RED initially until the adapters are implemented and wired.

## 10. Acceptance Criteria

- All new and existing v2 GUI tests pass:
  - `pytest tests/gui_v2 -v`
- All safety tests remain green:
  - `pytest tests/safety -v`
- `pytest -v` passes in the current environment (aside from the known Tk/Tcl skip, if any).
- `StableNewGUI` no longer directly:
  - Merges pipeline configs (beyond simple collection from panels).
  - Calls randomizer/planner functions directly.
  - Implements detailed status/ETA mapping logic.
- Adapter modules are import‑safe and Tk‑free.

## 11. Rollback Plan

- Revert the adapter modules and `StableNewGUI` changes to the previous commit.
- Restore the earlier randomizer/status wiring (already covered by v2 tests).
- Because this PR is intended as a structural refactor without behavior change, rollback risk is low and localized to GUI v2.

## 12. Codex Execution Constraints

- Do **not** modify files outside the **Allowed Files** list without explicit approval.
- Do **not** change behavior visible to end‑users (no text/label changes, no new buttons).
- Keep diffs small and localized; avoid unrelated “cleanup” refactors.
- Preserve all existing imports and keep new ones minimal.
- When adding new modules, keep them Tk‑free and test‑backed.
- After each logical step, run the targeted tests and include the full output in your response.

## 13. Smoke Test Checklist (Post‑Merge)

After this PR is merged, perform the following manual checks:

1. Run StableNew via `python -m src.main` and confirm:
   - GUI launches without errors.
   - Pipeline config panel still shows current stage cards and fields.
   - Randomizer panel behaves as before (variant count label updates as you change matrix/fanout).
   - Status bar reflects running/idle/error states and progress/ETA as before.

2. Trigger a pipeline run (with a simple prompt pack & small settings):
   - Confirm the run completes successfully.
   - Confirm logs show expected randomizer/plan behavior (if used).

3. Confirm no new Tk runtime errors or tracebacks appear during startup or shutdown.

---

## Codex Chat Instructions for PR-GUI-V2-ADAPTERS-001

Paste the following text into Codex Chat for this PR:

PR NAME: PR-GUI-V2-ADAPTERS-001 – GUI v2 Adapters Consolidation

ROLE: You are acting as the Implementer (Codex) for the StableNew project. Follow the PR design exactly and do not modify files outside the allowed list. Do not introduce visual/UX changes. Keep the GUI layer focused on widgets/layout and move cross‑cutting logic into Tk‑free adapters.

CURRENT REPO STATE: Use the existing StableNew repo on my machine as truth, including the latest v2 GUI work (stage cards, StatusBarV2, RandomizerPanelV2) and learning hooks (learning_* modules, learning_record and pipeline_runner/controller integration). Do not assume older branches; work from HEAD of my current MoreSafe branch.

OBJECTIVE:
- Introduce the `src/gui_v2/adapters` package.
- Implement PipelineAdapterV2, RandomizerAdapterV2, StatusAdapterV2, and LearningAdapterV2 as Tk‑free helpers.
- Wire `StableNewGUI` to use these adapters instead of ad‑hoc logic.
- Keep all existing v2 behavior identical.

HARD CONSTRAINTS:
- Do NOT change behavior visible to the user (no new buttons, no layout changes, no text changes).
- Do NOT modify legacy GUI v1 tests or modules (under tests/gui and older config_panel).
- Do NOT modify pipeline core semantics beyond the minimal adapter hook points, and ask before touching `src/pipeline/pipeline_runner.py`.
- Adapters MUST NOT import `tkinter`, `ttk`, or `src.gui.*` directly.
- Follow TDD: add/extend tests first so they fail, then implement the adapters until tests pass.

IMPLEMENTATION STEPS (HIGH LEVEL):
1) Create `src/gui_v2/adapters/__init__.py` as an empty namespace module.
2) Add `src/gui_v2/adapters/pipeline_adapter_v2.py` with a helper that:
   - Receives base config and per‑stage overrides (txt2img/img2img/upscale).
   - Produces an effective config identical to what StableNewGUI currently uses.
   - Provides a small helper to call the controller’s run method.
3) Add `src/gui_v2/adapters/randomizer_adapter_v2.py`:
   - Move/refine logic from the existing randomizer adapter so this module owns variant planning given normalized options.
   - Reuse `build_variant_plan` and `apply_variant_to_config` exactly as currently wired.
4) Add `src/gui_v2/adapters/status_adapter_v2.py`:
   - Wrap StatusBarV2 and expose methods (e.g., on_state_change, on_progress) to translate controller events into StatusBarV2 calls.
5) Add `src/gui_v2/adapters/learning_adapter_v2.py`:
   - Wrap existing learning stubs/records so a future GUI flow can ask for a learning context without knowing implementation details.
   - Do NOT wire new GUI buttons or flows in this PR.
6) Update `src/gui/main_window.py`:
   - Replace direct config merging/randomizer/status logic with calls into the adapters, preserving behavior.
   - Keep the visual layout intact.
7) Add/extend tests:
   - `tests/gui_v2/test_gui_v2_pipeline_adapter.py`
   - `tests/gui_v2/test_gui_v2_randomizer_adapter_integration.py`
   - `tests/gui_v2/test_gui_v2_status_adapter_progress_eta.py`
   - `tests/safety/test_gui_v2_adapters_no_tk_imports.py`

TEST COMMANDS TO RUN AND REPORT:
- pytest tests/gui_v2 -v
- pytest tests/safety -v
- pytest -v

When you’re done, summarize:
- Files touched (with +/- line counts).
- Any behavior differences discovered and how you ensured none were introduced.
- Full pytest outputs for the commands above.
