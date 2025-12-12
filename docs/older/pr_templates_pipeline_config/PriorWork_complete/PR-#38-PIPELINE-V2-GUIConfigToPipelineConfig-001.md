Timestamp: 2025-11-22 18:42 (UTC-06)
PR Id: PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001
Spec Path: docs/pr_templates/PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001.md

# PR-#38-PIPELINE-V2-GUIConfigToPipelineConfig-001: GUI → PipelineConfig Contract Hardening

## What’s new

- Defines and centralizes the **contract** between GUI/Controller state and `PipelineConfig`, making it the single source of truth for all stage parameters in line with `ARCHITECTURE_v2_COMBINED.md` and `PIPELINE_RULES.md`.
- Introduces a small, testable **PipelineConfigAssembler** (or equivalent helper) that:
  - Accepts GUI-derived inputs (stage cards, randomizer overlays, learning flags).
  - Produces a validated `PipelineConfig` instance.
- Updates `PipelineController` (and any related helpers) to rely on the new assembler rather than ad-hoc config dictionaries or loosely structured merges.
- Adds focused tests that:
  - Map representative GUI V2 states to expected `PipelineConfig` objects.
  - Enforce pipeline invariants: stage ordering, safe defaults, megapixel limits, and opt-in learning.
- Documents the contract and its invariants and updates the rolling summary for Codex.

This PR is **purely about configuration assembly**; it does not modify pipeline execution logic, queue semantics, or GUI layout beyond small adapter/helpers if needed.

---

## Files touched

> Use existing naming and structure in the repo; adjust module names to match reality, but keep the responsibilities scoped as described.

### Pipeline / config

- `src/pipeline/pipeline_config.py` (or equivalent)
  - Ensures `PipelineConfig`:
    - Captures all core stage parameters (txt2img, img2img, upscale, adetailer/refiner).
    - Includes fields for:
      - Model, VAE, sampler, steps, CFG, width, height, batch size.
      - img2img strength and source image refs (if used).
      - Upscale settings: upscaler type, resize factor, tile parameters in line with `PIPELINE_RULES.md`.
      - Learning + randomizer metadata (e.g., run id, prompt pack id, learning_enabled flag).
    - Provides:
      - `from_dict()` / `to_dict()` helpers restricted to internal use (no GUI imports).
      - Optional validation helpers (e.g., `validate()` to enforce safe defaults and megapixel limits).

### Controller

- `src/controller/pipeline_config_assembler.py` **(new)** (name flexible, but must live in controller layer)
  - Implements a pure, testable assembler such as:
    - `build_pipeline_config(base_config, gui_overrides, randomizer_overlay, learning_enabled) -> PipelineConfig`
  - Responsibilities:
    - Start from a base/default configuration (e.g., loaded from config manager).
    - Apply GUI overrides:
      - Stage toggles from PipelinePanelV2 cards.
      - Prompt / model / sampler / steps / resolution changes.
      - Upscale and adetailer toggles.
    - Apply randomizer overlay if active:
      - Seed / variation overrides.
      - Style/matrix expansions where applicable (but the randomizer core still lives in utils).
    - Apply learning flags:
      - `learning_enabled` boolean.
      - Any learning metadata required for the LearningRecord builder.
    - Enforce invariants:
      - Stage order remains txt2img → adetailer (optional) → img2img (optional) → upscale (optional).
      - Max megapixel / tile limits as per `PIPELINE_RULES.md`.
      - No hard-coded paths or environment-sensitive assumptions.

- `src/controller/pipeline_controller.py`
  - Replaces any inline config assembly logic with calls to `PipelineConfigAssembler`, for example:
    - `config = self.config_assembler.build_pipeline_config(...)`
  - Ensures:
    - The controller no longer manually mutates config dicts.
    - The contract is funneled through a single code path.
  - No changes to the controller’s public GUI-facing methods (Run/Stop, etc.), preserving the V2 layering described in `ARCHITECTURE_v2_COMBINED.md`.

### GUI adapters (minimal)

- `src/gui_v2/pipeline_adapter.py` **(new or extended)**
  - Provides a small adapter that:
    - Extracts the current GUI state (e.g., from PipelinePanelV2 stage cards).
    - Produces a structured “GUI overrides” object for the controller (dataclass or typed dict).
  - Must:
    - Live in GUI layer and depend only on controller-facing types/interfaces.
    - Not import `src/pipeline` or API clients.

No changes to the visual layout, only the state → config extraction.

### Tests

- `tests/controller/test_pipeline_config_assembler.py` **(new)**
  - Constructs representative combinations of:
    - Base config (e.g., 512x512, default sampler, safe steps).
    - GUI overrides (e.g., switch to 768x768, enable upscale 2x).
    - Randomizer overlays (e.g., variant seeds).
    - Learning toggles.
  - Asserts resulting `PipelineConfig`:
    - Matches expected stage flags and parameters.
    - Respects megapixel limits and safe defaults.
    - Correctly captures learning metadata when enabled.

- `tests/gui_v2/test_pipeline_adapter_roundtrip.py` **(new)**
  - Uses a test harness for GUI V2 panels:
    - Sets known values in stage cards (prompt, sampler, steps, resolution, toggles).
    - Calls the adapter to produce “GUI overrides”.
    - Passes overrides into a fake assembler.
  - Asserts:
    - Roundtrip integrity: changes in GUI lead to expected overrides.
    - No cross-layer imports (randomizer or pipeline) leak into GUI layer.

