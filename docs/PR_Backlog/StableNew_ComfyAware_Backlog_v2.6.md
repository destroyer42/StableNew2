# StableNew Comfy-Aware Backlog v2.6

Status: Active subordinate backlog  
Updated: 2026-03-19

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
- `PR-VIDEO-084` still missing: sequence orchestration and segment planning
- `PR-VIDEO-085` still missing: stitch/interpolation/clip-assembly unification
- `PR-VIDEO-086` substantially covered by `PR-OBS-212`; future improvements are now incremental polish
- `PR-VIDEO-087` still missing: continuity packs
- `PR-VIDEO-088` still missing: story/shot planning

## Common Missing Functionality

Beyond the old numbered plan, the current repo still lacks a few important product layers:

- workflow-video output routing is not yet as mature as image output routing
- history/recent-output affordances for workflow-video are functional but still thin
- there is no first-class long-form sequence job model
- post-video stitching and interpolation are not yet expressed as one canonical artifact path
- Movie Clips and Video Workflow are adjacent surfaces, not yet one coherent video workspace

## Revised Video/Product Queue

### `PR-VIDEO-215-Workflow-Video-Output-Routing-and-History-Convergence`

Close the gap between `video_workflow`, history, manifests, and output routing.

Required outputs:

- deterministic workflow-video output routing
- cleaner history/recent-output affordances for workflow-video jobs
- clearer handoff between Video Workflow, SVD, and Movie Clips

Execution spec:

- `docs/PR_Backlog/PR-VIDEO-215-Workflow-Video-Output-Routing-and-History-Convergence.md`

### `PR-VIDEO-216-Sequence-Orchestration-and-Segment-Planning`

Add the long-form orchestration layer on top of the current backend foundation.

Required outputs:

- `VideoSequenceJob`
- `VideoSegmentPlan`
- deterministic carry-forward rules
- segment provenance in canonical artifacts/manifests

Execution spec:

- `docs/PR_Backlog/PR-VIDEO-216-Sequence-Orchestration-and-Segment-Planning.md`

### `PR-VIDEO-217-Stitching-Interpolation-and-Clip-Assembly-Unification`

Unify post-video assembly under StableNew-owned contracts.

Required outputs:

- stitched-output artifacts
- interpolated-output artifacts
- explicit bridge from sequence outputs into Movie Clips/export paths

Execution spec:

- `docs/PR_Backlog/PR-VIDEO-217-Stitching-Interpolation-and-Clip-Assembly-Unification.md`

### `PR-VIDEO-218-Continuity-Pack-Foundation`

Add continuity containers that persist across runs and sequences.

Required outputs:

- `ContinuityPack`
- character/wardrobe/scene references
- anchor-set linkage through manifests/history

Execution spec:

- `docs/PR_Backlog/PR-VIDEO-218-Continuity-Pack-Foundation.md`

### `PR-VIDEO-219-Story-and-Shot-Planning-Foundation`

Add the first manual planning layer above raw sequence jobs.

Required outputs:

- `StoryPlan`
- `ScenePlan`
- `ShotPlan`
- `AnchorPlan`
- deterministic plan-to-sequence compilation

Execution spec:

- `docs/PR_Backlog/PR-VIDEO-219-Story-and-Shot-Planning-Foundation.md`

### `PR-GUI-220-UX-First-Workspace-Polish-on-Tkinter`

Improve the experience of the now-stable surfaces before considering a toolkit rewrite.

Required outputs:

- tighter queue/history/video-workflow ergonomics
- clearer status and result surfaces
- lower-friction movement between PromptPack, History, SVD, Video Workflow, and Movie Clips

Execution spec:

- `docs/PR_Backlog/PR-GUI-220-UX-First-Workspace-Polish-on-Tkinter.md`

## Done Definition

The next stage of video work is successful when:

- short-form workflow-video is as coherent as short-form image generation
- long-form video has a first-class planning/orchestration path
- post-video outputs are canonical artifacts, not side utilities
- continuity and shot-planning data can persist through manifests/history
- the GUI feels designed around the actual workflow set rather than around historical seams
