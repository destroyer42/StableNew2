StableNew Roadmap v2.6.md
(Canonical Edition)

Status: Authoritative  
Updated: 2026-03-29  
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

- `pytest --collect-only -q` -> `2964 collected / 0 skipped`

## 2. Remaining Structural Debt

The biggest remaining cross-cutting debt is now narrower and more product-facing:

- `src/controller/app_controller.py` remains about `5658` LOC
- `src/controller/pipeline_controller.py` remains about `1572` LOC
- `tests/compat/` still preserves temporary migration behavior that should continue shrinking
- `AppStateV2.run_config` still exists as a GUI-facing dict projection, even though
  canonical config layers are now mirrored alongside it
- adaptive refinement now exists through detector-backed observation,
  ADetailer-safe actuation, prompt/upscale policy integration, and
  learning-aware feedback; remaining image-path debt is now mainly product UX
  cleanup rather than missing refinement foundations
- Pipeline sidebar and review/reprocess UX still carry product-level cleanup
  debt around pack discovery, scan roots, and duplicated surfaces
- StableNew-owned secondary motion now has a shared engine/provenance layer
  across SVD native, AnimateDiff, and workflow-video, with canonical manifest,
  replay, and container-summary coverage already landed through
  `PR-VIDEO-241`; remaining video work is now follow-on UX, metadata
  inspection, and structural cleanup rather than missing backend rollout

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

Completion record:

- `docs/CompletedPR/PR-CTRL-221-GUI-Config-Adapter-and-Final-Controller-Shrink.md`

### 8. `PR-HARDEN-224-Adaptive-Refinement-Contracts-and-Dark-Launch-Foundation`

Status: Completed 2026-03-20

Establish the canonical adaptive refinement contract before any behavior change.

Primary outcomes:

- one nested `intent_config["adaptive_refinement"]` contract
- a StableNew-owned `src/refinement/` package boundary
- builder and NJR persistence without new job models
- import-boundary guard tests and a schema document

Completion record:

- `docs/CompletedPR/PR-HARDEN-224-Adaptive-Refinement-Contracts-and-Dark-Launch-Foundation.md`

Guiding roadmap:

- `docs/CompletedPlans/ADAPTIVE_REFINEMENT_EXECUTABLE_ROADMAP_v2.6.md`

### 9. `PR-HARDEN-225-Prompt-Intent-Analysis-and-Observation-Only-Decision-Capture`

Status: Completed 2026-03-20

Add the deterministic observation layer before any output-changing behavior.

Primary outcomes:

- prompt-intent analysis reusing the current prompt subsystem
- observation-only decision bundles in runner metadata
- null-detector fallback and no stage mutation

Completion record:

- `docs/CompletedPR/PR-HARDEN-225-Prompt-Intent-Analysis-and-Observation-Only-Decision-Capture.md`

### 10. `PR-HARDEN-226-Detector-Boundary-and-Optional-OpenCV-Subject-Assessment`

Status: Completed 2026-03-20

Add the first real subject-assessment path without making OpenCV mandatory.

Primary outcomes:

- optional OpenCV detector support
- threshold versioning for scale-band assessment
- richer observation bundles with deterministic fallback behavior

Completion record:

- `docs/CompletedPR/PR-HARDEN-226-Detector-Boundary-and-Optional-OpenCV-Subject-Assessment.md`

### 11. `PR-HARDEN-227-Safe-ADetailer-Adaptive-Policy-Application`

Status: Completed 2026-03-20

Roll out the first controlled runtime actuation, limited to ADetailer.

Primary outcomes:

- per-image ADetailer-safe overrides
- explicit rollout modes and rollback path
- manifest-facing provenance for applied overrides

Completion record:

- `docs/CompletedPR/PR-HARDEN-227-Safe-ADetailer-Adaptive-Policy-Application.md`

### 12. `PR-HARDEN-228-Prompt-Patch-and-Upscale-Policy-Integration`

Status: Completed 2026-03-20

Complete the runtime portion of adaptive refinement with bounded prompt and
upscale integration.

Primary outcomes:

- stage-scoped prompt patches with deterministic merge order
- bounded upscale policy application
- original-prompt and final-prompt provenance for replay

Completion record:

- `docs/CompletedPR/PR-HARDEN-228-Prompt-Patch-and-Upscale-Policy-Integration.md`

### 13. `PR-HARDEN-229-Learning-Loop-and-Recommendation-Aware-Refinement-Feedback`

Status: Completed 2026-03-20

Close the loop by making refinement decisions visible to the local learning
system without weakening evidence-tier safeguards.

Primary outcomes:

- scalar refinement metrics in learning records
- refinement-aware recommendation context
- conservative, evidence-tier-respecting feedback for future tuning

Completion record:

- `docs/CompletedPR/PR-HARDEN-229-Learning-Loop-and-Recommendation-Aware-Refinement-Feedback.md`

