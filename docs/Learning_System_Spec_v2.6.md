Learning_System_Spec_v2.6.md

Status: Canonical
Updated: 2026-03-19

0. Purpose

This document defines the Learning subsystem behavior for StableNew v2.6.
It covers:

- experiment persistence
- stage-aware experiment design
- variable selection contracts
- review and rating capture
- recommendation evidence rules

Learning remains a post-execution subsystem. It consumes outputs and ratings; it
does not build alternate execution paths and it does not modify the canonical
`Intent Surface -> Builder/Compiler -> NJR -> Queue -> Runner` architecture.

Current scope note:

- Learning is still primarily image-stage focused.
- Workflow-video, sequence planning, continuity packs, and story-planning are
  not yet first-class learning surfaces.
- When those arrive, this document must be extended rather than bypassed.
- Adaptive refinement learning is currently limited to compact scalar metadata
  and conservative recommendation context; it does not auto-tune policies or
  persist crops/binary detector artifacts.

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

---

## 5. Rating Detail Analytics (PR-CORE-LEARN-046)

### 5.1 Overview

The recommendation engine consumes richer rating detail when present, while preserving full backward compatibility with older flat-rating records.

### 5.2 Record Shapes

Two on-disk shapes are supported:

| Field | `learning_experiment_rating` | `review_tab_feedback` |
|---|---|---|
| Subscores stored under | `subscores` and `rating_details` | `subscores` |
| Context flags under | `rating_context` | `review_context` |
| Schema version | `rating_schema_version: 2` | absent (0) |

The canonical normalization entry-point is `LearningRecord.extract_rating_detail(metadata)`, which returns `{subscores, context_flags, schema_version}` for any record shape.

### 5.3 Weighting Rules

Context-aware weight adjustments are applied by `RecommendationEngine._apply_rating_detail_adjustment()`.

All adjustments are **deterministic, bounded (±0.15 total), and additive on top of the base contextual weight**. The aggregate `user_rating` remains the primary signal.

| Rule | Condition | Adjustment |
|---|---|---|
| Subscore quality | avg subscore vs 3.0 | `(avg − 3.0) × 0.025` → at most ±0.05 |
| Context mismatch | query has people, record does not, anatomy < 3.0 | −0.10 |

A minimum floor of `0.05` is always applied so no record's weight reaches zero.

### 5.4 People Detection

`RecommendationEngine._build_query_context()` infers `has_people` from the query prompt text using a keyword list (`_PEOPLE_KEYWORDS`). This value is propagated as a string (`"True"`/`"False"`) in the query context dict.

### 5.5 Backward Compatibility

Records without any subscore or context detail receive zero adjustment (the helper returns empty dicts and the adjustment function is a no-op when `subscores` is empty). Older records continue to contribute exactly as before PR-046.


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
- adaptive refinement context may weight or stratify recommendations, but it
  must not bypass existing evidence-tier protections

6.1 Adaptive Refinement Learning Context

When a run carries the canonical `adaptive_refinement` block, Learning stores a
compact summary under `LearningRecord.metadata["adaptive_refinement"]`.

Allowed fields are compact scalar or short-string values such as:

- `mode`
- `profile_id`
- `algorithm_version`
- `policy_id`
- `policy_ids`
- `detector_id`
- `scale_band`
- `pose_band`
- `face_detected`
- `face_count`
- `face_area_ratio`
- `face_height_ratio`
- `face_width_ratio`
- `prompt_intent_band`
- `requested_pose`
- `wants_face_detail`
- `has_prompt_patch`
- `has_applied_overrides`
- `prompt_patch_ops`
- `applied_override_keys`
- `image_decision_count`
- optional cheap local metric: `sharpness_variance`

Rules:

- these learning-facing values must be mapped from the canonical runtime
  `adaptive_refinement` carrier, not renamed into a parallel schema
- image crops, detector frames, and other large binary artifacts remain
  forbidden
- recommendation queries may include refinement context, but resulting
  recommendations stay advisory unless the existing evidence-tier rules already
  permit automation

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
