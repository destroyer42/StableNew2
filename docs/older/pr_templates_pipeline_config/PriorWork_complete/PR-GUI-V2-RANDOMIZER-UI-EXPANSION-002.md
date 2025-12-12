# PR-GUI-V2-RANDOMIZER-UI-EXPANSION-002
## Title
GUI V2 Randomizer Panel Expansion (Matrix & Fanout Controls)

## Summary
This PR expands the GUI V2 randomizer panel into a first-class configuration surface for matrix/fanout behavior. It adds user-visible controls for matrix entries, variant mode, and fanout count, plus a live variant-count preview wired through the existing randomizer adapter. Functionality is limited to UI + adapter behavior only; the pipeline still executes a single-variant path per the current architecture, but the wiring ensures that preview and pipeline share the same variant-planning logic.

## Problem Statement
The current V2 randomizer panel is a minimal shell: it exposes only a basic mode selector and a thin bridge into the randomizer adapter. Users cannot:
- Edit matrix entries in a structured way.
- Choose fanout per variant.
- See how many variants will be produced from their matrix configuration.
- Preview (in the GUI) how matrix mode and fanout interact before running.

Without these controls, the randomizer is effectively invisible, and we can’t validate parity between GUI preview and the underlying randomizer planning logic.

## Goals
- Provide a usable RandomizerPanelV2 with:
  - Variant mode dropdown (off, sequential, rotate, expand, etc. – matching randomizer modes).
  - Matrix editor rows for common dimensions (e.g., model, hypernetwork, scheduler, sampler).
  - Fanout count control (integer).
  - Live “total variants” preview that reflects matrix and fanout settings.
- Keep the panel’s state expressed as plain dict structures suitable for randomizer_adapter, with no Tk dependencies in the adapter.
- Extend GUI V2 tests to verify:
  - Roundtrip of randomizer config (load from config, modify, export).
  - Live variant-count preview is based on the same logic that the adapter uses to build plans.
- Preserve safety/architecture constraints:
  - No changes to randomizer core algorithm or pipeline execution behavior.
  - No regression to safety wrappers or GUI isolation rules.

## Non-goals
- No changes to src/utils/randomizer core planning logic (modes, parsing, combo generation).
- No changes to PipelineRunner or actual multi-variant execution; runs still use first-variant semantics only.
- No changes to the learning subsystem (learning plans, learning runner, or feedback packaging).
- No changes to V1/legacy GUI tests under tests/gui_v1_legacy.

## Allowed Files
- src/gui/randomizer_panel_v2.py
- src/gui/main_window.py (only V2-related wiring and accessors)
- src/gui_v2/randomizer_adapter.py (adapter shaping and helper functions)
- tests/gui_v2/conftest.py
- tests/gui_v2/test_gui_v2_randomizer_integration.py
- tests/gui_v2/test_gui_v2_randomizer_matrix_ui.py (new)
- tests/gui_v2/test_gui_v2_randomizer_variant_count_preview.py (new)
- docs/pr_templates/PR-GUI-V2-RANDOMIZER-UI-EXPANSION-002.md (this file)

