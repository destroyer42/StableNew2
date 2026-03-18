# PR-CORE-060: NJR-Only Queue and History Compatibility Removal

**Status**: Implemented
**Priority**: HIGH
**Effort**: SMALL
**Phase**: Phase 1 Canonical Migration
**Date**: 2026-03-16
**Implementation Date**: 2026-03-16

## Context & Motivation

### Problem Statement
Queue and history runtime code still carry transitional compatibility semantics around `Job.pipeline_config` and `history_version`, even though the live execution model is NJR-only for new work.

### Why This Matters
These compatibility fields keep the old mental model alive. They increase ambiguity in queue/history tests and make it easier for future changes to smuggle legacy payload assumptions back into active code.

### Current Architecture
- Queue jobs execute through `_normalized_record` snapshots and `config_snapshot`
- History persistence is validated against schema `2.6`
- Runtime still exposed:
  - `Job.pipeline_config`
  - `HistoryRecord.history_version`
  - docstrings and tests that treated these as active compatibility surfaces

### Reference
- `docs/StableNew_Revised_Top20_Recommendations.md`
- `src/queue/job_model.py`
- `src/history/history_record.py`
- `src/history/history_schema_v26.py`

## Goals & Non-Goals

### Goals
1. Remove `Job.pipeline_config` from the active queue model.
2. Remove transitional `history_version` persistence from the history schema and record model.
3. Rewrite queue/history tests so they validate NJR-only runtime behavior instead of retired legacy acceptance.
4. Update queue/history docstrings to describe the current NJR-only contract.

### Non-Goals
1. Do not retire controller legacy bridge code in this PR.
2. Do not remove `legacy_njr_adapter` in this PR.
3. Do not rewrite GUI/controller references to legacy concepts outside directly affected tests.

## Allowed Files

### Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `docs/PR_MAR26/PR-CORE1-060-NJR-Only-Queue-History-Compatibility-Removal.md` | PR spec and implementation record | 180 |

### Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `src/queue/job_model.py` | remove `pipeline_config` compatibility field/property | 40 |
| `src/queue/job_queue.py` | align queue contract docstring with NJR-only runtime | 10 |
| `src/queue/job_history_store.py` | align history-store docstring with NJR-only runtime | 10 |
| `src/history/history_record.py` | remove `history_version` transitional field and keep NJR-only serialization | 20 |
| `src/history/history_schema_v26.py` | drop `history_version` from optional schema fields | 10 |
| `src/history/job_history_store.py` | stop preserving `history_version` on write | 10 |
| `tests/queue/test_job_model.py` | update queue model expectations | 20 |
| `tests/queue/test_queue_njr_path.py` | remove legacy queue acceptance test and codify NJR-only behavior | 40 |
| `tests/queue/test_single_node_runner_loopback.py` | rewrite loopback test to use NJR-backed jobs | 35 |
| `tests/queue/test_job_variant_metadata_v2.py` | remove archived `PipelineConfig` dependency | 25 |
| `tests/history/test_history_roundtrip.py` | remove transitional `history_version` assertions and legacy-entry framing | 25 |
| `tests/history/test_history_schema_roundtrip.py` | make roundtrip coverage canonical-only | 20 |

### Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| `src/controller/**` | controller bridge retirement belongs to the next PR |
| `src/pipeline/legacy_njr_adapter.py` | legacy adapter removal belongs to a later migration slice |
| `src/gui/**` | GUI cleanup belongs to later PRs |

## Implementation Plan

### Step 1: Remove queue-model compatibility field
Delete `pipeline_config` from `Job`, including the property/setter shim. Keep `config_snapshot` and `snapshot` as the active metadata surfaces.

### Step 2: Remove transitional history field
Delete `history_version` from `HistoryRecord`, from schema optional fields, and from deterministic history ordering/writes.

### Step 3: Rewrite affected tests
Convert queue/history tests from "legacy compatibility preserved" to "NJR-only runtime enforced". Keep tests deterministic and local.

### Step 4: Align queue/history narrative
Update queue/history docstrings so the active runtime contract no longer advertises compatibility fields as part of normal behavior.

## Testing Plan

