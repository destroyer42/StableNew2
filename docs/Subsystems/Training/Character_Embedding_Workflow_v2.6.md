Character_Embedding_Workflow_v2.6.md

Status: Active subsystem reference
Updated: 2026-03-29

## 0. Purpose

This document describes the shipped character training surface in StableNew
v2.6.

The current scope is deliberately narrow:

- queue-backed `train_lora` submission
- runner-owned subprocess execution of an external trainer command
- manifest registration of produced weights plus prompt-side lookup metadata
- a thin Tk Character Training tab for operator submission

This feature does not create a second runtime architecture. Character training
still follows the canonical path:

`Character Training Tab -> AppController -> PipelineRunRequest -> JobBuilderV2 -> NormalizedJobRecord -> JobService Queue -> PipelineRunner -> CharacterEmbedder subprocess -> LoRAManager manifest`

## 1. Prerequisites

StableNew does not ship a trainer backend. A training job requires one of the
following:

- a `trainer_command` provided in the Character Training form
- the `STABLENEW_TRAIN_LORA_COMMAND` environment variable

If neither is set, submission still succeeds as a queued NJR, but runtime
execution fails fast with a clear configuration error instead of hanging the
GUI or inventing a fallback path.

## 2. Submission Surface

The Character Training tab captures these fields:

- `character_name`
- `image_dir`
- `output_dir`
- `epochs`
- `learning_rate`
- optional `base_model`
- optional `trigger_phrase`
- optional `rank`
- optional `network_alpha`
- optional `trainer_command`

Validation rules enforced before queue submission:

- character name is required
- image directory must exist
- output directory is required
- epochs must be a positive integer
- learning rate must be a positive number
- rank and network alpha must be positive integers when present

## 3. Canonical Execution Contract

The execution config carries a standalone `train_lora` block and the matching
`pipeline.train_lora_enabled` flag.

Rules:

- `train_lora` is a valid standalone stage type
- `train_lora` must be the only enabled stage in the NJR
- `train_lora` does not produce image artifacts
- the runner records a weight artifact and manifest registration instead

The current validated payload includes:

- `character_name`
- `image_dir`
- `output_dir`
- `epochs`
- `learning_rate` / `lr`
- optional `base_model`
- optional `trigger_phrase`
- optional `rank`
- optional `network_alpha`
- optional `trainer_command`
- optional `trainer_args`
- optional `trainer_working_dir`
- optional explicit produced-weight hints for deterministic wrappers/tests

## 4. Runtime Behavior

`CharacterEmbedder` owns the external process seam.

Current behavior:

- builds a trainer command from the payload or environment
- launches the trainer as a subprocess
- captures a bounded log tail
- polls until completion
- supports cooperative cancellation via the existing cancel token path
- resolves the produced weight path from an explicit hint or the output folder

`LoRAManager` owns the lightweight character-weight manifest under
`data/embeddings/manifest.json`.

Each registered entry stores:

- character name
- resolved weight path
- resolved `trigger_phrase` when supplied
- resolved LoRA name metadata used for prompt-side resolution
- registration timestamp
- lightweight metadata such as job identity

This metadata is stored so follow-on PromptPack and `plan_origin` actor
resolution can reuse the character-training manifest as the canonical
actor-to-LoRA lookup surface. The current shipped scope is still manifest-
backed runtime plumbing, not richer GUI multi-character authoring.

## 5. Dataset And Output Guidance

Current operator guidance:

- keep one character per image directory
- use a stable output directory such as `data/embeddings`
- keep trainer-specific dataset preparation outside StableNew for now
- treat the manifest as the canonical lookup surface for produced weights

## 6. Current Limits

What this PR ships:

- queue-safe training submission
- subprocess-based execution
- manifest registration and lookup by character name
- persistence of `trigger_phrase` and LoRA naming metadata for follow-on
  prompt-side actor resolution

What remains follow-on work:

- richer GUI prompt-side application of character assets in authoring surfaces
- richer multi-character orchestration in scene and prompt planning
- style-LoRA specialization beyond the generic manifest surface
- dataset preparation helpers and trainer-specific presets
