PROMPT_PACK_LIFECYCLE_v2.6.md

(Canonical)

StableNew – PromptPack Lifecycle Specification (v2.6)
Last Updated: 2025-12-09
Status: Canonical, Binding**

0. Purpose

A PromptPack is the only input source for all jobs executed in StableNew.

This document defines:

How PromptPacks are created, edited, validated, stored, loaded, and consumed

How PromptPacks integrate with the builder pipeline

How PromptPacks interact with randomization, sweeps, and config defaults

Ownership, restrictions, allowed behaviors, and forbidden behaviors

The entire lifecycle from authoring → execution → history → learning

This document eliminates all legacy v1/v2.0-v2.5 ambiguity.
If behavior contradicts this file, the code must be updated.

1. PromptPack Definition

A PromptPack is defined by exactly two files, same base name:

{name}.txt      # prompt rows
{name}.json     # metadata


No PromptPack exists without both.

1.1 .txt (Prompt Rows)

A list of prompt “rows,” each a self-contained positive prompt.

Each row may contain placeholders for matrix slots.

Rows are indexed (0..N-1).

Rows must be plain text, UTF-8.

Comments are allowed using # at line start.

1.2 .json (Metadata)

The JSON file defines:

A. Matrix Slots

Example:

"matrix": {
  "character": ["knight", "princess", "rogue"],
  "environment": ["forest", "castle"]
}

B. PromptPack Defaults
"defaults": {
  "cfg_scale": 7,
  "steps": 30,
  "sampler": "dpmpp_2m",
  "width": 1024,
  "height": 1024
}

C. Stage Toggles

Reflecting available backend stages:

"stages": {
  "txt2img": true,
  "img2img": false,
  "refiner": false,
  "hires": false,
  "upscale": false,
  "adetailer": false
}

D. Global Negative Stage Flags

Allowing per-stage control:

"apply_global_negative": {
  "txt2img": true,
  "img2img": false,
  "refiner": false,
  "hires": false,
  "upscale": true,
  "adetailer": false
}

E. Tags / Style Metadata (optional)
"tags": ["fantasy", "cinematic", "sdxl"]

F. Versioning

All packs carry a version:

"version": "2.6"

2. PromptPack Lifecycle Overview
Author → Validate → Store → Select → Resolve → Expand → Build NJR → Execute → History → Learning


This lifecycle is strict, deterministic, and enforced.

3. Authoring Phase (Creation & Editing)
3.1 Single Authoring Location

A PromptPack may only be edited inside:

Advanced Prompt Builder (GUI)

TXT editor

JSON editor (structured)

Validation engine

Preview & test substitution panel

Save & publish

Direct file system editing is possible but discouraged.
The GUI version is canonical unless invalid JSON/TXT is detected.

3.2 Rules for Authoring

TXT rows must be valid prompts, not empty.

JSON must be strictly schema-validated.

Matrix slot variables must be referenced using {slot_name} syntax.

Matrix slot definitions in JSON must match placeholders in TXT (detect unused or undefined slots).

Defaults must be valid pipeline config values.

Stage toggles must represent a valid pipeline chain.

3.3 Forbidden at Authoring

Inline free-text negative prompts in TXT (negatives are resolved via JSON + global negative).

Pipeline/executor settings embedded directly in TXT.

Dynamic Python logic or script expressions in TXT.

User-defined placeholders outside matrix slots.

4. Selection Phase (Pipeline Tab)

The pipeline tab does not modify PromptPack data.
It only selects:

PromptPack

Row

Overrides (CFG, steps, sampler, dimensions, stage toggles)

Randomization Settings

Config Sweep Settings

Global Negative Enable Flag (per run)

The pipeline tab constructs a JobDraft inside AppStateV2.

5. Validation Phase

Every PromptPack loaded undergoes:

A. Schema Validation

JSON structure

Required fields

Stage toggles

Defaults

B. Matrix Slot Validation

Check placeholders in TXT exist in JSON

Check JSON matrix slots are referenced at least once

Validate each slot value is string or literal list of strings

C. Prompt Row Validation

Lines must be non-empty unless commented

No leading/trailing control characters

D. Stages Validation

Stage chain must represent a legal pipeline (txt2img first, etc.)

If any validation fails:

Pack is marked invalid

Cannot be selected

Error surfaced in UI

6. Resolution Phase