### 14. `PR-HARDEN-230-ADetailer-Payload-Checkpoint-Pinning-and-Detector-Model-Key-Cleanup`

Status: Completed 2026-03-20

Remove the remaining hidden model-switch ambiguity from the image path.

Primary outcomes:

- explicit SD checkpoint pinning in the actual ADetailer/img2img payload path
- manifest model precedence hardened to prefer requested stage config over
  ambient WebUI state
- removal of the generic ADetailer `model` alias from canonical config merging
- regression coverage proving txt2img, ADetailer, and upscale stay pinned to
  the NJR base model by default

Completion record:

- `docs/CompletedPR/PR-HARDEN-230-ADetailer-Payload-Checkpoint-Pinning-and-Detector-Model-Key-Cleanup.md`

### 15. `PR-HARDEN-231-Output-Root-Normalization-and-Route-Classification-Audit`

Status: Completed 2026-03-20

Remove route confusion from output directory selection and make the base output
root deterministic.

Primary outcomes:

- `output_dir` means root only, not route-plus-root
- known legacy route suffixes stripped before route resolution
- canonical route selection derived from job/stage intent instead of folder-name
  guesswork
- regression tests for regular image, AnimateDiff, workflow-video, and
  discovered-output scanning

Completion record:

- `docs/CompletedPR/PR-HARDEN-231-Output-Root-Normalization-and-Route-Classification-Audit.md`

### 16. `PR-GUI-232-Pack-Selector-Cleanup-and-Real-Pack-Refresh-Discovery`

Status: Completed 2026-03-20

Fix the confusing PromptPack selector UX and make refresh behavior real.

Primary outcomes:

- remove the empty legacy pack text field from the Pipeline sidebar
- make refresh rediscover actual PromptPack files, including JSON-backed packs
- align the selector label and empty state with current PromptPack behavior
- add GUI tests for refresh, discovery, and state persistence

Completion record:

- `docs/CompletedPR/PR-GUI-232-Pack-Selector-Cleanup-and-Real-Pack-Refresh-Discovery.md`

### 17. `PR-LEARN-233-Canonical-Discovered-Scan-Root-Fix`

Status: Completed 2026-03-20

Make discovered-experiment scanning use the same canonical output root as the
rest of the product.

Primary outcomes:

- remove fallback scanning from ad hoc `app_state.output_dir`
- use canonical config/engine output root for discovered runs
- add regression coverage for regular image outputs and routed video outputs

Completion record:

- `docs/CompletedPR/PR-LEARN-233-Canonical-Discovered-Scan-Root-Fix.md`

### 18. `PR-GUI-234-Reprocess-Surface-Consolidation`

Status: Completed 2026-03-20

Reduce duplicated reprocess UX and keep one canonical advanced reprocess
surface.

Primary outcomes:

- `Review` becomes the canonical advanced reprocess surface
- sidebar reprocess is reduced to a minimal launcher or removed
- duplicated behaviors and confusing parallel controls are eliminated

Completion record:

- `docs/CompletedPR/PR-GUI-234-Reprocess-Surface-Consolidation.md`

### 19. `PR-GUI-235-Core-Config-to-Base-Generation-and-Recipe-Summary-UX`

Status: Completed

Replace the legacy-feeling `Core Config` surface with a real base-generation
ownership boundary and readable recipe UX.

Primary outcomes:

- `Core Config` removed from the active v2 path and replaced by `Base Generation`
- txt2img no longer acts as a second owner for global base-generation fields
- `Pipeline Presets` become readable `Saved Recipes` with summaries
- sidebar/controller `core_*` GUI vocabulary is retired in the active v2 path
- visible precedence between base generation and stage overrides

Completion record:

- `docs/CompletedPR/PR-GUI-235-Core-Config-to-Base-Generation-and-Recipe-Summary-UX.md`

### 19A. `PR-GUI-235A-PresetNaming`

Status: Completed

Clean up the active Pipeline v2 naming after the ownership reset so the live
sidebar/controller path speaks in `Saved Recipe` terms instead of `Preset`
terms, while leaving the underlying `ConfigManager` storage contract untouched.

Primary outcomes:

- active sidebar variables and callbacks use `saved_recipe_*` naming
- active pipeline controller callbacks use `saved_recipe` terminology
- active GUI tests follow the new names and intent
- legacy storage still remains under `presets/` until a future storage-contract
  cleanup PR explicitly changes that boundary

Completion record:

- `docs/CompletedPR/PR-GUI-235A-PresetNaming.md`

### 20. `PR-VIDEO-236-Secondary-Motion-Intent-Contract-and-Observation-Only-Policy-Carrier`

Status: Completed 2026-03-21

Freeze the secondary-motion outer contract before any backend behavior change.

Primary outcomes:

- one nested `intent_config["secondary_motion"]` payload distinct from the
  existing `motion_profile`
