BUILDER PIPELINE DEEP-DIVE (v2.6).md

StableNew – Canonical Execution Architecture
Last Updated: 2025-12-09
Status: Canonical**

0. Purpose

This document provides a full internal breakdown of the Builder Pipeline—the subsystem that converts a user’s PromptPack selection into a fully deterministic graph of NormalizedJobRecord (NJR) objects to be executed by the runner.

This is the definitive reference for:

how PromptPack selection becomes a job

how randomization, matrix slots, config sweeps, and overrides are resolved

exactly how NJRs are built and validated

the allowed vs forbidden behaviors in the builder path

how PR-CORE-A/B/C/D/E integrate

If behavior contradicts this file, the code must be updated.

1. Builder Pipeline Overview

The Builder Pipeline begins after the user selects:

PromptPack

Row(s)

Config overrides

Randomization settings

Config sweeps

Enable/disable global negative

…and ends with a list of NJR objects ready for queue/runner execution.

2. End-to-End Flow (High Level)
PromptPack (txt+json)
        ↓
Validation Layer
        ↓
RandomizerEngineV2 (matrix expansion)
        ↓
ConfigVariantPlanV2 (sweep expansion)
        ↓
UnifiedPromptResolver (positive + negative)
        ↓
UnifiedConfigResolver (pipeline config per stage)
        ↓
JobBuilderV2 (Cartesian expansion)
        ↓
NormalizedJobRecord[]


There is no alternate path.
No GUI prompt text.
No legacy payloads.
No ad-hoc job dicts.

3. Builder Pipeline Responsibilities

The builder pipeline is responsible for exactly:

Prompt resolution

Randomization / matrix substitution

Sweep expansion

Stage chain assembly

Config override application

Seed allocation

NJR creation (immutable)

Validation of final records

It is not responsible for:

queue behavior

runner behavior

model execution

preview panel formatting

writing image files

pack editing

4. The Five Deterministic Expansion Dimensions

Every job produced by the Builder Pipeline arises from:

(1) Row selection — which line(s) of the PromptPack are chosen
(2) Matrix Randomization — substitution for each slot
(3) Config Variants — parameter sweeps
(4) Batch size — N images per job
(5) Seed generation — deterministic if seed fixed, random otherwise

The total job count:

job_count = rows × matrix_variants × config_variants × batch_size

5. Core Components (Canonical Definitions)
5.1 RandomizerEngineV2

Generates matrix slot combinations:

Inputs:

Pack JSON matrix definition

Randomization settings (sampling mode, count)

Outputs:

A list of MatrixVariant objects:

{
  "slot_values": { "character": "knight", "environment": "desert" },
  "index": 0
}


Engine produces fully deterministic variants for repeatability.

5.2 ConfigVariantPlanV2

From PR-CORE-E, used for sweeps:

[
  {
    "label": "cfg_low",
    "overrides": {"txt2img.cfg_scale": 4.5},
    "index": 0
  },
  {
    "label": "cfg_high",
    "overrides": {"txt2img.cfg_scale": 10.0},
    "index": 1
  }
]


This applies per job, never globally.
Does not modify PromptPack or presets.

5.3 UnifiedPromptResolver
Inputs:

raw TXT row

slot substitution values

global negative + stage flags

override-negative (future reserved)

Outputs:
ResolvedPositivePrompt
ResolvedNegativePrompt
resolved_metadata (matrix slot map, global-negative-applied flag)


Rules:

Substitute slots first

Layer negatives in canonical order

Produce final prompt text used by NJR

The runner sees only these final strings.

5.4 UnifiedConfigResolver

Combines:

Pack JSON defaults

Config snapshot

Per-run overrides

Sweep variant overrides

Stage flags

Global negative (if applicable)

Produces full config per stage:

txt2img: width, height, sampler, steps, cfg, model, negative, seed…
refiner: enabled?, strength, model…
hires: enabled?, upscale factor…
adetailer: enabled?, face model…


No inference outside the pack + overrides.

5.5 NormalizedJobRecord (NJR)

The canonical execution DTO.

Contains:

Resolved prompt text

Resolved negative text

Complete pipeline config

Stage chain

Randomizer result

Sweep variant label + index

Seeds

PromptPack origin metadata

Global-negative-applied flags

Batch index

Everything runner needs

Immutable

After creation, NJR may not be mutated.
If any component requires mutation → new NJR must be built.

6. JobBuilderV2 – Internal Mechanics
6.1 Master Build Loop
for row in selected_rows:
  for cfg_variant in sweep_variants:
    for matrix_variant in matrix_variants:
      for b in range(batch_size):
         yield NJR


This loop must remain simple, pure, predictable.

6.2 Row Resolution
resolved_txt = substitute_slots(row, matrix_variant.slot_values)


If a slot is missing → validation error.

6.3 Negative Layering
final_neg = (
    pack_negatives     # currently none in v2.6
    + global_negative  # if enabled for this stage
    + override_negative # future reserved
)

6.4 Config Resolution Flow
config = merge(
  pack_defaults,
  runtime_overrides,
  sweep_variant.overrides
)
config = apply_stage_chain(config)
config = embed_negative(config, final_neg)
config = assign_seed(config, user_seed or random)

6.5 Stage Assembly
stage_chain = [
  StageConfig("txt2img", config.txt2img, enabled=True),
  StageConfig("img2img", config.img2img, enabled=False),
  ...
]


Illegal chains are pre-blocked via pack schema validation.

