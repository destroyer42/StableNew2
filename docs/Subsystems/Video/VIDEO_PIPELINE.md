# Video pipeline

Status: living document, edit in place
Owner area: video generation and post-processing (`src/video/`, the video branch of `src/pipeline/pipeline_runner.py`, `src/controller/svd_controller.py`, `src/controller/video_workflow_controller.py`, `config/managed_comfy_runtime.json`)

How to keep this true:
- Change this file in the same PR that changes video behavior, ownership, a workflow's governance state or a safety rule. Edit the existing row or sentence.
- Do not append per-PR sections, dates or test counts. History lives in `git log` and the per-PR records listed at the end.
- Labels: **[V]** read in the code when this was written; **[A]** taken from `docs/audits/2026-10-16_repo_audit_and_roadmap.md`, not re-checked.

## 1. Scope, what is accepted, and the canonical path

This document covers image-to-video: the native Stable Video Diffusion XT path and its post-processing (CodeFormer, Real-ESRGAN-style upscale, RIFE), the Comfy Video Workflow (workflow catalog, NJR builder, Comfy backend, managed Comfy runtime), the neutral video execution contract, motion sources, provenance and replay, and Movie Clips assembly. Still-image work is in `docs/Subsystems/Image/IMAGE_PIPELINE.md`.

### 1.1 Production versus experimental

| Capability | Status | Rule |
|---|---|---|
| Native SVD XT (`svd_native`) | **Accepted for production.** The only accepted video backend (`STATUS.md`, `AGENTS.md`). | Runs by default once queued. |
| SVD post-processing: CodeFormer, Real-ESRGAN-style upscale, RIFE x2/x4, secondary motion | Accepted, optional per job, each needs its own local assets. | Section 3.2. |
| SVD post-processing: GFPGAN | **Unsupported.** Offered in the SVD tab, refused at admission (`GFPGAN_UNSUPPORTED_ISSUE`). | Section 3.2. |
| Wan2.2 TI2V-5B prompt-directed I2V (`wan22_ti2v_5b_i2v_v1`) | **Experimental**, the only conditionally qualified directed-motion candidate. Never approved, never default. | Per-job opt-in. |
| Wan-Animate-2, prompt mode and driving-video mode (`wan_animate2_prompt_i2v_v1`, `wan_animate2_drive_i2v_v1`) | **Experimental.** Promotion readiness is not met (owner decision pending). | Per-job opt-in, managed Comfy launched with `--disable-pinned-memory`. |
| LTX multi-frame anchor (two specs) | **Disabled.** Contract metadata only; the bridge nodes do not exist. Not offerable, not runnable. | Section 4.2. |
| AnimateDiff (`animatediff`) | Registered backend with no GUI control; needs the WebUI executor. Retirement is an open owner decision. | Section 9. |
| Movie Clips (FFmpeg assembly of existing outputs) | Retained feature, not a generation path and not queued. | Section 7. |

No Comfy workflow is `approved`. Promoting one is an owner decision (audit G7, roadmap P5-7) and starts with a catalog governance change plus the audit's P3-3 and P3-4 fixes (managed process containment, Comfy cancellation) [A].

### 1.2 The path for a video job

The repository-wide path applies (authority: `AGENTS.md`, `docs/ARCHITECTURE_v2.6.md`). For video:

| Step | Video reality | Where |
|---|---|---|
| Intent | SVD tab form, SVD folder batch, Video Workflow form, one-variable experiment, multi-source batch, replay | `src/controller/svd_controller.py`, `src/controller/video_workflow_controller.py`, `src/video/video_workflow_experiment.py`, `src/video/video_workflow_batch.py` |
| Compiler | SVD: `SVDController._build_svd_njr`. Workflow: `VideoWorkflowNjrBuilder` (`freeze_inputs` then `build_job`). Both end in `ReprocessJobBuilder.build_reprocess_job` | `src/video/video_workflow_njr_builder.py`, `src/pipeline/reprocess_builder.py` |
| NJR | Immutable record with a `VideoWorkloadSpec` and one stage (`svd_native` or `video_workflow`). `SourceKind.VIDEO_WORKFLOW` is stamped for every video stage, including SVD [V] | `src/pipeline/njr_core_v26.py` |
| JobService | `JobService.submit_njrs` is the only fresh-submission boundary; batches and experiments cross it exactly once | `src/controller/job_service.py` |
| Queue/Repository | SQLite `JobRepository`. `classify_record` marks `svd_native` and `video_workflow`/`comfy` jobs `INDEPENDENT_VIDEO` (no WebUI needed); `animatediff` is `REQUIRES_WEBUI` | `src/queue/backend_dependency.py` |
| Runner | `PipelineRunner.run_njr` -> `_video_resolver.is_video_stage` -> `_execute_video_stage` | `src/pipeline/pipeline_runner.py` |
| Handler | `VideoExecutionResolver` -> `VideoBackendRegistry` -> backend `execute` | `src/video/` |
| Artifacts/History | MP4/GIF/frames, per-run manifest JSON, container metadata, `PipelineRunResult` metadata (`video_artifacts`, `video_primary_artifact`, `video_backend_results`) | Section 8 |

