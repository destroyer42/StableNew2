PR-E — Unified Prompt & Config Resolution Layer (V2.5).md

Discovery Reference: D-11 (Pipeline Run Controls), D-20 (JobBundle Ownership), D-23 (Prompt/Config Misalignment), Logs from 2025-12-07 showing missing prompt propagation and incorrect stage configs.

Date: 2025-12-07
Author: GPT-5.1 (Planner)

1. Summary (Executive Abstract)

This PR introduces a single, authoritative resolution layer that transforms GUI inputs, prompt fields, prompt pack data, global negative configuration, pipeline stage toggles, and preset/default overrides into a normalized structure used for JobPart → JobBundle → NormalizedJobRecord → Runner payload.

Today, prompt and config propagation is fractured across GUI widgets, controllers, builder code, and default fallbacks. This fragmentation directly causes the failures observed in the logs:

Positive prompt missing

Negative prompt missing

Incorrect or defaulted stage configs (refiner start = 0, hires steps = 0, adetailer not resolved, etc.)

Randomizer not applied

Pack prompts not merged correctly

Preview showing stages different from the pipeline runner

This PR creates the UnifiedPromptResolver and UnifiedConfigResolver, making all prompt and config assembly deterministic, testable, and pipeline-accurate.

The GUI will no longer guess what the pipeline will do—the preview, queue, and runner now consume data from the same resolution path.
This is required for PR-D (queue/history alignment), PR-B/C (JobBundle integrity), and PR-U1 (debug harness).

2. Motivation / Problem Statement
Current Behavior (Incorrect)

Prompt text from the prompt field does not appear in created JobParts.

Global negative may not be applied, depending on code path.

Prompt pack prompts are read, but config JSON is not merged into JobPart configs.

Refiner/Hires defaults are incorrect (0, None, missing model fields).

ADetailer dropdowns do not populate and config is ignored.

Randomizer values and seeds do not propagate into JobPart config.

Preview panel shows different stages than the pipeline runner actually executes.

Resulting JobParts yield incomplete NormalizedJobRecords, causing pipeline execution errors (e.g., invalid encoded image from WebUI).

Why This Is Incorrect

Violates architectural principle: Preview = Queue = Runner.

Prevents deterministic reproduction of images.

Makes debugging impossible—users cannot trust what the system thinks it will run.

Breaks presets, packs, randomizer tuning, ADetailer, refiner/hires logic.

Causes pipeline divergence and malformed WebUI payloads.

Why Solving Now

PR-A through PR-D fix lifecycle, draft ownership, and queue/history flows; however everything still breaks if JobParts are assembled incorrectly.
This PR provides the foundation required for:

Correct preview display

Correct pipeline execution

Debug harness accuracy

Accurate history records

Future template expansion (styles, presets, advanced randomization, etc.)

3. Scope & Non-Goals
In Scope

Create a new Unified Prompt + Config Resolution layer with two core components:

UnifiedPromptResolver

UnifiedConfigResolver

Integrate resolvers into JobBundleBuilder and PipelineController.

Update JobPart creation so all fields are resolved through these resolvers.

Update DTOs so preview, queue, and history panels reflect resolved data.

Add a full simulation test (test_prompt_config_resolution_e2e) verifying output against expected WebUI payloads.

Non-Goals

No GUI redesign.

No pack format changes (we only consume).

No changes to pipeline execution flow outside payload formation.

No incorporation of learning system or preference weighting.

4. Behavioral Changes
Before

Prompt text is frequently missing.

Global negative inconsistently applies.

Pack configs are partly or entirely ignored.

Stages such as ADetailer, Hires, Refiner resolve to defaults (0, None).

Preview panel and runner do not match.

Seeds, randomness, multiplier values either missing or overwritten.

After

Every JobPart is built from a unified, deterministic resolution path.

Prompt = prepend text + base prompt + pack prompt (if present).

Negative = global negative (if enabled) + pack negative + preset negative.

Model selection, sampler, scheduler, refiner start, hires model, ADetailer config all resolved once in a single location.

Preview panel matches exactly what will run.

Queue and history receive fully resolved DTOs.

Runner payloads are correct, eliminating invalid encoded image errors.

5. Design Overview
5.1 New Module: src/pipeline/resolution_layer.py

Defines two primary classes:

UnifiedPromptResolver

Inputs:

GUI prompt field value

Prompt pack prompt

Prepend text

Global negative value

Enable global negative toggle

Pack negative

Preset-derived defaults

Randomizer overrides

Outputs:

@dataclass(frozen=True)
class ResolvedPrompt:
    positive: str
    negative: str


Behavior:

Concatenates prompts with deterministic order.

Applies pack config overrides.

Ensures negative prompts always include safety text when enabled.

Supports truncation for preview-only DTOs.

UnifiedConfigResolver

Resolves:

Stage toggles

Txt2Img base model

Img2Img strength