- runner observation-only motion planning metadata for the existing video
  stages
- a StableNew-owned `src/video/motion/` package boundary and schema document

Delivered outcomes:

- `src/video/motion/` now owns the versioned intent and policy carrier
- `secondary_motion` survives canonicalization and NJR persistence through main,
  prompt-pack, and CLI builders
- runner video requests now receive metadata-only
  `context_metadata["secondary_motion_policy"]`
- run metadata now records observation-only per-video-stage policies without
  mutating backend behavior, manifests, or container metadata

Schema reference:

- `docs/Architecture/SECONDARY_MOTION_POLICY_SCHEMA_V1.md`

Guiding roadmap:

- `docs/CompletedPlans/SECONDARY_MOTION_EXECUTABLE_ROADMAP_v2.6.md`

### 21. `PR-VIDEO-237-Shared-Secondary-Motion-Engine-and-Provenance-Contract`

Status: Completed 2026-03-21

Land the shared deterministic engine and the one canonical provenance contract
before backend rollout.

Primary outcomes:

- a StableNew-owned shared secondary-motion engine and worker contract
- compact replay and container-metadata summaries plus detailed manifest helpers
- no backend wiring yet, only the reusable runtime and summary contract

Completion record:

- `docs/CompletedPR/PR-VIDEO-237-Shared-Secondary-Motion-Engine-and-Provenance-Contract.md`

### 21A. `PR-HARDEN-256-WebUI-Pressure-Guardrails-and-Failure-Damping`

Status: Completed 2026-03-21

Interleaved critical hardening gate before the next runtime-heavy backend
rollout.

Primary outcomes:

- GPU-pressure risk classification and pre-stage warnings for image pipeline
  execution
- managed WebUI launch profiles including an SDXL-guarded low-memory mode
- failure damping for repeated readiness, watchdog, and diagnostics storms
- improved diagnostics bundles for stall and pressure incidents
- explicit warnings when live WebUI model state drifts from requested stage
  intent

Reason for slotting here:

- current image/runtime instability is significant enough that continuing
  backend-runtime rollout first would reduce confidence in later video PR
  validation

Completion record:

- `docs/CompletedPR/PR-HARDEN-256-WebUI-Pressure-Guardrails-and-Failure-Damping.md`

Validation note:

- live 10-job validation improved observability but did not materially stabilize
  the workload on its own
- the required follow-on hardening pass was delivered by `PR-HARDEN-257`
- combined outcome: the same workload class later completed successfully under
  guarded recovery and admission control

### 21B. `PR-HARDEN-257-WebUI-State-Recovery-and-Admission-Control`

Status: Implemented 2026-03-21

Follow-on critical hardening gate after `PR-HARDEN-256` real-world validation
showed that warnings alone are not enough.

Primary outcomes:

- detect poisoned or stale WebUI runtime state before heavy jobs begin
- force guarded clean restart and readiness recovery when runtime state is not
  healthy
- refuse clearly unsafe heavy stage execution instead of timing out deep in
  WebUI
- make watchdog and diagnostics single-flight authoritative
- surface duplicate-process risk and stale-process pressure in logs and
  diagnostics

Completion record:

- `docs/CompletedPR/PR-HARDEN-257-WebUI-State-Recovery-and-Admission-Control.md`

Reason for slotting here:

- `PR-HARDEN-256` reduced blind spots but did not reduce failures enough on its
  own, so runtime admission and guarded restart behavior had to land before the
  next runtime-heavy video PR

Validation note:

- heavy rerun using the same `AA LoRA Strength` workload class completed
  successfully: `10 / 10` complete `txt2img -> adetailer -> upscale` chains,
  `0` failures, `0` diagnostics bundles, average wall time `117.358s`
- validation summary: `reports/pr257_validation_summary.json`
- `PR-VIDEO-238` is now unblocked

### 21C. `PR-HARDEN-258-Workload-Aware-WebUI-Launch-Policy`

Status: Implemented 2026-03-21

Non-blocking follow-on to keep the global WebUI default conservative while
automatically upgrading heavy SDXL image workloads to `sdxl_guarded`.

Primary outcomes:

- retains `standard` as the global default launch profile
- automatically prefers `sdxl_guarded` for SDXL-heavy geometry and
  `txt2img -> adetailer/upscale` workload chains
- uses the managed restart/recovery path instead of ad hoc profile switching
- treats `low_memory` as an already-guarded profile

Completion record:

- `docs/CompletedPR/PR-HARDEN-258-Workload-Aware-WebUI-Launch-Policy.md`

### 22. `PR-VIDEO-238-SVD-Native-Secondary-Motion-Postprocess-Integration`

Status: Completed 2026-03-24

Use the safest existing postprocess seam to land the first real runtime motion
path.

Primary outcomes:

