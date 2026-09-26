# StableNew Codex map

This is a task-oriented navigation map, not an architecture authority. Start
from the task row, and do not expand into adjacent subsystems without
evidence. Read `STATUS.md`, this map, and only the relevant section of
`docs/ARCHITECTURE_v2.6.md` before exploring implementation.

## Canonical runtime

`Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`

- GUI intent and application wiring: `src/controller/app_controller.py`,
  `src/gui/app_state_v2.py`, and `src/gui/views/`.
- PromptPack draft and submission coordination:
  `src/controller/pipeline_controller.py`,
  `src/controller/app_controller_services/run_submission_service.py`, and
  `src/controller/pipeline_controller_services/`.
- PromptPack native storage, discovery, interchange, and migration:
  `src/promptpacks/paths.py` resolves the per-user authority and
  `src/promptpacks/storage.py` owns the versioned JSON format; typed GUI editing remains in
  `src/gui/models/prompt_pack_model.py`.
- PromptPack expansion/compilation: `src/pipeline/prompt_pack_job_builder.py`,
  `src/pipeline/prompt_pack_parser.py`, and `src/pipeline/resolution_layer.py`.
- Matrix/randomization: `src/pipeline/config_variant_plan_v2.py`,
  `src/pipeline/randomizer_v2.py`, and `src/randomizer/`.
- NJR contract and serialization: `src/pipeline/njr_core_v26.py` and
  `src/pipeline/config_contract_v26.py`.
- Other typed compilers: `src/pipeline/replay_njr_compiler.py`,
  `src/pipeline/training_njr_compiler.py`, `src/pipeline/cli_njr_builder.py`,
  and `src/video/workflow_compiler.py`.
- Submission and queue policy: `src/controller/job_service.py`,
  `src/controller/submission_policy_v26.py`, and `src/queue/job_queue.py`.
- SQLite jobs/history: `src/queue/job_repository.py`,
  `src/queue/job_history_store.py`, and `src/history/`.
- Execution: `src/queue/single_node_runner.py`,
  `src/pipeline/pipeline_runner.py`, and `src/pipeline/executor.py`.
- GPU hard-crash evidence (observation only):
  `docs/Subsystems/Runtime/DIAG-GPU-100_Hard_Crash_Correlation_and_Survivor_Telemetry.md`
  -> `src/utils/gpu_survivor_telemetry.py` ->
  `src/utils/process_inspector_v2.py::collect_gpu_survivor_snapshot` ->
  `src/pipeline/pipeline_runner.py`; offline correlation is
  `tools/diagnostics/correlate_gpu_incidents.py`. These surfaces do not own
  queue state, runtime lifecycle, GPU settings, or execution control.
- Current A1111 image implementation boundary: `src/api/`,
  `src/pipeline/payload_builder.py`, and the typed image handlers in
  `src/pipeline/executor.py`.
- Implemented post-v2.6 backend-neutral image boundary (`PR-IMG-100`):
  `docs/Subsystems/Image/PR-IMG-100_Backend-Neutral_Image_Execution.md`,
  `src/image_backends/image_backend_types.py`,
  `src/image_backends/image_backend_registry.py`,
  `src/image_backends/a1111_webui_backend.py`,
  `src/pipeline/njr_core_v26.py`, `src/pipeline/config_contract_v26.py`,
  image NJR compilers/builders, `src/pipeline/pipeline_runner.py`, controller
  runtime ports, and the A1111 executor/client boundary.
- Completed `PR-IMG-110` target-hardware qualification (generic Diffusers
  substrate viable; its Ideogram 4 no-go is superseded by `PR-IMG-110R`, Ideogram 4
  NF4 PASS — CONSTRAINED):
  `docs/Subsystems/Image/PR-IMG-110_Diffusers_Ideogram4_Qualification.md`,
  `docs/Subsystems/Image/PR-IMG-110R_Ideogram4_Requalification.md`, and
  qualification-only evidence tooling in `tools/qualification/img110/` and
  `tools/qualification/img110r/`.