### Unit Tests
- `tests/queue/test_job_model.py`
- `tests/queue/test_queue_njr_path.py`
- `tests/queue/test_single_node_runner_loopback.py`
- `tests/queue/test_job_variant_metadata_v2.py`
- `tests/history/test_history_roundtrip.py`
- `tests/history/test_history_schema_roundtrip.py`

### Integration Tests
- none

### Journey Tests
- none

### Manual Testing
1. Grep `src/queue` and `src/history` for active `pipeline_config` compatibility surfaces.
2. Confirm saved history entries no longer include `history_version`.
3. Confirm queue tests no longer import archived `PipelineConfig` just to validate `Job` basics.

## Verification Criteria

### Success Criteria
1. `Job` no longer exposes `pipeline_config`.
2. History writes no longer preserve or emit `history_version`.
3. Queue/history tests validate NJR-only behavior and pass.
4. `pytest --collect-only -q` remains green.

### Failure Criteria
- runtime queue/history code still carries `pipeline_config` compatibility in `Job`
- history serialization still writes `history_version`
- active tests continue defending legacy queue-only `PipelineConfig` jobs

## Risk Assessment

### Low Risk Areas
Queue/history runtime models and their direct tests.

### Medium Risk Areas
Removing `pipeline_config` changes positional `Job(...)` construction semantics.
- **Mitigation**: active runtime already uses keyword construction; rewrite directly affected tests.

### High Risk Areas
None expected in runtime, since controller legacy bridges are not being changed here.

### Rollback Plan
Restore `pipeline_config` and `history_version`, then revert the rewritten tests.

## Tech Debt Analysis

## Tech Debt Removed
- queue-model `pipeline_config` compatibility field
- transitional history `history_version` persistence
- queue/history tests that still normalized retired legacy behavior

## Tech Debt Added
- None expected

**Net Tech Debt**: -3

## Architecture Alignment

### Enforces Architecture v2.6
This PR narrows queue/history runtime surfaces to NJR-only semantics.

### Follows Testing Standards
Tests are deterministic, local, and do not depend on WebUI.

### Maintains Separation of Concerns
The PR is limited to queue/history runtime plus directly affected tests.

## Dependencies

### External
- none

### Internal
- `src.queue`
- `src.history`

## Timeline & Effort

| Task | Effort | Duration |
|------|--------|----------|
| queue/history model cleanup | 0.25 day | same day |
| test rewrites | 0.25 day | same day |
| verification | 0.25 day | same day |

**Total**: under 1 day

## Approval & Sign-Off

**Planner**: Codex
**Executor**: Codex
**Reviewer**: Rob

**Approval Status**: Implemented

## Next Steps

1. Move to controller legacy bridge retirement in the next PR.
2. Keep queue/history runtime free of new `pipeline_config` compatibility additions.
3. Revisit legacy adapter removal only after controller paths are cut over.

## Implementation Summary

**Implementation Date**: 2026-03-16
**Executor**: Codex
**Status**: COMPLETE

### What Was Implemented

#### 1. Queue model cleanup
Removed `pipeline_config` from `Job` and left `config_snapshot` and `snapshot` as the active queue metadata surfaces.

#### 2. History cleanup
Removed `history_version` from `HistoryRecord`, schema optional fields, and persistence ordering.

#### 3. Test migration
Rewrote queue/history tests that still encoded legacy `PipelineConfig` acceptance so they now validate NJR-only runtime behavior.

#### 4. Contract wording cleanup
Updated queue/history docstrings to describe current runtime expectations instead of transitional compatibility.

### Verification

```bash
pytest tests/queue/test_job_model.py tests/queue/test_queue_njr_path.py tests/queue/test_single_node_runner_loopback.py tests/queue/test_job_variant_metadata_v2.py tests/history/test_history_roundtrip.py tests/history/test_history_schema_roundtrip.py -q
pytest --collect-only -q
rg -n "def pipeline_config\b|history_version\b" src/queue src/history
```

The targeted tests passed (`16 passed`), `pytest --collect-only -q` remained green (`2210 collected / 1 skipped`), and the runtime grep returned no `Job.pipeline_config` or `history_version` compatibility surfaces in `src/queue` or `src/history`.

Deliberate remaining `pipeline_config` mentions in these subsystems are limited to deprecated-field detection and legacy-entry cleanup logic, not active queue/history runtime execution surfaces.
