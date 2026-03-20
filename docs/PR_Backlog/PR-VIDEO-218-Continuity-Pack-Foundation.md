# PR-VIDEO-218 - Continuity Pack Foundation

Status: Specification
Priority: HIGH
Effort: MEDIUM
Phase: Post-Unification Video Productization
Date: 2026-03-19

## Context & Motivation

### Problem Statement

StableNew now has short-form workflow-video and planned sequence orchestration,
but there is no persistent continuity layer for characters, wardrobe, scenes,
and anchor references across related jobs.

### Why This Matters

This is the missing foundation from the older `PR-VIDEO-087` plan. Without a
continuity container, repeated video and image jobs cannot cleanly share a
durable creative context beyond raw prompt reuse.

### Current Architecture

Current state:

- NJR can carry canonical intent/execution/backend metadata
- video and image artifacts are canonical
- no continuity model exists above individual jobs or sequences

### Reference

- `docs/ARCHITECTURE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`

## Goals & Non-Goals

### Goals

1. Add StableNew-owned `ContinuityPack` models and persistence helpers.
2. Allow NJR-backed jobs and sequence jobs to reference a continuity pack by
   stable identity.
3. Preserve continuity linkage through manifests, history, and canonical result
   summaries.
4. Keep the first version data-oriented and deterministic.

### Non-Goals

1. Do not build a smart continuity engine or automatic planning system.
2. Do not redesign prompt composition around continuity in this PR.
3. Do not build a heavy GUI editor in this PR.
4. Do not make continuity a required field for any job type.

## Guardrails

1. Continuity packs are StableNew-owned data containers, not backend contracts.
2. Continuity pack linkage must remain optional and additive.
3. Do not hard-code continuity behavior into prompt-builder internals in this
   PR.
4. Do not bypass canonical manifests/history; linkage must travel through them.

## Allowed Files

### Files to Create

| File | Purpose |
|------|---------|
| `src/video/continuity_models.py` | Continuity pack models |
| `src/video/continuity_store.py` | Persistence helpers for continuity packs |
| `tests/video/test_continuity_models.py` | Model coverage |
| `tests/video/test_continuity_store.py` | Persistence coverage |

### Files to Modify

| File | Reason |
|------|--------|
| `src/pipeline/config_contract_v26.py` | Allow continuity linkage metadata |
| `src/pipeline/job_models_v2.py` | Preserve continuity metadata in NJR-backed jobs |
| `src/pipeline/pipeline_runner.py` | Stamp continuity linkage into result metadata/manifests |
| `src/video/sequence_models.py` | Optional continuity linkage for sequences |
| `src/controller/video_workflow_controller.py` | Accept continuity pack selection metadata if present |
| `tests/pipeline/test_pipeline_runner.py` | continuity summary assertions |
| `tests/controller/test_video_workflow_controller.py` | controller linkage assertions |

### Forbidden Files

| File/Directory | Reason |
|----------------|--------|
| `src/controller/job_service.py` | No queue or submission semantic changes |
| `src/controller/archive/` | No legacy runtime paths |
| `src/gui/main_window_v2.py` | No large GUI work in this PR |

## Implementation Plan

### Step 1: Add continuity models and persistence

Create models for:

- continuity pack identity
- character references
- wardrobe references
- scene references
- anchor sets

Files:

- create `src/video/continuity_models.py`
- create `src/video/continuity_store.py`
- create related tests

### Step 2: Add optional continuity linkage to runtime metadata

Permit NJR-backed jobs and sequence plans to reference a continuity pack by ID
and snapshot summary.

Files:

- modify `src/pipeline/config_contract_v26.py`
- modify `src/pipeline/job_models_v2.py`
- modify `src/video/sequence_models.py`

### Step 3: Preserve continuity through runner/manifests/history

Stamp continuity linkage into canonical result metadata and manifests so replay,
history, and later planning layers can recover it.

Files:

- modify `src/pipeline/pipeline_runner.py`
- modify tests accordingly

### Step 4: Minimal controller intake

Allow the Video Workflow controller to carry continuity linkage if supplied by a
future UI surface or import path.

Files:

- modify `src/controller/video_workflow_controller.py`
- modify `tests/controller/test_video_workflow_controller.py`

## Testing Plan

### Unit Tests

- `tests/video/test_continuity_models.py`
- `tests/video/test_continuity_store.py`

### Integration Tests

- `tests/pipeline/test_pipeline_runner.py`
- `tests/controller/test_video_workflow_controller.py`

### Manual Testing

1. Create a continuity pack fixture.
2. Submit a workflow-video job with continuity linkage.
3. Confirm manifests/history summaries retain the continuity reference.

## Verification Criteria

### Success Criteria

1. Continuity packs persist as StableNew-owned data.
2. Jobs and sequences can optionally reference continuity packs.
3. Continuity linkage survives through canonical manifests/result metadata.

### Failure Criteria

1. Continuity logic becomes mandatory for normal runs.
2. Continuity data leaks into backend-local or workflow-JSON contracts.
3. Continuity linkage is lost after execution.

## Risk Assessment

### Low-Risk Areas

- new continuity model and store files

### Medium-Risk Areas

- result metadata expansion
  - Mitigation: keep continuity linkage additive and optional

### High-Risk Areas

- over-scoping into a full planning or prompt system
  - Mitigation: explicitly limit this PR to models, storage, and linkage

### Rollback Plan

Remove continuity linkage fields while preserving the underlying workflow-video
and sequence features.

## Tech Debt Analysis

### Tech Debt Removed

- lack of durable continuity container above individual jobs

### Tech Debt Intentionally Deferred

- story- and shot-level authored planning over continuity packs
  - Owner: `PR-VIDEO-219`
- continuity-aware UX/editor polish
  - Owner: `PR-GUI-220`

## Documentation Updates

- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`

## Dependencies

### Internal

- canonical config metadata
- pipeline runner result summaries
- optional sequence planning

### External

- none

## Approval & Execution

Planner: ChatGPT/Codex planning surface
Executor: Copilot or Codex
Reviewer: Rob
Approval Status: Pending

## Next Steps

1. Execute `PR-VIDEO-218`.
2. Use continuity packs in `PR-VIDEO-219`.
3. Expose workflow UX around continuity in `PR-GUI-220`.