6.6 NJR Creation
NJR(
  prompt=resolved_txt,
  negative=final_neg,
  row_index=row.index,
  matrix_index=matrix_variant.index,
  matrix_values=matrix_variant.slot_values,
  config_variant_label=cfg_variant.label,
  config_variant_index=cfg_variant.index,
  config_variant_overrides=cfg_variant.overrides,
  stage_chain=stage_chain,
  seed=seed,
  batch_index=b,
  pack_name=pack.name,
  pack_version=pack.version
)

7. Builder Pipeline Invariants

The Builder Pipeline must always comply with:

7.1 Single Source of Prompt Truth

Only PromptPack TXT rows supply prompt text.

Forbidden:

GUI text fields

Controller-provided prompts

Legacy draft bundles

“Manual prompt” mode

7.2 Single Builder Path

Only JobBuilderV2 may construct jobs.

7.3 PromptPack Immutability

Execution cannot modify PromptPack files.

7.4 Determinism

Given identical input → builder produces identical NJRs.

7.5 No Silent Defaults

If a config field is missing, builder must:

fill with explicit pack default or

raise an error
but never silently substitute hidden values.

7.6 No Runner-Dependent Behavior

Builder must not ask the runner for information.

### 7.7 **CORE1 Hybrid State Note** (PR-CORE1-A3, December 2025)

**JobBuilderV2 Role:**
- JobBuilderV2 is the canonical builder for **NormalizedJobRecord**
- All job construction goes through JobBuilderV2.build_jobs()
- Produces immutable NJR instances with complete execution metadata

**JobBundle / JobBundleBuilder Status:**
- **Legacy but active** during CORE1-A/B phases
- Used for:
  - PipelineController draft job lifecycle (`_draft_bundle`)
  - Preview panel display via JobBundleSummaryDTO
  - Some end-to-end tests
- **NOT scheduled for removal in PR-CORE1-A3**
- Will be retired in **CORE1-D/CORE1-E** after full NJR-only migration

**Why Both Exist:**
- JobBuilderV2: New, canonical, NJR-producing builder
- JobBundleBuilder: Transitional support for draft job features
- Display layer fully migrated to NJR (PR-CORE1-A3)
- Execution layer migration to NJR-only pending CORE1-B

**Rules:**
- ✅ New features MUST use JobBuilderV2
- ✅ Display DTOs MUST derive from NJR, not JobBundle
- ⚠️ JobBundle remains valid for draft features until CORE1-D
- ❌ Do NOT add new JobBundle-based execution paths

### 7.8 **NJR-Only Job Construction** (PR-CORE1-B3)

- NJRs are the only execution payload produced by JobBuilderV2 for v2.6 jobs; pipeline_config is left None.
- PipelineController._to_queue_job() attaches _normalized_record, sets pipeline_config = None, and builds NJR-driven queue/history snapshots.
- Queue, JobService, Runner, and History rely on NJR snapshots for display/execution. Any non-null pipeline_config values belong to legacy pre-v2.6 data.

8. Builder Diagnostics & Debug Hooks (DebugHub v2.6)

The Builder Pipeline emits a structured DTO:

BuilderDebugInfo {
  prompt_layers: [...],
  matrix_slot_values: {...},
  config_final: {...},
  stage_chain: [...],
  sweep_variant: {...},
  negative_layers: [...],
  computed_seed: 12345,
  njr_preview: {...}
}


DebugHub surfaces:

pre-NJR prompt layer stack

final config after merges

slot substitution map

sweep variant metadata

stage sequence

seed path

This is essential for correctness testing and learning.

9. Interaction with Tech-Debt Cleanup (2025–2026)

The Builder Pipeline is replacing:

Legacy Component	Status
Legacy PromptResolver	Delete
Legacy JobDraft / DraftBundle	Delete
Legacy RunPayload	Delete
All ad-hoc job dicts in GUI	Delete
Old stage sequencing logic	Delete
PromptPack v1 schema	Delete
Builder functions in AppController	Delete (move to JobBuilderV2)

The Pipeline must become:

the only job construction path

the only prompt resolution engine

the only config resolution engine

10. Golden Path Integration (E2E)

Builder Pipeline participates in Golden Path tests:

GP1 – Simple Single-Row Job
GP2 – Matrix Randomization
GP3 – Config Sweep Expansion
GP4 – Seeds & Determinism
GP5 – Stage Chain Enforcement
GP6 – Global Negative Integration
GP7 – Learning Replay Consistency

All Golden Path failures produce BuilderDiagnostic output.

11. Failure Modes & Required Behavior
A. Invalid Matrix Slot

→ Builder error with slot name and row index.

B. Invalid Config Override

→ Reject PR or block run.

C. Illegal Stage Chain

→ Validation error at Preview stage.

D. Missing Defaults

→ Validation error (no silent repair).

E. Empty PromptPack

→ Fatal; cannot build.

F. Zero jobs produced

→ Fatal; pipeline must abort.

12. Testing the Builder Pipeline
12.1 Unit Tests

slot substitution

negative layering

config merging

sweep expansion

seed assignment

NJR immutability

12.2 Integration Tests

Golden Path full-chain tests

replaying NJR into runner consistently

12.3 Fuzz Tests

random PromptPacks

random sweep shapes

random matrix structures

No builder code may be merged without test coverage.

13. Summary: Why the Builder Pipeline Exists

To eliminate:

4 execution paths

3 job formats

2 prompt sources

dozens of legacy shims

thousands of lines of architectural debt

…and replace them with:

One job format: NJR

One prompt source: PromptPack

One builder: JobBuilderV2

This creates:

Stability

Predictability

Testability

Performance consistency

Clean controller architecture

Learning-ready metadata

END OF BUILDER PIPELINE DEEP-DIVE v2.6 (Canonical Edition)