Nothing in the GUI or a controller calls a backend, the executor, Comfy or the SVD runner.

## 2. The neutral video execution contract

Types are in `src/video/video_backend_types.py`:

- `VideoBackendCapabilities`: `tasks` (only `image_to_video` exists, `KNOWN_VIDEO_TASKS`), `controls`, `required_controls`. Controls are semantic input forms (`KNOWN_VIDEO_CONTROLS`: source image, prompt text, negative prompt, start/end/mid anchors, control video, pose video, camera intent), never model names. `stage_types` and the `supports_*` flags are legacy sugar folded into `controls` on construction.
- `VideoExecutionRequest` (neutral request, carries `task`, `requested_controls`, `workflow_id/version`, `experimental_opt_in`, `cancel_token`) and `VideoExecutionResult` (canonicalized through `src/pipeline/artifact_contract.py`; `to_variant_payload` feeds the runner).
- `VideoBackendInterface`: `backend_id`, `capabilities`, `execute(pipeline, request)`.

`VideoBackendRegistry` (`build_default_video_backend_registry`) registers three backends: `animatediff` (`AnimateDiffVideoBackend`), `svd_native` (`SVDNativeVideoBackend`) and `comfy` (`ComfyWorkflowVideoBackend`).

`VideoExecutionResolver` (`src/video/video_execution_resolver.py`) is the only place a stage becomes a validated (backend, task, controls) triple. Validation runs before any backend is called and raises `VideoContractError` with a code (`unknown_backend`, `unsupported_task`, `unsupported_control`, `missing_control`, `backend_required`, `invalid_workflow`). There is no fallback and no silent dropping of a control. Two intent sources:

- **Neutral (new work):** a `video_execution` block in the stage config (`backend_id`, `task`, `controls`, `workflow_id`, `workflow_version`, `experimental_opt_in`). The backend is chosen only by `backend_id`. `build_video_execution_block` writes it (`src/video/video_workflow_intent.py`).
- **Legacy bridge:** a stage without the block resolves through `LEGACY_STAGE_BINDINGS` and `VideoBackendRegistry.get_for_stage`.

**Trap [V]: the native SVD path uses the legacy bridge.** `_build_svd_njr` writes no `video_execution` block, so the one accepted production backend routes by stage name. The resolver's documented removal condition ("every producer compiles the neutral block") is therefore not met. Do not delete `LEGACY_STAGE_BINDINGS` or `get_for_stage` without first making SVD compile the neutral block and proving replay of existing SVD records.

Backends that need extra checks implement `validate_workflow(request)` (the Comfy backend does); `VideoExecutionResolver.apply` runs it for neutral work and stamps `context_metadata["video_contract"]`.

## 3. Native SVD XT

### 3.1 Flow

`SVDController` (`submit_svd_job`, `submit_svd_folder_batch`) validates the config (`validate_svd_postprocess_config`), runs `get_svd_preflight` (`src/video/svd_capabilities.py`; reads no model, downloads nothing), builds one NJR per source and crosses `JobService.submit_njrs`. Folder batch is non-recursive and all-or-nothing (`discover_svd_folder_sources` in `src/video/svd_preprocess.py`): any unreadable supported file blocks the batch; with "match source aspect" each source gets its own target from `select_svd_target_size` (`src/video/svd_target.py`, seven vetted stride-64 sizes near 0.6 MP).

At run time: `SVDNativeVideoBackend.execute` -> `RuntimeTransitionCoordinator.prepare_for(RUNTIME_SVD_NATIVE)` (releases StableNew-owned A1111/Comfy residency, never an external runtime) -> `Pipeline.run_svd_native_stage` in `src/pipeline/executor.py` -> `SVDRunner.run` (`src/video/svd_runner.py`):

`validate postprocess config -> SVDService.prepare_runtime (model load) -> prepare_svd_input (resize policy) -> SVDService.generate_frames -> SVDPostprocessRunner.process_frames -> export (mp4 | gif | frames, optional preview PNG) -> embed portable provenance (mp4) -> write_svd_run_manifest`.

Cancellation is checked between every phase and per denoising step (`_build_step_callback`); on any exception `SVDRunner._remove_partial_outputs` deletes only files this run created. Runtime memory is released in `finally`.

### 3.2 Config, defaults and post-processing

