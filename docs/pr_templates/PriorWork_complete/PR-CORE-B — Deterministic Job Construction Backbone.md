PR-CORE-B — Deterministic Job Construction Backbone.md

Version: v2.6-CORE
Tier: Tier 3 (builder stack; config merger; prompt+config resolvers; randomizer engine; job builder)
Date: 2025-12-08
Author: ChatGPT (Planner), approved by Rob
Discovery Reference: D-22
Depends on:

PR-CORE-A (UnifiedJobSummary + PromptPack-only invariant + canonical NormalizedJobRecord schema)

1. Summary (Executive Abstract)

PR-CORE-B defines and implements the entire job-construction backbone for StableNew v2.6:

PromptPack → ConfigMergerV2 → UnifiedPromptResolver → UnifiedConfigResolver → RandomizerEngineV2 → JobBuilderV2 → NormalizedJobRecord[list]

This PR makes job construction:

PromptPack-only (Pipeline Tab cannot supply raw prompts)

Deterministic across rows, variants, batches, seeds

Structured using true PromptPack TXT + Config JSON semantics

Pure / side-effect free

Fully compliant with PR-CORE-A’s required job fields (embedding metadata, LoRA tags, stage chain, matrix slot values, aesthetic configs, pipeline semantics, etc.)

The output of PR-CORE-B is a complete, immutable list of NormalizedJobRecord objects, ready for Queue ingestion (PR-CORE-C) and full UI rendering (PR-CORE-D).

2. Motivation / Problem Statement

Previous versions of the builder pipeline suffered from:

Multiple contradictory prompt sources

GUI-injected prompt strings

Incomplete/malformed intermediate job objects

Randomization steps not synchronized with prompt/matrix resolution

Inconsistent merging of preset configs, pack configs, and runtime overrides

No clean isolation between:

prompt construction

stage configuration

variant expansion

batch expansion

seed resolution

Now that PR-CORE-A establishes a strict PromptPack-only origin and a rich, explicit NormalizedJobRecord schema, the builder must:

Precisely fill that schema

Never defer resolution to Queue/Runner/UI

Produce fully populated jobs that can be executed without interpretation

3. Scope & Non-Goals
In Scope

ConfigMergerV2

UnifiedPromptResolver

UnifiedConfigResolver

RandomizerEngineV2

JobBuilderV2

Builder-level helpers (seed resolver, row selection utilities, variant expansion utilities, etc.)

Builder-level validation and fail-fast behavior

Complete test suite for each component

Not In Scope

Queue lifecycle (PR-CORE-C)

UI binding / rendering (PR-CORE-D)

Learning system logic

Preset authoring

PromptPack authoring

4. Architectural Alignment
4.1 PromptPack-Only Invariant (MANDATORY)

PR-CORE-B must enforce:

Every job MUST have a prompt_pack_id.

No builder stage can accept free-text prompts from UI.

Prompt text must come from PromptPack TXT rows + config + matrix substitution.

RandomizationPlan may only vary matrix slots or scalar numeric fields — not the prompt source itself.

4.2 NormalizedJobRecord Compliance

All jobs produced must match the finalized PR-CORE-A record schema, including:

Prompt fields (positive, negative, embeddings, LoRAs)

Config fields (sampler, cfg_scale, stage configs)

Matrix metadata (slot → value per variant)

Variant and batch metadata

PromptPack provenance

4.3 Purity and Determinism

Builder pipeline must be:

Pure functions

Deterministic under same input

Stateless (no global state allowed)

Fully testable in isolation

5. Detailed Subsystem Responsibilities

This section provides the fully canonical definitions for all builder subsystems.

5.1 ConfigMergerV2
Intent

Create a single merged config from:

Preset config

PromptPack config JSON (the file next to your TXT pack)

Runtime overrides from the Pipeline tab

Contract
merged_config = merge(preset_config, pack_config, runtime_overrides)

Rules

Merge order:
runtime_overrides > pack_config > preset_config

No mutation of inputs.

Output must preserve structure:

