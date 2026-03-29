PR-CORE-001 - Finalize Native SVD Integration

Status: Specification
Priority: HIGH
Effort: MEDIUM
Phase: Post‑Unification Core Refinement
Date: 2026-03-29

2. Context & Motivation

The v2.6 branch already contains a complete implementation of the native
Stable Video Diffusion (SVD) pipeline and a dedicated GUI tab
(SVDTabFrameV2) for animating still images into short clips. The
SVDService, SVDRunner, svd_preprocess.py, svd_postprocess.py, and
svd_tab_frame_v2.py provide a fully functional pipeline for
image‑to‑video diffusion and optional post‑processing (secondary motion,
interpolation, upscale, face restore). Thus the
goal of PR‑CORE‑001 is not to build an SVD tab from scratch—this work
already exists—but to finalize its integration into the StableNew
architecture. The tasks include aligning the SVD pipeline with the
canonical job model (NJR), ensuring all configuration options round‑trip
through the builder and queue, improving tests and documentation, and
closing any remaining gaps noted in the backlog (e.g. pipeline defaults,
history handling, and error propagation). Completing this PR will
eliminate confusion about whether an SVD backend is missing and will
prepare the ground for advanced features like ControlNet and longer
sequence jobs.

3. Goals & Non‑Goals
Goal: Ensure the native SVD stage is fully compatible with the
canonical job model (NormalizedJobRecord) and can be invoked
through the queue/runners without bypassing NJR. The config fields
used by svd_tab_frame_v2 must map to validated intent fields in
config_contract_v26.
Goal: Add or update unit tests and integration tests to cover
end‑to‑end SVD runs (preprocess → diffusion → postprocess → export).
Tests should mock the diffusers pipeline to avoid GPU requirements
while verifying parameter wiring.
Goal: Document the SVD feature clearly, updating docs and
help panels to reflect that the native SVD backend exists and how
users should choose between SVD and AnimateDiff/WebUI.
Goal: Unify default settings and presets in SVD with the
global configuration infrastructure so that changes are persisted and
surfaced consistently in the GUI.
Non‑Goal: Implement ControlNet, camera motion, or other new
features. These will be addressed in separate PRs (see PR‑CORE‑005
and PR‑CORE‑017). PR‑CORE‑001 focuses on finalizing existing SVD
functionality and aligning it with the architecture.
4. Guardrails
Preserve the single NJR job model. Do not reintroduce direct
execution or bypasses; svd_native must remain a valid stage type.
Maintain the separation between pipeline configuration layers and
backend execution. SVD parameter translation should live in the
builder/controller, not in the UI widgets.
Do not alter Comfy or WebUI backends. This PR only touches the
native SVD pipeline and its integration points.
Keep GUI changes limited to wiring existing fields to the
configuration and status surfaces; no redesign of the Tkinter layout.
5. Allowed Files
Files to Create
tests/video/test_svd_integration.py – new integration test to
simulate an NJR submission of an SVD job using a dummy image and
verifying that the SVDRunner produces the expected output files and
metadata.
Files to Modify
src/pipeline/config_contract_v26.py – add or update schema
definitions for the SVD intent fields so that the builder can
validate and normalize SVD parameters.
src/pipeline/job_builder_v2.py – ensure SVD form data from the
GUI is translated into the correct StageConfig fields and that
default values are filled in from presets.
src/controller/app_controller.py – adjust submit_svd_job and
related methods to queue SVD work via the NJR, returning a job ID.
src/gui/views/svd_tab_frame_v2.py – minor updates to use
app_controller.build_svd_defaults() and to confirm that form
generation aligns with the updated config contract.
docs – update user documentation (e.g. Movie_Clips_Workflow_v2.6.md
and StableNew Roadmap v2.6.md) to reflect that the native SVD
backend is available and supported. Add a “SVD Quickstart” section.
Forbidden Files
Do not modify any files under src/video/ that pertain to the
low‑level SVD runtime (svd_service.py, svd_runner.py, etc.). The
underlying pipeline is considered stable and should only be touched
through configuration.
Do not alter Comfy or WebUI backends (src/video/comfy_*).
6. Implementation Plan
Contract Extension: Update
src/pipeline/config_contract_v26.py to include a svd_native
intent block with the fields currently passed by
svd_tab_frame_v2 (e.g. preprocess.target_width, inference.fps,
postprocess.face_restore.enabled). Provide default values and
validation constraints (e.g. motion_bucket in 0–255). Add unit
tests verifying the schema loads and rejects invalid types.
Job Builder Wiring: Extend
job_builder_v2.py to recognize svd_native stages in the
intent config. When building the StageConfig, map form fields to
the SVDConfig dataclass (already defined in svd_config.py).
Ensure that default presets from svd_tab_frame_v2 are applied if
parameters are omitted. Add test coverage for this mapping.
Controller Submission: In
app_controller.py, modify submit_svd_job to create a
PipelineRunRequest with an svd_native stage. The method should
enqueue the NJR via job_service.submit() and return the job ID.
Provide graceful error handling if the SVD service is unavailable.
GUI Adjustments: In
svd_tab_frame_v2.py, ensure that build_svd_defaults() and
get_supported_svd_models() from the controller supply model
options and runtime presets. Remove any direct file system calls
for defaults. Ensure the UI fields map directly to the intent
contract keys.
Testing: Implement tests/video/test_svd_integration.py. Use
a dummy image from tests/data/ and monkeypatch the diffusers
pipeline to return deterministic frames. Submit an NJR job via the
controller and verify that the runner produces an MP4 file, a
manifest with correct metadata, and that the job completes without
raising exceptions. Also add or update unit tests in
tests/pipeline for the config contract changes.
Documentation: Update the relevant docs with instructions for
using the native SVD tab and noting differences from WebUI/AnimateDiff.
Review & Hardening: Prior to merging, run the full test suite
(pytest -q) to confirm no regressions. Inspect logs for any
uncaught errors. Provide manual verification instructions for
maintainers to animate a sample image via the GUI and CLI.
7. Testing Plan