- `SVDConfig` (`src/video/svd_config.py`) groups `preprocess`, `inference`, `output`, `postprocess`. Supported model ids are in `src/video/svd_models.py` (`img2vid`, `img2vid-xt`, `img2vid-xt-1-1`); the default is `stabilityai/stable-video-diffusion-img2vid-xt`.
- Defaults differ by origin [V]. The dataclass default is `local_files_only=False`, 25 frames, 7 fps. `SVDController.build_default_config` (what the SVD tab loads) sets `local_files_only=True`, 14 frames, motion bucket 48. Audit E5 ("SVD defaults to online") is true only for configs built without that key (for example a hand-built config). With `local_files_only=False`, `SVDService._load_pipeline` will download the model at job time and will fall back to a remote refresh if a cached load fails.
- Post-processing order inside `SVDPostprocessRunner.process_frames` (`src/video/svd_postprocess.py`): secondary motion (in-process, `src/video/motion/`), face restore, interpolation, upscale. Face restore and upscale run in a helper process, `python -m src.video.svd_postprocess_worker`, which calls the StableNew-owned adapters in `src/video/restoration/` (`CodeFormerRestorer` through Spandrel plus the isolated `legacy_face_helper.py`; `RRDBUpscaler`). Readiness is import-only (`src/video/restoration/runtime.py`, `get_codeformer_runtime_issues`, `get_realesrgan_runtime_issues`); install with `scripts/bootstrap_windows.ps1 -WithPostprocess`.
- RIFE runs the external `rife-ncnn-vulkan` executable, resolved in order: config `executable_path`, `STABLENEW_RIFE_EXE`, `PATH`, then a `rife-ncnn-vulkan.exe` in a repo-relative rife folder under tools if an operator placed one there (not shipped; `resolve_rife_executable`). Multipliers 2 and 4 only; the effective export fps is derived by `get_effective_svd_export_fps`.
- **GFPGAN [V]:** `SVDFaceRestoreMethod` still admits `"GFPGAN"` and the SVD tab offers it (`_FACE_RESTORE_METHODS`), but `get_gfpgan_runtime_issues` always reports `GFPGAN_UNSUPPORTED_ISSUE`, so admission fails. Either remove the option or qualify a replacement (audit E3).
- **No timeout or cancellation on post-process subprocesses [V]:** `_run_worker_stage` and `_run_rife_command` call `subprocess.run(...)` without `timeout` and without the cancel token. A hung worker blocks the single queue runner and can hold VRAM (audit B8). A bounded runner already exists in `src/video/driving_video_inspection.py`; the roadmap item is a shared `run_bounded()` (P3-3) [A].

## 4. Comfy Video Workflow

### 4.1 Layers

| Layer | Module | Role |
|---|---|---|
| Spec types | `src/video/workflow_contracts.py` | `WorkflowSpec` (frozen), input/output bindings, `WorkflowDependencySpec`, governance state (`approved`, `experimental`, `disabled`), capability tags that decide `accepted_controls` |
| Catalog | `src/video/workflow_catalog.py`, `src/video/workflow_catalog_wan_animate2.py` | `build_builtin_workflow_specs()`: all graphs as inline Python dicts in `backend_defaults["prompt_template"]` (adapter-private; never in the NJR) |
| Registry | `src/video/workflow_registry.py` | `WorkflowRegistry.get(..., allow_experimental=)` enforces governance; `list_offerable_specs` (approved plus experimental, never disabled); `get_offerable` for form validation |
| Controller port | `src/controller/ports/default_runtime_ports.py` | `DefaultWorkflowRegistryPort` exposes the offerable list to the controller; `VideoWorkflowController.list_workflow_specs` shows only the newest version of each workflow |
| Declarative controls | `src/video/workflow_controls.py`, `workflow_frame_count.py`, `workflow_source_preparation.py`, `workflow_readiness.py`, `workflow_motion_guidance.py` | Spec-declared operator controls, 4n+1 frame length, source preparation, resource floors, advisory guidance. None branch on a workflow or model name |
| Compiler | `src/video/workflow_compiler.py` (`WorkflowCompiler`) | Binds frozen request fields to the template; produces `CompiledWorkflowRequest` |
| Backend | `src/video/comfy_workflow_backend.py` (`ComfyWorkflowVideoBackend`) | Governance, dependency probe, readiness, queue prompt, history wait, output localization, manifest |
| Clients and runtime | `src/video/comfy_api_client.py`, `comfy_dependency_probe.py`, `comfy_healthcheck.py`, `comfy_process_manager.py` | HTTP, `/object_info` dependency check, readiness polling, managed process lifecycle |

### 4.2 The catalog today (11 specs) [V]

| Workflow id | Versions | State | Notes |
|---|---|---|---|
| `wan22_ti2v_5b_i2v_v1` | 1.0.0, 1.1.0, 1.2.0 | experimental | Stock nodes, three pinned model files with SHA-256. 1.0.0 fixed 49 frames. 1.1.0 adds `frame_count_policy` (17..81, 4n+1, 24 fps) and `release_owned_runtime_after_job`. 1.2.0 is the identical graph requalified on managed ComfyUI 0.38.0 (provenance only). Source-aware 480x832 / 832x480. Resource floor 10,000 MiB VRAM available to Comfy, 16 GB host RAM. |
| `wan_animate2_prompt_i2v_v1` | 1.0.0, 1.1.0, 1.2.0 | experimental | Reference image + prompt, no driving video; motion is subtle and exploratory. |
| `wan_animate2_drive_i2v_v1` | 1.0.0, 1.1.0, 1.2.0 | experimental | Adds a driving video (the qualified mode). 1.1.0 binds the real `WanAnimate2ToVideo` controls (motion prompt, pose strength, pose window, reference strength). Requires `--disable-pinned-memory`. |
| `ltx_multiframe_anchor_v1`, `ltx_multiframe_anchor_v1_conditioned` | 1.0.0 | disabled | Reference `StableNewLTXAnchorBridge` / `StableNewLTXDepthControlBridge` nodes that do not exist. |

