# PR-VIDEO-216 - Sequence Orchestration and Segment Planning

Status: Specification
Priority: HIGH
Effort: LARGE
Phase: Post-Unification Video Productization
Date: 2026-03-19

## Context & Motivation

### Problem Statement

StableNew can execute short-form video jobs, but there is still no first-class
long-form orchestration layer. The repo lacks a deterministic sequence model,
segment planning, carry-forward rules, overlap metadata, and per-segment
provenance.

### Why This Matters

Without a StableNew-owned sequence layer, longer video generation remains an
ad hoc manual workflow. That blocks the older `PR-VIDEO-084` intent and keeps
long-form video outside the same quality bar as image and short-form video.

### Current Architecture

Current short-form path:

`Intent -> NJR -> Queue -> PipelineRunner -> video backend -> canonical artifact`

Missing layer:

- sequence planning above repeated backend runs
- segment-level provenance and overlap policy
- deterministic carry-forward from one segment to the next

### Reference

- `docs/ARCHITECTURE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`
- `docs/PR_Backlog/PR-VIDEO-215-Workflow-Video-Output-Routing-and-History-Convergence.md`

## Goals & Non-Goals

### Goals

1. Introduce StableNew-owned internal sequence planning models:
   `VideoSequenceJob`, `VideoSegmentPlan`, and sequence provenance records.
2. Keep NJR as the only outer executable job contract.
3. Let one NJR-backed workflow-video submission carry a sequence plan that the
   runner executes deterministically segment by segment.
4. Persist per-segment artifacts and a sequence-level summary into canonical
   manifests/result metadata.

### Non-Goals

1. Do not add stitching or interpolation in this PR.
2. Do not add continuity packs or story planning in this PR.
3. Do not add a new top-level queue/job model parallel to NJR.
4. Do not add raw GUI-heavy planning UX in this PR beyond minimal controller
   plumbing if required.

## Guardrails

1. NJR remains the only outer executable contract.
2. Sequence planning lives under `src/video/` plus minimal runner/config hooks.
3. Backends still execute only one compiled segment request at a time.
4. Sequence plans must be deterministic and serializable.
5. Do not introduce backend-owned long-form magic as the primary abstraction.

## Allowed Files

### Files to Create

| File | Purpose |
|------|---------|
| `src/video/sequence_models.py` | Sequence and segment planning dataclasses |
| `src/video/sequence_planner.py` | Deterministic planning and carry-forward rules |
| `src/video/sequence_manifest.py` | Sequence/segment manifest helpers |
| `tests/video/test_sequence_models.py` | Model serialization/validation |
| `tests/video/test_sequence_planner.py` | Planning logic coverage |
| `tests/video/test_sequence_manifest.py` | Sequence manifest coverage |

### Files to Modify

| File | Reason |
|------|--------|
| `src/video/workflow_contracts.py` | Carry sequence-related workflow input metadata if needed |
| `src/video/workflow_compiler.py` | Compile segment-scoped workflow requests |
| `src/video/comfy_workflow_backend.py` | Execute one compiled segment and return segment artifact details |
| `src/pipeline/config_contract_v26.py` | Allow sequence intent/backend options for workflow-video |
| `src/pipeline/job_models_v2.py` | Preserve sequence metadata on NJR-backed jobs |
| `src/pipeline/stage_sequencer.py` | Accept a terminal workflow-video stage with sequence metadata |
| `src/pipeline/pipeline_runner.py` | Orchestrate repeated segment execution and aggregate outputs |
| `tests/pipeline/test_pipeline_runner.py` | Sequence runner assertions |
| `tests/pipeline/test_stage_sequencer_plan_builder.py` | Stage-plan assertions |
| `tests/video/test_comfy_workflow_backend.py` | Segment execution assertions |

### Forbidden Files

| File/Directory | Reason |
|----------------|--------|
| `src/controller/archive/` | No legacy paths |
| `src/controller/job_service.py` | No queue semantic changes |
| `src/gui/views/video_workflow_tab_frame_v2.py` | Avoid expanding UI scope before planning core exists |
| `src/gui/main_window_v2.py` | No top-level GUI work in this PR |

## Implementation Plan

### Step 1: Add internal sequence and segment models

