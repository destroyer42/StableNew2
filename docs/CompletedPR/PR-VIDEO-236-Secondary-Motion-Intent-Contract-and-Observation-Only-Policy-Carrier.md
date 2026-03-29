# PR-VIDEO-236 - Secondary Motion Intent Contract and Observation-Only Policy Carrier

Status: Completed 2026-03-21

## Summary

This PR froze the outer secondary-motion contract for StableNew so later video
runtime work could layer on top of one NJR-carried `secondary_motion` intent
without overloading `motion_profile` or changing backend behavior.

## Delivered

- added canonical `intent_config["secondary_motion"]` preservation and
  extraction in `src/pipeline/config_contract_v26.py`
- preserved the nested motion intent through current builder paths in:
  - `src/pipeline/job_builder_v2.py`
  - `src/pipeline/prompt_pack_job_builder.py`
  - `src/pipeline/cli_njr_builder.py`
- created the StableNew-owned motion contract package in:
  - `src/video/motion/secondary_motion_models.py`
  - `src/video/motion/secondary_motion_policy_service.py`
- added observation-only runner planning for video stages in
  `src/pipeline/pipeline_runner.py` so derived policy data flows through
  `request.context_metadata` and `result.metadata` without changing backend
  execution behavior
- added contract and architecture-guard coverage in:
  - `tests/video/test_secondary_motion_models.py`
  - `tests/video/test_secondary_motion_policy_service.py`
  - `tests/video/test_secondary_motion_layer_imports.py`
- froze the v1 schema document in `docs/Architecture/SECONDARY_MOTION_POLICY_SCHEMA_V1.md`

## Key Files

- `src/pipeline/config_contract_v26.py`
- `src/pipeline/job_builder_v2.py`
- `src/pipeline/prompt_pack_job_builder.py`
- `src/pipeline/cli_njr_builder.py`
- `src/pipeline/pipeline_runner.py`
- `src/video/motion/secondary_motion_models.py`
- `src/video/motion/secondary_motion_policy_service.py`
- `tests/video/test_secondary_motion_models.py`
- `tests/video/test_secondary_motion_policy_service.py`
- `tests/video/test_secondary_motion_layer_imports.py`
- `docs/Architecture/SECONDARY_MOTION_POLICY_SCHEMA_V1.md`

## Tests

Focused verification passed:

- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/video/test_secondary_motion_models.py tests/video/test_secondary_motion_policy_service.py tests/video/test_secondary_motion_layer_imports.py tests/pipeline/test_config_contract_v26.py tests/pipeline/test_job_builder_v2.py tests/pipeline/test_prompt_pack_job_builder.py tests/pipeline/test_cli_njr_builder.py tests/pipeline/test_pipeline_runner.py -q`
- result: `55 passed in 3.24s`