Version rule: **a published (id, version) is never edited.** Older versions stay registered so persisted jobs replay against the exact graph they froze (`tests/video/test_pr_comfy_runtime_100_workflow_versions.py` pins this). A requalification on a newer runtime currently mints a new version (the same graph appears as 1.0.0/1.1.0/1.2.0); roadmap P4-6 would separate qualification records from graph versions (audit E3) [A].

Only the ids in the table can reach `ComfyWorkflowVideoBackend.execute`; an experimental spec needs `request.experimental_opt_in`, which comes only from the job's own `video_execution.experimental_opt_in` (set when the form ticked "Enable experimental workflow for this job"). There is no process-global switch.

### 4.3 Building the job (`VideoWorkflowNjrBuilder`)

1. `validate_form_data` / `capability_errors`: required inputs derived from the spec, opt-in required for experimental specs, controls the spec does not declare are refused (not dropped).
2. `freeze_inputs`: concrete seed (`parse_seed_input`, never generated at run time), driving-video path and SHA-256, declared source preparation (`prepare_declared_workflow_source`: EXIF transpose, cover resize, centred crop to the catalog target, published as a StableNew-owned PNG with its hash) and source hash.
3. `build_job`: writes the `video_workflow` stage config (workflow id/version, prompt, `video_execution` block, `frame_count`/`fps` when the spec declares a policy, `operator_controls` via `resolve_operator_controls`, `pose_video_path` and `pose_video_sha256`, `source_preparation`), `extra_metadata["video_workflow"]` (including `governance_state`, `experimental_opt_in`, `source_identity` for batches) and calls `ReprocessJobBuilder`.

The same builder serves a normal submission, every arm of a one-variable experiment (`VideoWorkflowExperimentService`; arms must differ only in the chosen control; admission via `ExperimentAdmissionService` in `src/learning/experiment_execution.py`) and a multi-source batch of 1-25 images (`VideoWorkflowBatchService`: `assess`, `preview`, `admit`; one `submit_njrs` call; provenance descriptor `stablenew.batch.v1`, 0-based `source_index`). Do not create another path that builds a video NJR.

### 4.4 Execution (`ComfyWorkflowVideoBackend.execute`)

Order: registry governance check (an unknown/disabled/un-opted-in workflow never starts a runtime) -> frame-count legality -> `_verify_required_launch_flags` (the configured `comfy_command` must contain the spec's flags; an external runtime's flags cannot be proven, so it is refused) -> `RuntimeTransitionCoordinator.prepare_for(RUNTIME_COMFY)` -> `_ensure_runtime_ready` (managed launch or an already-healthy endpoint) -> `/object_info` -> `ComfyDependencyProbe.probe_workflow` (stock nodes, model files, custom nodes) -> `WorkflowResourceReadiness.evaluate` when the spec declares `resource_readiness` (fails closed if the driver figure cannot be read) -> `WorkflowCompiler.compile` -> `queue_prompt` -> `_wait_for_history_entry` (liveness reported every 5 s through `_prompt_is_live`) -> `_localize_comfy_outputs` (downloads `/view` outputs into the run dir; only `type: output` files count) -> `_write_manifest` (`<run>/manifests/<stem>.json`: compiled workflow, dependency probe, queue response, history entry, control record, actual runtime identity) -> optional secondary-motion re-encode.

When the spec's `runtime_policy.release_owned_runtime_after_job` is true (Wan2.2 TI2V-5B from 1.1.0 and every Wan-Animate-2 version), `execute` stops the Comfy that StableNew owns on every exit path (`BaseException`), through `ComfyProcessManager.stop()` only; a not-owned runtime is not asked to stop.

### 4.5 Managed Comfy runtime

Identity lives in `config/managed_comfy_runtime.json` (ComfyUI v0.38.0 at a pinned commit, CPython 3.13 standard GIL, Torch 2.14.0+cu130, loopback only, required flags `--disable-pinned-memory` and `--disable-auto-launch`, no custom nodes) and `constraints/comfy-windows-py313-cu130-v0.38.0.txt`. Build: `scripts/bootstrap_managed_comfy_windows.ps1`; read-only verifier: `tools/runtime/verify_managed_comfy.py`; operator procedure: `docs/runbooks/managed_comfy_runtime.md`. It never shares an environment with the application (CPython 3.14).

