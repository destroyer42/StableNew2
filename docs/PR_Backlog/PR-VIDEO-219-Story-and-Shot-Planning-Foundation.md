# PR-VIDEO-219 - Story and Shot Planning Foundation

Status: Specification
Priority: HIGH
Effort: LARGE
Phase: Post-Unification Video Productization
Date: 2026-03-19

## Context & Motivation

### Problem Statement

The repo still lacks the top planning layer from the older `PR-VIDEO-088`
concept. There is no durable manual planning model for story, scene, shot, and
anchor structure above sequence jobs.

### Why This Matters

Once sequences, continuity, and canonical post-video artifacts exist, the next
missing layer is authored planning. This provides a deterministic bridge from
creative planning to executable sequence jobs without turning StableNew into an
autonomous planner.

### Current Architecture

Current and planned layers:

- workflow-video job execution exists
- sequence orchestration is planned in `PR-VIDEO-216`
- continuity packs are planned in `PR-VIDEO-218`
- no story/scene/shot plan model exists yet

### Reference

- `docs/ARCHITECTURE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/PR-VIDEO-216-Sequence-Orchestration-and-Segment-Planning.md`
- `docs/PR_Backlog/PR-VIDEO-218-Continuity-Pack-Foundation.md`

## Goals & Non-Goals

### Goals

1. Add StableNew-owned manual planning models:
   `StoryPlan`, `ScenePlan`, `ShotPlan`, `AnchorPlan`.
2. Add deterministic compilation from plan structures into sequence job intent.
3. Preserve plan linkage through manifests/result metadata where a plan-origin
   sequence is executed.
4. Keep the first version purely manual and deterministic.

### Non-Goals

1. Do not add AI-generated planning or autonomous shot generation.
2. Do not add a full storyboard editor UI in this PR.
3. Do not change NJR outer job ownership.
4. Do not bundle continuity editing UX into this PR.

## Guardrails

1. Story/shot planning is a StableNew planning layer above sequence jobs.
2. Plans compile into sequence intent; they do not replace NJR.
3. Plan compilation must be deterministic and serializable.
4. Do not push plan structures into backend-local JSON or workflow internals.

## Allowed Files

### Files to Create

| File | Purpose |
|------|---------|
| `src/video/story_plan_models.py` | Story/scene/shot/anchor plan dataclasses |
| `src/video/story_plan_compiler.py` | Deterministic plan-to-sequence compilation |
| `src/video/story_plan_store.py` | Persistence helpers for plans |
| `tests/video/test_story_plan_models.py` | Model coverage |
| `tests/video/test_story_plan_compiler.py` | Compiler coverage |
| `tests/video/test_story_plan_store.py` | Store coverage |

### Files to Modify

| File | Reason |
|------|--------|
| `src/video/sequence_models.py` | Accept plan-origin metadata |
| `src/video/continuity_models.py` | Optional continuity linkage from plans |
| `src/pipeline/config_contract_v26.py` | Preserve plan linkage metadata |
| `src/pipeline/pipeline_runner.py` | Stamp plan-origin metadata into results/manifests |
| `tests/pipeline/test_pipeline_runner.py` | plan-origin result assertions |

### Forbidden Files

| File/Directory | Reason |
|----------------|--------|
| `src/controller/job_service.py` | No queue semantics |
| `src/controller/archive/` | No legacy surfaces |
| `src/gui/main_window_v2.py` | No large GUI planning editor in this PR |

## Implementation Plan

### Step 1: Add manual planning models

Create plan dataclasses for:

- story
- scene
- shot
- anchor

Files:

- create `src/video/story_plan_models.py`
- create `tests/video/test_story_plan_models.py`

### Step 2: Add deterministic compilation to sequence intent

Build a compiler that turns story/scene/shot structures into ordered sequence
plan intent without hidden inference.

Files:

- create `src/video/story_plan_compiler.py`
- create `tests/video/test_story_plan_compiler.py`

### Step 3: Add persistence and linkage

Persist story plans and preserve plan-origin metadata on compiled sequence jobs
and later result/manifests.

Files:

- create `src/video/story_plan_store.py`
- create `tests/video/test_story_plan_store.py`
- modify `src/pipeline/config_contract_v26.py`
- modify `src/pipeline/pipeline_runner.py`
- modify `tests/pipeline/test_pipeline_runner.py`

## Testing Plan

### Unit Tests

- `tests/video/test_story_plan_models.py`
- `tests/video/test_story_plan_compiler.py`
- `tests/video/test_story_plan_store.py`

### Integration Tests

- `tests/pipeline/test_pipeline_runner.py`

### Manual Testing

1. Create a minimal story plan fixture.
2. Compile it into sequence intent.
3. Execute one compiled sequence job and verify plan-origin metadata survives.

## Verification Criteria

### Success Criteria

1. Story/scene/shot data persists in StableNew-owned plan structures.
2. Plans compile deterministically into sequence intent.
3. Executed results retain plan-origin linkage.

### Failure Criteria

1. Plan compilation is heuristic or nondeterministic.
2. Plans become a second outer job model.
3. Plan linkage disappears after execution.

## Risk Assessment

### Low-Risk Areas

- new model/store/compile files

### Medium-Risk Areas

- interaction with sequence planning metadata
  - Mitigation: treat plans as a producer of sequence intent only

### High-Risk Areas

- scope creep into a large planning UI/editor
  - Mitigation: keep this PR data- and compiler-only

### Rollback Plan

Remove story-plan compiler/store integration while keeping sequence and
continuity layers intact.

## Tech Debt Analysis

### Tech Debt Removed

- absence of a manual planning layer above sequence jobs

### Tech Debt Intentionally Deferred

- story/shot planning UX
  - Owner: `PR-GUI-220`
- additional controller extraction around plan-oriented surfaces
  - Owner: `PR-CTRL-221`

## Documentation Updates

- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`

## Dependencies

### Internal

- sequence planning
- continuity linkage
- canonical result metadata

### External

- none

## Approval & Execution

Planner: ChatGPT/Codex planning surface
Executor: Copilot or Codex
Reviewer: Rob
Approval Status: Pending

## Next Steps

1. Execute `PR-VIDEO-219`.
2. Surface plan-origin UX in `PR-GUI-220`.
3. Finish GUI config/controller cleanup in `PR-CTRL-221`.