- runner-injected transient SVD motion execution config
- shared-engine application as SVD postprocess stage zero
- canonical motion provenance in SVD manifest, replay, and container metadata

Completion record:

- `docs/CompletedPR/PR-VIDEO-238-SVD-Native-Secondary-Motion-Postprocess-Integration.md`

### 23. `PR-VIDEO-239-AnimateDiff-Secondary-Motion-Frame-Pipeline-Integration`

Status: Completed 2026-03-24

Insert the shared engine into the existing AnimateDiff frame pipeline.

Primary outcomes:

- shared-engine application between frame write and video encode
- skip-safe AnimateDiff motion behavior with stable output-path semantics
- canonical motion provenance in AnimateDiff manifest, replay, and container metadata

Completion record:

- `docs/CompletedPR/PR-VIDEO-239-AnimateDiff-Secondary-Motion-Frame-Pipeline-Integration.md`

### 24. `PR-VIDEO-240-Workflow-Video-Secondary-Motion-Parity-and-Replay-Closure`

Status: Completed 2026-03-24

Close the last major backend parity gap for the shared motion carrier.

Primary outcomes:

- StableNew-owned extract/apply/re-encode parity path for workflow-video
- canonical replay closure without a new custom Comfy node dependency
- consistent motion summary shape across all three current video backends
- skip-safe fallback to the original workflow artifact when local prerequisites
  or re-encode steps are unavailable

Completion record:

- `docs/CompletedPR/PR-VIDEO-240-Workflow-Video-Secondary-Motion-Parity-and-Replay-Closure.md`

### 25. `PR-VIDEO-241-Learning-and-Risk-Aware-Secondary-Motion-Feedback`

Status: Completed 2026-03-24

Close the loop by making the shared motion carrier visible to learning and
recommendation flows without weakening evidence-tier safeguards.

Primary outcomes:

- scalar motion metrics in learning records
- backend-aware and application-path-aware motion recommendation context
- explicit backend/policy/path/status cohorting for motion evidence
- no raw frame or dense motion payload retention in centralized learning data

Completion record:

- `docs/CompletedPR/PR-VIDEO-241-Learning-and-Risk-Aware-Secondary-Motion-Feedback.md`

## 4A. Post-`PR-VIDEO-241` Prompt Optimizer Tranche

The next product-facing image/prompt tranche is tracked in:

- `docs/CompletedPlans/PROMPT_OPTIMIZER_EXECUTABLE_ROADMAP_v2.6.md`

It is intentionally queued after the current secondary-motion video sequence
and before broader lower-leverage cleanup. The planned rollout is:

- `PR-PROMPT-241A-Format-Only-Safety-and-Dedupe-Hardening`
- `PR-PROMPT-241B-Orchestrator-and-Intent-Bundle-Recommend-Only`
- `PR-PROMPT-241C-Stage-Policy-Engine-and-Auto-Safe-Fill-Missing`
- `PR-PROMPT-241D-Manifest-Schema-v3-and-Replay-Contract`
- `PR-PROMPT-241E-Learning-Hooks-and-Tuning-Scaffolding`

## 4AA. Learning/Review Staged Curation Tranche

The next Learning/Review product tranche is tracked in:

- `docs/CompletedPlans/STAGED_CURATION_EXECUTABLE_ROADMAP_v2.6.md`

This tranche is accepted in direction, but it is intentionally shaped to fit
the current product:

- `Learning` becomes the canonical evidence-and-advancement workspace
- `Review` remains the canonical advanced reprocess workspace
- no standalone competing curation architecture is introduced

Priority note:

- this tranche is now explicitly prioritized after the image output-route
  regression is closed and after recognizing `PR-VIDEO-238` through
  `PR-VIDEO-241` as completed backend/runtime work
- immediate order:
  1. close the image output-route regression
  2. treat `PR-LEARN-259A` as verified baseline
  3. treat `PR-LEARN-260A` through `PR-LEARN-260C` as completed
  4. treat `PR-LEARN-260D` as completed
  5. treat `PR-LEARN-260E` as completed
  6. treat `PR-LEARN-260F` as completed
  7. treat `PR-LEARN-261` as completed
  8. treat `PR-LEARN-262` as completed
  9. treat `PR-LEARN-263` as completed
  10. treat `PR-LEARN-264` as completed
  11. treat `PR-VIDEO-238` as completed
  12. treat `PR-VIDEO-239` as completed
  13. treat `PR-VIDEO-240` as completed
  14. treat `PR-VIDEO-241` as completed
  15. treat `PR-PROMPT-241A` as completed
  16. treat `PR-PROMPT-241B` as completed
  17. treat `PR-PROMPT-241C` as completed
  18. treat `PR-PROMPT-241D` as completed
  19. treat `PR-PROMPT-241E` as completed
  20. treat `PR-UX-265` as completed
  21. treat `PR-UX-266` as completed
  22. treat `PR-UX-271` as completed
  23. treat `PR-UX-267` as completed
  24. treat `PR-UX-268` as completed
  25. treat `PR-UX-269` as completed
  26. treat `PR-UX-270` as completed
  27. treat `PR-UX-272` as completed
  28. treat `PR-UX-273` as completed
  29. treat `PR-UX-274` as completed
  30. treat `PR-UX-275` as completed
  31. treat `PR-UX-276` as completed
  32. treat `PR-UX-277` as completed
  33. treat `PR-UX-278` as completed
  34. treat `PR-UX-279` as completed

