StableNew Roadmap v2.6.md
(Canonical Edition)

Status: Authoritative  
Updated: 2026-03-20  
Applies To: Codex, Copilot, ChatGPT Planner, Human Contributors

## 0. Strategic Objective

Turn StableNew into a polished local orchestrator for image and video creation
with:

- one architecture
- one outer job model
- one queue-first submission path
- one runner
- one canonical artifact/history/replay contract
- one coherent documentation and testing surface

North Star runtime:

`Intent Surface -> Builder/Compiler -> NJR -> JobService Queue -> PipelineRunner -> Stage/Backend Execution -> Canonical Artifacts -> History/Learning/Diagnostics`

## 1. What Is Now Done

The original v2.6 unification sequence is complete through `PR-POLISH-214`.

Delivered outcomes:

- fresh execution is queue-only
- NJR is the outer job contract for both image and video work
- live archive execution seams are gone
- canonical config layering exists
- test taxonomy is normalized
- diagnostics and replay are unified across image and video
- the managed Comfy runtime exists
- one pinned LTX workflow exists
- the dedicated `Video Workflow` GUI surface exists
- the last live `submit_direct()` and `PipelineConfigPanel` compatibility seams are gone

Current collection baseline:

- `pytest --collect-only -q` -> `2540 collected / 0 skipped`

## 2. Remaining Structural Debt

The biggest remaining cross-cutting debt is now narrower and more product-facing:

- `src/controller/app_controller.py` remains about `5658` LOC
- `src/controller/pipeline_controller.py` remains about `1572` LOC
- `tests/compat/` still preserves temporary migration behavior that should continue shrinking
- `AppStateV2.run_config` still exists as a GUI-facing dict projection, even though
  canonical config layers are now mirrored alongside it
- higher-level video sequence, stitch, continuity, and planning layers are not yet implemented

## 3. Status of the Older Revised Video Queue

The earlier `PR-VIDEO-078` to `PR-VIDEO-088` plan has been partially or fully absorbed by the
unification work:

- `PR-VIDEO-078` completed in substance via the canonical video backend registry and adapters
- `PR-VIDEO-079` completed via workflow registry/spec work in `src/video/`
- `PR-VIDEO-080` completed via the managed local Comfy runtime
- `PR-VIDEO-081` completed via the workflow compiler
- `PR-VIDEO-082` completed via the first pinned LTX workflow
- `PR-VIDEO-083` is substantially complete via the dedicated `Video Workflow` GUI tab, but still needs richer workflow/video UX convergence
- `PR-VIDEO-084` completed in substance via `PR-VIDEO-216` sequence orchestration and segment planning
- `PR-VIDEO-085` completed in substance via `PR-VIDEO-217` stitch/interpolation/clip-assembly unification
- `PR-VIDEO-086` is substantially covered by `PR-OBS-212`; future improvements are now follow-on polish, not a blocked foundation item
- `PR-VIDEO-087` completed in substance via `PR-VIDEO-218` continuity pack foundation
- `PR-VIDEO-088` completed in substance via `PR-VIDEO-219` story and shot planning foundation

## 4. Revised Post-Unification PR Queue

This is the real queue from current repo state, not from an older idealized snapshot.

### 1. `PR-VIDEO-215-Workflow-Video-Output-Routing-and-History-Convergence`

Status: Completed 2026-03-19

Closed the remaining gap between `video_workflow`, history, manifests, and
output routing.

Primary outcomes:

- deterministic output routing for workflow-video jobs
- better recent/history affordances for video workflow outputs
- cleaner handoff between `Video Workflow`, SVD, and Movie Clips surfaces
- removal of any remaining stage-specific video UI assumptions that should now be generic

Completion record:

- `docs/CompletedPR/PR-VIDEO-215-Workflow-Video-Output-Routing-and-History-Convergence.md`

Detailed execution spec:

- `docs/PR_Backlog/PR-VIDEO-215-Workflow-Video-Output-Routing-and-History-Convergence.md`

### 2. `PR-VIDEO-216-Sequence-Orchestration-and-Segment-Planning`

Status: Completed 2026-03-19

Implemented the first-class long-form video planning layer.

Primary outcomes:

- `VideoSequenceJob`
- `VideoSegmentPlan`
- deterministic carry-forward rules
- overlap metadata
- per-segment provenance in canonical artifacts/manifests

Completion record:

- `docs/CompletedPR/PR-VIDEO-216-Sequence-Orchestration-and-Segment-Planning.md`