- Native SVD/video: `src/video/svd_service.py`, `src/video/svd_runner.py`,
  `src/video/svd_native_backend.py`, and `src/video/workflow_contracts.py`.
- SVD folder-batch submission: `docs/Subsystems/Video/PR-SVD-100_Folder_Batch_Submission.md`
  -> `src/video/svd_preprocess.py` -> `src/controller/svd_controller.py` ->
  `src/controller/svd_submission_service.py` -> `src/controller/app_controller.py`
  -> `src/gui/views/svd_tab_frame_v2.py` -> `JobService.submit_njrs`.
- Portable SVD provenance: `src/video/svd_portable_provenance.py` ->
  `src/video/container_metadata.py` -> `src/video/svd_runner.py` ->
  `src/video/svd_registry.py`.
- Learning experiments: `src/learning/experiment_execution.py` ->
  `src/learning/execution_controller.py` -> `JobService.submit_njrs`; durable
  evidence/recommendations live in `learning_record.py` and
  `recommendation_engine.py`; draft/library classification, sample-derived
  conclusions, deterministic source freeze, and isolated derived-job suggestion
  patches live in `experiment_lifecycle.py`, `experiment_conclusion.py`,
  `experiment_freeze.py`, and `staged_recommendations.py`, with GUI coordination in
  `src/gui/controllers/learning_controller.py`.
- Artifacts and replay: `src/pipeline/artifact_contract.py`,
  `src/pipeline/result_contract_v26.py`, and `src/pipeline/replay_engine.py`.

## Start here by task

