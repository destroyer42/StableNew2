#CANONICAL
E2E_Golden_Path_Test_Matrix_v2.6.md
End-to-End Validation Suite for StableNew v2.6 (CORE A–E)

Status: Canonical
Updated: 2025-12-08
Covers: PromptPack-Only Architecture • Deterministic Builder • Queue/Runner Lifecycle • UI Panels • Learning • Debug Hub • Config Sweeps • Global Negative Layering • Multi-Stage Pipelines

1. Overview

The purpose of this document is to define the Golden Path test suite for StableNew v2.6—
the essential E2E flows that must work flawlessly before any advanced features can be trusted.

The Golden Path validates the full canonical execution path:

Advanced Prompt Builder
→ PromptPack TXT + JSON
→ Pipeline Tab (PromptPack-only)
→ Controller
→ ConfigMergerV2
→ RandomizationPlanV2
→ ConfigVariantPlanV2 (PR-CORE-E)
→ RandomizerEngineV2
→ UnifiedPromptResolver
→ UnifiedConfigResolver
→ JobBuilderV2
→ NormalizedJobRecord[]
→ JobService / Queue
→ Runner
→ Outputs
→ History
→ Learning
→ Debug Hub


The scenarios:

Begin exclusively from user-visible flows (Pipeline Tab, Queue actions, History restore)

Traverse the entire controller → builder → queue → runner → history → learning chain

Assert state in GUI panels (Queue, Running Job, History, Debug Hub)

Exercise deterministic expansion rules across:

PromptPack rows

Randomization matrix variants

Config sweeps

Batch sizes

Multi-stage SDXL pipelines

ADetailer

Global negative application

Respect PromptPack-only invariant: NO free-text prompting outside the Pack Editor

2. High-Level Test Matrix (Updated for v2.6)

Each scenario maps to CORE modules:

A — CORE-A: UnifiedJobSummary / single source of truth

B — CORE-B: Deterministic builder pipeline

C — CORE-C: Queue/Runner lifecycle

D — CORE-D: UI/Preview/History/Debug correctness

E — CORE-E: Config sweeps + global negative integration

Updated matrix:

ID	Scenario Name	Mode	Randomizer	Sweeps	Stages	CORE Coverage
GP1	Single Simple Run (No Randomizer)	Run Now	Off	Off	txt2img	A, B, C, D
GP2	Queue-Only Run (Multiple Jobs, FIFO)	Queue	Off	Off	txt2img	A, B, C, D
GP3	Batch Expansion (N>1)	Run Now	Off	Off	txt2img	B, C, D
GP4	Randomizer Variant Sweep (No Batch)	Run Now	On	Off	txt2img	B, C, D
GP5	Randomizer × Batch Cross Product	Queue	On	Off	txt2img	B, C, D
GP6	Multi-Stage SDXL (Refiner + Hires + Upscale)	Run Now	Off	Off	txt2img → refiner → hires → upscale	B, C, D
GP7	ADetailer + Multi-Stage Combination	Queue	Off	Off	txt2img → adetailer → refiner → hires	B, C, D
GP8	Stage Enable/Disable Integrity	Run Now	Off	Off	Any stage combination	B, C, D
GP9	Failure Path (Runner Error)	Run Now	Off	Off	txt2img	A, C, D
GP10	Learning Integration	Queue	Off/On	Off	typical multi-stage	C, D
GP11	Mixed Queue (Randomized + Non-Randomized)	Queue	Mixed	Off	txt2img / multi-stage	A, B, C, D
GP12	Restore from History → Re-Run	Run Now	Off/On	Off	any	A, B, C, D
GP13	Config Sweep (PR-CORE-E)	Run Now	Off	On	txt2img	A, B, C, D, E
GP14	Config Sweep × Randomizer Matrix	Queue	On	On	txt2img	B, C, D, E
GP15	Global Negative Application Integrity	Run Now	Off/On	Off	any	B, C, D, E

