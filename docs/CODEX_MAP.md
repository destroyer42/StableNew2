# StableNew Codex map

This is a task-oriented navigation map, not an architecture authority. Read
`STATUS.md`, this map, and only the relevant section of
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
  `src/promptpacks/storage.py`; typed GUI editing remains in
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
- Image backend boundary: `src/api/`, `src/pipeline/payload_builder.py`, and
  the typed image handlers in `src/pipeline/executor.py`.
- Native SVD/video: `src/video/svd_service.py`, `src/video/svd_runner.py`,
  `src/video/svd_native_backend.py`, and `src/video/workflow_contracts.py`.
- Learning: `src/learning/`, with GUI coordination in
  `src/gui/controllers/learning_controller.py`.
- Artifacts and replay: `src/pipeline/artifact_contract.py`,
  `src/pipeline/result_contract_v26.py`, and `src/pipeline/replay_engine.py`.

## Start here by task

| Task | Start here |
|---|---|
| PromptPack behavior | `src/promptpacks/storage.py` -> `prompt_pack_model.py` -> `prompt_pack_job_builder.py` |
| Matrix/randomization | `config_variant_plan_v2.py` -> `src/randomizer/` |
| GUI submission | `app_controller.py` -> `run_submission_service.py` -> `job_service.py` |
| Queue/history | `job_service.py` -> `job_queue.py` -> `job_repository.py` |
| Image execution | `pipeline_runner.py` -> `executor.py` -> `src/api/` |
| Video/SVD | `workflow_compiler.py` -> `svd_service.py` -> `svd_native_backend.py` |
| Replay/learning | `replay_engine.py`, `src/learning/`, `job_history_store.py` |
| Tests/CI | `pyproject.toml`, `tools/ci/`, `.github/workflows/ci.yml` |

## Controller decomposition

Controllers coordinate; cohesive work belongs behind services/coordinators.
Existing extraction homes are `src/controller/app_controller_services/` and
`src/controller/pipeline_controller_services/`. Runtime ports live in
`src/controller/ports/`. Before adding responsibility to a ratcheted controller,
look for an existing service or create one with a single clear owner.

## Documentation authority

1. `AGENTS.md`
2. `docs/ARCHITECTURE_v2.6.md`
3. `docs/StableNew Roadmap v2.6.md`
4. `docs/StableNew_Coding_and_Testing_v2.6.md`
5. `STATUS.md` for current verified state and immediate priority

Git history and archive/recovery material are not searched unless a historical
question requires them. Runtime history code under `src/history/` is current
production code and is not archival material.