`ComfyProcessManager` (`src/video/comfy_process_manager.py`) is the only lifecycle authority: it launches only when `probe_comfy_endpoint` says the endpoint is free, stops only the process it started, and never adopts an external one. The launch command comes from the `comfy_command` setting (`build_default_comfy_process_config`); **the JSON contract is not read by production code [V]** (only by the verifier, bootstrap and tests), so StableNew relies on the operator copying the launch command and on `_verify_required_launch_flags` for the flags the spec requires.

Known gaps (audit B7, still true when this was written) [V/A]: `Popen` has no job object or process group and uses `text=True` without an explicit encoding; the history wait ignores the cancel token and no `/interrupt` is ever sent (a Wan job cannot be cancelled mid-run and can wait up to 600 s for Wan 1.1.0+ and 1200 s for Animate-2); a read timeout on `POST /prompt` surfaces as a raw `requests` exception, so any retry above it could duplicate GPU work; after a hard crash an orphaned Comfy looks like a healthy external one and StableNew refuses to launch or stop it. Do not add retries around `queue_prompt`.

## 5. Motion sources and guidance

- Still source: prepared and frozen before admission (4.3). Landscape/portrait/square handling is declared per spec (`source_preparation`), not decided by the backend. `preview_declared_workflow_source` computes the exact pixels and crop rectangle without writing, using the same transform as admission.
- Driving video (Animate-2 drive): path and SHA-256 frozen in the job; extensions `.mp4 .webm .mov .mkv`. `inspect_driving_video` (`src/video/driving_video_inspection.py`) is a bounded, read-only FFprobe/FFmpeg probe (wall-clock timeouts, byte-capped stdout, at most a few small preview frames, `file` protocol only, cancellable).
- Advisories (`src/video/motion_source_readiness.py`, `src/video/workflow_motion_guidance.py`): display-only projections of geometry and timing (how much a centred crop discards, how many driving frames the output consumes) and of recorded evidence. They never alter the prompt, the job, or admission.
- Secondary motion (`src/video/motion/`): an optional post-process applied to SVD frames or a finished Comfy video; intent comes from `extract_secondary_motion_intent` (`src/pipeline/config_contract_v26.py`) and its policy is recorded in run metadata.
- Camera presets, ControlNet/depth conditioning (`DepthMapResolver`, `_resolve_conditioning_inputs`, `_normalize_camera_intent` in the builder) are consumed only by the disabled LTX conditioned spec [V]; no enabled workflow reads them.

## 6. Qualification evidence versus production

Experimental status is a statement about evidence, not a toggle. Wan2.2 TI2V-5B has an accepted real run on the target machine (about 83 s for 49 frames at 480x832 including a cold managed-Comfy start) and a characterization of what prompt motion does and does not do. Wan-Animate-2 passed local execution and an owner motion-value verdict but fails the frozen automated motion-curve guardrail, and the adjudication is "technically not yet promotion-ready". Identity preservation is observed, never guaranteed (`VideoBackendCapabilities` deliberately has no such capability). Qualification harnesses are operator-only code in `tools/qualification/vid*` and `tools/acceptance/vid130_wan_acceptance.py`; they are not part of the production path or CI. Physical GPU work is on HOLD (`STATUS.md` Holds).

## 7. Movie Clips and assembly

`MovieClipService` (`src/video/movie_clip_service.py`) validates a `ClipRequest`, orders sources by filename and routes through `AssemblyService` (`src/video/assembly_service.py`: `AssemblyRequest`, image-sequence export, `stitch_video_segments`, a pluggable `InterpolationProvider` with `NoOpInterpolationProvider`), writing a manifest with schema `stablenew_assembly_manifest_v1`. FFmpeg is resolved by `resolve_ffmpeg_executable` (`src/pipeline/video.py`).

Exception to the canonical path [V]: `AppController.on_build_movie_clip` runs the service on a tracked daemon worker thread, writes to the `movie_clips` output route, and never calls `JobService`. It is CPU-only assembly of existing outputs, creates no NJR and no queue/history record, and has no cancellation. Keep it that way (no GPU, no model, no backend call); anything that generates frames must use the queue. `send_history_job_to_movie_clips` and `video_workspace_handoff.py` only route an existing output into the tab.

## 8. Provenance, artifacts and replay lineage

| Artifact | Producer | Contract |
|---|---|---|
| SVD MP4 with embedded portable provenance | `SVDRunner._embed_portable_svd_provenance` | `PortableVideoProvenanceContractV26` in `src/video/svd_portable_provenance.py` (schema `stablenew.video-provenance.v2.6`, raw or gzip+base64 payload, payload SHA-256, media-content hash that must be unchanged by the remux and is re-verified). Failure raises `SVDExportError` and the run fails. |
| SVD run manifest | `write_svd_run_manifest` (`src/video/svd_registry.py`) | Config, source, preprocess, postprocess, provenance summary |
| GIF/MP4 container tags | `write_video_container_metadata` (`src/video/container_metadata.py`) | Public metadata tags |
| Comfy run manifest | `ComfyWorkflowVideoBackend._write_manifest` | Section 4.4; includes `actual_runtime` identity the server reported and, for controlled jobs, a `control_record` (workflow identity, qualified graph hash, source SHA, prompts, seed, controls, driving video) |
| Runner metadata | `_execute_video_stage` | `video_artifacts[stage]`, `video_primary_artifact`, `video_backend_results`, `svd_native_artifact` / `video_workflow_artifact`, continuity link, source preparation, secondary motion |
| Artifact record | `VideoExecutionResult.from_stage_result` | `stablenew.artifact.v2.6` via `src/pipeline/artifact_contract.py` |