Hires fix model, refiner model, refiner start %, steps

Upscaler mode, tile sizes

ADetailer model/detector/confidence/mask blur

Seeds/batch count/batch size

Randomizer overrides

Default fallback constants

Output:

@dataclass(frozen=True)
class ResolvedPipelineConfig:
    stages: Dict[str, StageConfig]  # fully resolved
    seed: int
    batch_size: int
    batch_count: int
    width: int
    height: int
    final_size: Tuple[int, int]

5.2 Integration With JobBundleBuilder

During JobPart creation:

resolved_prompt = prompt_resolver.resolve(...)
resolved_config = config_resolver.resolve(...)

job_part = JobPart(
    prompt=resolved_prompt.positive,
    negative=resolved_prompt.negative,
    config=resolved_config,
)


This eliminates all GUI-driven assembly, guaranteeing pipeline consistency.

5.3 Preview Panel Changes

Preview reads the ResolvedPrompt and ResolvedPipelineConfig from DTOs.

Final-size label, stage summaries, batch totals now always match real pipeline execution.

5.4 Queue & History Integration

DTOs now include:

resolved_prompt_preview

resolved_stage_list

resolved_final_size

resolved_batch_size

History records also store the resolved metadata for reproducibility.

6. Files & Subsystems
New Files

src/pipeline/resolution_layer.py

tests/pipeline/test_unified_prompt_resolution.py

tests/pipeline/test_unified_config_resolution.py

tests/pipeline/test_resolution_e2e.py

Modified Files

src/controller/pipeline_controller.py

src/pipeline/job_bundle_builder.py

src/pipeline/job_models_v2.py (JobPart extended but not breaking)

src/gui/preview_panel_v2.py

src/controller/app_controller.py

src/services/job_service_v2.py (small adaptation to use resolved configs)

Documentation

ARCHITECTURE_v2.5.md — Add “Unified Resolution Layer” subsystem section

StableNew_Coding_and_Testing_v2.5.md — Add test rules for prompt/config determinism

7. Implementation Plan (Step-by-Step)

Create resolution layer module with resolvers + dataclasses.

Write unit tests for each resolver class.

Modify JobBundleBuilder to call resolvers during JobPart creation.

Update PipelineController to supply correct input parameters to resolvers.

Update DTOs to include resolved prompt/config summaries.

Patch preview panel to reflect resolved values.

Patch queue panel to reflect resolved values.

Patch runner payload builder (JobBuilderV2) to use resolved config exclusively.

Add end-to-end tests for prompt/config correctness.

Update documentation.

8. Testing Strategy
Unit Tests

Resolve positive prompt with prepend + pack + text field.

Resolve negative prompt with global toggle on/off.

Resolve missing fields gracefully (model not selected, hires steps unspecified).

Resolve stage sequence correctness.

Resolve ADetailer dropdown mapping + defaults.

Integration Tests

Build JobBundle from GUI-mocked inputs.

Verify preview panel summary matches final payload.

Verify re-enqueued job is identical to preview.

Regression Tests

Packs with no negative prompt.

Packs with their own configs (hires/refiner).

Randomizer forced-mode values.

9. Risks & Mitigations
Risk 1: GUI fields may diverge from resolver expectations

Mitigation: Controller translates GUI → resolver; GUI never calls resolvers directly.

Risk 2: Pack config diversity (missing or partial files)

Mitigation: Resolver implements layered fallbacks (pack → preset → defaults).

Risk 3: PipelineRunner metadata mismatch

Mitigation: All WebUI payloads built from ResolvedPipelineConfig, never from GUI state.

Risk 4: Performance concerns if resolving large packs

Mitigation: Cached pack JSON parse; resolver is lightweight (pure functions).

10. Rollback Plan

Revert new module.

Restore JobBundleBuilder to non-resolved assembly mode.

Re-enable GUI-side prompt assembly.

Remove DTO fields referencing resolved configs.

No stateful migrations; rollback is clean.

11. Migration / Data Considerations

No schema changes.

History records now include resolved metadata, but this is non-breaking.

Old history entries remain compatible.

12. Telemetry / Observability

Integrates tightly with PR-A logging:

Log full resolution input + output for each JobPart when debug mode is enabled.

Log merges of pack config overrides.

Log final pipeline resolved configuration.

Log discrepancies between GUI → resolver inputs.

13. Documentation Updates

Add new Architecture section: Unified Prompt & Config Resolution Layer:

Single deterministic path

Eliminates GUI/pipeline mismatch

Ensures reproducibility

Required for ADetailer, Hires Fix, Refiner correctness

Makes preview trustworthy

14. Additional Notes

This PR is foundational:
It eliminates the single biggest source of system-wide inconsistency:
divergent prompt/config assembly paths.

After PR-E, all remaining defects become observable and predictable, allowing PR-F (GUI completeness), PR-G (full-stage card sync), and PR-H (preset/style expansion) to proceed cleanly.