BUILDER PIPELINE DEEP-DIVE (v2.6).md

StableNew - PromptPack Builder and NJR Construction Deep-Dive
Last Updated: 2026-03-29
Status: Canonical

## 0. Scope

This document is the deep-dive for the PromptPack builder path.

It explains how PromptPack-authored image intent becomes deterministic
`NormalizedJobRecord` instances ready for queue-first execution.

It does not describe every intent surface in the product. Reprocess, image
edit, replay, learning, CLI, and video workflow have their own intake paths,
but they must still converge to NJR before execution.

## 1. PromptPack Builder Overview

For PromptPack-authored work, the canonical path is:

PromptPack -> Validation -> Randomizer / matrix expansion -> Config sweeps ->
Prompt resolution -> Config normalization -> JobBuilder -> NJR list

There is no alternate PromptPack execution path.

## 2. Responsibilities

The PromptPack builder path is responsible for:

- row selection
- matrix substitution
- prompt resolution
- config sweep expansion
- normalized execution config construction
- variant metadata creation
- immutable NJR creation

It is not responsible for:

- queue policy
- runner policy
- artifact writing
- history storage
- backend execution

## 3. Deterministic Expansion Dimensions

PromptPack-authored jobs may expand across:

1. selected rows
2. matrix variants
3. config sweep variants
4. images-per-prompt or batch behavior represented in the normalized config
5. seed assignment rules

Expansion must be deterministic for identical inputs.

## 4. Canonical PromptPack Builder Components

### 4.1 Validation

Validation ensures:

- pack files exist
- row text is usable
- metadata is schema-valid
- matrix placeholders reconcile
- pack defaults are legal

### 4.2 Randomizer and matrix resolution

Matrix and randomizer logic operate before queueing and before execution.

The builder must not defer randomization to the runner.

### 4.3 Prompt resolution

Prompt resolution combines:

- selected row text
- matrix substitutions
- applicable global negative behavior
- carried actor provenance from linked intent surfaces when present
- allowed PromptPack-side metadata

For PromptPack work derived from `story_plan` intent, scene-level and shot-
level actor metadata may arrive pre-merged on `plan_origin` before NJR
construction. Prompt resolution may use that carried provenance to inject actor
trigger phrases into the positive prompt and prepend resolved actor LoRA tags
ahead of pack-authored LoRAs with stable de-duplication.

The builder produces final prompt text and final LoRA prompt ordering stored on
the NJR-backed job.

### 4.4 Config normalization

The builder path produces stage-ready normalized execution config from:

- pack defaults
- user overrides
- sweep variants
- allowed stage toggles and per-stage settings

The result is executable config, not a draft blob and not a live
`pipeline_config` execution object.

### 4.5 JobBuilder

`JobBuilder` produces immutable NJR-backed records with:

- PromptPack provenance
- resolved prompt text
- normalized execution config
- variant metadata
- output-routing intent
- replayable context

## 5. Builder Output Contract

The builder output for PromptPack work is:

- one or more NJR-backed jobs
- each carrying deterministic execution-ready config
- no fresh-execution `PipelineConfig` dependency
- no GUI-owned prompt/config assembly after build time

## 6. Queue-First Runtime Relationship

Once PromptPack-derived NJRs are built:

- they are submitted to `JobService`
- fresh execution is queue-only
- `PipelineRunner` consumes NJR-backed normalized config
- history stores NJR-backed provenance and canonical result summaries

Any actor-aware prompt or LoRA augmentation is complete before queue
submission. The builder does not own execution or result recording.

## 7. Invariants

The PromptPack builder path must preserve:

- immutable NJR output
- deterministic expansion
- carried actor provenance through canonical intent/config layering when
  present
- no GUI prompt construction
- no runtime randomization
- no direct runner invocation for fresh execution

## 8. Forbidden Patterns

The following are defects:

- building fresh execution payloads directly in GUI code
- rebuilding execution config inside the runner
- storing draft-only config as executable runtime truth
- treating PromptPack as the only valid intent surface across the entire product

## 9. Relationship To Other Intent Surfaces

Other surfaces may build NJR-backed work without PromptPack:

- replay
- reprocess
- image edit
- learning-generated submissions
- CLI
- video workflow

That does not weaken the PromptPack builder path. It simply means this document
is the deep-dive for one canonical builder family, not the whole product.
