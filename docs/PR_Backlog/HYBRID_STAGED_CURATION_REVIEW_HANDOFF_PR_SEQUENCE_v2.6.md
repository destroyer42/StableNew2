# Hybrid Staged Curation -> Review Handoff PR Sequence v2.6

Status: Proposed  
Date: 2026-03-22  
Branch baseline: `feature/video-secondary-motion-pr-236`  
Applies to: Learning, Staged Curation, Review, reprocess, derived-stage queueing

## 0. Purpose

This PR sequence closes the current workflow gap where staged-curation decisions can
be turned into immediate queue-backed derived jobs, but the user cannot first move a
candidate into the canonical `Review` workspace to inspect, edit, and deliberately
adjust prompt/config before enqueue.

This sequence preserves the existing queue-first NJR path while adding the missing
manual-intervention handoff.

## 1. Product Goal

Target product behavior:

- `Learning -> Staged Curation` remains the evidence/selection workspace
- `Review` remains the canonical advanced reprocess workspace
- the user gets **two** advancement paths:
  - **Edit in Review** for deliberate prompt/config intervention
  - **Queue Now** for fast bulk throughput
- staged-curation candidates show the source prompt directly in the Learning UI so
  reason tags such as `prompt_drift` and `strong_prompt_match` are grounded
- source-vs-derived comparison becomes visible after intervention so the operator can
  see what changed

## 2. Guardrails

- no second execution path
- no second outer job model
- no GUI-owned lineage truth
- all execution remains NJR-backed and queue-backed
- `Review` stays the only advanced manual editing surface
- direct queueing remains available for bulk workflows
- manual handoff must preserve lineage and selection-event provenance

## 3. Current Gap Summary

Current staged-curation behavior:

- candidate decisions are stored in Learning
- `Generate Refine Jobs` / `Generate Face Jobs` / `Generate Upscale Jobs` compile
  selected candidates into derived NJRs
- those jobs are immediately enqueued
- there is no intermediate edit surface before enqueue
- there is no explicit source-prompt panel in the staged-curation selection workspace
- there is no first-class source-vs-derived comparison loop after intervention

## 4. Recommended Rollout

### PR-LEARN-260A-Staged-Curation-Source-Prompt-Surface-and-Decision-Context

Purpose:

- expose the source prompt and negative prompt directly in the staged-curation
  workspace so prompt-related decisions are grounded

Primary outcomes:

- add read-only `Source Prompt` and `Source Negative Prompt` panels to the right-side
  staged-curation selection workspace in `learning_tab_frame_v2.py`
- add a compact `Derived Stage Plan Preview` block showing the effective target stage
  and whether the path is `Queue Now` or `Edit in Review`
- extend replay summary to include source prompt/model/stage summary
- keep current preview image, reason tags, notes, and face-tier controls

Implementation notes:

- load prompt text from the selected `DiscoveredReviewItem`
- prefer embedded metadata-derived prompt fields already reconstructed in the
  discovered-review item and reprocess baseline path
- do not make source prompt editable in Learning

Primary file targets:

- `src/gui/views/learning_tab_frame_v2.py`
- `src/gui/controllers/learning_controller.py`
- `tests/gui_v2/test_learning_tab_state_persistence.py`
- add focused staged-curation UI tests as needed

Execution gate:

- source prompt/negative prompt must always be visible when a candidate is selected
- no enqueue behavior change in this PR

### PR-LEARN-260B-Staged-Curation-Plan-Build-vs-Enqueue-Seam

Purpose:

- split plan construction from queue submission so both `Queue Now` and `Edit in Review`
  can share one canonical derivation path

Primary outcomes:

- refactor `submit_staged_curation_advancement(...)` into:
  - `build_staged_curation_advancement_plan(...)`
  - `submit_staged_curation_advancement(...)` as a thin wrapper around build + enqueue
- define a stable return contract that includes:
  - built jobs
  - target stage
  - source candidate ids
  - selected source items
  - selection-event provenance
- preserve existing direct queue behavior with no change in output semantics

Primary file targets:

- `src/gui/controllers/learning_controller.py`
- `src/curation/curation_workflow_builder.py`
- `src/pipeline/reprocess_builder.py` (only if helper extraction is needed)
- `tests/curation/test_curation_workflow_builder.py`
- new controller tests for build-vs-submit seam

Execution gate:

- existing `Generate Refine/Face/Upscale Jobs` behavior must still work unchanged
- plan objects must preserve lineage metadata and source selection details

### PR-LEARN-260C-Learning-To-Review-Handoff-and-Review-Draft-Load

Purpose:

- let staged-curation candidates open in the canonical `Review` workspace before
  enqueue so the user can modify prompt/stages/settings deliberately

Primary outcomes:

- add new staged-curation actions:
  - `Edit Refine in Review`
  - `Edit Face in Review`
  - `Edit Upscale in Review`
- add a Review-side import/draft-loading path that accepts staged-curation source
  selections and preloads:
  - selected source images
  - source prompt and negative prompt
  - default stage toggles for target action
  - target-stage-aware derived baseline config
- auto-focus the Review tab after handoff
- keep `Queue Now` buttons for the bulk-throughput path

Suggested action mapping:

- refine -> `img2img=True`, `adetailer=False`, `upscale=False`
- face triage -> `img2img=False`, `adetailer=True`, `upscale=False`
- upscale -> `img2img=False`, `adetailer=False`, `upscale=True`

