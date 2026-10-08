Learning_System_Spec_v2.6.md

Status: Canonical subsystem reference
Updated: 2026-10-07

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
`Typed Intent -> Compiler -> NJR -> JobService -> Queue/JobRepository ->
PipelineRunner.run_njr` architecture. Learning-generated work uses its own
typed source descriptor and does not fabricate PromptPack identity.

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

### 2.1 Frozen preview and queue admission

`experiment_id` is a durable opaque identity, distinct from the editable display
name. Build Preview captures canonical JSON containing the effective baseline
prompt/negative prompt, model/VAE/stage configuration, tested variable, variant
values, and images-per-value. Run compiles every variant from that snapshot
before one ordinary `JobService.submit_njrs(all_njrs, SubmissionPolicy())` call.
There is no Learning queue, runner, history, or process authority. A compile or
validation failure admits no variant; after admission each NJR has the normal
independent SQLite lifecycle.

Preview also freezes path-free model identity, canonical policy id, family and
evidence class, exact profile id/version when present, target stage and the
applicable control/feature contract. Run independently validates that frozen
contract; changing a live stage-card model does not reinterpret the experiment.
The canonical model compile-policy seam runs after variable validation and
override. If normalization erases the tested value or changes the frozen exact
profile, the experiment is rejected before batch admission.

New ordinary previews use `learning_executor_base/1` source evidence. Row/Matrix
prompts are frozen as executor-base strings; global text and complete stage
enablement are frozen separately in baseline config. The canonical executor
applies globals once. Ordinary LoRA overrides keep workload and config prompts
consistent. Ratings label base semantics and retain available final runtime
readback separately; causality and recommendation rules are unchanged.

Run refuses older Pack previews that may preapply enabled Global Negative, and
saved previews missing frozen global policy, with **Rebuild Preview** guidance.
It never rewrites saved execution semantics or reinterprets completed NJRs or
replay. Safe complete-policy legacy previews remain usable unchanged. See
`PR-LEARN-141_Ordinary_Global_Prompt_Correctness.md` for the precise legacy policy.

### 2.2 Explicit Model Comparison Study

Snapshots without `study_type` retain `controlled_variable` behavior. The
ordinary Model variable still requires compatible evidenced policy envelopes.
`model_comparison` is a separate image txt2img, PromptPack-only study of at
least two distinct registry-evidenced SDXL or exact qualified model targets.
It freezes one row and the first canonical Matrix vector as a serialized
`PackPromptIntent`, then freezes every effective arm during Build Preview
using canonical model policy, structured prompt adaptation and compile policy.

All arms share the source-intent digest, requested seed/subseed policy, sample
count and exact geometry. The configured backend and geometry must already
support every candidate. Unsupported execution features and incomplete
adaptation evidence refuse preview; no runtime switching or geometry correction
occurs. Fixed settings and effective prompt features may differ by target.

The additive `learning_model_comparison/1` snapshot contract preserves exact
profile/adaptation references, target-adapted structured evidence, executor
base prompts/configuration, frozen executor-owned Global Prompt policy,
embeddings, LoRAs and shared evidence. Global-negative participation may remain
in adaptation evidence, but base prompts do not preapply executor-owned terms.
The canonical executor applies frozen globals; qualified Klein policy disables
standard global/negative semantics. No mutable global source is read at Run.
`prompt_semantics="executor_base_before_globals_and_optimizer"` distinguishes
Preview inputs from literal backend strings. Ratings separately retain available
executor `final_prompt` / `final_negative_prompt` in `runtime_prompt_readback`,
including empty negatives, without inventing final strings when unavailable.
Run validates frozen arms and constructs ordinary
Learning NJRs without reopening source, reading live model evidence or
rerunning adaptation. All arms compile before one atomic JobService admission.

The persisted claim is `target_envelope_preference` with
`causal_one_variable=false`. Equal requested seeds do not mean identical latent
noise across architectures. Existing review/rating UX is reused; conclusions
describe preference under each frozen envelope. See
`PR-LEARN-140_Model_Comparison_Study.md` for contract and bounded scope.

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
- the UI must only surface the intersection of stage-valid variables and
  canonical model/profile-valid capabilities, including stage-local controls.
- the controller must reject invalid stage and input combinations before job submission.

