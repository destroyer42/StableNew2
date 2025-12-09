DEBUG HUB v2.6.md
Canonical Specification

Status: Mandatory
Last Updated: 2025-12-09

0. Purpose

Debug Hub v2.6 is the single diagnostic surface for all pipeline, builder, and job-execution introspection within StableNew. It exposes:

Prompt layering (row → pack → global negative → overrides)

Config layering (pack config → variant overrides → stage chain)

Randomizer matrix derivations

Sweep expansions

Final, immutable NJR contents

Pipeline execution timeline

Runner lifecycle events

Error + failure metadata

DebugHub never mutates data, never edits configs, never builds jobs, never interacts with the runner.
It is purely observable.

1. Core Principles

DebugHub v2.6 adheres to five strict invariants.

1.1 Immutability

DebugHub must only read final artifacts:

PromptRow

MatrixVariant

ConfigVariant

StageConfig bundle

NormalizedJobRecord

Runner events

DebugHub may not modify:

PromptPack files

Builder output

History metadata

Runtime pipeline state

GUI state

1.2 Canonical Sources Only

DebugHub consumes data from exactly three locations:

NormalizedJobRecord (NJR) — authoritative snapshot

Lifecycle events streamed from JobService

Config metadata stored in NJR.history → debug_data

DebugHub must not:

fetch prompts from GUI

fetch config from controller

use legacy draft bundles

use state_manager shadow data

All diagnostic surfaces must use the NJR exclusively.

1.3 Deterministic Reconstruction

DebugHub must reproduce ALL effective job inputs exactly as the builder produced them:

Effective prompt

Effective negative

Effective overrides

Stage chain

Model identifiers

Seeds

Per-stage modifiers

DebugHub is required to match:

“If DebugHub recreates the request payload, it must match the original runner payload byte-for-byte.”

Any mismatch indicates:

a regression in builder determinism

a bug in stage resolution

a bug in negative layering

a GUI → controller leakage

prompt drift

1.4 No Runner Dependencies

DebugHub cannot:

ping backend

inspect GPU state

inspect WebUI internal logs

reconstruct the physical images

It views job metadata only, never execution context.

1.5 User-Facing Clarity

DebugHub must:

clearly label each layer

provide readable diffs

show merged config in pretty format

highlight variant-specific values

show negative prompt layers visually

collapse/expand complex sections

2. DebugHub User Interface Structure

DebugHub v2.6 consists of five UI panels, each reflecting a different layer of the execution pipeline.

2.1 Panel 1 — Job Summary

Displays:

Field	Description
job_id	Globally unique identifier
pack_name	PromptPack used
row_index	Which row from the pack
matrix_variant_index	Randomizer variant
config_variant_label	Sweep variant label
batch_index	batch number
model	final chosen model
seed	final seed after resolution
created_at	timestamp

Also exposes a one-sentence "Effective Job Identity" string:

[SDXL_angels R3 | mv=1 | cfg_high | b=0 | seed=12345]

2.2 Panel 2 — Prompt Layering (Canonical)

DebugHub visualizes prompt construction in this strict order:

2.2.1 Source Layers

P1: PromptPack.Row.Positive

P2: PromptPack.JSON.Negatives

P3: Global Negative Prompt (conditional by stage + user toggle)

P4: Runtime Negative Overrides (rare, but supported)

DebugHub must show:

POSITIVE PROMPT LAYERS:
-----------------------------------------
[P1 Row Base]        "angelic warrior..."

NEGATIVE PROMPT LAYERS:
-----------------------------------------
[P2 Pack Negatives]  "bad composition..."
[P3 Global Negative] "blurry, malformed..."
[P4 Overrides]       ""  (none)


DebugHub then displays the Merged Prompt exactly as NJR contains it.

2.3 Panel 3 — Config Layering + Sweep Detail

Config layering is deterministic and follows:

Pack JSON config

ConfigVariant overrides (cfg, steps, sampler, denoising, widths, toggles, etc.)

Stage-specific merges (refiner, hires, upscale, adetailer)

DebugHub shows:

CONFIG LAYERING:
[P1 Pack Default]     cfg=7, steps=25, sampler="DPM++ 2M"
[P2 Variant Override] cfg=10  (label=cfg_high)
[P3 Stage Merges]      hires.enabled=False, refiner.enabled=True

FINAL CONFIG:
{
  "model": "juggernautXL",
  "sampler": "DPM++ 2M",
  "steps": 25,
  "cfg_scale": 10,
  "refiner": {
    "enabled": true,
    "model": "refiner-xl",
    "denoise": 0.35
  },
  "adetailer": {...}
}


DebugHub clearly highlights which values changed due to sweeps.

