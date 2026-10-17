# StableNew task map

Where to start for a task. This is navigation, not architecture authority, and it is hand-written and short on purpose
(capped at 60 lines by `tools/ci/ci_truth.py`, every path checked). Find any other module in the generated
[`docs/CODE_MAP.md`](CODE_MAP.md); read the matching feature record under `docs/Subsystems/` (one folder per area) before changing a feature.
The earlier per-PR version of this file is in Git (`git show 7e311d1d:docs/CODEX_MAP.md`).

`Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`

## Start here by task

| Task | Start here, in order |
|---|---|
| GUI to queue submission | `src/controller/app_controller.py` -> `src/controller/job_service.py` -> `src/queue/job_queue.py` -> `src/queue/job_repository.py` |
| Job record (NJR) and compilers | `src/pipeline/njr_core_v26.py`, `src/pipeline/config_contract_v26.py`, `src/pipeline/job_builder_v2.py` |
| Running a job | `src/pipeline/pipeline_runner.py` -> `src/pipeline/executor.py` -> `src/api/client.py` |
| PromptPacks | `docs/Subsystems/PromptPacks/PROMPTPACKS_AND_PROMPTING.md`; `src/pipeline/prompt_pack_parser.py` -> `src/pipeline/prompt_pack_job_builder.py`; `src/promptpacks/` |
| Matrix and randomization | `src/pipeline/config_variant_plan_v2.py` -> `src/randomizer/` |
| Image backends and model profiles | `docs/Subsystems/Image/IMAGE_PIPELINE.md` and `MODEL_PROFILES.md` first, then `src/image_backends/image_backend_registry.py`, `src/image_backends/model_policy.py` |
| Prompt compatibility and adaptation | `src/prompting/`; `docs/Subsystems/Prompting/` |
| Assets (models, LoRAs, embeddings) | `src/assets/registry.py`; `docs/Subsystems/Image/PR-ASSET-110_Local_Asset_Registry.md` |
| WebUI process, outage and startup hold | `docs/Subsystems/Runtime/QUEUE_AND_RUNTIME.md`; `src/api/webui_process_manager.py`, `src/controller/webui_outage_coordinator.py`, `src/controller/job_service_outage.py` |
| GPU device-loss containment | `src/controller/gpu_loss_coordinator.py`; `docs/Subsystems/Runtime/PR-QUEUE-GPU-180_GPU_Loss_Dispatch_Containment.md` |
| Native SVD video | `docs/Subsystems/Video/VIDEO_PIPELINE.md`; `src/video/svd_service.py` -> `src/video/svd_native_backend.py` -> `src/video/svd_runner.py` |
| Comfy Video Workflow | `src/video/workflow_catalog.py` -> `src/video/video_workflow_njr_builder.py` -> `src/video/comfy_workflow_backend.py`; `docs/Subsystems/Video/` |
| Artifacts, replay and history | `src/pipeline/artifact_contract.py`, `src/pipeline/result_contract_v26.py`, `src/pipeline/replay_engine.py`, `src/history/` |
| Learning and experiments | `docs/Subsystems/Learning/LEARNING.md`; `src/learning/`, `src/gui/controllers/learning_controller.py` |
| Review, reprocess and batch operations | `docs/Subsystems/GUI/PHOTO_REVIEW_REPROCESS.md`; `src/controller/review_batch_service.py`, `src/controller/batch_operations_service.py`, `src/queue/batch_projection.py` |
| Photo Optimize | `docs/Subsystems/GUI/PHOTO_REVIEW_REPROCESS.md`; `src/photo_optimize/`, `src/controller/photo_optimize_submission.py` |
| Adaptive refinement and ADetailer | `src/refinement/`, `src/pipeline/adetailer_contract.py` |
| GUI views and state | `src/gui/views/`, `src/gui/app_state_v2.py`, `src/gui/main_window_v2.py` |
| Crash-safe state files | `src/utils/atomic_io.py` (every persisted JSON/text store goes through it) |
| Tests, CI and ratchets | `docs/Subsystems/Testing/TESTING_AND_CI.md`; `python tools/ci/run_pr_gate.py`, `.github/workflows/ci.yml`, `tools/ci/`, `docs/StableNew_Coding_and_Testing_v2.6.md` |
| Offline qualification evidence | `tools/qualification/`, `tools/acceptance/` (operator-only; never part of the production path) |

## Controller decomposition

Controllers coordinate; cohesive work belongs behind services. Extraction homes are
`src/controller/app_controller_services/` and `src/controller/pipeline_controller_services/`; runtime ports live in
`src/controller/ports/`. Before adding responsibility to a ratcheted controller, find an existing service or create one with a
single clear owner (the controller-surface ratchet only allows line counts to shrink).

## Documentation authority

1. `AGENTS.md`
2. `STATUS.md`
3. This map, then the relevant section of `docs/ARCHITECTURE_v2.6.md`
4. The relevant section of `docs/StableNew_Coding_and_Testing_v2.6.md`
5. `docs/StableNew Roadmap v2.6.md` for sequencing
6. Git history only when current evidence is insufficient; `src/history/` is production code, not archive material.

Product, value and priority assessment: [assessment entry point](assessments/README.md).