Planned rollout:

- `PR-PROMPT-241A-Format-Only-Safety-and-Dedupe-Hardening`
  Completed 2026-03-24

- `PR-PROMPT-241B-Orchestrator-and-Intent-Bundle-Recommend-Only`
  Completed 2026-03-24

- `PR-PROMPT-241C-Stage-Policy-Engine-and-Auto-Safe-Fill-Missing`
  Completed 2026-03-24

- `PR-UX-266-Action-Buttons-and-High-Risk-Controls-Explained`
  Completed 2026-03-24

- `PR-UX-268-Effective-Config-Summaries-and-Why-This-Value-Is-Used`
  Completed 2026-03-25

- `PR-UX-269-Workflow-Pathway-Guidance-and-Use-Case-Recommendations`
  Completed 2026-03-25

- `PR-UX-270-Contextual-Help-Mode-and-Inspectable-UI-Language-Polish`
  Completed 2026-03-25

- `PR-UX-272-GUI-Audit-and-Consistency-Inventory`
  Completed 2026-03-25

- `PR-UX-273-Shared-Dark-Mode-Tokens-and-Widget-Theme-Discipline`
  Completed 2026-03-25

- `PR-UX-274-Shared-Layout-Minimums-and-Resize-Discipline`
  Completed 2026-03-26

- `PR-UX-275-Pipeline-and-Stage-Card-Resilience-Sweep`
  Completed 2026-03-26

- `PR-UX-276-Prompt-and-LoRA-Row-Usability-Sweep`
  Completed 2026-03-26

- `PR-UX-277-Review-Learning-and-Video-Panel-Consistency-Sweep`
  Completed 2026-03-26

- `PR-UX-278-Dialog-Inspector-and-Secondary-Surface-Consistency-Sweep`
  Completed 2026-03-26

- `PR-UX-279-GUI-Consistency-Regression-Checks-and-Maintenance-Checklist`
  Completed 2026-03-26

- `PR-PROMPT-241D-Manifest-Schema-v3-and-Replay-Contract`
  Completed 2026-03-24

- `PR-PROMPT-241E-Learning-Hooks-and-Tuning-Scaffolding`
  Completed 2026-03-24

- `PR-UX-265-Tab-Overview-Panels-and-Workflow-Explainers`
  Completed 2026-03-24

- `PR-UX-271-GUI-Layout-Resilience-and-LoRA-Control-Usability`
  Completed 2026-03-25

- `PR-UX-267-Stage-Card-Settings-Help-and-Config-Intent-Descriptions`
  Completed 2026-03-25

- `PR-LEARN-259A-Curation-Contracts-Lineage-and-Selection-Events`
  Completed 2026-03-21
- `PR-LEARN-259B-Learning-Workspace-Staged-Curation-Mode`
  Completed 2026-03-21
- `PR-LEARN-259C-Review-History-Import-and-Large-Compare-Surface`
  Completed 2026-03-21
- `PR-LEARN-259D-Derived-Stage-Advancement-and-Face-Triage-Routing`
  Completed 2026-03-21
- `PR-LEARN-259E-Learning-Evidence-Bridge-and-Reason-Tag-Analytics`
  Completed 2026-03-21
- `PR-LEARN-259F-Replay-Diagnostics-and-Workflow-Summaries`
  Completed 2026-03-21
- `PR-LEARN-260A-Staged-Curation-Source-Prompt-Surface-and-Decision-Context`
  Completed 2026-03-22
- `PR-LEARN-260B-Staged-Curation-Plan-Build-vs-Enqueue-Seam`
  Completed 2026-03-22
- `PR-LEARN-260C-Learning-To-Review-Handoff-and-Review-Draft-Load`
  Completed 2026-03-23
- `PR-LEARN-260D-Review-Derived-Config-Inspector-and-Effective-Settings-Summary`
  Completed 2026-03-23
- `PR-LEARN-260E-Source-vs-Derived-Outcome-Compare-and-Lineage-Jump`
  Completed 2026-03-23
- `PR-LEARN-260F-Queue-Now-vs-Edit-in-Review-UX-Polish-and-Bulk-Selection-Rules`
  Completed 2026-03-23
- `PR-LEARN-261-Portable-Review-Metadata-Stamping`
  Completed 2026-03-23
