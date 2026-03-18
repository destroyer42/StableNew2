# PR-PIPE-062: Pipeline Config Boundary Validation and Normalization

**Status**: Implemented
**Priority**: HIGH
**Effort**: SMALL
**Phase**: Phase 1 Canonical Migration
**Date**: 2026-03-16
**Implementation Date**: 2026-03-16

## Context & Motivation

### Problem Statement
Pipeline config normalization was duplicated across multiple pipeline surfaces:

- `stage_sequencer.build_stage_execution_plan()` expected one config shape
- `payload_builder.build_sdxl_payload()` accepted a slightly different alias set
- `JobBuilderV2.build_from_run_request()` reinterpreted config snapshots independently

That meant alias keys such as `model_name`, `sampler`, `scheduler_name`, `upscaler_name`, and hires/refiner variants could behave differently depending on which boundary consumed them first.

### Why This Matters
The pipeline boundary should have one canonical config contract. Without that, stage planning, NJR construction, and payload build can drift even when they are consuming the same logical settings.

## Goals & Non-Goals

### Goals
1. Introduce one pipeline config normalizer for canonical alias/default handling.
2. Make stage planning consume normalized pipeline config.
3. Make payload building consume normalized stage payload config.
4. Make `JobBuilderV2.build_from_run_request()` normalize config snapshots before emitting NJRs.

### Non-Goals
1. Do not redesign controller/UI config assembly in this PR.
2. Do not modify runner/executor contracts.
3. Do not remove deprecated `PipelineConfig` helpers outside the pipeline boundary.

## Allowed Files

### Files to Create
| File | Purpose |
|------|---------|
| `src/pipeline/config_normalizer.py` | canonical pipeline/stage config normalizer |
| `docs/PR_MAR26/PR-PIPE-062-Pipeline-Config-Boundary-Validation-and-Normalization.md` | PR record |
| `tests/pipeline/test_config_normalizer.py` | direct normalizer tests |

### Files to Modify
| File | Reason |
|------|--------|
| `src/pipeline/stage_sequencer.py` | normalize config before stage validation/build |
| `src/pipeline/payload_builder.py` | normalize stage payload config before payload construction |
| `src/pipeline/job_builder_v2.py` | normalize run-request config snapshots before NJR creation |
| `tests/pipeline/test_stage_sequencer_plan_builder.py` | alias normalization coverage |
| `tests/api/test_sdxl_payloads.py` | alias normalization coverage for payload build |
| `tests/pipeline/test_job_builder_v2.py` | run-request normalization coverage |

### Forbidden Files
| File/Directory | Reason |
|----------------|--------|
| `src/controller/**` | controller cleanup is handled in separate Phase 1 PRs |
| `src/queue/**` | queue compatibility cleanup already landed |
| `src/gui/**` | UI config cleanup is not part of this boundary PR |

## Implementation Summary

1. Added `normalize_pipeline_config()` and `normalize_stage_payload_config()` in `src/pipeline/config_normalizer.py`.
2. `build_stage_execution_plan()` now validates against normalized nested config instead of raw alias-dependent input.
3. `build_sdxl_payload()` now normalizes stage payload aliases before applying stage-specific payload rules.
4. `JobBuilderV2.build_from_run_request()` now normalizes entry config snapshots before deriving `StageConfig` and emitted NJR config.

## Verification

```bash
pytest tests/pipeline/test_config_normalizer.py tests/pipeline/test_stage_sequencer_plan_builder.py tests/api/test_sdxl_payloads.py tests/pipeline/test_job_builder_v2.py tests/controller/test_pipeline_controller_run_modes_v2.py tests/controller/test_pipeline_controller_webui_gating.py -q
pytest --collect-only -q
python -m compileall src/pipeline/config_normalizer.py src/pipeline/stage_sequencer.py src/pipeline/payload_builder.py src/pipeline/job_builder_v2.py tests/pipeline/test_config_normalizer.py tests/pipeline/test_stage_sequencer_plan_builder.py tests/api/test_sdxl_payloads.py tests/pipeline/test_job_builder_v2.py
```
