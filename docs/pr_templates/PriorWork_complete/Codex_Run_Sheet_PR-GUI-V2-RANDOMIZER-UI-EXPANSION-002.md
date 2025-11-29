# Codex Run Sheet – PR-GUI-V2-RANDOMIZER-UI-EXPANSION-002

Paste this entire block into Codex chat when you’re ready to implement this PR.

---

You are implementing PR-GUI-V2-RANDOMIZER-UI-EXPANSION-002.

High-level intent:
- Expand the GUI V2 randomizer panel into a functional matrix/fanout UI.
- Keep all behavior confined to GUI V2 + adapter glue.
- Do not modify randomizer core logic, pipeline behavior, or learning modules.

Reference PR template:
- docs/pr_templates/PR-GUI-V2-RANDOMIZER-UI-EXPANSION-002.md (already describes scope and constraints).

## Scope and File Boundaries

Allowed files:
- src/gui/randomizer_panel_v2.py
- src/gui/main_window.py (V2 wiring only)
- src/gui_v2/randomizer_adapter.py
- tests/gui_v2/conftest.py
- tests/gui_v2/test_gui_v2_randomizer_integration.py
- tests/gui_v2/test_gui_v2_randomizer_matrix_ui.py (new)
- tests/gui_v2/test_gui_v2_randomizer_variant_count_preview.py (new)

Forbidden:
- src/utils/randomizer.py (no changes to algorithms or imports)
- src/pipeline/*
- src/controller/*
- tests/gui/*
- tests/gui_v1_legacy/*
- src/learning/*

If you think another file must be changed, stop and ask in the PR template instead of guessing.

## Implementation Steps

1. Expand RandomizerPanelV2 UI
   - In src/gui/randomizer_panel_v2.py:
     - Add tk variables and widgets for:
       - variant_mode (StringVar) with supported mode choices (e.g., off, sequential, rotate, expand) aligned with the existing randomizer API.
       - matrix dimension entries for at least two dimensions, such as model and hypernetwork (you may also include sampler/scheduler if they are easy to support cleanly).
       - fanout (IntVar or StringVar with validation) for per-variant fanout.
       - a read-only label to display “Total variants: N”.
     - Implement:
       - load_from_config(config_dict) – intake a dict and set mode, matrix fields, and fanout appropriately.
       - get_randomizer_options() – return a dict such as:
         - {"mode": ..., "fanout": ..., "matrix": {"model": [...], "hypernetwork": [...], ...}}
       - get_variant_count() – returns the last computed variant count (integer) to simplify testing.

2. Adapter helper for variant-count preview
   - In src/gui_v2/randomizer_adapter.py:
     - Add a pure helper function that computes variant count using the same planning logic as build_variant_plan but without mutating input configs, e.g.:
       - compute_variant_count(options: dict, base_config: dict) -> int
     - Internally, reuse the same code path used to build a RandomizerPlanResult so that the count exactly matches the plan length under the same conditions.
     - This helper must be Tk-free and must not import GUI modules.

3. Wire the panel to the adapter in StableNewGUI
   - In src/gui/main_window.py (GUI V2 areas only):
     - Ensure self.randomizer_panel_v2 is initialized and accessible.
     - During startup (where V2 panels are wired and config is loaded):
       - Call randomizer_panel_v2.load_from_config with an appropriate randomizer config (either derived from the base config or a dedicated structure).
       - After loading, compute the initial variant count via the adapter helper and update the panel’s label.
     - On user changes (mode, matrix fields, fanout):
       - Use root.after or equivalent safe mechanism to recompute the variant count via compute_variant_count and update the label.
     - Before running the pipeline:
       - Retrieve options from get_randomizer_options and pass them into the existing randomizer_adapter code path that yields RandomizerPlanResult.
       - Do not change how the pipeline currently executes variants (first-variant semantics remain as-is).

4. Tests – GUI V2 randomizer UI
   - Create tests/gui_v2/test_gui_v2_randomizer_matrix_ui.py:
     - Use existing GUI V2 fixtures (DummyController, DummyConfigManager, gui_app_with_dummies).
     - Assert that:
       - randomizer panel widgets exist (mode dropdown, matrix fields, fanout control, variant count label).
       - load_from_config followed by get_randomizer_options produces a consistent shape with expected values.
   - Create tests/gui_v2/test_gui_v2_randomizer_variant_count_preview.py:
     - Configure matrix options with simple known cardinalities (e.g., two model entries and two hypernetwork entries, fanout=2).
     - Assert that:
       - the variant count label shows the expected number.
       - changing fanout or matrix entries updates the label accordingly.
     - Ensure the variant count equals the length of the plan produced by the adapter helper for the same options.

5. Tests – existing randomizer integration
   - Update tests/gui_v2/test_gui_v2_randomizer_integration.py to add assertions that:
     - get_randomizer_options plus the adapter plan builder yields a plan whose length equals the UI’s displayed count.
     - randomizer_adapter still imports without pulling in any Tk or GUI modules (you can inspect sys.modules or use existing safety patterns).

6. Keep safety and isolation intact
   - Run tests/safety to ensure no new import violations appear.
   - Do not introduce imports from src/gui into src/gui_v2/randomizer_adapter.py or any non-GUI module.
   - Keep changes additive and localized.

## Required Test Commands

Run these in order and paste the outputs into the PR discussion:

1) pytest tests/gui_v2/test_gui_v2_randomizer_matrix_ui.py -v
2) pytest tests/gui_v2/test_gui_v2_randomizer_variant_count_preview.py -v
3) pytest tests/gui_v2/test_gui_v2_randomizer_integration.py -v
4) pytest tests/gui_v2 -v
5) pytest tests/safety -v
6) pytest -v

If any test fails, stop and fix the failure within this PR’s allowed scope. Do not “fix” unrelated modules.

## Guardrails / Reminders

- Do not edit src/utils/randomizer.py logic.
- Do not change pipeline behavior or multi-variant execution.
- Do not re-enable legacy GUI tests or touch tests/gui_v1_legacy.
- Keep diffs small, well-commented, and focused on this PR’s goal.