This phase converts a PromptPack into fully resolved prompt text during job construction (UnifiedPromptResolver).

6.1 Inputs

TXT row

JSON metadata

RandomizerEngineV2 output (matrix variant values)

Global negative

Stage toggles

Config overrides

6.2 Positive Prompt Resolution

Load TXT row

Substitute matrix slot values

Output ResolvedPositivePrompt

6.3 Negative Prompt Resolution

Negative prompt is formed from layers:

Row-level negative (none in v2.6)
Pack-level negative (optional future extension)
Global negative (if stage-enable flag is true)
Runtime negative override (reserved for future learning optimizations)


Output: ResolvedNegativePrompt.

7. Expansion Phase

PromptPacks enable two dimensions of expansion:

Matrix Variants → set by RandomizerEngineV2

Config Variants (Sweeps) → ConfigVariantPlanV2

The total number of jobs:

job_count = rows_selected × matrix_variants × config_variants × batch_size


All expansions are pure and deterministic.

8. Job Construction Phase (JobBuilderV2)

Outputs a list of NormalizedJobRecord objects.

Each NJR stores:

PromptPack metadata

Resolved positive/negative prompts

Randomized slot values

Config sweep overrides

Full pipeline config per stage

Row index

Seeds

Variant IDs

Execution metadata

NJR is immutable and becomes the only job representation allowed further in the system.

9. Execution Phase (Queue & Runner)

PromptPacks no longer participate in execution.
Their resolved content is embedded in NJRs.

Runner does not:

Re-load PromptPack

Resolve slots

Apply defaults

Look up JSON config

Runner consumes only NJR & pipeline config.

10. Post-Execution Phase
10.1 History

Stores:

Full NJR snapshot

Output paths

Timing

Failure reason

Ratings

History → learning system.

10.2 Learning

Learning receives NJR + output → trains scoring model.

Learning may propose:

Better config defaults

Prompt expansions

Negative prompt adjustments

But learning may not modify PromptPack files directly.

11. Ownership Rules (Canonical)
Concern	Owner
Prompt text	PromptPack (.txt)
Matrix slots	PromptPack (.json)
Pack defaults	PromptPack (.json)
Runtime overrides	Pipeline Tab
Sweeps	Pipeline Tab
Global negative	User settings
Job expansion	Builder Pipeline
Job execution	Queue + Runner
History	History Service
Recommendations	Learning System
12. Forbidden Behaviors

The following must not exist:

12.1 GUI Prompt Text Entry

No editing or overriding prompt text in Pipeline Tab.

12.2 PromptPack Mutation During Execution

No controller or pipeline step may modify PromptPack content.

12.3 Legacy Prompt Sources

Forbidden:

“Enter prompt” text boxes

Job payloads storing prompt text

Prompt reconstruction from GUI fields

12.4 Multiple Job Construction Paths

Only the Unified Builder Pipeline is allowed.

12.5 Pack JSON Editing in Pipeline Tab

Only Advanced Prompt Builder may modify packs.

13. Versioning & Migration Rules
13.1 Pack Version Field

Each pack includes:

"version": "2.6"

13.2 Backward Compatibility

If a PromptPack lacks new fields, the validator inserts defaults but never modifies the pack file without user approval.

13.3 Future Extensions

Extensions must go through:

Architecture Proposal

PromptPack JSON schema update

Validator update

Builder Pipeline update

14. Golden Path for PromptPack
1. Author pack in Advanced Prompt Builder
2. Save TXT + JSON
3. Pipeline Tab: select pack + row
4. Configure overrides, sweeps, global negative
5. Builder pipeline resolves prompts, config, variants
6. JobService receives NJRs
7. Runner executes
8. History records results
9. Learning consumes history


Any deviation is considered a bug.

15. Summary of Invariants
15.1 PromptPack is the only prompt source

Nothing else feeds prompt text into jobs.

15.2 PromptPack TXT + JSON form an atomic unit

They are validated together.

15.3 No mutation during job execution

Packs remain static.

15.4 No GUI prompt editing

Pipeline Tab is for configuration only.

15.5 Builder is the sole job constructor

No alternate flows allowed.

15.6 All expansions are deterministic

Randomizer + sweeps yield reproducible paths.

END OF PROMPT_PACK_LIFECYCLE_v2.6.md (Canonical Edition)