Detailed execution spec:

- `docs/PR_Backlog/PR-VIDEO-216-Sequence-Orchestration-and-Segment-Planning.md`

### 3. `PR-VIDEO-217-Stitching-Interpolation-and-Clip-Assembly-Unification`

Status: Completed 2026-03-19

Turned post-video assembly into a StableNew-owned artifact path instead of
disconnected utilities.

Primary outcomes:

- stitched-output artifacts
- interpolated-output artifacts
- sequence-aware clip/export integration
- explicit bridge between sequence outputs and Movie Clips

Completion record:

- `docs/CompletedPR/PR-VIDEO-217-Stitching-Interpolation-and-Clip-Assembly-Unification.md`

Detailed execution spec:

- `docs/PR_Backlog/PR-VIDEO-217-Stitching-Interpolation-and-Clip-Assembly-Unification.md`

### 4. `PR-VIDEO-218-Continuity-Pack-Foundation`

Status: Completed 2026-03-20

Added continuity containers that can survive across jobs and sequences.

Primary outcomes:

- `ContinuityPack`
- anchor-set linkage
- character/wardrobe/scene references
- manifest/history linkage for continuity-aware runs

Completion record:

- `docs/CompletedPR/PR-VIDEO-218-Continuity-Pack-Foundation.md`

Detailed execution spec:

- `docs/PR_Backlog/PR-VIDEO-218-Continuity-Pack-Foundation.md`

### 5. `PR-VIDEO-219-Story-and-Shot-Planning-Foundation`

Status: Completed 2026-03-20

Added manual planning structures above sequence jobs.

Primary outcomes:

- `StoryPlan`
- `ScenePlan`
- `ShotPlan`
- `AnchorPlan`
- deterministic compilation from plan -> sequence jobs

Completion record:

- `docs/CompletedPR/PR-VIDEO-219-Story-and-Shot-Planning-Foundation.md`

Detailed execution spec:

- `docs/PR_Backlog/PR-VIDEO-219-Story-and-Shot-Planning-Foundation.md`

### 6. `PR-GUI-220-UX-First-Workspace-Polish-on-Tkinter`

Status: Completed 2026-03-20

Focus on the user experience of the current product without changing toolkits yet.

Primary outcomes:

- tighter queue/history/video workflow ergonomics
- clearer status and result surfaces
- less modal friction across PromptPack, History, SVD, Video Workflow, and Movie Clips
- better progressive disclosure and defaults for video workflows

Completion record:

- `docs/CompletedPR/PR-GUI-220-UX-First-Workspace-Polish-on-Tkinter.md`

Detailed execution spec:

- `docs/PR_Backlog/PR-GUI-220-UX-First-Workspace-Polish-on-Tkinter.md`

### 7. `PR-CTRL-221-GUI-Config-Adapter-and-Final-Controller-Shrink`

Status: Completed 2026-03-20

Finish the most visible cross-cutting cleanup that still affects GUI work.

Primary outcomes:

- replace more direct `run_config` dict usage with a dedicated GUI config adapter
- further reduce `AppController` and `PipelineController`
- keep UX work from hard-coding against legacy state shape

Delivered outcomes:

- `AppStateV2` now exposes a dedicated `GuiConfigAdapterV26` facade over
  canonical config layers
- GUI-facing config mutation for randomizer and submission projection now routes
  through `GuiConfigService`
- history replay/hydration logic moved behind a bounded pipeline-controller
  handoff service instead of living directly in the top-level controller

Detailed execution spec:

- `docs/PR_Backlog/PR-CTRL-221-GUI-Config-Adapter-and-Final-Controller-Shrink.md`

## 5. Missing Common Functionality to Fold Into the Queue

These are the important missing capabilities that are not just "nice to have":

- continuity and story-planning still need richer UX exposure on top of the now-coherent video workspace
- further controller reduction is still desirable, but no longer blocked on the GUI config adapter seam

## 6. Done Definition for the Next Stage

StableNew's next stage is successful when:

- image and short-form video are both solid under the current queue-first architecture
- long-form video has a first-class planning/orchestration path
- post-video outputs are canonical artifacts, not side utilities
- continuity and shot-planning data can persist through manifests/history
- the GUI feels intentionally designed around the current workflow set

## 7. Guiding Principle

Prefer doing it right over doing it easy.

At this point, “right” means:

- keep the architecture stable
- add missing product layers on top of the stable core
- improve UX before considering a toolkit rewrite
