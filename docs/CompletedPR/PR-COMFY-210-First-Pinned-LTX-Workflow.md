# PR-COMFY-210 - First Pinned LTX Workflow

Status: Completed 2026-03-19

## Purpose

Ship the first real Comfy-backed workflow through the existing StableNew v2.6
architecture:

`NJR -> Queue -> PipelineRunner -> Video backend registry -> Comfy backend -> Canonical artifacts/history/replay`

This PR had to preserve the existing invariants:

- NJR remains the only outer job contract
- `VideoExecutionRequest` remains internal to the runner/backend seam
- no Comfy leakage outside `src/video/`
- no second video job model

## What Changed

### Canonical workflow-backed video stage

Updated:

- `src/pipeline/stage_models.py`
- `src/pipeline/stage_sequencer.py`
- `src/pipeline/config_normalizer.py`
- `src/pipeline/job_models_v2.py`
- `src/pipeline/run_plan.py`
- `src/pipeline/pipeline_runner.py`
- `src/pipeline/prompt_pack_job_builder.py`
- `src/pipeline/reprocess_builder.py`
- `src/pipeline/artifact_contract.py`

This adds `video_workflow` as a real canonical video stage instead of a hidden
backend-only special case.

Delivered behavior:

- normalized config support for `video_workflow`
- canonical stage ordering and validation for workflow-backed video
- NJR stage chains and run plans can now carry `video_workflow`
- runner validation now treats workflow video as a terminal video stage
- generic video artifact summaries continue to work for the new stage

### First managed Comfy workflow backend

Added:

- `src/video/comfy_workflow_backend.py`

Updated:

- `src/video/video_backend_registry.py`
- `src/video/__init__.py`
- `src/video/comfy_api_client.py`
- `src/video/workflow_catalog.py`
- `src/video/workflow_compiler.py`

Delivered behavior:

- default video backend registry now includes managed `comfy` support for
  `video_workflow`
- the pinned `ltx_multiframe_anchor_v1` spec now includes a StableNew-owned
  prompt template
- the compiler now materializes a queueable Comfy prompt payload from workflow
  metadata plus `VideoExecutionRequest`
- the backend validates Comfy dependencies before queueing
- the backend submits the compiled workflow to Comfy, waits on prompt history,
  resolves final output artifacts, and writes a StableNew-owned manifest

### Canonical replay and artifact metadata

Comfy-backed workflow runs now emit:

- canonical artifact payloads under `stablenew.artifact.v2.6`
- StableNew-owned manifest files in the run `manifests/` directory
- workflow replay metadata including:
  - `backend_id`
  - `workflow_id`
  - `workflow_version`
  - `prompt_id`
  - dependency snapshot
  - compiled input summary

## Optional Dependency Cleanup

OpenCV is now installed in this environment, which exposed the real reason the
global skipped SVD worker test could not run: `torch` is not installed here.

Updated:

- `tests/video/test_svd_postprocess_worker.py`

The test now cleanly skips when either optional dependency is missing instead of
failing collection after `cv2` becomes available.

Current global skip reason:

- `tests/video/test_svd_postprocess_worker.py` skips on missing `torch`

## Tests

Added:

- `tests/video/test_comfy_workflow_backend.py`

Updated:

- `tests/video/test_comfy_api_client.py`
- `tests/video/test_video_backend_registry.py`
- `tests/video/test_workflow_compiler.py`
- `tests/pipeline/test_pipeline_runner.py`
- `tests/pipeline/test_stage_sequencer_plan_builder.py`
- `tests/video/test_svd_postprocess_worker.py`

Verification:

- `pytest tests/video/test_workflow_registry.py tests/video/test_workflow_compiler.py tests/video/test_comfy_api_client.py tests/video/test_comfy_dependency_probe.py tests/video/test_comfy_workflow_backend.py tests/video/test_video_backend_registry.py -q`
- `pytest tests/pipeline/test_pipeline_runner.py tests/pipeline/test_stage_sequencer_plan_builder.py tests/pipeline/test_config_contract_v26.py -q`
- `pytest tests/app/test_bootstrap_comfy_autostart.py tests/video/test_comfy_process_manager.py tests/video/test_comfy_healthcheck.py tests/pipeline/test_svd_runtime.py tests/pipeline/test_animatediff_runtime.py tests/controller/test_app_controller_svd.py tests/gui_v2/test_job_history_panel_v2.py -q`
- `pytest --collect-only -q -rs` -> `2377 collected / 1 skipped`
- `python -m compileall src/video src/pipeline tests/video tests/pipeline tests/app`

## Architectural Result

StableNew now has a real first Comfy-backed workflow path while preserving the
v2.6 architecture:

- one outer job contract: NJR
- one orchestration system: StableNew
- one video backend seam under `src/video/`
- one canonical artifact/history contract shared by native and Comfy-backed
  video

## Deferred To Next PR

Owned by `PR-TEST-211`:

- canonical vs compat/quarantine suite normalization
- removal of remaining archive DTO imports from active test surfaces
- establishing the new collection baseline as the canonical test-governance
  target

Next planned PR: `PR-TEST-211`