GP13–GP15 are new for v2.6 and validate PR-CORE-E.

3. Scenario Details (Updated & Expanded)

Below: Each scenario includes:

Preconditions

Steps

Expected results

Core coverage

Relevant architectural links

GP1 — Single Simple Run (No Randomizer)

Purpose: Validate the absolute minimum viable loop.

Preconditions

One PromptPack exists.

Randomizer disabled.

All optional stages disabled.

RunMode: DIRECT.

Steps

In Pipeline Tab: select PromptPack + ConfigPreset.

Confirm Preview summary correct.

Click Run Now.

Poll JobService → History for completion.

Inspect Queue panel, RunningJob panel, History, Debug Hub.

Expected

Builder emits exactly 1 NormalizedJobRecord.

variant_index=0, batch_index=0.

Queue transitions: SUBMITTED → QUEUED → RUNNING → COMPLETED.

Debug Hub “Explain Job” shows full builder trace (prompt, slot resolution, config).

History entry contains correct UnifiedJobSummary.

Coverage

A, B, C, D

GP2 — Queue-Only Run (Multiple Jobs, FIFO)

Purpose: Validate deterministic queue ordering.

Steps

Build PromptPack job A → “Add to Queue”.

Build PromptPack job B → “Add to Queue”.

Poll until both complete.

Expected

FIFO order: A then B.

Runner processes A fully before starting B.

Queue panel shows predictable status transitions.

Debug Hub logs lifecycle events in correct order.

Coverage

A, B, C, D

GP3 — Batch Expansion (Batch > 1)

Purpose: Validate batch fan-out.

Steps

Set batch size = 3.

Run Now.

Expected

Builder emits 3 records: batch_index=0,1,2.

Prompts identical.

Queue runs 3 jobs.

History contains 3 entries.

Coverage

B, C, D

GP4 — Randomizer Variant Sweep (Single Batch)

Purpose: Validate matrix → variants → substitution.

Preconditions

Pack JSON contains matrix slots (environment, lighting).

Randomizer enabled.

Steps

Select pack with tokens in TXT.

Enable randomizer (e.g., 3 variants).

Run Now.

Expected

Builder produces 3 variants with distinct variant_index.

Prompts contain substituted slot values.

Debug Hub shows substitution steps.

Coverage

B, C, D

GP5 — Randomizer × Batch Cross Product

Purpose: Validate 2D expansion (matrix × batch).

Steps

Enable randomizer (2 variants).

Set batch size = 2.

Add to Queue.

Expected

4 jobs emitted.

Distinct combinations: (variant 0, batch 0‒1), (variant 1, batch 0‒1).

Queue handles everything cleanly.

Coverage

B, C, D

GP6 — Multi-Stage SDXL Pipeline: Refiner + Hires + Upscale
Steps

Enable Refiner, Hires, Upscale.

Run Now.

Expected

UnifiedConfigResolver builds canonical StageChain.

Runner receives structured stage configurations.

Debug Hub Explain Job shows the full stage chain.

Coverage

B, C, D

GP7 — ADetailer + Multi-Stage
Steps

Start from GP6 config.

Enable ADetailer.

Add to Queue.

Expected

Stage chain includes AD at correct position.

AD config appears in job record.

Coverage

B, C, D

GP8 — Stage Enable/Disable Integrity
Steps

Run with all stages enabled.

Disable refiner + hires; rerun.

Expected

New job’s stage chain omits disabled stages.

No stale data persists between runs.

Builder respects StageOverridesBundle.

Coverage

B, C, D

GP9 — Failure Path (Runner Error)
Steps

Trigger controlled runner error (invalid sampler, etc).

Run Now.

Expected

Job transitions to FAILED.

Queue not stuck.

History contains error details.

Debug Hub shows runner crash logs.

Coverage

A, C, D

GP10 — Learning Integration
Steps

Run job.

