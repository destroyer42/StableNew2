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
- Native SVD/video: `src/video/svd_service.py`, `src/video/svd_runner.py`,
  `src/video/svd_native_backend.py`, and `src/video/workflow_contracts.py`.
- SVD folder-batch submission: `docs/Subsystems/Video/PR-SVD-100_Folder_Batch_Submission.md`
  -> `src/video/svd_preprocess.py` -> `src/controller/svd_controller.py` ->
  `src/controller/svd_submission_service.py` -> `src/controller/app_controller.py`
  -> `src/gui/views/svd_tab_frame_v2.py` -> `JobService.submit_njrs`.
- Portable SVD provenance: `src/video/svd_portable_provenance.py` ->
  `src/video/container_metadata.py` -> `src/video/svd_runner.py` ->
  `src/video/svd_registry.py`.
- Learning: `src/learning/`, with GUI coordination in
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
| `PR-IMG-100` backend-neutral image execution | `docs/Subsystems/Image/PR-IMG-100_Backend-Neutral_Image_Execution.md` -> `src/image_backends/image_backend_types.py` / `src/image_backends/image_backend_registry.py` / `src/image_backends/a1111_webui_backend.py` -> `njr_core_v26.py` / `config_contract_v26.py` -> image compilers -> `pipeline_runner.py` -> runtime ports -> A1111 executor/client boundary |
| Video/SVD | `workflow_compiler.py` -> `svd_service.py` -> `svd_native_backend.py` |
| Portable SVD provenance | `src/video/svd_portable_provenance.py` -> `src/video/container_metadata.py` -> `src/video/svd_runner.py` -> `src/video/svd_registry.py` |
| Windows runtime/bootstrap | `scripts/bootstrap_windows.ps1` -> `docs/runbooks/windows_runtime_bootstrap.md` |
| Replay/learning | `replay_engine.py`, `src/learning/`, `job_history_store.py` |
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