Replay and lineage: a replay is a new NJR with `SourceKind.HISTORY_REPLAY` and parent job/artifact ids (`src/pipeline/replay_njr_compiler.py`), re-entering `run_njr` through `ReplayEngine`. `frozen_input_checks` (`src/pipeline/replay_input_verification.py`) re-verifies, by recorded SHA-256 where one exists, the prepared source, driving video, anchors and depth map before a replay or retry. Batch jobs carry `source_identity` (original and prepared path and hash, preparation policy, parent job and artifact ids); a replay does not inherit its parent's active batch membership. Workflow replay is exact only because published catalog versions never change (4.2); the SVD replay depends on the frozen `SVDConfig` in the NJR.

Provenance can be lost on the image side (audit B9) and `gzip.decompress` of embedded video provenance is unbounded on read (`svd_portable_provenance.py`, audit B11) [V/A].

## 9. Unreachable, dead and broken (verified unless marked)

| Item | State |
|---|---|
| LTX specs, `ltx_*` catalog graphs | Disabled; exercised only by `tests/helpers/video_contract_registry.py`, which rewrites their state to `approved` in a private registry. `src/video/depth_map_resolver.py`, `_resolve_conditioning_inputs` and the camera/ControlNet builder fields exist only for them [V]. Decision: owner question 6 in `STATUS.md`. |
| `animatediff` | `AnimateDiffVideoBackend` and `Pipeline.run_animatediff_stage` are registered and executable for a persisted `animatediff` stage, but no GUI or controller builds such a job [V: no producer in `src/gui`/`src/controller`]; it needs the A1111 extension [A]. |
| Multi-segment sequences | `PipelineRunner._execute_sequence` runs when a `video_workflow` stage config has `sequence_metadata.total_segments > 1`, but nothing in `src` writes `sequence_metadata` [V]. `src/video/sequence_planner.py`, `sequence_models.py`, `sequence_manifest.py` and `ComfyWorkflowVideoBackend.execute_segment` (no callers) are reachable only through that path or tests. |
| Story plan and continuity | `src/video/story_plan_compiler.py`, `story_plan_models.py`, `story_plan_store.py`, `continuity_store.py` are imported only by each other and tests [V]. `continuity_models.normalize_continuity_link` is live (the builder and runner use it; the form fields are blank by default). Audit counts 677 unreachable lines [A]. |
| GFPGAN option | Offered, always refused (3.2). |
| Wan/LTX stale text | `workflow_readiness.py` docstring says the LTX pair is "approved"; they are disabled. |
| Startup dependency probe | `build_optional_dependency_snapshot` (`src/app/optional_dependency_probes.py`) iterates `registry.list_specs_for_backend("comfy")`, which returns only approved specs, so it reports no workflow while none is approved [V]. |

Audit E3 counts 3 video backends and 11 workflow specs with none approved; roadmap P5-7 proposes retiring the disabled LTX specs, AnimateDiff and story-plan [A]. Retirement is an owner decision (`STATUS.md` open decision 6): do not delete these on your own.

## 10. Invariants that must not be broken

1. Canonical path only. No second queue, runner, history or compiler authority; one NJR builder for Video Workflow (`VideoWorkflowNjrBuilder`). The GUI and controllers never call a backend, Comfy or `SVDRunner`.
2. The NJR is immutable. Seed, frame count, source, prepared source, driving video hash, controls and workflow version are frozen at admission; the backend must not derive any of them at run time.
3. Refuse before dispatch. Unknown backend, task, control, workflow, illegal frame count, missing dependency, unmet resource floor, missing launch flag: raise before the first Comfy `POST /prompt`. No silent fallback, no dropped control.
4. Experimental means a per-job opt-in recorded in the job. No global switch; disabled never runs.
5. Published workflow versions are immutable; a change is a new version and the old one stays registered.
6. StableNew controls lifecycle only for a Comfy process `ComfyProcessManager` launched. External Comfy is never adopted, stopped or restarted. Never replay an ambiguous dispatched prompt.
7. Native SVD and Comfy do not share residency: use `RuntimeTransitionCoordinator` before loading either.
8. Advisories and guidance (`motion_source_readiness`, `workflow_motion_guidance`, `driving_video_inspection`) are display-only and must stay unable to change a job.
9. Persisted state goes through `src/utils/atomic_io.py`; outputs are written under the run directory and partial outputs removed on failure.
10. Physical GPU work is on HOLD (`STATUS.md` Holds). No real SVD, Wan, Comfy start or qualification run without explicit owner authorization. Tests must not start Comfy, load a model or touch a GPU.
11. Protected actions (push to `main`, merge, publish, secrets, material architecture changes) need explicit owner approval (`AGENTS.md` section 5).

