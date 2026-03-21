# StableNew Comfy-Aware Backlog v2.6

Status: Active subordinate backlog  
Updated: 2026-03-21

## Purpose

Extend StableNew's existing video architecture so ComfyUI can act as a managed
execution backend without becoming a second orchestration system.

This backlog now reflects current repo truth after the v2.6 unification and
Comfy foundation work, not the earlier idealized pre-migration plan.

## Current Repo Truth

The repo already has the necessary foundation:

- `src/video/video_backend_types.py`
- `src/video/video_backend_registry.py`
- canonical video backend adapters for AnimateDiff, SVD native, and Comfy workflow execution
- a managed local Comfy runtime
- a workflow registry and deterministic compiler
- one pinned LTX workflow routed through NJR, queue, runner, history, and canonical artifacts
- a dedicated `Video Workflow` GUI surface

This means the next work is productization and expansion, not first-foundation plumbing.

## Core Invariants

All future Comfy/video work must preserve:

- NJR as the only outer executable job contract
- queue/runner/history/artifacts owned by StableNew
- `VideoExecutionRequest` as an internal runner-to-backend request, not a second job model
- no Comfy imports outside `src/video/`
- no workflow JSON in GUI/controller/public runtime contracts

## Status of the Earlier Revised Video Queue

The earlier `PR-VIDEO-078` through `PR-VIDEO-088` plan maps to current repo state as follows:

- `PR-VIDEO-078` completed in substance via the canonical video backend registry/adapters
- `PR-VIDEO-079` completed via workflow registry/spec work
- `PR-VIDEO-080` completed via the managed local Comfy runtime
- `PR-VIDEO-081` completed via the workflow compiler
- `PR-VIDEO-082` completed via the first pinned LTX workflow
- `PR-VIDEO-083` substantially completed via the dedicated `Video Workflow` tab, with some remaining UX convergence still needed
- `PR-VIDEO-084` completed in substance via `PR-VIDEO-216` sequence orchestration and segment planning
- `PR-VIDEO-085` completed in substance via `PR-VIDEO-217` stitch/interpolation/clip-assembly unification
- `PR-VIDEO-086` substantially covered by `PR-OBS-212`; future improvements are now incremental polish
- `PR-VIDEO-087` completed in substance via `PR-VIDEO-218` continuity pack foundation
- `PR-VIDEO-088` completed in substance via `PR-VIDEO-219` story and shot planning foundation

## Common Missing Functionality

Beyond the old numbered plan, the current repo still lacks a few important product layers:

- the GUI still needs the dedicated config adapter/final controller shrink pass
- continuity and story planning still need richer first-class UX on top of the new workspace flow
- there is no StableNew-owned secondary motion layer that can be replayed
  across `animatediff`, `svd_native`, and `video_workflow`
- manifests, replay, and learning do not yet carry a canonical secondary-motion
  summary distinct from the existing `motion_profile`

## Revised Video/Product Queue

### `PR-VIDEO-215-Workflow-Video-Output-Routing-and-History-Convergence`

Status: Completed 2026-03-19

Closed the gap between `video_workflow`, history, manifests, and output
routing.

Required outputs:

- deterministic workflow-video output routing
- cleaner history/recent-output affordances for workflow-video jobs
- clearer handoff between Video Workflow, SVD, and Movie Clips

Completion record:

- `docs/CompletedPR/PR-VIDEO-215-Workflow-Video-Output-Routing-and-History-Convergence.md`

Execution spec:

- `docs/PR_Backlog/PR-VIDEO-215-Workflow-Video-Output-Routing-and-History-Convergence.md`

### `PR-VIDEO-216-Sequence-Orchestration-and-Segment-Planning`

Status: Completed 2026-03-19

Added the long-form orchestration layer on top of the current backend
foundation.

Required outputs:

- `VideoSequenceJob`
- `VideoSegmentPlan`
- deterministic carry-forward rules
- segment provenance in canonical artifacts/manifests