{
  "txt2img": {...},
  "img2img": {...},
  "upscale": {...},
  "adetailer": {...},
  "pipeline": {...},
  "randomization": {...},
  "aesthetic": {...},
}

Key Values From Real Pack Configs

(Examples extracted from uploaded files)

txt2img: steps, cfg_scale, width/height, model, refiner settings, scheduler/sampler, clip_skip

img2img: steps, denoise, cfg_scale

upscale: upscaler, resize, sampler, denoise

adetailer: enable, model, conf, sampler, steps, prompts, negatives

pipeline: loop_type, loop_count, images_per_prompt, variant_mode

randomization.matrix: slot definitions (environment, lighting, style, camera, world_flavor…)

aesthetic: enabled, weight, text

Validation

Missing required numeric fields (cfg/steps) → fail early

Missing mandatory stage params when enabled → fail

5.2 UnifiedPromptResolver
Intent

Convert a PromptPack TXT row + matrix slot values + merged config into fully-resolved prompts:

positive_prompt

negative_prompt

embeddings

LoRA tags

matrix-substituted subject line

aggregated negatives

Inputs

prompt_pack_id

row_index

prompt_pack_row (parsed row structure)

matrix_slot_values

merged_config.txt2img.negative_prompt

global prepend / global negatives

Outputs

Populate fields required in NormalizedJobRecord:

positive_prompt
negative_prompt
positive_embeddings: list[str]
negative_embeddings: list[str]
lora_tags: list[LoRATag]
matrix_slot_values: dict[str, str]

Behavior

Extract embedding tags from pack line:
Example:

<embedding:stable_yogis_pdxl_positives>

<embedding:stable_yogis_realism_positives_v1>

Extract style/quality line:

(masterpiece, best quality) portrait, detailed skin, ...

Substitute matrix tokens in subject template:

armored angelic knight over [[environment]] → “armored angelic knight over volcanic lair”

Extract LoRA tags with strengths:

<lora:add-detail-xl:0.65>

<lora:JuggernautXL_Hyperrealism:0.55>

Build final positive_prompt string.

Build final negative_prompt string:

pack negatives (“neg: ...”)

negative embedding tags (<embedding:negative_hands>)

prompt_pack JSON negatives (if provided)

global negatives

Validation

Missing matrix slot values → fail

Empty final prompt → fail

5.3 UnifiedConfigResolver
Intent

Produce the complete, resolved, stage-aware configuration for a job.

Inputs

merged_config

Outputs

For NormalizedJobRecord:

stage_chain: list[StageConfig]
seed, cfg_scale, steps, width, height, sampler_name, scheduler, clip_skip
base_model, vae
loop_type, loop_count, images_per_prompt, variant_mode
randomization_enabled, matrix_name, matrix_mode, matrix_prompt_mode

Behavior

Build one StageConfig per enabled stage:

txt2img

img2img

adetailer

upscale

Inherit numeric values from merged config.

Ensure stage order matches architecture (txt2img → img2img → adetailer → hires/upscale).

Validation

Enabled stage missing sampler/steps/denoise → fail

Missing model when txt2img enabled → fail

5.4 RandomizerEngineV2
Intent

Convert the merged config + randomization matrix into a deterministic sequence of VariantConfig objects.

Inputs

merged_config

RandomizationPlanV2 (mode, slot lists, scalar axes, variant_count)

Outputs

List of VariantConfig each containing:

matrix_slot_values: dict[str, str]
scalar_overrides: dict[str, Any]
variant_index: int
resolved_seed: int

Behavior

Determine variant count:

If matrix mode = rotate → slot_value_count

If combine → cross-product

If prompt_mode = prepend → modify prompt construction path

Resolve seeds according to seed mode:

fixed, per-variant, per-batch, etc.

No prompt mutation; variant only drives slot assignments or scalar config changes.

Validation

Empty matrix slots → fail

randomization_enabled but missing variant definitions → fail

5.5 JobBuilderV2
Intent

Expand:

