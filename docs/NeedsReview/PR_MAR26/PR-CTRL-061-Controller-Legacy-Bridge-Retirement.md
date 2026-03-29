# PR-CTRL-061: Retire Controller Legacy Bridge Paths

**Status**: Implemented
**Priority**: HIGH
**Effort**: MEDIUM
**Phase**: Phase 1 Canonical Migration
**Date**: 2026-03-16
**Implementation Date**: 2026-03-16

## Context & Motivation

### Problem Statement
`AppController` and `PipelineController` still carried deprecated controller bridge behavior:

- `AppController._start_run_v2()` fell back to `start_run()`
- `AppController.on_add_job_to_queue_v2()` fell back to older add/run handlers
- `PipelineController.start_pipeline()` still assembled a legacy `PipelineConfig`
- `PipelineController.run_pipeline()` still converted legacy config via `legacy_njr_adapter`

That left the GUI controller path partially migrated even after queue/executor cleanup.

### Why This Matters
These bridges kept the legacy `pipeline_config` execution model reachable from controller code. That violates the v2.6 architecture and makes it easier for future work to drift back into duplicate execution behavior.

### Current Architecture
- GUI/controller runs should submit NJR-backed jobs only
- Queue/direct semantics should be expressed through `run_mode`
- `PipelineController._run_job()` plus `run_njr()` is the canonical execution surface

## Goals & Non-Goals

### Goals
1. Remove `AppController` fallback to legacy run methods from V2 entrypoints.
2. Make `PipelineController.start_pipeline()` submit preview NJRs directly instead of assembling legacy config.
3. Remove `PipelineController.run_pipeline()` and its `legacy_njr_adapter` dependency.
4. Rewrite controller tests so they validate canonical controller behavior only.

### Non-Goals
1. Do not remove every remaining archived `PipelineConfig` helper in this PR.
2. Do not touch queue/runtime core contracts beyond controller call sites.
3. Do not change GUI widget wiring outside the existing controller-facing APIs.

## Allowed Files

### Files to Create
| File | Purpose |
|------|---------|
| `docs/PR_MAR26/PR-CTRL-061-Controller-Legacy-Bridge-Retirement.md` | PR record |

### Files to Modify
| File | Reason |
|------|--------|
| `src/controller/app_controller.py` | remove legacy V2 controller fallbacks |
| `src/controller/pipeline_controller.py` | retire adapter-backed controller execution bridge |
| `tests/controller/test_app_controller_pipeline_bridge.py` | rewrite bridge tests to canonical-only behavior |
| `tests/controller/test_app_controller_add_to_queue_v2.py` | align add-to-queue tests with explicit controller semantics |
| `tests/controller/test_controller_event_api_v2.py` | remove legacy fallback expectations |
| `tests/controller/test_pipeline_controller_webui_gating.py` | validate canonical start path |
| `tests/controller/test_pipeline_controller_run_modes_v2.py` | add canonical start_pipeline coverage |

### Forbidden Files
| File/Directory | Reason |
|----------------|--------|
| `src/pipeline/**` | runner/executor changes are out of scope here |
| `src/queue/**` | queue model cleanup landed in PR-CORE1-060 |
| `src/gui/**` | GUI cleanup belongs to later PRs |

## Implementation Summary

1. `AppController.start_run_v2()` and `_start_run_v2()` now require `pipeline_controller.start_pipeline()` and do not fall back to `start_run()`.
2. `AppController.on_add_job_to_queue_v2()` now uses `enqueue_draft_jobs()` only; it logs and returns when the pipeline controller is unavailable or enqueue fails.
3. `PipelineController.start_pipeline()` now delegates to the preview/NJR submission path instead of `_build_pipeline_config_from_state()` plus `_run_pipeline_job()`.
4. `PipelineController.run_pipeline()` and the `legacy_njr_adapter` import were removed.

## Verification

```bash
pytest tests/controller/test_app_controller_pipeline_bridge.py tests/controller/test_app_controller_add_to_queue_v2.py tests/controller/test_controller_event_api_v2.py tests/controller/test_pipeline_controller_webui_gating.py tests/controller/test_pipeline_controller_run_modes_v2.py tests/controller/test_app_controller_run_bridge_v2.py tests/controller/test_app_to_pipeline_run_bridge_v2.py tests/controller/test_app_controller_run_now_bridge.py tests/controller/test_app_controller_njr_exec.py -q
pytest --collect-only -q
python -m compileall src/controller/app_controller.py src/controller/pipeline_controller.py tests/controller/test_app_controller_pipeline_bridge.py tests/controller/test_app_controller_add_to_queue_v2.py tests/controller/test_controller_event_api_v2.py tests/controller/test_pipeline_controller_webui_gating.py tests/controller/test_pipeline_controller_run_modes_v2.py
```
