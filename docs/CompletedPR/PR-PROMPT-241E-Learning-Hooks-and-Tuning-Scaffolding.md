# PR-PROMPT-241E - Learning Hooks and Tuning Scaffolding

Status: Completed 2026-03-24
Priority: MEDIUM
Effort: MEDIUM
Phase: Prompt Optimizer v3 Learning Closure

## Summary

Extended the post-execution learning path so `prompt_optimizer_v3` evidence can
be captured as an explicit opt-in dataset hook and compared through bounded,
named optimizer presets without introducing a new runtime mutation path.

## Delivered

- added an explicit `prompt_optimizer_learning_enabled` gate so optimizer
  evidence only enters learning datasets when requested
- compacted `prompt_optimizer_v3` replay data into stable
  `prompt_optimizer_learning` metadata for learning records
- added deterministic prompt-optimizer preset definitions for bounded
  comparison runs
- added a dedicated prompt-optimizer preset comparison learning-plan helper and
  runner scaffolding
- kept all behavior post-execution and fail-open, with no alternate execution
  path added to the builder/runner pipeline

## Key Files

- `src/learning/learning_record_builder.py`
- `src/learning/learning_contract.py`
- `src/learning/learning_plan.py`
- `src/learning/learning_runner.py`
- `tests/learning/test_learning_record_builder.py`
- `tests/learning/test_learning_hooks_pipeline_runner.py`
- `tests/learning/test_learning_runner_stubs.py`
- `tests/learning/test_learning_plan_factory.py`
- `tests/learning_v2/test_learning_contract.py`

## Validation

- focused 241E slice:
  - `pytest tests/learning/test_learning_record_builder.py tests/learning/test_learning_hooks_pipeline_runner.py tests/learning/test_learning_runner_stubs.py tests/learning/test_learning_plan_factory.py tests/learning_v2/test_learning_contract.py -q`
  - `19 passed in 4.13s`
- broader regression note:
  - `pytest tests/learning -q tests/learning_v2/test_learning_contract.py tests/pipeline/test_pipeline_learning_hooks.py -q`
  - surfaced pre-existing unrelated failures in `tests/learning/test_learning_paths_contract.py` and `tests/pipeline/test_pipeline_learning_hooks.py`; no new 241E-targeted failures were introduced in the focused slice