2.4 Panel 4 — Stage Chain Visualization

DebugHub v2.6 displays the full execution chain:

STAGE CHAIN:
1. txt2img
2. refiner (if enabled)
3. hires (if enabled)
4. upscale (if enabled)
5. adetailer (if enabled)


For each stage, DebugHub shows:

Field	Description
enabled	true/false
model	resolved model
denoise	float
width/height	final dims
sampler	final
seed	inherited or fresh depending on chain rules
2.5 Panel 5 — Lifecycle Timeline and Runner Events

Lifecycle events appear in strict order:

SUBMITTED (t=...)  
QUEUED (t=...)  
RUNNING (t=...)  
STAGE_START txt2img  
STAGE_END txt2img  
STAGE_START refiner  
STAGE_END refiner  
COMPLETED  


If failed:

FAILED: error="Sampler not recognized"


DebugHub must display:

pipeline_controller messages

builder info logs

resolved payload (debug version only)

failure root cause

3. Debug Data Model (Canonical DTOs)

All debug surfaces are based on DebugJobDataV2, embedded inside NJR.history.debug.

class DebugJobDataV2(BaseModel):
    prompt_layers: PromptLayeringData
    config_layers: ConfigLayeringData
    stage_chain: list[StageDebugData]
    seeds: SeedResolutionData
    variant_info: VariantDebugData
    lifecycle: list[LifecycleEvent]
    original_payload: dict | None


No part of DebugHub may build its own DTOs or transform types.

4. Builder → DebugHub Contracts

DebugHub relies on builder providing:

4.1 Required Fields from JobBuilderV2
Field	Source
row text	PromptPack TXT
pack negatives	Pack JSON
global negative applied flag	UnifiedPromptResolver
matrix variant index	RandomizerEngineV2
config variant details	ConfigVariantPlanV2
final config	UnifiedConfigResolver
stage chain	StageResolverV2
seeds	SeedResolver
lifecycle seed state	PipelineController

If any field is missing → builder bug.

5. Failure Mode Diagnostics

DebugHub must automatically detect:

5.1 Prompt Drift

If merged prompt != builder bytestring → warn.

5.2 Config Inconsistency

If final config contains values not attributable to a layer → error.

5.3 Unexpected Stage

If a stage appears in NJR but not in pack JSON → error.

5.4 Missing Variant Data

If config variant label exists but overrides missing → error.

6. Integration with History Panel

History stores snapshots of DebugJobDataV2.

Clicking an item in History loads:

full debug view

variant metadata

prompt layering

config layering

lifecycle timeline

NJR ID

DebugHub must always show details for that specific NJR, not the original PromptPack or current config.

7. Test Requirements for DebugHub v2.6

DebugHub requires three layers of tests:

7.1 Unit Tests

prompt layering order correct

negative stacking correct

variant override diffs computed

stage chain formatting correct

debug data models valid

7.2 Integration Tests

Using real PromptPacks:

verify DebugHub matches builder output

verify lifecycle timeline ordering

verify variant labeling and seed inheritance

verify no GUI-derived values leak into debug

7.3 Golden Path Tests

GP tests that exercise DebugHub:

GP	Requirement
GP6	multi-stage chain correctness
GP7	adetailer stage inclusion
GP8	stage enable/disable integrity
GP9	failure path correctness
GP12	replay consistency

DebugHub must pass all GP tests.

8. Tech Debt Rules (Mandatory)

DebugHub must not depend on:

DraftBundle

PromptConfig or RunPayload

direct controller fields

GUI models

legacy prompt_resolver modules

All DebugHub references to removed modules must be eliminated immediately.

9. DebugHub Roadmap (v2.6 → v2.7)
9.1 v2.6 (Current)

Full canonical layering

Accurate NJR reconstruction

Complete lifecycle events

Sweep + matrix support

Multi-stage chain support

9.2 v2.7 (Planned)

Compare two NJRs side-by-side

“Config lineage view”

“Prompt lineage diff”

Batch visualization improvements

10. Summary

DebugHub is the authoritative diagnostic tool for the entire StableNew pipeline.
Its responsibilities:

✔ Visualize prompt layering
✔ Visualize config layering
✔ Visualize stage chain
✔ Visualize sweep/matrix expansion
✔ Visualize seeds
✔ Visualize lifecycle events
✔ Provide exact NJR reconstruction

Its restrictions:

✘ Never mutate
✘ Never build
✘ Never guess values
✘ Never fetch from GUI
✘ Never use legacy systems

StableNew v2.6's reliability depends on DebugHub producing exact, deterministic introspection of the pipeline.

END — DebugHub_v2.6 (Canonical Edition)