- `PR-LEARN-262-Portable-Review-Metadata-Rehydration-and-UI-Surfacing`
  Completed 2026-03-23
- `PR-LEARN-263-Artifact-Metadata-Inspector-and-Debug-UI`
  Completed 2026-03-23
- `PR-LEARN-264-Canonical-Metadata-Schemas-and-Contracts`
  Completed 2026-03-23

### Completed follow-on: Content Visibility Safety Tranche

Status: Completed 2026-03-27

This follow-on tranche is now complete for the active prompt, preview, queue,
history, learning, review, and video-facing GUI surfaces.

Delivered outcomes:

- `PR-CONFIG-271` added the canonical persisted `sfw` / `nsfw` mode contract
  and app-state notification path
- `PR-CTRL-272` added the shared resolver and wired filtering/redaction through
  prompt-pack, LoRA, history, and discovered-review selector paths
- `PR-GUI-273` added the global shell toggle plus live cross-tab filtering,
  redaction notices, and refresh wiring across mounted v2 surfaces
- `PR-TEST-274` added deterministic regression, journey, and learning-path
  hardening for persistence, live updates, and legacy metadata fallback

Completion records:

- `docs/CompletedPR/PR-CONFIG-271-Content-Visibility-Mode-Contract-and-Persistence.md`
- `docs/CompletedPR/PR-CTRL-272-Content-Visibility-Resolver-and-Selector-Wiring.md`
- `docs/CompletedPR/PR-GUI-273-Mode-Toggle-UX-and-Cross-Tab-Filtering.md`
- `docs/CompletedPR/PR-TEST-274-Content-Visibility-Regression-and-Journey-Hardening.md`

Sequencing note:

- close the current image output-route regression before beginning this tranche,
  because discovered/imported review quality depends on correct output
  classification

## 4AB. GUI Responsiveness Closure Tranche

Status: Completed 2026-03-29

This tranche closed the gap between runner/controller architectural separation
and actual GUI repaint-cadence ownership.

Repo-truth status:

- `PR-GUI-283-AppController-UI-Boundary-Closure-and-Operator-Log-Projection`
  Completed 2026-03-28
- `PR-GUI-284-AppState-Batched-Invalidation-and-Flush-Contract`
  Completed 2026-03-28
- `PR-GUI-285-Hot-Surface-Refresh-Scheduler-and-Subscription-Ownership`
  Completed 2026-03-28
- `PR-GUI-286-Incremental-Projection-Reconciliation-and-Visibility-Gating`
  Completed 2026-03-29
- `PR-HARDEN-287-Runtime-Status-Backpressure-GUI-Perf-Journey-and-Architecture-Guards`
  Completed 2026-03-29

Delivered outcomes:

- `AppController` no longer writes operator-log or bottom-status text directly
  into Tk widgets
- `AppStateV2` now batches hot runtime keys and exposes an explicit operator-log
  buffer plus `flush_now()`
- `PipelineTabFrameV2` owns hot queue/history/preview refresh scheduling for
  the pipeline shell
- hidden pipeline hot surfaces now defer work instead of burning Tk time while
  unmapped
- the same visibility-gated deferral now reaches prompt/review/learning/photo-optimize/
  SVD/movie/video/Debug Hub hot refresh surfaces
- architecture enforcement now blocks controller-side Tk imports and direct
  widget mutation patterns
- the deterministic synthetic busy-run perf journey is now the canonical GUI
  responsiveness proof, with `p95 <= 35 ms` and `max <= 100 ms`

## 4B. Post-`PR-VIDEO-241` Structural Queue

The structural queue that followed the secondary motion tranche was tracked in:

- `docs/PR_Backlog/TOP_20_VERDICTS_AND_POST_VIDEO241_QUEUE_v2.6.md`

That queue converted the 2026-03-21 deep-research audit into a repo-truth-based
remediation sequence. The highest-priority follow-on items were:

- `PR-ARCH-242-Controller-GUI-Boundary-Core-Controller-Reset`
  Completed 2026-03-27
- `PR-ARCH-243-Archive-Import-Fencing-and-Reference-Relocation`
  Completed 2026-03-29; live archive Python modules were removed from
  `src/**/archive/**`, relocated reference-only code now lives under
  `tools/archive_reference/`, and archive import regressions are fenced by
  `tests/safety/test_no_archive_python_modules_under_src.py` plus the
  architecture/taxonomy enforcement suite
- `PR-HYGIENE-244-Tracked-Runtime-State-Purge-and-Hygiene-Enforcement`
  Completed 2026-03-29; runtime-state ownership is centralized through
  `src/state/workspace_paths.py`, tracked-state drift is guarded by
  `tests/safety/test_runtime_state_hygiene.py`, and the short canonical
  contract now lives in `docs/runbooks/TRACKED_RUNTIME_STATE_HYGIENE_v2.6.md`