Primary file targets:

- `src/gui/views/learning_tab_frame_v2.py`
- `src/gui/controllers/learning_controller.py`
- `src/gui/views/review_tab_frame_v2.py`
- `src/gui/controllers/review_workflow_adapter.py`
- app-controller/main-window wiring where tab switching is coordinated
- new GUI/controller tests for Learning -> Review handoff

Execution gate:

- handoff must not enqueue automatically
- Review must open with the correct source image(s), source prompts, and target stage
  toggles already applied
- direct queue path must remain available

### PR-LEARN-260D-Review-Derived-Config-Inspector-and-Effective-Settings-Summary

Purpose:

- make the effective queue-bound config visible in Review before submission

Primary outcomes:

- add an `Effective Reprocess Settings` summary surface in Review showing the config
  that will be applied if submitted
- include at minimum:
  - source model / vae
  - source stage
  - effective target stages
  - sampler / scheduler / steps / cfg / denoise used for the target stage
  - whether prompt/negative prompt are inherited, appended, replaced, or modified
- expose the direct-queue staged-curation defaults in a human-readable way

Primary file targets:

- `src/gui/views/review_tab_frame_v2.py`
- `src/gui/controllers/review_workflow_adapter.py`
- `src/pipeline/reprocess_builder.py` (only if summary helper is needed)
- targeted Review tests

Execution gate:

- operators must be able to see what will actually be queued before they click
  reprocess

### PR-LEARN-260E-Source-vs-Derived-Outcome-Compare-and-Lineage-Jump

Purpose:

- close the loop by showing what changed because of the intervention

Primary outcomes:

- add source->derived linkage surfacing after a Review-originated or direct staged-
  curation derived job completes
- support opening the derived output next to the source candidate in a compare view
- add a quick jump from staged-curation candidate to latest derived descendant
- preserve lineage blocks already stamped into derived jobs

Primary file targets:

- `src/gui/views/learning_tab_frame_v2.py`
- `src/gui/views/review_tab_frame_v2.py`
- `src/curation/workflow_summary.py`
- `src/curation/curation_manifest.py`
- tests around lineage reconstruction / replay summary

Execution gate:

- user can see original source image and newest derived output together
- lineage survives both direct queue and Review-mediated paths

### PR-LEARN-260F-Queue-Now-vs-Edit-in-Review-UX-Polish-and-Bulk-Selection-Rules

Purpose:

- finalize the hybrid operator experience and make single-item vs bulk behavior clear

Primary outcomes:

- make `Edit in Review` the preferred/default action for single-candidate deliberate
  work
- keep `Queue Now` prominent for multi-select / bulk throughput work
- clarify labels and tooltips:
  - `Queue Refine Now`
  - `Queue Face Now`
  - `Queue Upscale Now`
  - `Edit in Review`
- add selection rules for bulk handoff and queueing
- add operator help text explaining when to use each path

Primary file targets:

- `src/gui/views/learning_tab_frame_v2.py`
- `src/gui/views/review_tab_frame_v2.py`
- optional docs update in `docs/PR_Backlog/STAGED_CURATION_EXECUTABLE_ROADMAP_v2.6.md`

Execution gate:

- single-item deliberate flow is obvious
- bulk-throughput flow remains fast
- no ambiguity over whether a button edits or enqueues

## 5. Recommended Order

Completed:

- `PR-LEARN-260A-Staged-Curation-Source-Prompt-Surface-and-Decision-Context`
- `PR-LEARN-260B-Staged-Curation-Plan-Build-vs-Enqueue-Seam`
- `PR-LEARN-260C-Learning-To-Review-Handoff-and-Review-Draft-Load`
- `PR-LEARN-260D-Review-Derived-Config-Inspector-and-Effective-Settings-Summary`
- `PR-LEARN-260E-Source-vs-Derived-Outcome-Compare-and-Lineage-Jump`
- `PR-LEARN-260F-Queue-Now-vs-Edit-in-Review-UX-Polish-and-Bulk-Selection-Rules`
- `PR-LEARN-264-Canonical-Metadata-Schemas-and-Contracts`

Next:

1. `PR-VIDEO-238-SVD-Native-Secondary-Motion-Postprocess-Integration`

## 6. Validation Expectations

At completion, validate these operator flows:

### Flow A - Fast bulk queueing

- mark multiple candidates `To Face`
- click `Queue Face Now`
- verify canonical NJR-backed derived jobs are enqueued
- verify lineage and selection-event metadata survive

### Flow B - Deliberate single-candidate edit

- select one candidate
- click `Edit Face in Review`
- verify Review opens with source image, source prompt, source negative prompt,
  and `adetailer` enabled
- modify prompt/settings
- submit
- compare source vs derived output

### Flow C - Prompt-grounded review

- select a staged-curation candidate
- verify source prompt and source negative prompt are visible in Learning
- verify prompt-related reason tags can be applied with prompt context visible

## 7. Non-Goals

- no new standalone curation tab
- no replacement of Review as the advanced manual workspace
- no automation-only routing that hides effective prompts/config from the operator
- no bypass of queue-backed execution

## 8. Recommendation

Adopt the hybrid model as the canonical staged-curation UX:

- `Learning` decides and routes
- `Review` edits and inspects
- both paths converge on the same NJR-backed reprocess execution model
