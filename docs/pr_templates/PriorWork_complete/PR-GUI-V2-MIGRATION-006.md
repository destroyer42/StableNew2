# PR-GUI-V2-MIGRATION-006

## Title
V2 Pipeline Config Validation — Field-Level Checks, Error Surfacing, and Run-Blocking Rules

## Objective

Strengthen the StableNew GUI V2 pipeline configuration flow by adding clear, deterministic validation for core txt2img fields. Invalid configs must be caught **before** the controller is invoked, surfaced visibly in the StatusBarV2, and prevent “Run Full Pipeline” from firing until the issues are resolved.

This PR focuses only on **txt2img-level validation** in the V2 GUI. No changes to pipeline internals, API calls, or randomizer behavior.

---

## Goals

1. Introduce a dedicated, testable config validation layer for txt2img fields used by PipelinePanelV2 and Txt2ImgStageCard.
2. Wire validation results into StableNewGUI so:
   - the Run button is disabled when the config is invalid,
   - StatusBarV2 displays a short error summary, and
   - no pipeline start is attempted while invalid.
3. Ensure validation rules are deterministic, simple, and unit-tested:
   - steps, CFG, width, height, scheduler, sampler, model, and VAE.
4. Preserve the existing V2 layout and controller contract.

---

## Non-Goals

- No changes to legacy GUI V1.
- No changes to PipelineRunner behavior or config schema.
- No learning/tuning logic.
- No randomizer/matrix integration.
- No img2img/adetailer/upscale validation in this PR (txt2img only).

---

## Design

### 1. Config Validation Module

Create a small, GUI-agnostic validator:

- Location:
  - `src/gui_v2/validation/pipeline_txt2img_validator.py` (or similarly named under a V2 GUI namespace).
- Responsibilities:
  - Accept a simple dict of txt2img fields (e.g. `steps`, `cfg_scale`, `width`, `height`, `sampler_name`, `scheduler`, `model`, `vae`).
  - Return a structured result object, for example:
    - `is_valid` (bool)
    - `errors` (mapping from field name to human-readable error message, e.g. `"steps": "Steps must be between 1 and 150."`)
- Rules (initial baseline):
  - `steps`: integer, 1 ≤ steps ≤ 150 (configurable via module-level constants).
  - `cfg_scale`: float, 0.0 ≤ cfg_scale ≤ 30.0.
  - `width` and `height`: integers, multiples of 8, 256 ≤ value ≤ 1536.
  - `model`: non-empty string.
  - `vae`: non-empty string (but accept `"None"`/`"none"` as valid choice).
  - `sampler_name`: non-empty string.
  - `scheduler`: non-empty string.
- Implementation notes:
  - No Tk imports.
  - No controller or pipeline imports.
  - Pure functions only.

### 2. PipelinePanelV2 + Txt2ImgStageCard Integration

Extend the existing V2 pipeline structures:

- `PipelinePanelV2`:
  - Provide a helper method such as `get_txt2img_config_view()` which returns a dict suitable for validation.
  - Provide a method `validate_txt2img()` that calls the validator and returns the structured result.
- `Txt2ImgStageCard`:
  - Ensure it exposes the variables needed to produce the validation dict.
  - No direct dependency on the validator; keep validation logic in the panel to centralize behavior.

### 3. StableNewGUI Wiring

Within `src/gui/main_window.py` for the V2 path:

- On startup:
  - After constructing the GUI V2 panels, perform an initial validation.
  - Set the Run button enabled/disabled accordingly.
- On relevant field changes:
  - Hook into Tk variable traces or explicit callbacks in `PipelinePanelV2` so that when txt2img fields change, validation re-runs.
- Before pipeline start:
  - When the Run button is clicked:
    - Re-run validation.
    - If invalid:
      - Do **not** call the controller.
      - Push an error status into `StatusBarV2` with a short summary (e.g. “Invalid config: steps out of range”).
    - If valid:
      - Proceed as today.

Run button behavior:
- Run button is only enabled when the latest validation result is valid.
- In case of transient Tk or environment issues, fail-safe to disabled rather than allowing an invalid run.

### 4. StatusBarV2 Integration

Extend `StatusBarV2` minimally:

- Additional method to display validation errors, e.g. `set_validation_error(message: str)`, which:
  - Sets the status label to an “Error” color/style.
  - Optionally clears progress/ETA for clarity.
- Do not alter existing progress/ETA logic.

---

## Tests

Create a new test module for validation logic:

- `tests/gui_v2/test_gui_v2_pipeline_txt2img_validation.py`

Test cases:

1. **Pure validation unit tests**:
   - Import the validator module directly.
   - Verify rules:
     - Valid configuration returns `is_valid = True` and no errors.
     - Out-of-range steps, cfg_scale, width, height produce appropriate error messages.
     - Non-multiple-of-8 dimensions fail with a clear error.
     - Empty model/sampler/scheduler/vae fields fail.
2. **GUI-level enable/disable behavior** (V2 only):
   - Use `gui_app_with_dummies` fixture.
   - Construct StableNewGUI V2.
   - Force an invalid config via Tk variables (e.g. steps = -1).
   - Assert:
     - Run button is disabled.
     - StatusBarV2 shows an error state/message.
   - Fix the config (e.g. steps = 20).
   - Assert:
     - Validation flips to valid.
     - Run button becomes enabled.
3. **Pre-run validation guard**:
   - Monkeypatch the controller’s `start_pipeline` so it raises an AssertionError if called when config is invalid.
   - Click Run with invalid fields and assert:
     - `start_pipeline` is NOT called.
     - StatusBarV2 shows an error message.

---

## Acceptance Criteria

- `pytest tests/gui_v2 -v` passes.
- `pytest -v` passes (subject to existing, acknowledged Tk skips only).
- Invalid txt2img configurations:
  - Disable the Run button.
  - Surface clear error messages via StatusBarV2.
  - Never reach the controller.
- No changes to:
  - PipelineRunner or pipeline internals.
  - Randomizer or StageCards for img2img/upscale.
  - Legacy GUI tests under `tests/gui_v1_legacy`.

---

## Codex Guardrails

When implementing this PR:

- Do NOT modify any files under `tests/gui_v1_legacy/`.
- Do NOT change controller or pipeline behavior.
- Do NOT add new dependencies outside the GUI V2 namespace and core utils.
- Keep the validator pure and GUI-agnostic.
- Keep changes small and focused on txt2img validation and Run button behavior only.