- `PR-CI-245-CI-Truth-Sync-and-Smoke-Suite-Contract`
  Completed 2026-03-29; CI now runs the named required smoke gate
  `tools/ci/run_required_smoke.py`, and workflow/docs drift is enforced by
  `tests/system/test_ci_truth_sync_v2.py`
- `PR-ARCH-246-Architecture-Enforcement-Expansion-and-Import-Guards`
  Completed 2026-03-29; the enforcement suite now covers controller-side Tk
  import bans, direct widget-mutation bans, archive/reference fencing, and
  backend-runtime imports constrained to the controller port layer
- `PR-CTRL-247-PipelineController-Service-Extraction-and-Facade-Reduction`
  Completed 2026-03-29; queue-submission orchestration now lives in
  `src/controller/pipeline_controller_services/queue_submission_service.py`,
  reducing `PipelineController` to a thinner facade over bounded submission and
  history-handoff services
- `PR-PORTS-248-Backend-Port-Boundaries-for-Image-and-Video-Runtimes`
  Completed 2026-03-29; controller-owned image-runtime and workflow-registry
  ports now live in `src/controller/ports/runtime_ports.py`, default concrete
  adapters are isolated to `src/controller/ports/default_runtime_ports.py`, and
  `AppController`, `PipelineController`, and `VideoWorkflowController` are
  wired through that boundary
- `PR-OBS-249A-Structured-Event-Logging-Contract-and-Ascii-Normalization`
  Completed 2026-03-21
- `PR-OBS-249B-Log-Trace-Panel-Severity-Coloring-and-Event-Filters`
  Completed 2026-03-21
- `PR-OBS-249C-Repeated-Event-Collapse-and-WebUI-Outage-Dedup`
  Completed 2026-03-21
- `PR-OBS-249D-Operator-vs-Trace-Log-Surface-Split`
  Completed 2026-03-21
- `PR-REPLAY-250-Replay-Fidelity-Contract-and-Versioned-Validation`
  Completed 2026-03-29; replay now validates versioned intent contracts and
  hash closure before hydrating NJR snapshots, with compat coverage for legacy
  snapshots that lack the new contract
- `PR-APP-251-Shared-Application-Bootstrap-and-Kernel-Composition`
  Completed 2026-03-29; GUI and CLI now compose through the shared
  `src/app/bootstrap.py` `ApplicationKernel`
- `PR-HARDEN-252-Optional-Dependency-Capabilities-and-Startup-Probes`
  Completed 2026-03-29; optional dependency readiness is now published through
  the shared snapshot contract in `src/app/optional_dependency_probes.py` and
  surfaced via application diagnostics
- `PR-CI-253-Mypy-Smoke-Gate-and-Whitelist-Expansion`
  Completed 2026-03-29; CI now runs the bounded typed-seam gate in
  `tools/ci/run_mypy_smoke.py`
- `PR-CONTRACT-254-Intent-Artifact-Versioning-and-Hash-Closure`
  Completed 2026-03-29; intent artifacts now carry explicit schema/version/hash
  metadata in config layers and job snapshots
- `PR-VIDEO-255-Workflow-Registry-Governance-and-Pinning-Closure`
  Completed 2026-03-29; workflow specs now encode governance state and pinned
  revision, and the canonical registry returns only approved pinned workflows

Recommendation L is now delivered through `PR-OBS-249A` through
`PR-OBS-249D`. After `PR-OBS-249D`, the bottom log is the operator surface and
the Debug Hub is the detailed trace surface.

## 4C. Current Remaining Backlog Queue

Status: Rebased 2026-03-29

After validating the current backlog docs against `docs/CompletedPR/`,
`docs/CompletedPlans/`, live source, and the current test suite baseline, the
remaining active queue is narrower than several older backlog docs imply.

Repo-truth corrections:

- `PR-UX-278` is already completed; see
  `docs/CompletedPR/PR-UX-278-Dialog-Inspector-and-Secondary-Surface-Consistency-Sweep.md`.
- `PR-UX-279` is already completed; see
  `docs/CompletedPR/PR-UX-279-GUI-Consistency-Regression-Checks-and-Maintenance-Checklist.md`.
- `PR-TEST-280` is no longer a live blocker: `pytest --collect-only -q` now
  succeeds with `2964 collected / 0 skipped`, and the stale spec has been
  retired to `docs/archive/reference/PR-TEST-280-Full-Suite-Collection-Recovery-and-Test-Hygiene.md`.
- `PR-HARDEN-281` appears largely absorbed in current source and tests: default
  ADetailer request-local pinning is off, request-local override remains opt-in,
  structured `NansException` failures do not trigger restart recovery, and the
  request-local ambient drift downgrade is covered.