## 11. How to test

Configuration is `pyproject.toml` only. Run `python tools/ci/run_pr_gate.py` for the required gate; run focused tests first.

| Area | Tests | Hermetic seam |
|---|---|---|
| Neutral contract, registry, resolver | `tests/video/test_video_execution_contract.py`, `tests/video/test_video_backend_registry.py` | In-test `_FakeBackend`; `tests/helpers/video_contract_registry.py` for LTX-shaped contracts |
| Catalog, registry, compiler, versions | `tests/video/test_workflow_registry.py`, `tests/video/test_workflow_compiler.py`, `tests/video/test_pr_comfy_runtime_100_workflow_versions.py`, `tests/video/test_wan22_experimental_workflow.py`, `tests/video/test_pr_vid_190_wan_animate2.py`, `tests/video/test_pr_vid_192_animate2_controls.py` | Pure data; version tests pin published graphs byte for byte |
| Comfy backend, lifecycle, liveness | `tests/video/test_comfy_workflow_backend.py`, `tests/video/test_pr_vid_190_comfy_lifecycle_frame_count.py`, `tests/video/test_pr_runtime_110_comfy_liveness.py`, `tests/video/test_comfy_process_manager.py` | `_FakeComfy` / `_FakeManager` in those files; no process or socket |
| Builder, experiments, batch, readiness | `tests/video/test_pr_vid_194_one_variable_experiments.py`, `tests/video/test_pr_vid_batch_200_multisource.py`, `tests/video/test_pr_vid_196_*.py`, `tests/video/test_workflow_source_preparation.py` | Temp dirs, synthetic images |
| Managed runtime contract | `tests/system/test_managed_comfy_runtime.py` | Reads `config/managed_comfy_runtime.json` and constraints only |
| Native SVD | `tests/video/test_svd_runner.py`, `test_svd_service.py`, `test_svd_postprocess.py`, `test_svd_postprocess_worker.py`, `test_svd_portable_provenance.py`, `test_svd_target.py`, `test_svd_folder_discovery.py`, `test_svd_runtime_hardening.py`, `test_svd_integration.py`, `test_svd_restoration_adapters.py` | Fake diffusers pipeline and stub services under `tests/video/` |
| Assembly and Movie Clips | `tests/video/test_assembly_service.py`, `test_movie_clip_service.py`, `test_movie_clips_tab_service_smoke.py` | Fake FFmpeg seams |
| Runner video branch, replay, queue | `tests/pipeline/test_pipeline_runner.py` (including the `sequence_metadata` cases), `tests/pipeline/test_replay_*`, `tests/queue/` | `tests/helpers/fake_pipeline_runner.py`, `tests/helpers/njr_factory.py` |

For a new refusal, assert both the error and that no `queue_prompt` call was recorded. Qualification code in `tools/qualification/` and `tools/acceptance/` is never run in CI. `real_backend` is the opt-in marker for anything that contacts an external backend.

## 12. Known debt and traps

- `src/video/comfy_workflow_backend.py` is 1,374 lines and mixes governance, readiness, upload, history polling, output localization and manifest writing in one class. Adding a Comfy-hosted model needs about 3 files; a native backend about 15 [A, audit E3].
- Workflow graphs are inline Python dicts, requalification mints versions, and the qualification record is embedded in the spec (`provenance`, `governance_notes`). Roadmap P4-6 [A].
- SVD uses the legacy resolver bridge (section 2); `SourceKind.VIDEO_WORKFLOW` is used for SVD NJRs [V]. Filtering history by "video workflow" therefore includes SVD jobs.
- No cancellation for Comfy waits or SVD post-process subprocesses; no timeouts on the latter (3.2, 4.5). Cancel only takes effect between SVD phases and denoising steps.
- `SVDRunner.run` returns a successful result even when optional post-process warnings were recorded; check `postprocess["warnings"]` (CodeFormer pastes an unrestored face back and only warns).
- The executor swallows non-SVD exceptions in `run_svd_native_stage` and returns `None`, which the runner reports as no output. `SVDError` subclasses propagate; raise refusals as those (`src/video/svd_errors.py`).
- `PipelineRunner._execute_video_stage` still names `animatediff` and `svd_native` in places (filenames, postprocess merge, legacy metadata keys). It is part of the executor-sized `run_njr` debt (roadmap P4-1) [A].
- Disk space is not checked before SVD frame dumps or Comfy downloads (audit E6) [A]. A user-set `comfy_command` is not checked for `--listen 0.0.0.0` (audit E5) [A].
- `cv2` is used by restoration/refinement code but declared only in the SVD/postprocess extra [A].