| Task | Start here |
|---|---|
| PromptPack behavior | `paths.py` -> `storage.py` -> `prompt_pack_model.py` -> `prompt_pack_job_builder.py` |
| Matrix/randomization | `config_variant_plan_v2.py` -> `src/randomizer/` |
| GUI submission | `app_controller.py` -> `run_submission_service.py` -> `job_service.py` |
| Queue/history | `job_service.py` -> `job_queue.py` -> `job_repository.py` |
| Current image execution | `pipeline_runner.py` -> `executor.py` -> `src/api/` |
| `PR-ASSET-DISCOVERY-100` local A1111 asset census | `docs/Subsystems/Image/PR-ASSET-DISCOVERY-100_Local_A1111_Asset_Census.md` -> `tools/asset_census.py` (offline/operator-only; explicit roots, streamed SHA-256 cache, safetensors-header-only metadata, optional LoRA cache evidence; not a production scanner or registry) -> `tests/tools/test_asset_census.py`; live A1111 projection remains `src/api/webui_resources.py` / `src/api/webui_resource_service.py` |
| `PR-ASSET-110` local Asset Registry | `docs/Subsystems/Image/PR-ASSET-110_Local_Asset_Registry.md` -> `src/assets/registry.py` (offline SHA-256 identity/cache) -> legacy `src/utils/lora_scanner.py` / `embedding_scanner.py` projections; `src/api/webui_resource_service.py` remains the independent live-A1111 projection |
| `PR-IMG-100` backend-neutral image execution | `docs/Subsystems/Image/PR-IMG-100_Backend-Neutral_Image_Execution.md` -> `src/image_backends/image_backend_types.py` / `src/image_backends/image_backend_registry.py` / `src/image_backends/a1111_webui_backend.py` -> `njr_core_v26.py` / `config_contract_v26.py` -> image compilers -> `pipeline_runner.py` -> runtime ports -> A1111 executor/client boundary |
| `PR-IMG-110` / `PR-IMG-110R` qualification evidence | `docs/Subsystems/Image/PR-IMG-110_Diffusers_Ideogram4_Qualification.md` -> `tools/qualification/img110/`; `docs/Subsystems/Image/PR-IMG-110R_Ideogram4_Requalification.md` -> `tools/qualification/img110r/` (qualification-only; no production backend) |
| `PR-VID-130` Wan2.2 experimental workflow | `docs/Subsystems/Video/PR-VID-130_Wan22_Experimental_Vertical_Slice.md` -> `src/video/workflow_catalog.py` (spec) / `src/video/workflow_registry.py` (experimental gate) / `src/video/video_workflow_intent.py` (capability-driven producer intent) / `src/video/workflow_readiness.py` (observe-only guard) / `src/video/comfy_workflow_backend.py` / `src/controller/video_workflow_controller.py` -> `tools/acceptance/vid130_wan_acceptance.py` |
| `PR-VID-140` Wan2.2 operator readiness | `docs/Subsystems/Video/PR-VID-140_Wan22_Operator_Readiness.md` -> `src/video/workflow_catalog.py` (LTX governance and Wan projection) / `src/video/workflow_source_preparation.py` (catalog-declared deterministic source preparation) / `src/controller/video_workflow_controller.py` (admission-frozen seed and prepared-source NJR) -> `src/video/comfy_process_manager.py` (owned configured readiness) -> `tools/acceptance/vid130_wan_acceptance.py` (bounded real acceptance evidence) |
| `PR-RUNTIME-100` owned GPU transition policy | `docs/Subsystems/Runtime/PR-RUNTIME-100_Owned_Runtime_Transition_Policy.md` -> `src/services/runtime_transition_service.py` -> read-only configured endpoint probes (`src/api/healthcheck.py::probe_webui_endpoint`, `src/video/comfy_healthcheck.py::probe_comfy_endpoint`) -> `src/image_backends/a1111_webui_backend.py` / `src/video/comfy_workflow_backend.py` / `src/video/svd_native_backend.py` -> existing `WebUIProcessManager` / `ComfyProcessManager` / `SVDService` release boundaries |
| `PR-VID-120` neutral video execution contract | `docs/Subsystems/Video/PR-VID-120_Neutral_Video_Execution_Contract.md` -> `src/video/video_backend_types.py` / `src/video/video_execution_resolver.py` / `src/video/video_backend_registry.py` / `src/video/workflow_contracts.py` -> `pipeline_runner.py::_execute_video_stage` (resolver call only) |
| `PR-VID-110` directed-motion qualification evidence | `docs/Subsystems/Video/PR-VID-110_Directed_Motion_Qualification.md` -> `tools/qualification/vid110/` (qualification-only; Wan2.2 CONDITIONAL, VACE-1.3B NO-GO; no production backend) |
| `PR-VID-150` Wan2.2 motion characterization | `docs/Subsystems/Video/PR-VID-150_Wan22_Motion_Characterization.md` -> `tools/qualification/vid150/run.py` (qualification-only, reuses `tools/acceptance/vid130_wan_acceptance.py` stack + `tools/qualification/vid110/` metrics/monitor; `local_motion_viable_locomotion_weak`; no production backend) |
| `PR-VID-160B` Wan2.2-Animate resource-feasibility evidence | `docs/Subsystems/Video/PR-VID-160B_Wan22_Animate_Target_Hardware_Feasibility.md` -> `tools/qualification/vid160b/` (qualification-only; direct manager-owned-Comfy dispatch; Animate is not a registered StableNew workflow; `ANIMATE_BACKBONE_RESOURCE_FLOOR_PASS`, but `pose_video` was not exercised, so Move-mode resource gate remains open; no production backend) |
| `PR-VID-160C` Wan2.2-Animate Move-mode resource closure | `docs/Subsystems/Video/PR-VID-160C_Wan22_Animate_Move_Mode_Resource_Closure.md` -> `tools/qualification/vid160c/` (qualification-only; reuses `tools/qualification/vid160b/` telemetry/ownership/graph constants + `tools/qualification/vid110/comfy_client.py`; adds a real `pose_video` and Windows commit-aware telemetry (`win_memory.py`); adjudicated `MOVE_MODE_RESOURCE_PASS_32GB` (supersedes an interim physical-RAM-only guard trigger); no production backend) |
| `PR-VID-170` Wan2.2-Animate motion-transfer characterization | `docs/Subsystems/Video/PR-VID-170_Wan22_Animate_Motion_Transfer_Characterization.md` -> `tools/qualification/vid170/` (qualification-only; reuses `tools/qualification/vid160b/`+`vid160c/` telemetry/ownership/graph constants + `tools/qualification/vid110/comfy_client.py`+metrics; adds official Wan2.2-Animate sampling settings and deterministic/synthetic pose-case tooling (`synthetic_pose.py`); `ANIMATE_QUALITY_INSUFFICIENT_AT_SMALL_ENVELOPE`; no production backend) |
| `PR-VID-175` Wan2.2-Animate 480x832 interpretability gate | `docs/Subsystems/Video/PR-VID-175_Wan22_Animate_480x832_Interpretability.md` -> `tools/qualification/vid175/` (qualification-only; thin extension reusing `tools/qualification/vid170/graph.py` unchanged plus `vid160b/`+`vid160c/` ownership/telemetry; `ANIMATE_480x832_INTERPRETABLE_PASS`; no production backend) |
| `PR-VID-180` Wan2.2-Animate 480x832 motion-transfer characterization | `docs/Subsystems/Video/PR-VID-180_Wan22_Animate_480x832_Motion_Transfer_Characterization.md` -> `tools/qualification/vid180/` (qualification-only; `run.py` extends `tools/qualification/vid170/run.py` restricted to runnable Case A/B only (no Case C submission path); adds `native_pose.py`, a native-480x832 reimplementation of `vid170/synthetic_pose.py`'s motion semantics (resolution-independent angle/phase/translation-fraction formulas, proven frame-by-frame equal), reusable for future native-envelope synthetic pose-control work; `ANIMATE_CHARACTERIZATION_INCONCLUSIVE` (procedural-synthetic-vs-detector-derived pose-conditioning confound, not a capability verdict; secondary finding `BACKGROUND_INSTABILITY_CROSS_CASE`); no production backend) |
| `PR-VID-181` Wan2.2-Animate real-driving pose adjudication | `docs/Subsystems/Video/PR-VID-181_Wan22_Animate_Real_Driving_Pose_Adjudication.md` -> `tools/qualification/vid181/` (qualification-only; `preprocess_launcher.py` runs ONLY in a disposable CPU-only env outside StableNew/Comfy/A1111 over the pinned upstream Wan2.2 animation pose path (`provenance.py` pins SHA/checkpoints and rejects production env prefixes); `driving_prep.py` fixed 29:52 crop, `finalize.py` freezes 480x832/13f/8fps controls; reusable for any future upstream-compatible pose control; `run.py` runs the two frozen controls through the accepted 480x832 Animate graph with control-hash enforcement (A/B only); `ANIMATE_REAL_POSE_LOCAL_MOTION_ONLY` + `BACKGROUND_INSTABILITY_CROSS_CASE`; no production backend) |
| `PR-VID-183` Wan2.2-Animate controlled basic-retarget A/B | `docs/Subsystems/Video/PR-VID-183_Wan22_Animate_Basic_Retargeting_Controlled_AB.md` -> `tools/qualification/vid183/` (qualification-only; thin reuse of VID-181's CPU-isolated detector/finalizer and manager-owned runner; frozen natural source and reference feed A/B, while B calls pinned upstream `get_retarget_pose` with `use_flux=False`; exact control hashes plus a non-no-op/temporal-motion pair gate are required before either of the two allowed submissions; `BASIC_RETARGET_APPLIES; REFERENCE_BOUND_LOCOMOTION_NOT_DEMONSTRATED`; no production backend) |
| Video/SVD | `workflow_compiler.py` -> `svd_service.py` -> `svd_native_backend.py` |
| Portable SVD provenance | `src/video/svd_portable_provenance.py` -> `src/video/container_metadata.py` -> `src/video/svd_runner.py` -> `src/video/svd_registry.py` |
| Windows runtime/bootstrap | `scripts/bootstrap_windows.ps1` -> `docs/runbooks/windows_runtime_bootstrap.md` |
| Replay/learning | `replay_engine.py`, `src/learning/`, `job_history_store.py` |
| `PR-LEARN-300` experiment workflow | `experiment_execution.py` / `experiment_lifecycle.py` / `experiment_conclusion.py` / `experiment_freeze.py` -> `execution_controller.py` -> `learning_controller.py` -> `resource_access.py` / `experiment_naming.py` / `review_workspace.py` / `discovered_review_store.py` / `staged_recommendations.py` -> `learning_record.py` / `recommendation_engine.py` |
| Operator-journey harness | `python -m tools.operator_journey` -> `tools/operator_journey/cli.py` -> `journeys/learning_lora_strength.py` / `journeys/discovered_outputs_review.py` (+ `fixtures.py`, `dialogs.py`) -> `tk_driver.py` (semantic Tk) / `workspace.py` (isolation) / `observe.py` / `capture.py` / `evidence.py` / `fake_a1111.py`; tests in `tests/tools/test_operator_journey_*.py` |
| Tests/CI | `pyproject.toml`, `tools/ci/`, `.github/workflows/ci.yml` |
| A1111 generation / transport | `src/pipeline/pipeline_runner.py` -> `src/pipeline/executor.py` -> `src/api/client.py` |
| A1111 process ownership / lifecycle | `src/api/webui_process_manager.py` -> `src/controller/webui_connection_controller.py` |
| Generation progress / stall diagnostics | `src/pipeline/executor.py` -> `src/controller/core_pipeline_controller.py` -> `src/controller/app_controller.py` runtime projection -> `src/services/watchdog_system_v2.py` |
| Operator readiness | `src/services/operator_readiness_service.py` -> `src/gui/panels_v2/operator_readiness_panel_v2.py` -> `src/gui/main_window_v2.py` |
| SVD geometry/presets | `src/gui/views/svd_tab_frame_v2.py` -> `src/video/svd_target.py` -> `src/video/svd_service.py` -> `src/video/svd_models.py` |
| `PR-SVD-100` folder batch | `svd_preprocess.py` -> `svd_controller.py` -> `svd_submission_service.py` -> `app_controller.py` -> `svd_tab_frame_v2.py` -> `JobService.submit_njrs` |
| Queue/history recovery UX | `src/gui/panels_v2/queue_panel_v2.py` + `src/gui/job_history_panel_v2.py` -> `src/controller/job_history_service.py` / `src/controller/job_service.py` -> `src/queue/job_queue.py` -> `src/queue/job_repository.py` |

## Controller decomposition

Controllers coordinate; cohesive work belongs behind services/coordinators.
Existing extraction homes are `src/controller/app_controller_services/` and
`src/controller/pipeline_controller_services/`. Runtime ports live in
`src/controller/ports/`. Before adding responsibility to a ratcheted controller,
look for an existing service or create one with a single clear owner.

## Documentation authority

1. `AGENTS.md`
2. `STATUS.md`
3. `docs/CODEX_MAP.md`
4. Relevant section of `docs/ARCHITECTURE_v2.6.md`
5. Relevant section of `docs/StableNew_Coding_and_Testing_v2.6.md`
6. `docs/StableNew Roadmap v2.6.md` for sequencing
7. Git history only when current evidence is insufficient or history is asked

Git history and archive/recovery material are not searched unless a historical
question requires them. Runtime history code under `src/history/` is current
production code and is not archival material.