Open Learning Tab.

Rate the output.

Expected

Learning receives full job metadata.

Ratings saved independently of History.

Coverage

C, D

GP11 — Mixed Queue (Randomized + Non-Randomized)
Steps

Queue job A (simple).

Queue job B (randomized).

Run job C (Run Now).

Allow queue to drain.

Expected

Correct interleaving: A, B-variants, C.

No config contamination.

History clear about variant metadata.

Coverage

A, B, C, D

GP12 — Restore from History → Re-Run
Steps

Run job.

In History: Restore to Pipeline.

Run again.

Expected

Restored GUI state matches canonical summary.

Second run produces identical prompt & config signature.

Two history entries, same configuration, different timestamp.

Coverage

A, B, C, D

New for PR-CORE-E
GP13 — Config Sweep (PR-CORE-E)

Purpose: Validate ConfigVariantPlanV2 → builder → queue path.

Preconditions

Sweep Designer enabled.

Multiple cfg/steps/sampler variants defined.

Steps

Create sweep with e.g., cfg=[4.5,7.0,10.0].

Run Now.

Expected

Builder emits N jobs, one per variant.

Prompts identical.

Config differs exactly as defined.

Metadata fields: config_variant_label, config_variant_index, config_variant_overrides.

History entries clearly separate variants.

Coverage

A, B, C, D, E

GP14 — Config Sweep × Matrix Randomizer
Steps

Enable randomizer: M variants.

Enable config sweep: N variants.

Batch size=1.

Add to Queue.

Expected

Total jobs = N × M.

JobBuilderV2 expands cross-product deterministically.

Learning & History show full metadata for both config-sweep and matrix-variant.

Coverage

B, C, D, E

GP15 — Global Negative Integration
Preconditions

Global negative defined in app settings.

Per-stage apply flags in pack JSON.

Steps

Enable global negative in Pipeline Tab.

Run Now.

Disable global negative; run again.

Expected

UnifiedPromptResolver produces different final negative prompts depending on toggles.

History and Debug Hub clearly show whether global negative applied.

No mutation of pack JSON.

Coverage

B, C, D, E

4. E2E Testing Guardrails (Required)

These apply to all scenarios:

No direct sleeps

Use JobService/History polling with timeouts.

Never assert on original job object

Always assert on UnifiedJobSummary, History records, Debug Hub logs, or NormalizedJobRecord copies.

Never bypass controller → builder → queue flow

No calling the runner directly.
No tests that inject unnormalized jobs.

Keep E2E tests small in count but large in coverage

Use matrix expansion rather than dozens of individual tests.

Always use PromptPack-only inputs

No free-text prompts in Pipeline Tab.
All prompts come from PromptPack TXT.

5. Artifacts Produced per Run

Each E2E scenario should verify:

History

job_id

prompt_pack_id

variant_index, batch_index

config_variant metadata (if any)

stage chain

final prompts

negative layering

success/failure

timestamp

Debug Hub

lifecycle logs

final resolved payload

explainers (matrix slot substitution & config sweep choice)

Learning

prompt & config signature

metadata for scoring

user ratings

Outputs

correctly named files

metadata in output sidecar JSON

6. Coverage Summary

This E2E matrix covers every CORE module:

CORE	Description	Covered In
A	UnifiedJobSummary / source-of-truth	GP1, GP2, GP9, GP11, GP12, GP13
B	Deterministic builder pipeline	GP1–GP15
C	Queue/Runner lifecycle	GP1–GP15
D	UI recovery & panel correctness	GP1–GP15
E	Config sweeps + global negative integration	GP13–GP15
7. Conclusion

These E2E Golden Path tests define the minimum acceptable functionality for a StableNew v2.6 build.
If these pass, the system is usable end-to-end.
If these fail, the system is unstable for real users regardless of how many unit tests pass.

This matrix becomes the benchmark for future regressions, major refactors, and new features.