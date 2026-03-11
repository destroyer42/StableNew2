Learning_System_Spec_v2.6.md

Status: Canonical
Updated: 2026-03-10

0. Purpose

This document defines the Learning subsystem behavior for StableNew v2.6.
It covers:

- experiment persistence
- stage-aware experiment design
- variable selection contracts
- review and rating capture
- recommendation evidence rules

Learning remains a post-execution subsystem. It consumes outputs and ratings; it does not build alternate execution paths and it does not modify the `PromptPack -> Builder -> NJR -> Queue -> Runner` architecture.

1. Learning Workspace

Learning experiments are persisted under:

`data/learning/experiments/{experiment_id}/`

Each experiment workspace stores:

- definition payload
- session payload
- review progress
- references to produced outputs

UI state may remember the last-opened experiment id, but durable experiment state must live in the Learning workspace, not only in generic UI state.

2. Experiment Model

An experiment must capture:

- experiment identity
- target stage
- prompt source
- variable under test
- generated variant values
- images per variant
- optional required input image for image-based stages

The Learning UI may suggest names and descriptions, but the persisted experiment definition is the source of truth.

3. Stage Capability Contract

Learning is stage-aware.

Supported stages:

- `txt2img`
- `img2img`
- `adetailer`
- `upscale`

Rules:

- `txt2img` requires no input image.
- `img2img`, `adetailer`, and `upscale` require an image source.
- the UI must only surface variables that are valid for the selected stage.
- the controller must reject invalid stage and input combinations before job submission.

4. Variable Types

Learning supports three variable families:

- numeric sweep variables
- resource-backed variables
- LoRA-driven variables

4.1 Numeric Variables

Numeric variables use a start / end / step range editor.

Examples:

- steps
- CFG scale
- denoise strength
- upscale factor

4.2 Resource-Backed Variables

Resource-backed variables must use the same normalized WebUI resource feed as Pipeline.

Examples:

- model
- VAE
- sampler
- scheduler

The Learning subsystem must store stable internal values, not raw UI display labels.

4.3 LoRA Variables

LoRA experiments must be derived from runtime prompt and baseline state, not only ad hoc GUI state.

Supported patterns:

- one LoRA across multiple strengths
- multiple LoRAs compared at fixed strength

5. Review and Rating

Learning review uses:

- aggregate user rating
- optional context flags
- optional sub-scores
- freeform notes

Structured rating data must be persisted alongside the aggregate score.

Current record typing:

- `learning_experiment_rating`
- `review_tab_feedback`

Review-tab feedback and Learning experiment ratings are both stored as learning records, but they must remain semantically distinct.

6. Recommendation Evidence Rules

Recommendations are stage-scoped and evidence-gated.

Rules:

- recommendations must prefer `learning_experiment_rating` data when sufficient evidence exists
- sparse experiment evidence must not be replaced with noisy review feedback
- review-tab feedback may be used only when experiment evidence is absent
- unsupported or unknown record kinds must be ignored

If evidence quality is insufficient, the correct behavior is to return no recommendation.

7. Non-Goals

The Learning subsystem does not:

- create alternate job submission paths
- mutate historical outputs
- bypass the queue
- construct PromptPacks from GUI text

8. Testing Requirements

Learning changes must include:

- persistence and resume coverage
- stage capability validation
- variable selection contract coverage
- rating persistence coverage
- recommendation evidence guard tests
- Golden Path regression validation