Completion record:

- `docs/CompletedPR/PR-VIDEO-216-Sequence-Orchestration-and-Segment-Planning.md`

Execution spec:

- `docs/PR_Backlog/PR-VIDEO-216-Sequence-Orchestration-and-Segment-Planning.md`

### `PR-VIDEO-217-Stitching-Interpolation-and-Clip-Assembly-Unification`

Status: Completed 2026-03-19

Unified post-video assembly under StableNew-owned contracts.

Required outputs:

- stitched-output artifacts
- interpolated-output artifacts
- explicit bridge from sequence outputs into Movie Clips/export paths

Completion record:

- `docs/CompletedPR/PR-VIDEO-217-Stitching-Interpolation-and-Clip-Assembly-Unification.md`

Execution spec:

- `docs/PR_Backlog/PR-VIDEO-217-Stitching-Interpolation-and-Clip-Assembly-Unification.md`

### `PR-VIDEO-218-Continuity-Pack-Foundation`

Status: Completed 2026-03-20

Added continuity containers that persist across runs and sequences.

Required outputs:

- `ContinuityPack`
- character/wardrobe/scene references
- anchor-set linkage through manifests/history

Completion record:

- `docs/CompletedPR/PR-VIDEO-218-Continuity-Pack-Foundation.md`

Execution spec:

- `docs/PR_Backlog/PR-VIDEO-218-Continuity-Pack-Foundation.md`

### `PR-VIDEO-219-Story-and-Shot-Planning-Foundation`

Status: Completed 2026-03-20

Added the first manual planning layer above raw sequence jobs.

Required outputs:

- `StoryPlan`
- `ScenePlan`
- `ShotPlan`
- `AnchorPlan`
- deterministic plan-to-sequence compilation

Completion record:

- `docs/CompletedPR/PR-VIDEO-219-Story-and-Shot-Planning-Foundation.md`

Execution spec:

- `docs/PR_Backlog/PR-VIDEO-219-Story-and-Shot-Planning-Foundation.md`

### `PR-GUI-220-UX-First-Workspace-Polish-on-Tkinter`

Status: Completed 2026-03-20

Improve the experience of the now-stable surfaces before considering a toolkit rewrite.

Required outputs:

- tighter queue/history/video-workflow ergonomics
- clearer status and result surfaces
- lower-friction movement between PromptPack, History, SVD, Video Workflow, and Movie Clips

Completion record:

- `docs/CompletedPR/PR-GUI-220-UX-First-Workspace-Polish-on-Tkinter.md`

Execution spec:

- `docs/PR_Backlog/PR-GUI-220-UX-First-Workspace-Polish-on-Tkinter.md`

With `PR-HARDEN-224` through `PR-HARDEN-229` assumed complete, the next
video/runtime tranche is the StableNew-owned secondary motion layer.

### `PR-VIDEO-236-Secondary-Motion-Intent-Contract-and-Observation-Only-Policy-Carrier`

Status: Completed 2026-03-21

Freeze the secondary-motion outer contract before any backend behavior change.

Required outputs:

- one nested `intent_config["secondary_motion"]` payload distinct from
  `motion_profile`
- runner observation-only policy metadata for the existing video stages
- a StableNew-owned `src/video/motion/` package boundary and schema document

Delivered outcomes:

- `src/video/motion/` now exists as a StableNew-owned pure policy subsystem
- `secondary_motion` survives canonicalization and all current NJR builder paths
- runner video requests now carry observation-only
  `context_metadata["secondary_motion_policy"]`
- run metadata now records `secondary_motion` stage-policy observations without
  changing backend output behavior

Schema reference:

- `docs/SECONDARY_MOTION_POLICY_SCHEMA_V1.md`

Guiding roadmap:

- `docs/PR_Backlog/SECONDARY_MOTION_EXECUTABLE_ROADMAP_v2.6.md`

