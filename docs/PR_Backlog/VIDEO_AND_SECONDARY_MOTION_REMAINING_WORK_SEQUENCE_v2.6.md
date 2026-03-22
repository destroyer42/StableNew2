# Video and Secondary Motion Remaining Work Sequence v2.6

Status: Proposed  
Date: 2026-03-22  
Branch baseline: `feature/video-secondary-motion-pr-236`  
Applies to: video subsystem, secondary motion, backend integration, learning, UX

## 1. Executive Summary

The video work on this branch is **not** fully finished end-to-end.

What is complete:

- `PR-VIDEO-236` established the canonical secondary-motion intent contract and
  observation-only policy carrier
- `PR-VIDEO-237` added the shared StableNew-owned secondary-motion engine,
  worker contract, and provenance helpers

What is not yet complete:

- backend-specific integration into SVD native video flows
- backend-specific integration into AnimateDiff flows
- workflow-video / Comfy-aware parity integration
- learning integration for secondary motion
- operator-facing GUI/UX exposure for video motion behavior

So the correct repo truth is:

- **secondary-motion foundation is complete**
- **secondary-motion rollout is not complete**

## 2. Current Completed Foundation

### `PR-VIDEO-236`

Delivered foundation:

- canonical `secondary_motion` contract under `intent_config`
- runner observation-only motion policy carrier
- no backend execution mutation yet

### `PR-VIDEO-237`

Delivered core runtime:

- deterministic shared motion engine
- directory-based worker contract
- shared provenance helpers
- compact summary wiring into container metadata and result descriptors

## 3. Remaining Work Overview

The remaining work should be executed in this order:

1. `PR-VIDEO-238-SVD-Native-Secondary-Motion-Postprocess-Integration`
2. `PR-VIDEO-239-AnimateDiff-Secondary-Motion-Frame-Pipeline-Integration`
3. `PR-VIDEO-240-Workflow-Video-Secondary-Motion-Parity-Integration`
4. `PR-VIDEO-241-Secondary-Motion-Learning-and-Evidence-Integration`
5. `PR-VIDEO-242-Video-UX-Exposure-and-Operator-Controls`
6. `PR-VIDEO-243-Video-Metadata-and-Result-Inspection-UX-Polish`

## 4. Recommended PR Sequence

### PR-VIDEO-238-SVD-Native-Secondary-Motion-Postprocess-Integration

Purpose:

- wire the shared secondary-motion engine into SVD native postprocess execution
  so SVD-native video jobs can actually apply StableNew-owned secondary motion

Primary outcomes:

- connect `secondary_motion` policy resolution to the SVD-native execution path
- apply the shared motion engine where policy and stage conditions allow
- stamp shared secondary-motion provenance into result/manifest outputs
- preserve observation-only and disabled modes cleanly
- keep backend-specific code thin by reusing the shared engine and provenance
  helpers from `PR-VIDEO-237`

Primary file targets:

- `src/video/svd_native_backend.py`
- `src/video/svd_runner.py`
- `src/pipeline/pipeline_runner.py` only if a light integration seam is required
- `tests/video/*svd*`
- targeted pipeline/video integration tests

Execution gate:

- an SVD-native video job can carry secondary motion from intent -> policy ->
  runtime application -> provenance summary

### PR-VIDEO-239-AnimateDiff-Secondary-Motion-Frame-Pipeline-Integration

Purpose:

- wire the shared motion engine into AnimateDiff-oriented video/frame flows

Primary outcomes:

- apply the shared secondary-motion runtime to AnimateDiff-compatible video frame
  outputs where policy allows
- preserve the same provenance contract used by SVD integration
- prevent backend-specific forks in summary shape or policy interpretation

Primary file targets:

- AnimateDiff backend/runtime files in `src/video/`
- shared pipeline seams only where needed
- focused AnimateDiff video tests

Execution gate:

- AnimateDiff video flows can use the same StableNew-owned motion policy and
  provenance contract as SVD flows

### PR-VIDEO-240-Workflow-Video-Secondary-Motion-Parity-Integration

Purpose:

- bring workflow-video / Comfy-aware video execution to parity with the shared
  secondary-motion model

Primary outcomes:

- support secondary motion for workflow-video execution paths without inventing
  a separate motion contract