- `tests/pipeline/test_pipeline_config_invariants.py` **(new or extended)**
  - Focuses on:
    - Max megapixel / safe tile constraints (as configured).
    - Stage ordering invariants.
    - Serialization/deserialization of `PipelineConfig` (if used in logs or learning records).

### Docs

- `docs/PIPELINE_RULES.md`
  - Clarify that:
    - `PipelineConfig` is the single source of truth for stage parameters.
    - GUI/Controller must use an assembler rather than bypassing this contract.
    - Any future stages must be represented in `PipelineConfig` and assembler logic.

- `docs/ARCHITECTURE_v2_COMBINED.md`
  - In the Pipeline and Controller sections, make explicit reference to:
    - The assembler as the **bridge** between GUI state and PipelineConfig.
    - The prohibition on GUI → pipeline imports, with `PipelineController` and the assembler owning config composition.

- `docs/codex_context/ROLLING_SUMMARY.md`
  - Add bullet points as specified in the “Rolling summary update” section below.

---

## Behavioral changes

- From a user’s perspective:
  - There should be **no visible behavioral change** in the GUI:
    - Same fields, same defaults, same run semantics.
  - However, configuration behavior is now:
    - More predictable.
    - Easier to reason about when debugging.
    - Less likely to drift over time.

- From a developer’s / AI agent’s perspective:
  - There is a clear, documented path for turning GUI settings into pipeline-ready configs:
    - GUI V2 → pipeline adapter → PipelineController → PipelineConfigAssembler → PipelineConfig.
  - When adding a new stage or option:
    - You update `PipelineConfig`.
    - You extend `PipelineConfigAssembler`.
    - You wire the GUI panel to feed in the appropriate override structure.
  - Ad-hoc config dict munging in controllers should be eliminated or reduced to zero in favor of the assembler.

- Pipeline invariants:
  - Stage order and safety limits remain unchanged and must still follow `PIPELINE_RULES.md`.
  - Learning remains opt-in; the assembler only sets learning fields when the learning flag is enabled (e.g., from PR-#34’s GUI toggle).

---

## Risks / invariants

- **Invariants**
  - `PipelineConfig` remains the only authoritative container for stage settings; there must be no parallel config structures in controllers.
  - GUI must not import `src/pipeline` directly; all pipeline-facing types should be mediated via controller/assembler interfaces.
  - `PipelineConfigAssembler` must:
    - Enforce megapixel limits and other safety rules defined in `PIPELINE_RULES.md`.
    - Keep learning behavior opt-in, consistent with `LEARNING_SYSTEM_SPEC.md`.
  - Default values must not change silently:
    - If a default (e.g., steps, sampler, resolution) is altered, tests must be updated and the change explicitly noted in `CHANGELOG.md` (not part of this PR unless intentionally changed).

- **Risks**
  - If the assembler is miswired, configurations might:
    - Disable stages that should be enabled.
    - Misconfigure upscaler or img2img parameters, causing subtle pipeline behavior differences.
  - Incorrect handling of randomizer overlays could cause preview/pipeline mismatches if future PRs wire the randomizer into the same contract.

- **Mitigations**
  - Strong test coverage:
    - Multiple representative configs (small, large, with/without upscale).
    - Roundtrip tests from GUI state to `PipelineConfig`.
  - Keep assembler logic pure and easily reviewable.
  - Avoid mixing assembler refactors with unrelated changes in controllers or pipeline runner.

---

## Tests

Run at minimum:

- Controller + assembler tests:
  - `pytest tests/controller/test_pipeline_config_assembler.py -v`

- GUI adapter tests:
  - `pytest tests/gui_v2/test_pipeline_adapter_roundtrip.py -v`

- Pipeline config invariants:
  - `pytest tests/pipeline/test_pipeline_config_invariants.py -v`
  - `pytest tests/pipeline -v`

- Full regression:
  - `pytest -v`

Expected outcomes:

- Assembler and adapter tests validate:
  - Correct mapping from GUI state to `PipelineConfig`.
  - Enforcement of megapixel and safety rules.
- Existing behavior tests (pipeline, controller, learning, GUI V2) remain green; any differences must be intentional and documented.

---

## Migration / future work

With the GUI → `PipelineConfig` contract hardened and centralized:

- Future work can:
  - Add new pipeline stages (e.g., video, refiner) by:
    - Extending `PipelineConfig`.
    - Updating `PipelineConfigAssembler`.
    - Wiring new GUI V2 stage cards to feed into the assembler.
  - Integrate randomizer more deeply:
    - Make randomizer plans produce structured overlays that the assembler merges into the base config for each variant.
  - Integrate learning plans:
    - Ensure learning-specific metadata is attached through the assembler for headless learning runs as well.

- This PR also prepares the ground for:
  - Better config logging (e.g., one-line summary of `PipelineConfig` per run).
  - Easier debugging when pipeline behavior doesn’t match GUI expectations.

---

## Rolling summary update (for `docs/codex_context/ROLLING_SUMMARY.md`)

Append under the appropriate date heading (e.g., `## 2025-11-22`):

- Centralized the **GUI → PipelineConfig** mapping behind a controller-layer assembler so all pipeline runs now share a single configuration contract.
- Hardened `PipelineConfig` invariants to enforce stage ordering, megapixel limits, and safe defaults as codified in `PIPELINE_RULES.md`.
- Added tests for assembler behavior and GUI V2 adapter roundtrips, improving confidence that GUI settings map cleanly to pipeline behavior.