Canonical `ModelPolicy` owns model applicability; Learning never detects model
families or duplicates LoRA compatibility rules. Fixed/restricted controls are
not controlled variables, and optional unverified features are not qualified.
Controlled-variable Model experiments require compatible evidenced policy envelopes. Exact LoRA
experiments require cache-only PR-IMG-117 admission evidence, the supported
stage, and a runnable prompt/style selection within the profile's count limit.
Old definitions stay loadable; invalid ones cannot execute new work.

Image recommendation parameters use the same target projection. Exact-profile
recommendations and automation eligibility require compatible frozen profile
evidence; absent historical proof is not applicability. Immediately before any
stage-card mutation, the whole recommendation patch is revalidated against the
current model/stage policy. See
`PR-LEARN-130D_Model_Scoped_Learning_Capability_Correctness.md`.

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

Records without subscore/context detail receive zero rating-detail adjustment.
Historical experiment rows lacking a durable ID plus frozen snapshot and executed
configuration remain readable, but are excluded from recommendation inference.


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
- `learning_model_comparison_rating` (target-envelope preference, noncausal)
- `review_tab_feedback`

Review-tab feedback and Learning experiment ratings are both stored as learning records, but they must remain semantically distinct.

6. Recommendation Evidence Rules

Recommendations are stage-scoped and evidence-gated.

Rules:

- complete controlled `learning_experiment_rating` data may recommend only the
  field explicitly varied in that frozen experiment
- `experiment_strong` requires at least two distinct tested values and at least
  three rated controlled samples in one durable experiment; row count alone is
  insufficient
- sparse controlled and observational review/curation evidence remains
  manual-only; it never becomes automatic evidence
- incomplete historical experiment rows remain readable but are excluded from
  recommendation inference
- unsupported or unknown record kinds must be ignored
- Model Comparison ratings and snapshots are excluded from ordinary parameter
  recommendations and automatic Model selection
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
- mutate a PromptPack, historical NJR, or historical artifact in place
- automatically tune parameters or add video-learning support

### 7.1 Recommendation application

`suggest_only` is display-only and does not expose an enabled Apply action.
`src/gui_v2/recommendation_targets.py` maps each stage/parameter to its executable
operator control. ADetailer Model targets the checkpoint override, never its
detector; Denoise Strength targets its own denoise variable. ADetailer/upscale VAE
and inherited checkpoint selection use Base Generation (the txt2img card aliases
those variables). Img2img uses its own CFG/steps/sampler/denoise controls and the
inherited Base Generation scheduler/model/VAE. Upscale Factor targets its factor
control. Every target and rollback value is resolved before any Tk mutation;
missing or unrepresentable controls reject the complete patch without partial
application. Unexpected setter failure restores the captured values.

Manual application is confirmation-gated and affects only the current/new
Pipeline draft intent; it never rewrites prior jobs, artifacts, or PromptPacks.

8. Testing Requirements

Learning changes must include:

- persistence and resume coverage
- stage capability validation
- variable selection contract coverage
- rating persistence coverage
- recommendation evidence guard tests
- Golden Path regression validation
- frozen-preview, all-or-none admission, controlled-evidence, and review-focus
  regression coverage

9. PR-LEARN-300 implementation checkpoint

- Execution profile: Standard, Local/Desktop; model recommendation was
  GPT-5.6 Terra High for cross-surface lifecycle/evidence work.
- Controller assessment: the GUI Learning coordinator delegates batch tracking
  to the existing Learning execution controller; no `src/controller/` ratchet
  ceiling changed.
- Token-efficient validation: focused deterministic Learning tests first, raw
  Ruff and controller ratchet, then GitHub required Python 3.11/3.12 CI. The
  local PR gate was attempted once and was blocked only by unavailable mypy.
- Resource-backed Model, VAE, sampler, and scheduler choices read the live
  `AppStateV2.resources` projection through one Learning accessor; refreshes are
  visible without restarting the application and display values map to runtime
  values before compilation.
- Learning output folders use a bounded sanitized experiment label plus a short
  ID discriminator; artifact names expose tested variable/value and variant/sample
  information. Full experiment/variant/job/NJR identity remains authoritative
  metadata, and collision protection remains in the existing pipeline helpers.
- The experiment-wide review workspace groups completed samples by variant/value,
  shows rated/unrated state and per-variant summaries, supports deterministic
  `Next Unrated` and bounded side-by-side comparison, reuses the existing
  full-resolution viewer, and preserves operator focus during background completion.
- Remaining acceptance work: aggregate operator smoke and end-to-end artifact /
  recommendation verification.
