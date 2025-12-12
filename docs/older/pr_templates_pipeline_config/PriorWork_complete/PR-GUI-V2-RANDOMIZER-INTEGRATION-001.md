# PR-GUI-V2-RANDOMIZER-INTEGRATION-001

## Title
V2 Randomizer Integration — Wire RandomizerPanelV2 to Pure utils.randomizer and Ensure Preview/Pipeline Parity

## Objective

Connect the V2 Randomizer panel to the existing, GUI-free `src/utils/randomizer.py` so that:

- matrix/random syntax entered in the GUI drives the same variant planning used by the pipeline,
- “one-click” runs respect the same variant plan in both preview and full pipeline flows, and
- the integration remains clean and fully isolated from Tk internals inside the randomizer module.

This PR focuses on **integration and parity**, not on changing randomizer algorithms.

---

## Goals

1. Wire RandomizerPanelV2 to the pure randomizer functions.
2. Introduce a small, GUI-facing adapter that:
   - builds matrix/randomization inputs from GUI state,
   - calls into `build_variant_plan` and `apply_variant_to_config`,
   - returns a consumable plan for the controller/pipeline.
3. Add tests that prove:
   - preview variant sequences match the pipeline’s variant sequences for the same inputs, and
   - importing `src.utils.randomizer` remains GUI-free (retains the safety guarantees from PR-RAND-SAN-001).

---

## Non-Goals

- No changes to randomizer core parsing or algorithms beyond minimal adapter needs.
- No changes to legacy GUI V1 randomization.
- No visual redesign of RandomizerPanelV2.
- No learning/tuning behavior.
- No new fields in pipeline manifests.

---

## Design

### 1. Randomizer Adapter (GUI-facing, Pure Logic)

Create a small adapter module:

- Location:
  - `src/gui_v2/randomizer_adapter.py` (or similar V2-specific path).
- Responsibilities:
  - Accept:
    - current base config dict (txt2img-only for this PR),
    - randomization options captured from the RandomizerPanelV2 (matrix expressions, counts, modes).
  - Invoke:
    - `build_variant_plan(...)` from `src.utils.randomizer`,
    - and later, `apply_variant_to_config(...)` to produce per-variant configs.
  - Produce:
    - a simple list of config dicts or a minimal plan object that StableNewGUI/controller can iterate over.

Constraints:
- The adapter must not import Tk or GUI widgets.
- The adapter may import:
  - `src.utils.randomizer` and any related pure helpers.

### 2. RandomizerPanelV2 → Adapter Integration

In `RandomizerPanelV2` (existing V2 panel):

- Expose methods:
  - `get_randomizer_options()`:
    - Returns a simple dict describing matrix/wildcard/randomization settings (e.g. raw expression strings, flags, fanout counts).
  - `build_variant_plan(base_config)`:
    - Uses the adapter module to generate a plan from GUI state + base config.
- Keep GUI concerns (Tk variables, widgets) within the panel; only the data is passed to the adapter.

### 3. StableNewGUI Integration

In `src/gui/main_window.py` for V2 path:

- When the Run button is clicked:
  - Obtain the **effective base config** from PipelinePanelV2 (already implemented in previous PRs).
  - Obtain the randomization options from RandomizerPanelV2.
  - Use the adapter to:
    - Build a variant plan (list of per-variant configs).
  - Decide run strategy (for this PR, keep it simple):
    - If plan contains more than one config:
      - Pass the plan to the controller in a form it already accepts (if a simple list of configs is compatible).
      - If that is not yet supported, limit this PR to a single “first variant” config and leave multi-variant execution to a future PR.
- Ensure preview/“dry run” (if available in V2 now) uses the same adapter so results match the pipeline’s variant ordering.

Important:
- If the existing controller/pipeline path does not support multiple configs in a single run safely, confine this PR to parity for a **single variant** and include a clear TODO comment and test placeholders for future multi-variant support.

### 4. Safety & Isolation

- The randomizer module (`src/utils/randomizer.py`) must remain GUI-free.
- The tests from PR-SAFE-ISOLATION-001 and PR-RAND-SAN-001 must still pass without modification.
- If any import errors or regressions surface, fix them in the adapter/GUI, **not** in randomizer core unless strictly necessary.

---

## Tests

Create:

- `tests/gui_v2/test_gui_v2_randomizer_integration.py`

Test scenarios:

1. **Adapter-only tests**:
   - Call the adapter with a simple base config and a basic matrix expression (e.g. two styles).
   - Assert that:
     - The plan contains the expected number of variants.
     - Each variant config contains the expected field changes.

2. **Preview vs. Pipeline parity** (if preview hooks are available in V2):
   - Use `gui_app_with_dummies` fixture.
   - Configure:
     - base config,
     - a simple randomization expression (e.g. two options for a single field).
   - Ask the adapter for a plan and record the sequence of configs.
   - Simulate a “pipeline run” using the same plan (dummy controller) and confirm:
     - The sequence of configs passed into the controller matches the adapter’s plan.

3. **Randomizer import safety**:
   - Reuse or extend `tests/safety/test_randomizer_import_isolation.py` only if necessary.
   - Confirm that importing `src.utils.randomizer` does not import Tk or GUI modules.

4. **Single-variant fallback (if multi-variant is not fully wired yet)**:
   - With GUI V2, set up a multi-option matrix expression.
   - Run the “Run Full Pipeline” button with dummy controller.
   - Assert:
     - At least the **first variant** from the adapter plan is used.
     - No crashes occur.
   - Document with TODO comments in tests for future multi-variant support.

---

## Acceptance Criteria

- `pytest tests/gui_v2 -v` passes.
- `pytest tests/safety -v` passes without modifications to the safety tests themselves.
- Randomizer remains GUI-free and import-safe.
- RandomizerPanelV2 can generate a plan using the adapter.
- Preview and pipeline (or dummy pipeline) share the same variant order for the same inputs.
- No regressions to:
  - PipelineRunner,
  - controller,
  - legacy GUI V1.

---

## Codex Guardrails

When implementing this PR:

- Do NOT change the internal algorithms of `src/utils/randomizer.py` unless absolutely necessary; prefer adapter-level changes.
- Do NOT import Tk or any GUI module inside the randomizer or adapter.
- Do NOT modify legacy GUI V1 randomization code or tests under `tests/gui_v1_legacy`.
- Keep GUI V2 changes confined to:
  - RandomizerPanelV2,
  - StableNewGUI V2 wiring,
  - the new adapter module,
  - and new tests under `tests/gui_v2/`.
- Ensure all existing safety tests still pass.