Execution spec:

- `docs/PR_Backlog/PR-VIDEO-236-Secondary-Motion-Intent-Contract-and-Observation-Only-Policy-Carrier.md`

### `PR-VIDEO-237-Shared-Secondary-Motion-Engine-and-Provenance-Contract`

Status: Completed 2026-03-21

Land the shared deterministic engine and provenance helpers before backend
rollout.

Required outputs:

- StableNew-owned shared motion engine and worker contract
- compact replay/container summary plus detailed manifest helper
- no backend wiring yet, only the reusable runtime and summary contract

Completion record:

- `docs/CompletedPR/PR-VIDEO-237-Shared-Secondary-Motion-Engine-and-Provenance-Contract.md`

Execution spec:

- `docs/PR_Backlog/PR-VIDEO-237-Shared-Secondary-Motion-Engine-and-Provenance-Contract.md`

### `PR-VIDEO-238-SVD-Native-Secondary-Motion-Postprocess-Integration`

Status: Planned

Use the safest current postprocess seam to land the first real motion runtime.

Required outputs:

- runner-injected transient SVD motion config
- shared-engine application as SVD postprocess stage zero
- canonical motion provenance in SVD artifacts

Execution spec:

- `docs/PR_Backlog/PR-VIDEO-238-SVD-Native-Secondary-Motion-Postprocess-Integration.md`

### `PR-VIDEO-239-AnimateDiff-Secondary-Motion-Frame-Pipeline-Integration`

Status: Planned

Insert the shared engine into the AnimateDiff frame pipeline.

Required outputs:

- shared-engine application between frame write and encode
- skip-safe AnimateDiff motion behavior with stable output-path semantics
- canonical motion provenance in AnimateDiff artifacts

Execution spec:

- `docs/PR_Backlog/PR-VIDEO-239-AnimateDiff-Secondary-Motion-Frame-Pipeline-Integration.md`

### `PR-VIDEO-240-Workflow-Video-Secondary-Motion-Parity-and-Replay-Closure`

Status: Planned

Close the last major parity gap for the shared motion carrier without adding a
new custom Comfy node dependency.

Required outputs:

- StableNew-owned extract/apply/re-encode parity path for workflow-video
- canonical replay closure for the final video artifact
- consistent motion summary shape across all current video backends

Execution spec:

- `docs/PR_Backlog/PR-VIDEO-240-Workflow-Video-Secondary-Motion-Parity-and-Replay-Closure.md`

### `PR-VIDEO-241-Learning-and-Risk-Aware-Secondary-Motion-Feedback`

Status: Planned

Make the shared motion carrier visible to learning and recommendation flows.

Required outputs:

- scalar motion metrics in learning records
- backend-aware and application-path-aware recommendation context
- no raw frame or dense motion payload retention in centralized learning data

Execution spec:

- `docs/PR_Backlog/PR-VIDEO-241-Learning-and-Risk-Aware-Secondary-Motion-Feedback.md`

## Adjacent Tranche Coordination

The next prompt/image-product tranche is tracked separately in:

- `docs/PR_Backlog/PROMPT_OPTIMIZER_EXECUTABLE_ROADMAP_v2.6.md`

That work is intentionally adjacent to this video tranche, but it should not
interrupt `PR-VIDEO-237` through `PR-VIDEO-241`.

## Done Definition

The next stage of video work is successful when:

- short-form workflow-video is as coherent as short-form image generation
- workflow-video, SVD native, and AnimateDiff can share a StableNew-owned
  secondary motion layer with canonical replay provenance
- long-form video has a first-class planning/orchestration path
- post-video outputs are canonical artifacts, not side utilities
- continuity and shot-planning data can persist through manifests/history
- learning can separate motion evidence by backend and application path instead
  of mixing incomparable video runs
- the GUI feels designed around the actual workflow set rather than around historical seams