## Forbidden Files
- src/utils/randomizer.py (no algorithmic changes; only existing public interface may be referenced)
- src/pipeline/* (no pipeline behavior changes)
- src/controller/* (except for minimal type hints if absolutely required, prefer not to touch)
- Any tests under tests/gui or tests/gui_v1_legacy
- Any files under src/learning/*

## Step-by-step Implementation Plan

1. RandomizerPanelV2 UI expansion
   - Extend RandomizerPanelV2 to include:
     - A variant mode selector bound to an internal tk variable, offering the supported randomizer modes (off, sequential, rotate, expand, etc., aligned with the current randomizer API).
     - A matrix editor area:
       - Each row represents a matrix dimension (e.g., model, hypernetwork, sampler, scheduler).
       - Each dimension row exposes an entry widget or multi-line widget where the user can define pipe- or comma-delimited values.
     - A fanout numeric control (e.g., Spinbox or validated Entry) bound to a tk variable representing per-variant fanout.
     - A read-only label that displays a “Total variants: N” preview.
   - Panel API:
     - load_from_config(config_dict): populate mode, matrix dimensions, and fanout from an incoming config structure (compatible with current randomizer_adapter expectations).
     - get_randomizer_options(): return a plain dict describing current randomizer settings (mode, matrix, fanout) in a shape directly consumable by randomizer_adapter.
     - get_variant_count(): compute or fetch the current variant count preview for testing.

2. Adapter integration: variant count preview
   - Extend randomizer_adapter to expose a helper such as compute_variant_count(options, base_config) that:
     - Accepts the same options dict produced by the panel and uses the same planning code path as build_variant_plan to determine how many variants would be produced.
     - Returns a stable integer count for the given options, without mutating configs.
   - Wire RandomizerPanelV2’s variant-count label to this helper via StableNewGUI:
     - After each relevant change (mode, matrix entries, fanout), panel or GUI should recompute and update the label.
     - Use root.after or equivalent marshaling to ensure UI updates are executed on the main Tk thread.

3. StableNewGUI wiring (V2 only)
   - In StableNewGUI, ensure:
     - The V2 randomizer panel is instantiated and accessible (e.g., self.randomizer_panel_v2).
     - On startup:
       - Load default randomizer configuration (or a derived structure from the base pipeline config) into the randomizer panel via load_from_config.
       - Trigger an initial variant-count computation so the label reflects the default plan.
     - Before running the pipeline:
       - Collect randomizer options from the panel via get_randomizer_options.
       - Pass those into the existing randomizer_adapter path that builds a RandomizerPlanResult, as already done in PR-GUI-V2-RANDOMIZER-INTEGRATION-001.
     - Ensure StatusBarV2 and run-button validation logic remain unchanged.

4. Tests – GUI V2 randomizer UI behavior
   - tests/gui_v2/test_gui_v2_randomizer_matrix_ui.py:
     - Construct a GUI V2 instance with DummyController/DummyConfigManager as per existing fixtures.
     - Assert that:
       - The randomizer panel contains expected controls (mode dropdown, matrix fields, fanout input, variant-count label).
       - load_from_config correctly reflects incoming configuration (roundtrip: load, read via get_randomizer_options, compare core fields).
   - tests/gui_v2/test_gui_v2_randomizer_variant_count_preview.py:
     - Use deterministic randomizer options (e.g., two values for model, two for scheduler, fanout=2).
     - Assert that the variant-count label matches the count returned by the adapter helper and that changing fanout/matrix entries updates the label correctly.

5. Tests – Adapter parity
   - Extend tests/gui_v2/test_gui_v2_randomizer_integration.py to:
     - Confirm that get_randomizer_options plus the adapter yields a RandomizerPlanResult whose plan length equals the variant count displayed in the UI.
     - Assert that no Tk widgets or GUI modules are imported when importing randomizer_adapter in isolation.

6. Maintain safety and isolation
   - Ensure imports remain GUI-free for adapter and randomizer core; all Tk references stay inside src/gui/*.
   - Respect existing safety tests under tests/safety; do not weaken or bypass them.
   - Keep all new logic purely additive; avoid changing behavior of existing, passing tests.

## Required Tests (Failing First)
- tests/gui_v2/test_gui_v2_randomizer_matrix_ui.py
  - Initially fail because the matrix controls and load_from_config/get_randomizer_options aren’t implemented.
- tests/gui_v2/test_gui_v2_randomizer_variant_count_preview.py
  - Initially fail because the variant count preview label and adapter helper are not wired.
- Extended tests/gui_v2/test_gui_v2_randomizer_integration.py
  - Initially fail on new assertions for variant-count parity between UI and adapter.

## Acceptance Criteria
- All new GUI V2 tests under tests/gui_v2 pass locally:
  - Randomizer matrix UI test suite.
  - Variant-count preview test suite.
  - Updated randomizer integration tests.
- Existing safety tests (tests/safety) continue to pass, including GUI isolation tests.
- pytest -v runs with GUI V2 and safety tests green in your environment (Tk skips, if any, are limited to known headless constraints and do not affect the new tests).
- The visible Randomizer panel in GUI V2 shows a variant-count preview that matches the adapter’s computed plan length for the same options.

## Rollback Plan
- If regressions are detected:
  - Revert changes to src/gui/randomizer_panel_v2.py, src/gui/main_window.py, and src/gui_v2/randomizer_adapter.py.
  - Remove newly added tests under tests/gui_v2 for randomizer matrix and variant count preview.
  - Confirm that:
    - pytest tests/gui_v2 -v returns to the prior green state.
    - Randomizer integration tests revert to previous behavior.

## Codex Execution Constraints
- Do not touch src/utils/randomizer.py algorithmic logic.
- Do not modify src/pipeline/* or src/controller/* behavior.
- Do not re-enable or modify any legacy GUI tests under tests/gui or tests/gui_v1_legacy.
- Do not introduce new direct imports from GUI modules into utils/pipeline layers.
- Keep changes small and focused on the GUI V2 files and tests listed in Allowed Files.

## Smoke Test Checklist
- Launch StableNew locally and open the GUI V2 main window.
- Confirm that:
  - The randomizer panel shows:
    - Variant mode selector.
    - Matrix fields for at least two dimensions.
    - Fanout control.
    - Total variants label.
  - Changing matrix entries and fanout updates the total variants value visually.
  - Running a pipeline with randomizer enabled still executes successfully, and no new exceptions are logged.
- Run:
  - pytest tests/gui_v2 -v
  - pytest tests/safety -v
  - pytest -v
- Confirm that no new Tk-related skips or import errors appear outside of the existing, known headless limitations.
