# PR-CORE-002 - Character Embedding Pipeline

Status: Completed 2026-03-29

## Summary

StableNew had no canonical character-training surface. This PR added a
queue-backed `train_lora` stage, a thin external trainer subprocess wrapper, a
manifest-backed LoRA registration surface, and a dedicated Character Training
tab while preserving the single NJR -> queue -> runner execution path.

## Delivered

- added `validate_train_lora_execution_config()` to the canonical config
  contract
- added standalone `train_lora` stage support in stage models and stage
  sequencing, with explicit mixed-plan rejection
- extended `JobBuilderV2` to build standalone `train_lora` NJRs from submitted
  config snapshots
- added `src/training/character_embedder.py` as the runner-owned subprocess
  seam for external trainer commands
- added `src/training/lora_manager.py` to register and resolve trained weights
  by character name through a manifest under `data/embeddings/`
- added a Character Training tab and explicit `AppController` entrypoints for
  queue submission
- added deterministic pipeline, training, and GUI coverage for the new path

## Key Files

- `src/pipeline/config_contract_v26.py`
- `src/pipeline/stage_models.py`
- `src/pipeline/stage_sequencer.py`
- `src/pipeline/job_models_v2.py`
- `src/pipeline/job_builder_v2.py`
- `src/pipeline/pipeline_runner.py`
- `src/training/character_embedder.py`
- `src/training/lora_manager.py`
- `src/gui/views/character_training_frame.py`
- `src/controller/app_controller.py`
- `src/gui/main_window_v2.py`
- `docs/Subsystems/Training/Character_Embedding_Workflow_v2.6.md`

## Validation

- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest -q tests/training/test_character_embedder.py tests/training/test_lora_manager.py tests/gui_v2/test_character_training_frame.py tests/gui_v2/test_main_window_smoke_v2.py tests/pipeline/test_stage_sequencer_plan_builder.py tests/pipeline/test_job_builder_v2.py tests/pipeline/test_pipeline_runner.py`
- result: `60 passed, 1 skipped in 5.05s`

## Notes

- runtime execution requires either a submitted `trainer_command` or the
  `STABLENEW_TRAIN_LORA_COMMAND` environment variable
- the shipped surface registers and resolves trained weights by character name;
  richer prompt-side multi-character application remains the next follow-on in
  `PR-CORE-014`