PromptPack Rows × Variants × Batch Size → NormalizedJobRecord instances

Inputs

prompt_pack_id

prompt_pack_name

row_indices

variants: list[VariantConfig]

merged_config

batch_size

run_mode, queue_source (from controller)

Outputs

A full list of NormalizedJobRecord objects.

Record Assembly Requirements

Each record must fully populate:

PromptPack provenance:

prompt_pack_id

prompt_pack_name

prompt_pack_row_index

prompt_pack_version/hash

Prompt fields

Embeddings / LoRAs

Matrix slot values

Config globals

Stage chain

Loop semantics

Aesthetic config

randomization_enabled, matrix_name/mode

variant_index, batch_index

run_mode, queue_source

Seed Logic

Seed must be resolved deterministically based on:

base_seed_from_config
variant_index
batch_index
(optional) row_index hashing

Validation

If no PromptPack row selected → fail

If no variants and randomization_enabled → fail

If any StageConfig is invalid → fail

6. System-Wide Validation & Error Handling
Fast Fail Rules

Builder must stop immediately if:

Missing prompt_pack_id

Missing matrix slot values

Empty positive_prompt

Any required stage field missing

Randomization definitions invalid

Error Surface

Return structured errors back to PipelineController for UI display:

“Prompt Pack not selected”

“Matrix slot ‘environment’ has no value for variant 2”

“adetailer.enabled = true but no sampler/steps provided”

“Empty positive prompt after resolution”

7. Tests
Unit Tests
ConfigMergerV2

Verify expected values match merged JSON snapshots.

UnifiedPromptResolver

Matrix substitutions correct

Embeddings and LoRAs parsed correctly

Negative prompt merged correctly

UnifiedConfigResolver

Stage chains correct

Pipeline-level fields correct

RandomizerEngineV2

Variant count correct

Slot assignment deterministic

Seeds match expected mode

JobBuilderV2

Row × variant × batch → correct record count

Field equality to expected golden examples

Integration Tests (Golden Packs)

Use your real uploaded packs:

SDXL_angelic_warriors_Realistic.txt / .json

SDXL_mythical_beasts_Fantasy.txt / .json

Verify:

StageChain matches config JSON

Seeds ensure reproducible results

Matrix slot substitutions produce correct prompts

LoRA tags & embeddings appear in resolved prompt strings

Job records fully populated

8. Acceptance Criteria

Builder accepts only PromptPack-driven jobs

Outputs only Immutable NormalizedJobRecord objects compliant with PR-CORE-A

All fields populated

No partial records

All resolution logic deterministic

All tests pass

Queue/Runner (PR-CORE-C) can operate exclusively on these records without additional computation

GUI (PR-CORE-D) can render all summaries cleanly

9. Documentation Updates
Must update:

ARCHITECTURE_v2.5.md

Add builder flow diagram

Add PromptPack-only requirement in Job Construction section

Roadmap_v2.5.md

Mark Phase B milestones complete

Note deterministic builder is dependency for Queue & Runner

StableNew_Coding_and_Testing_v2.5.md

Add expectations for builder tests and deterministic seed rules

CHANGELOG.md

Add PR-CORE-B entry

10. CHANGELOG Entry
## [PR-CORE-B] - 2025-12-08
Deterministic Job Construction Backbone (PromptPack-Only)
- Implemented PromptPack-only builder path.
- Added ConfigMergerV2, UnifiedPromptResolver, UnifiedConfigResolver, RandomizerEngineV2, JobBuilderV2.
- All jobs now expressed as immutable NormalizedJobRecord objects.
- Fully deterministic expansion across rows, variants, batches, seeds.
- All downstream systems (Queue, Runner, History, Debug Hub, Learning) now depend on PR-CORE-B outputs.

11. Rollback Plan

Remove PromptPack-only enforcement

Revert NormalizedJobRecord schema

Restore legacy builder behavior

Remove deterministic variant/batch expansion rules

Reintroduce free-text prompts (NOT recommended)

Rollback would severely degrade system correctness and must only be done in emergency.