- `PR-POLISH-282` is satisfied by this roadmap rebaseline and should not remain
  a separate near-term execution item unless fresh cross-doc drift appears; the
  stale spec has been retired to
  `docs/archive/reference/PR-POLISH-282-Canonical-Roadmap-Video-Status-Harmonization.md`.
- older completed or superseded sequence snapshots have been removed from
  `docs/PR_Backlog/`; completed rollout docs now live in `docs/CompletedPlans/`
  and stale snapshots live in `docs/archive/reference/`.

Current priority order:

1. `PR-CORE-001 - Finalize Native SVD Integration`
  Reason: the SVD runtime, controller, and GUI substrate already exists, but
  the repo still lacks dedicated end-to-end SVD integration coverage and a
  fully closed repo-truth execution spec for the active path.
2. `PR-CORE-011 - End-to-End Pipeline Tests`
  Reason: after `PR-CORE-001`, the highest-value follow-on is explicit golden-
  path coverage for the integrated SVD/video path rather than broader suite
  collection recovery.
3. `PR-CORE-004 - Cinematic Prompt Template Library`
  Reason: the prompt authoring layer is still missing and does not conflict
  with shipped architecture.
4. `PR-CORE-002 - Character Embedding Pipeline`
  Reason: this is still missing and high value, but it is operationally larger
  than the authoring-layer work above.
5. `PR-CORE-014 - Multi-Character Support`
  Reason: it should follow the character asset and training pipeline, not lead
  it.
6. merged `PR-CORE-005` / `PR-CORE-017` camera-control and ControlNet tranche
  Reason: the two current specs overlap heavily and should not be executed as
  separate parallel proposals.
7. `PR-CORE-008 - Style Consistency LoRA`
  Reason: style-control work is valuable, but it is cleaner once character and
  training surfaces are established.
8. `PR-CORE-018 - Documentation and Usage Examples`
  Reason: this should explain shipped behavior rather than lead it.
9. `PR-CORE-019 - Book Ingestion Tool`
  Reason: it depends on the re-scoped story-planning productization path.
10. `PR-CORE-020 - Research Spike: 3D and NeRF Exploration`
   Reason: this remains intentionally exploratory and low priority.

Execution note:

- use `docs/PR_Backlog/CORE_TOP_20_EXECUTABLE_MINI_ROADMAP_v2.6.md` as the
  active entry point for the split `PR-CORE-001` through `PR-CORE-020` specs
  now that the old bundled file has been retired
- do not execute `PR-CORE-003`, `PR-CORE-006`, `PR-CORE-007`, `PR-CORE-009`,
  `PR-CORE-010`, `PR-CORE-012`, `PR-CORE-013`, `PR-CORE-015`, or
  `PR-CORE-016` verbatim without re-scoping them against the shipped repo state

## 5. Missing Common Functionality to Fold Into the Queue

These are the important missing capabilities that are not just "nice to have":

- adaptive refinement rollout is complete through prompt-patch,
  upscale-policy, and learning-aware feedback; remaining work is inspection
  ergonomics, presentation clarity, and follow-on tuning rather than missing
  execution slices
- replay and learning still need clearer operator-facing inspection and
  summarization of canonical refinement-decision provenance
- secondary motion backend/runtime rollout is complete through `PR-VIDEO-241`;
  remaining video debt is now mainly operator UX exposure, inspection clarity,
  and longer-tail structural cleanup
- manifests, replay fragments, container metadata, and learning now carry
  canonical secondary-motion provenance; remaining work is chiefly presentation,
  inspection ergonomics, and broader contract cleanup rather than missing core
  provenance paths
- image/runtime stability now has pressure guardrails, runtime admission
  control, and workload-aware guarded-launch policy; remaining work is
  follow-on validation, diagnostics clarity, and longer-tail runtime cleanup
- content visibility now has a canonical persisted mode, shared resolver, live
  cross-tab filtering, and regression coverage; remaining work is optional
  policy strictness tuning rather than missing foundation behavior
- continuity and story-planning still need richer UX exposure on top of the now-coherent video workspace
- further controller reduction is still desirable, but no longer blocked on the GUI config adapter seam

## 6. Done Definition for the Next Stage

StableNew's next stage is successful when:

- image and short-form video are both solid under the current queue-first architecture
- image generation can apply runner-owned adaptive refinement under explicit
  rollout modes without creating a second execution model
- video generation can apply runner-owned secondary motion across the existing
  video backends without creating a new stage or new job model
- long-form video has a first-class planning/orchestration path
- post-video outputs are canonical artifacts, not side utilities
- continuity and shot-planning data can persist through manifests/history
- manifests, replay fragments, container metadata, and learning records can
  preserve both adaptive-refinement and secondary-motion provenance
- the GUI feels intentionally designed around the current workflow set

## 7. Guiding Principle

Prefer doing it right over doing it easy.

At this point, “right” means:

- keep the architecture stable
- add missing product layers on top of the stable core
- improve UX before considering a toolkit rewrite
