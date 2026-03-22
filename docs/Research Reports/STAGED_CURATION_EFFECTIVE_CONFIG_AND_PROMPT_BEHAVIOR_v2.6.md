# Staged Curation Effective Config and Prompt Behavior v2.6

Status: Research / Implementation Guidance  
Date: 2026-03-22  
Branch baseline: `feature/video-secondary-motion-pr-236`  
Applies to: Learning, Staged Curation, Review, reprocess, derived-stage queueing

## 0. Purpose

This note documents what the current direct staged-curation-to-queue path actually
applies for prompts, model/settings, and stage-specific behavior.

It is intended to remove ambiguity before the hybrid `Queue Now` + `Edit in Review`
workflow is implemented.

## 1. Short Answer

The current direct queue path is **not** applying a separate learning-optimized prompt
or a dynamic learning-tuned config profile.

Instead, it primarily uses:

1. source image metadata recovered from the selected staged-curation candidate
2. a fallback baseline config from the current app/stage-card baseline
3. target-stage derivation rules from the staged-curation builder
4. predefined face-triage tier presets when the target stage is `face_triage`

So the current queue path is best understood as:

- **source-derived reprocess config + target-stage routing**, not
- **learning-generated prompt/config rewrite**

## 2. Current Direct Queue Flow

### 2.1 Selection phase

In staged curation, the operator records decisions such as:

- `advanced_to_refine`
- `advanced_to_face_triage`
- `advanced_to_upscale`

These are stored as canonical selection events.

### 2.2 Submission phase

When the operator clicks:

- `Generate Refine Jobs`
- `Generate Face Jobs`
- `Generate Upscale Jobs`

StableNew currently:

- loads the selected staged-curation group
- filters candidates by latest decision
- rebuilds reprocess source context from the source image
- derives normal NJR-backed reprocess jobs
- immediately enqueues those jobs

There is currently no intermediate Review/edit step.

## 3. Where The Prompt Comes From

For direct staged-curation queueing, the prompt is inherited from the selected source
artifact, not generated from learning recommendations.

### 3.1 Source reconstruction path

The controller rebuilds a `ReprocessSourceItem` from the selected discovered-review
item by inspecting the source image and its embedded metadata.

That recovery path attempts to pull:

- positive prompt
- negative prompt
- model
- vae
- config block

from embedded metadata and the discovered item.

### 3.2 Effective prompt behavior

For direct queueing, the effective prompt is generally:

- `prompt = source.prompt`
- `negative_prompt = source.negative_prompt`

This means the direct queue path is currently **prompt-inheriting**, not
**prompt-editing**.

### 3.3 What is not happening

The following are **not** part of the current direct staged-curation queue path:

- no learned prompt rewrite
- no automatic prompt delta based on reason tags
- no automatic prompt optimization driven by learning analytics
- no explicit operator-visible prompt diff before enqueue

## 4. Where The Config Comes From

The direct queue path uses a merged configuration assembled from multiple sources.

## 4.1 Source recovered config

If the source artifact contains embedded metadata / stage manifest / generation
metadata, StableNew attempts to reconstruct a baseline config from that source.

This is the strongest config source for direct staged-curation queueing.

## 4.2 Fallback baseline config

If source metadata is incomplete, the controller also pulls a fallback baseline config
from the current app state / stage-card state.

This fallback is then merged into the derivation path.

## 4.3 Reprocess builder merge behavior

The reprocess builder groups and builds jobs by merging:

- fallback config
- per-item/source config
- model / vae inheritance
- prompt overrides where stage-specific logic requires them
- image-edit overrides if present

So the effective queued config is currently the result of **config recovery + config
merge**, not a single canonical “learning config preset.”

## 5. Target-Stage Behavior

## 5.1 Refine

Target mapping:

- `refine -> ["img2img"]`

Current behavior:

- inherits source prompt / negative prompt
- inherits recovered source config where available
- merges fallback baseline config
- queues a normal `img2img`-backed reprocess job

Important implication:

- there does **not** appear to be a dedicated staged-curation refine tuning profile
- refine behavior may vary depending on source metadata quality and current fallback
  baseline state

## 5.2 Face Triage

Target mapping:

- `face_triage -> ["adetailer"]`

Current behavior:

- inherits source prompt / negative prompt
- applies per-candidate face-triage tier settings
- queues a normal `adetailer`-backed reprocess job

This is the one target stage with clear automatic preset logic.

### Current face-triage tiers

- `skip`
- `light`
- `medium`
- `heavy`

### Current face-triage tier fields applied

The builder injects stage-specific ADetailer settings such as:

- confidence
- denoise
- steps
- mask padding

Important implication:

- face-triage queueing is automatic only in the sense that it uses a predefined tier
  preset
- it is **not** automatically tuned from historical learning evidence

## 5.3 Upscale

Target mapping:

- `upscale -> ["upscale"]`

Current behavior:

- inherits source prompt / negative prompt
- inherits recovered source config plus fallback baseline
- queues a normal upscale reprocess job

Important implication:

- there does **not** appear to be a dedicated staged-curation upscale preset profile
  in the curation builder

## 6. What The Operator Cannot Currently See Clearly

The current direct queue path hides too much of the effective execution state.

Today, the operator cannot easily see in staged curation:

- the full source prompt
- the full source negative prompt
- the exact effective merged config that will be queued
- whether values came from source metadata vs fallback baseline
- what stage-specific preset is being applied beyond the face-tier selector
- a before/after compare of source vs derived result once intervention finishes

This is why prompt-related reason tags such as:

- `strong_prompt_match`
- `prompt_drift`

are currently under-supported in the Learning UI: the prompt context is not visible
where the operator makes the decision.

## 7. Why This Matters For Hybrid Workflow Design

The hybrid design should treat the current direct queue path as a **fast inherited
reprocess path**, not as a fully inspectable deliberate intervention path.

That means:

- `Queue Now` is appropriate for throughput and obvious cases
- `Edit in Review` is appropriate when the operator needs to:
  - inspect the source prompt
  - change the prompt
  - modify the negative prompt
  - verify stage toggles
  - inspect effective settings before enqueue

## 8. Recommended Clarifications In UI

To remove ambiguity, the product should explicitly distinguish between:

### Queue Now

Meaning:

- use inherited source prompt/config
- apply target-stage derivation rules
- enqueue immediately

### Edit in Review

Meaning:

- move candidate into canonical Review workspace
- allow prompt/config edits
- show effective derived settings before enqueue
- submit only after operator inspection

## 9. Recommended Implementation Follow-Ons

The companion PR sequence should close the current ambiguity by adding:

1. source prompt / negative prompt visibility in staged curation
2. build-vs-enqueue separation in the controller seam
3. Learning -> Review handoff for deliberate edits
4. effective reprocess settings summary in Review
5. source-vs-derived compare after execution

## 10. Bottom Line

Current staged-curation direct queueing is:

- **selection-driven**
- **source-metadata-derived**
- **queue-first**
- **NJR-backed**

It is **not** currently:

- learning-optimized prompt generation
- auto-tuned config generation from learning evidence
- operator-transparent in terms of effective queued settings

That is why the hybrid model is the right next step:

- keep direct queueing for speed
- add Review handoff for inspection and deliberate intervention
- make prompts and effective settings visible before submission