- maintain contract compatibility with `PR-VIDEO-236` and runtime/provenance
  compatibility with `PR-VIDEO-237`
- ensure result metadata and diagnostics are consistent across all video backends

Primary file targets:

- workflow-video / Comfy video integration files
- shared result/metadata seams only where required
- focused parity tests

Execution gate:

- SVD, AnimateDiff, and workflow-video all emit the same motion-intent and
  motion-result semantics

### PR-VIDEO-241-Secondary-Motion-Learning-and-Evidence-Integration

Purpose:

- connect video/secondary-motion outcomes into Learning so motion settings and
  observed quality can become structured evidence rather than isolated execution

Primary outcomes:

- stamp secondary-motion context into learning records / review context where
  appropriate
- make motion-related outcomes analyzable in Learning and diagnostics
- support future recommendation or policy-tuning work without entangling backend
  logic with analytics logic

Primary file targets:

- `src/gui/controllers/learning_controller.py`
- learning record / analytics helpers
- result/metadata bridges
- video-learning tests

Execution gate:

- motion-aware video runs can be reviewed, compared, and analyzed through the
  Learning system

### PR-VIDEO-242-Video-UX-Exposure-and-Operator-Controls

Purpose:

- expose the secondary-motion capability to the operator in a clear, safe,
  explainable way

Primary outcomes:

- add GUI controls for secondary-motion intent where video stages are configured
- surface observation-only vs apply behavior clearly
- add tooltips/help text so the operator understands:
  - what secondary motion does
  - when to use it
  - what backend/stage support exists
  - how it interacts with existing video settings
- avoid ambiguous labels or hidden behavior

Primary file targets:

- video settings cards / tabs under `src/gui/` and `src/gui/views/`
- any stage-card adapters needed for UX wiring
- GUI tests for controls/help

Execution gate:

- a user can intentionally configure secondary motion without needing to read
  code or hidden docs

### PR-VIDEO-243-Video-Metadata-and-Result-Inspection-UX-Polish

Purpose:

- make video jobs and motion behavior inspectable after execution

Primary outcomes:

- add visible result summaries for video jobs showing motion status,
  provenance, and applied/observed behavior
- align with broader metadata-inspection work so video artifacts expose:
  - motion intent
  - policy summary
  - result/provenance summary
- improve compare/inspection flows for video outputs

Primary file targets:

- video result/inspection UI surfaces
- artifact metadata inspector integration points
- targeted UX/debug tests

Execution gate:

- an operator can tell what happened in a video run, what motion policy was used,
  and whether motion was observed or actually applied

## 5. Recommended Order

1. `PR-VIDEO-238-SVD-Native-Secondary-Motion-Postprocess-Integration`
2. `PR-VIDEO-239-AnimateDiff-Secondary-Motion-Frame-Pipeline-Integration`
3. `PR-VIDEO-240-Workflow-Video-Secondary-Motion-Parity-Integration`
4. `PR-VIDEO-241-Secondary-Motion-Learning-and-Evidence-Integration`
5. `PR-VIDEO-242-Video-UX-Exposure-and-Operator-Controls`
6. `PR-VIDEO-243-Video-Metadata-and-Result-Inspection-UX-Polish`

## 6. Validation Expectations

At completion, validate these flows:

### Flow A - SVD-native video with secondary motion

- configure video job with `secondary_motion`
- execute SVD-native video path
- confirm policy is interpreted correctly
- confirm runtime applies or observes motion according to mode
- confirm provenance appears in result metadata

### Flow B - AnimateDiff video with secondary motion

- configure AnimateDiff-compatible video path
- confirm motion integration uses the same contract and summary semantics

### Flow C - Learning-aware video review

- review a motion-aware video output
- confirm secondary-motion context is visible in review/learning surfaces
- confirm comparison and evidence capture survive into Learning

### Flow D - Operator understanding

- user can hover or inspect controls and understand what motion settings do,
  when to use them, and how they interact with video backends

## 7. Recommendation

Treat `PR-VIDEO-236` and `PR-VIDEO-237` as completed foundation work, then execute
`PR-VIDEO-238` through `PR-VIDEO-243` as the remaining rollout sequence needed to
make video and secondary motion truly complete from backend to Learning to UX.