## 13. Adding or changing video behavior today

- **A new Comfy workflow (experimental):** add a `WorkflowSpec` builder in `src/video/workflow_catalog.py` (or a sibling module like `workflow_catalog_wan_animate2.py`) and include it in `build_builtin_workflow_specs`. Pin model files by name and SHA-256, list stock nodes as dependencies, set `governance_state="experimental"`, declare `resource_readiness`, `frame_count_policy`, `runtime_policy` and operator controls in `backend_defaults` rather than in code. Do not add workflow-name branches to the builder, compiler or backend; add a neutral control if one is missing. Tests: registry, compiler, version-pinning and a `_FakeComfy` backend run. Qualification is owner-gated.
- **A new revision of an existing workflow:** a new version row; never edit the old one; update the version-pinning test.
- **A new neutral control or task:** extend `KNOWN_VIDEO_CONTROLS` / `KNOWN_VIDEO_TASKS` together with a backend that declares it and a workflow capability tag in `_WORKFLOW_TAG_CONTROLS`; update `requested_controls` and `capability_errors` in `src/video/video_workflow_intent.py`.
- **A new native backend:** implement `VideoBackendInterface`, register it in `build_default_video_backend_registry`, add a `RUNTIME_*` residency entry in `src/services/runtime_transition_service.py`, a branch in `src/queue/backend_dependency.py`, and have the producer write a `video_execution` block. Needs an owner architecture decision (`AGENTS.md`: SVD XT is the only MVP video backend).
- **Promoting a workflow to `approved`:** owner decision. Preconditions in the audit: managed process containment and Comfy cancellation (P3-3, P3-4). Then change `governance_state`, update section 1.1 and `STATUS.md`.
- **A new SVD post-process stage:** extend `SVDPostprocessConfig`, `validate_svd_postprocess_config`, `SVDPostprocessRunner.process_frames` and `get_svd_postprocess_capabilities`; run it as a bounded subprocess with a timeout and the cancel token, not as another unbounded `subprocess.run`.
- Update this file, `STATUS.md` (supported capabilities) and, for qualification evidence, a record under `docs/Subsystems/Video/`.

## 14. Evidence records

Per-PR records stay in `docs/Subsystems/Video/` as historical evidence. They may describe superseded behavior or a not-yet-merged state; the code and this file win.

| Record | Why it matters |
|---|---|
| `docs/Subsystems/Video/PR-VID-120_Neutral_Video_Execution_Contract.md` | The neutral contract, the legacy bridge and its removal condition |
| `docs/Subsystems/Video/PR-VID-110_Directed_Motion_Qualification.md` | Original Wan2.2 TI2V-5B qualification (the promoted graph) |
| `docs/Subsystems/Video/PR-VID-130_Wan22_Experimental_Vertical_Slice.md` | Experimental governance, opt-in, readiness floors, the first accepted real run |
| `docs/Subsystems/Video/PR-VID-150_Wan22_Motion_Characterization.md` | What Wan2.2 prompt motion does and does not do |
| `docs/Subsystems/Video/PR-VID-185_Wan_Animate_2_Promotion_Readiness_Adjudication.md` | Why Wan-Animate-2 is not promotion-ready |
| `docs/Subsystems/Video/PR-VID-190_Comfy_Runtime_Recycling_and_Frame_Count.md` | Per-job runtime release and the 4n+1 frame-count contract |
| `docs/Subsystems/Video/PR-VID-192_Animate2_Control_Truth.md` | Which Animate-2 controls the node really honors |
| `docs/Subsystems/Video/PR-VID-194_Animate2_One_Variable_Operator_Experiments.md` | One-variable experiments and the single NJR builder |
| `docs/Subsystems/Video/PR-VID-196_Motion_Source_Readiness.md` | Driving-video inspection and display-only advisories |
| `docs/Subsystems/Video/PR-VID-BATCH-200_MultiSource_Workflow_Batch.md` | Multi-source batch admission and `stablenew.batch.v1` |
| `docs/Subsystems/Video/PR-COMFY-RUNTIME-100_Managed_Comfy_Runtime.md` | Managed Comfy identity, authorities and requalification evidence |
| `docs/Subsystems/Video/PR-POSTPROC-100_Restoration_Isolation.md` | CodeFormer/upscale isolation, GFPGAN retirement, equivalence evidence |
| `docs/Subsystems/Video/PR-SVD-100_Folder_Batch_Submission.md` | SVD folder batch contract |
| `docs/Subsystems/Video/Movie_Clips_Workflow_v2.6.md` | Movie Clips tab behavior and SVD handoff |
| `docs/runbooks/managed_comfy_runtime.md` | Operator procedure for building and launching the managed runtime |
| `docs/audits/2026-10-16_repo_audit_and_roadmap.md` | Audit B7, B8, B11, E3, E5, G7 and roadmap P3-3, P3-4, P4-6, P5-7 |
