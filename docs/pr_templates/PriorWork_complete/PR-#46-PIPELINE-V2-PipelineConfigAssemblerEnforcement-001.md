Timestamp: 2025-11-22 20:15 (UTC-06)
PR Id: PR-#46-PIPELINE-V2-PipelineConfigAssemblerEnforcement-001
Spec Path: docs/pr_templates/PR-#46-PIPELINE-V2-PipelineConfigAssemblerEnforcement-001.md

# PR-#46-PIPELINE-V2-PipelineConfigAssemblerEnforcement-001: Enforce PipelineConfigAssembler for All Runs (Completes PR-#38)

## What’s new

This PR completes and hardens the **PipelineConfigAssembler** integration (initially introduced conceptually in PR-#38) by:

- Replacing all remaining **ad-hoc config assembly** (dict-building or partial config objects) in controllers and GUI adapters with calls into a single **PipelineConfigAssembler**.
- Ensuring that every pipeline run uses a **fully structured PipelineConfig**, including:
  - **Megapixel clamping** and size safety rules defined in `PIPELINE_RULES.md`.
  - **Learning flags** and metadata (passive/active learning, learning run IDs, and so on).
  - **Randomizer/matrix metadata** for later analysis and learning.
- Updating GUI V2 adapters so that they:
  - Collect user-facing overrides and form fields.
  - Pass them into the assembler as structured overrides.
  - Do not mutate pipeline config dicts directly.
- Expanding tests to validate that:
  - Controllers build PipelineConfig via the assembler for all run modes.
  - GUI → adapter → assembler → PipelineConfig roundtrips are consistent.
  - Pipeline invariants (for example, max megapixels, sane tiling) hold across multiple run modes.

This PR is **contract enforcement and invariant hardening**: it does not change the public GUI behavior or WebUI API usage, but it ensures all runs are built through a single, testable configuration path.

---

## Files touched

> Adjust names to match your tree; keep all configuration logic centralized in the assembler.

### Pipeline / assembler

- `src/pipeline/pipeline_config_assembler.py`
  - Ensure the assembler exposes a canonical API, for example:

    - `class PipelineConfigAssembler:`
      - `def build_from_gui_input(self, base_settings: BaseSettings, overrides: GuiOverrides) -> PipelineConfig`
      - `def build_for_learning_run(self, base_settings: BaseSettings, overrides: GuiOverrides, learning_metadata: LearningMetadata) -> PipelineConfig`
      - `def apply_megapixel_clamp(self, config: PipelineConfig) -> PipelineConfig`
      - `def attach_randomizer_metadata(self, config: PipelineConfig, rand_meta: RandomizerMetadata) -> PipelineConfig`

  - Ensure it:
    - Applies **megapixel clamp** rules from `PIPELINE_RULES.md`:
      - For example, computed `width * height / 1_000_000 <= max_mp`.
    - Attaches:
      - `learning_enabled`, `learning_mode`, `learning_run_id`, and similar fields when applicable.
      - `randomizer_run_id`, `matrix_id`, or equivalent randomizer metadata.
    - Performs **sanitization** as needed (for example, size bounds, seed handling, sampler defaults).

### Controller

- `src/controller/pipeline_controller.py`
  - Replace any remaining config-building logic that:
    - Manually constructs pipeline config dicts or ad hoc objects.
  - Instead:
    - Accept a `PipelineConfigAssembler` via constructor or factory.
    - In all run entrypoints (`run_pipeline`, `run_full_pipeline`, and others):
      - Collect the necessary inputs:
        - Current base config (for example, from app config or last-used run).
        - GUI overrides or run-time overrides.
        - Learning flags or metadata (if a learning run).
        - Randomizer metadata (if applicable).
      - Call the assembler to produce a `PipelineConfig`.
      - Pass that config to:
        - Direct pipeline runner (non-queue mode).
        - QueueExecutionController/Job submission (queue mode from PR-#45).

  - Ensure:
    - There is **no** fallback path that can bypass the assembler.
    - Tests confirm that the assembler is the **only** configuration construction path used in production runs.

### GUI V2 adapters

- `src/gui/pipeline_adapter_v2.py` (or equivalent)
  - Update the adapter so that:
    - It no longer builds full pipeline configs or partial untyped dicts.
    - Instead, it:
      - Extracts user-facing values from widgets (width, height, model, steps, and so on).
      - Packages them into a `GuiOverrides` (or equivalent) object or dict.
      - Calls into the controller or assembler entrypoint:
        - For example, `controller.request_run_with_overrides(overrides)`.
  - If a **preview** pipeline config is needed (for example, for estimate displays):
    - Use the assembler in a “preview” mode rather than duplicating assembly logic.

- `src/gui/main_window.py` and `src/gui/app_layout_v2.py`
  - Ensure wiring is updated so:
    - GUI uses controller methods that internally call the assembler.
    - GUI does not import PipelineConfig or assembler directly (remains UI-only).

### Learning / randomizer integration

- `src/controller/learning_execution_controller.py` and/or `src/learning/learning_execution_runner.py`
  - Ensure that:
    - Learning runs that involve the main pipeline use the same assembler path to construct their `PipelineConfig`, with:
      - Learning-specific metadata attached (for example, learning run id, rating targets, and so on).
  - No special-case config building outside assembler.

- `src/randomizer/randomizer_controller.py` or equivalent
  - When generating matrix or wildcard runs:
    - Use the assembler to create each per-variant `PipelineConfig`.
    - Ensure that randomizer metadata is attached in a consistent field for later learning analysis.

### Docs

- `docs/PIPELINE_RULES.md`
  - Update:
    - The “Configuration assembly” section to state:
      - All pipeline runs MUST use `PipelineConfigAssembler`.
      - Direct dict-based config construction is forbidden for production paths.
    - The megapixel clamp rules and how they are enforced by the assembler.

- `docs/ARCHITECTURE_v2_COMBINED.md`
  - Update the Pipeline section:
    - Add a clear diagram or bullet list:
      - GUI → Adapter → Controller → PipelineConfigAssembler → PipelineRunner / QueueExecutionController → Pipeline.
    - Mark `PipelineConfigAssembler` as the **single source of truth** for run configuration.

- `docs/codex_context/ROLLING_SUMMARY.md`
  - Updated as described below.

---

## Behavioral changes

- For end users:
  - Behavior should be:
    - Semantically equivalent or **more stable**:
      - All runs obey megapixel limits.
      - All runs have consistent learning/randomizer metadata attached.
    - Small user-facing differences may appear only where previous behavior was inconsistent or unsafe (for example, too-large resolutions now being clamped).

- For the system:
  - Configuration assembly is:
    - Deterministic.
    - Testable.
    - Centralized.
  - New features (for example, new pipeline stages or learning modes) can be:
    - Added via updates to the assembler and its tests, rather than modifying multiple ad hoc config sites.

---

## Risks / invariants

- **Invariants**

  - No production run path is allowed to:
    - Build pipeline configs directly without going through the assembler.
  - Megapixel constraints:
    - All pipeline configs must pass clamp rules defined in `PIPELINE_RULES.md`.
  - Learning / randomizer metadata:
    - If these features are enabled, the corresponding fields in PipelineConfig must be filled via assembler logic, not per-call hacks.

- **Risks**

  - If some legacy path still bypasses the assembler:
    - You may end up with inconsistent behavior between different run modes (for example, GUI vs. learning vs. randomizer).
  - If assembler logic is incorrectly merged:
    - It could clamp resolutions too aggressively or not at all.
  - If GUI adapters are not fully migrated:
    - There may be orphaned code paths that still use old dict-building logic.

- **Mitigations**

  - Use test coverage to:
    - Assert there are no remaining direct config-building call sites.
    - Validate that known scenarios (for example, 1024×1024, 2048×2044, and so on) produce expected clamped/unchanged configs.
  - Keep changes:
    - Focused and incremental:
      - First migrate PipelineController and primary GUI adapters.
      - Then migrate learning/randomizer controllers using the same patterns.

---

## Tests

Run at minimum:

- **Assembler + controller**

  - `tests/controller/test_pipeline_config_assembler.py -v`
    - Add cases to cover:
      - Standard txt2img, img2img, and upscale runs.
      - Learning-enabled runs (flags + metadata).
      - Randomizer/matrix-enabled runs.

  - `tests/controller/test_pipeline_controller_config_path.py -v` (or extend existing tests)
    - Assert that:
      - PipelineController always calls the assembler to build `PipelineConfig`.
      - Direct dict construction is no longer used.

- **GUI adapter roundtrip**

  - `tests/gui_v2/test_pipeline_adapter_roundtrip.py -v`
    - For several representative configurations:
      - Simulate GUI inputs.
      - Run through adapter → controller → assembler to obtain PipelineConfig.
      - Assert:
        - Fields match expected values.
        - Megapixel clamp is applied when needed.
        - Learning/randomizer metadata appears when those options are enabled.

- **Pipeline invariants**

  - `tests/pipeline/test_pipeline_config_invariants.py -v` (new or extended)
    - Validate:
      - All PipelineConfig instances produced by assembler:
        - Respect size/MP constraints.
        - Have valid sampler, steps, and other required fields.

- **Regression**

  - `pytest tests/pipeline -v`
  - `pytest tests/controller -v`
  - `pytest tests/gui_v2 -v`
  - `pytest -v`

Expected results:

- All new tests pass, confirming:
  - Centralized config assembly.
  - Invariant enforcement.
  - Stable GUI/controller behavior.
- Existing tests remain green, with only improvements where previous behavior was undefined or inconsistent.

---

## Migration / future work

With assembler enforcement in place:

- Future changes to:
  - Default resolutions.
  - New pipeline stages.
  - New learning or randomizer fields.
- Can be implemented:
  - In a single place (assembler + tests) and automatically affect all run paths.

It also enables:

- More advanced features, such as:
  - “dry-run” config validation.
  - Pre-run cost/ETA estimation based on config.
  - Learning rules that depend on config metadata (for example, only record certain runs).

---

## Rolling summary update (for `docs/codex_context/ROLLING_SUMMARY.md`)

Append under the appropriate date (for example, `## 2025-11-22`):

- Enforced use of **PipelineConfigAssembler** for all pipeline runs, eliminating ad-hoc config assembly in controllers and GUI adapters and centralizing megapixel clamps, learning flags, and randomizer metadata.
- Updated controller and GUI V2 integration so that configuration flows are: GUI → adapter → controller → assembler → pipeline/queue, simplifying future changes and strengthening invariant guarantees.
- Expanded tests across controller, GUI, and pipeline layers to validate that all run paths produce consistent, clamped, metadata-rich PipelineConfig instances, with no regressions in existing behavior.