Unit tests:

Add tests for the new SVD schema fields in
test_config_contract.py to ensure that default values are applied
and invalid inputs (e.g. negative FPS) are rejected.
Test job_builder_v2.py to verify that SVD intent config is
translated into SVDConfig correctly.

Integration tests:

tests/video/test_svd_integration.py – queue an SVD job using a
dummy image and assert that the output files and metadata exist and
have expected fields.
Update an existing GUI test (if any) to open the SVD tab and
confirm that model options and presets load without error.

Journey/smoke tests:

Manual run of the SVD tab in the GUI: load an image, select a
preset, submit, and ensure a video file is created in the output
directory.
8. Verification Criteria

Success criteria:

Submitting an SVD job via the UI or CLI produces a video file,
manifest, and optional preview/frames consistent with the chosen
settings.
All SVD configuration fields are validated and round‑trip through
NormalizedJobRecord without data loss.
The test suite passes, including the new integration test.

Failure criteria:

SVD jobs bypass the NJR and are executed directly.
Missing or invalid configuration fields cause runtime crashes.
The SVD tab fails to load models or presets after refactoring.
9. Risk Assessment

Low‑risk areas: Schema changes and job builder wiring are local
edits and can be covered by unit tests.

Medium‑risk areas: Controller submission changes may introduce
queueing bugs if not carefully coordinated with job service. Mitigate
by exercising the integration test on multiple runs.

High‑risk areas: None. This PR intentionally avoids altering the
underlying SVD runtime.

Rollback plan: If issues arise, revert changes to the config
contract and job builder, and retain the existing direct SVD submission
path temporarily until the next release.

10. Tech Debt Analysis

Debt removed: Aligning SVD with the canonical NJR model reduces
one-off execution paths and simplifies future support for ControlNet and
longer sequences.

Debt deferred: We do not address the monolithic controller size or the
UI redesign debt; these remain for later UI/UX PRs.

Next PR owner: Follow‑on tasks related to ControlNet and
interpolation tuning will be handled in PR‑CORE‑005 and PR‑CORE‑017.

11. Documentation Updates

Update the following docs in this PR:

docs/Movie_Clips_Workflow_v2.6.md – add a section on native SVD
usage and presets.
docs/StableNew Roadmap v2.6.md – mark the native SVD backend as
complete and reference this PR in the timeline.
docs/CompletedPR/ – after implementation, move this spec to
docs/CompletedPR/PR-CORE-001-Finalize-SVD-Integration.md and note
the completion date.
12. Dependencies
Internal: svd_service.py, svd_runner.py, svd_tab_frame_v2.py are
required to remain stable; we will not modify them. We depend on
existing job service and NJR queue infrastructure.
External: The Diffusers library and the Stable Video Diffusion
checkpoint must remain compatible. No new external dependencies are
introduced.
13. Approval & Execution

Planner: ChatGPT Planner
Executor: Codex/Developer
Reviewer: @pipeline-team
Approval Status: Pending

14. Next Steps

After merging this PR, proceed with PR‑CORE‑005 (Camera Control /
ControlNet) to extend SVD with optional depth/pose inputs, and
PR‑CORE‑006 to improve interpolation options beyond RIFE. Also begin
drafting user documentation for the SVD feature as part of
PR‑CORE‑018.