Create StableNew-owned models for:

- sequence identity
- ordered segment list
- carry-forward rules
- overlap metadata
- provenance records

Files:

- create `src/video/sequence_models.py`
- create `tests/video/test_sequence_models.py`

### Step 2: Build deterministic planning logic

Implement a planner that turns sequence intent into ordered segment plans with:

- fixed segment indices
- source-anchor rules
- carry-forward source policy
- overlap metadata
- reproducible plan output

Files:

- create `src/video/sequence_planner.py`
- create `tests/video/test_sequence_planner.py`

### Step 3: Extend workflow compilation and backend execution

Teach workflow compilation to compile per-segment backend requests without
changing the outer NJR contract.

Files:

- modify `src/video/workflow_compiler.py`
- modify `src/video/comfy_workflow_backend.py`
- modify `tests/video/test_comfy_workflow_backend.py`

### Step 4: Add runner-level sequence orchestration

Teach `PipelineRunner` to:

- detect sequence metadata on workflow-video jobs
- execute segment plans deterministically
- preserve per-segment artifact records
- emit a sequence summary in canonical result metadata

Files:

- modify `src/pipeline/pipeline_runner.py`
- modify `src/pipeline/job_models_v2.py`
- modify `src/pipeline/config_contract_v26.py`
- modify `tests/pipeline/test_pipeline_runner.py`

### Step 5: Add sequence manifests

Write a StableNew-owned sequence manifest layer that records:

- segment order
- carry-forward policy
- overlap settings
- segment artifact paths
- sequence summary artifact

Files:

- create `src/video/sequence_manifest.py`
- create `tests/video/test_sequence_manifest.py`
- modify `src/pipeline/pipeline_runner.py`

## Testing Plan

### Unit Tests

- `tests/video/test_sequence_models.py`
- `tests/video/test_sequence_planner.py`
- `tests/video/test_sequence_manifest.py`

### Integration Tests

- `tests/video/test_comfy_workflow_backend.py`
- `tests/pipeline/test_pipeline_runner.py`
- `tests/pipeline/test_stage_sequencer_plan_builder.py`

### Manual Testing

1. Submit one workflow-video job with sequence intent enabled.
2. Verify multiple segment outputs are produced in deterministic order.
3. Verify a sequence manifest exists and references each segment artifact.

## Verification Criteria

### Success Criteria

1. One NJR-backed job can execute multiple ordered video segments.
2. Each segment has its own artifact provenance.
3. The sequence as a whole has one StableNew-owned summary manifest/result.

### Failure Criteria

1. A second top-level job model is introduced.
2. Segment ordering is nondeterministic.
3. Sequence execution loses per-segment provenance.

## Risk Assessment

### Low-Risk Areas

- new internal sequence model files
- manifest helper files

### Medium-Risk Areas

- `PipelineRunner` sequence aggregation
  - Mitigation: keep single-segment workflow-video path intact and separately covered

### High-Risk Areas

- backend execution loop for segments
  - Mitigation: backend remains segment-scoped; orchestration stays runner-owned

### Rollback Plan

Disable sequence metadata handling in runner/backend and leave short-form
workflow-video unchanged.

## Tech Debt Analysis

### Tech Debt Removed

- absence of first-class long-form orchestration
- manual multi-run sequence planning outside canonical runtime

### Tech Debt Intentionally Deferred

- stitched/interpolated sequence outputs
  - Owner: `PR-VIDEO-217`
- continuity-aware carry-forward
  - Owner: `PR-VIDEO-218`
- story/shot authored sequence generation
  - Owner: `PR-VIDEO-219`

## Documentation Updates

- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`

## Dependencies

### Internal

- workflow compiler/backend
- canonical config and job metadata
- pipeline runner

### External

- managed Comfy runtime for manual sequence verification

## Approval & Execution

Planner: ChatGPT/Codex planning surface
Executor: Copilot or Codex
Reviewer: Rob
Approval Status: Pending

## Next Steps

1. Execute `PR-VIDEO-216`.
2. Continue immediately with `PR-VIDEO-217`.
3. Feed continuity and planning layers on top in `PR-VIDEO-218` and `PR-VIDEO-219`.
