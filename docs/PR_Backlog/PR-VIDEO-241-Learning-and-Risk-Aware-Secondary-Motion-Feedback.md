# PR-VIDEO-241 - Learning and Risk-Aware Secondary Motion Feedback

Status: Specification
Priority: HIGH
Effort: MEDIUM
Phase: Secondary Motion Learning Closure
Date: 2026-03-20

## Context & Motivation

### Current Repo Truth

After `PR-VIDEO-240`, StableNew can plan and apply the shared secondary-motion
layer across the three current video backends. The remaining gap is learning and
recommendation closure: the feature will be replayable, but not yet analyzable
or tunable through the repo's existing local learning surfaces.

### Specific Problem

If motion summaries are not folded into learning, the repo will gain a new
runtime capability with no evidence loop. But if learning naively stores raw
frames, masks, or dense motion fields, it will bloat storage, weaken privacy,
and make recommendations compare incomparable backend behaviors.

### Why This PR Exists Now

This PR closes the tranche by making motion outcomes visible to learning and
recommendations without weakening the repo's existing evidence-tier and
bounded-storage rules.

### Reference

- `docs/ARCHITECTURE_v2.6.md`
- `docs/Learning_System_Spec_v2.6.md`
- `docs/PR_Backlog/SECONDARY_MOTION_EXECUTABLE_ROADMAP_v2.6.md`
- `docs/PR_Backlog/PR-VIDEO-240-Workflow-Video-Secondary-Motion-Parity-and-Replay-Closure.md`

## Goals & Non-Goals

### Goals

1. Add a scalar-only motion-metrics helper for learning and recommendation use.
2. Extend learning record building so canonical motion intent, policy,
   application path, skip reason, and scalar metrics are persisted.
3. Extend recommendation logic so it stratifies motion evidence by backend and
   application path instead of mixing incomparable results.
4. Preserve the repo's existing evidence-tier safeguards and avoid automatic
   self-modifying behavior.

### Non-Goals

1. Do not change runtime motion application in this PR.
2. Do not store raw frames, masks, optical-flow fields, or other binary motion
   payloads in centralized learning storage.
3. Do not add automatic policy tuning or self-applied recommendation changes in
   this PR.
4. Do not add GUI review surfaces in this PR.

## Guardrails

1. Learning must consume canonical result metadata and manifests only, not live
   backend objects.
2. Persist scalar metrics, ids, and bounded summaries only.
3. Recommendation logic must stratify at least by `backend_id`,
   `application_path`, `policy_id`, and skip/apply state.
4. Skipped or unavailable motion runs may inform diagnostics, but they must not
   be treated as positive evidence for policy tuning.
5. Existing evidence-tier safeguards remain in force.

## Allowed Files

### Files to Create

| File | Purpose |
| ------ | ------- |
| `src/video/motion/secondary_motion_metrics.py` | Scalar metrics normalizer/helper |
| `tests/learning/test_secondary_motion_metrics.py` | Metrics-helper coverage |
| `tests/learning/test_learning_record_builder_secondary_motion.py` | Focused learning-record coverage |
| `tests/learning/test_recommendation_engine_secondary_motion.py` | Focused recommendation coverage |

### Files to Modify

| File | Reason |
| ------ | ------ |
| `src/learning/learning_record_builder.py` | Persist canonical motion learning summaries |
| `src/learning/recommendation_engine.py` | Stratify recommendations by backend/application path |
| `tests/learning/test_learning_record_builder.py` | Base learning-record assertions |
| `tests/learning/test_recommendation_engine_v2.py` | Base recommendation assertions |
| `tests/learning/test_learning_hooks_pipeline_runner.py` | Pipeline learning-hook coverage |
| `docs/SECONDARY_MOTION_POLICY_SCHEMA_v1.md` | Document learning-summary shape |

### Forbidden Files

| File/Directory | Reason |
| ---------------- | ------ |
| `src/pipeline/executor.py` | No runtime behavior changes |
| `src/video/animatediff_backend.py` | No backend behavior changes |
| `src/video/svd_native_backend.py` | No backend behavior changes |
| `src/video/comfy_workflow_backend.py` | No backend behavior changes |
| `src/gui/**` | No GUI work |
| `src/controller/**` | No controller work |

## Implementation Plan

### Step 1: Add a scalar metrics helper

Create a helper that normalizes canonical motion summaries into bounded scalar
learning inputs.

Required details:

- accept canonical motion summary payloads from result metadata or manifests
- output a scalar-only bundle suitable for learning storage
- include at least: `applied_motion_strength`, `frame_count_delta`,
  `quality_risk_score`, and any existing shared-engine scalar metrics that are
  stable across backends
- preserve `backend_id`, `application_path`, `policy_id`, and skip status as
  categorical context

Files:

- create `src/video/motion/secondary_motion_metrics.py`
- create `tests/learning/test_secondary_motion_metrics.py`

### Step 2: Extend learning-record building

Persist canonical motion context into learning records.

Required details:

- read from canonical result metadata and/or manifest payloads only
- store user intent, derived policy id, backend id, application path, skip
  reason, and scalar metrics
- do not store raw frame lists, masks, or dense motion fields

Files:

- modify `src/learning/learning_record_builder.py`
- modify `tests/learning/test_learning_record_builder.py`
- create `tests/learning/test_learning_record_builder_secondary_motion.py`

### Step 3: Stratify recommendation logic

Prevent the recommendation engine from comparing incompatible motion runs as if
they were the same evidence class.

Required details:

- stratify at least by `backend_id`, `application_path`, and `policy_id`
- treat skipped/unavailable runs as diagnostic context, not positive tuning
  evidence
- preserve existing evidence-tier thresholds and conservative rollout behavior

Files:

- modify `src/learning/recommendation_engine.py`
- modify `tests/learning/test_recommendation_engine_v2.py`
- create `tests/learning/test_recommendation_engine_secondary_motion.py`

### Step 4: Cover pipeline learning hooks and document the final shape

Ensure the new learning summaries are visible through the existing pipeline
learning hooks and freeze the learning-shape appendix in docs.

Files:

- modify `tests/learning/test_learning_hooks_pipeline_runner.py`
- modify `docs/SECONDARY_MOTION_POLICY_SCHEMA_v1.md`

## Testing Plan

### Unit Tests

- `tests/learning/test_secondary_motion_metrics.py`
- `tests/learning/test_learning_record_builder_secondary_motion.py`
- `tests/learning/test_recommendation_engine_secondary_motion.py`
- `tests/learning/test_learning_record_builder.py`
- `tests/learning/test_recommendation_engine_v2.py`

### Integration Tests

- `tests/learning/test_learning_hooks_pipeline_runner.py`

### Journey or Smoke Coverage

- none in this PR

### Manual Verification

1. Execute representative SVD, AnimateDiff, and workflow-video runs with motion
   applied and skipped states.
2. Confirm the learning record stores only scalar motion metrics and categorical
   context.
3. Confirm recommendation grouping keeps backend/application-path cohorts
   separate.

Suggested command set:

- `pytest tests/learning/test_secondary_motion_metrics.py tests/learning/test_learning_record_builder_secondary_motion.py tests/learning/test_recommendation_engine_secondary_motion.py tests/learning/test_learning_record_builder.py tests/learning/test_recommendation_engine_v2.py tests/learning/test_learning_hooks_pipeline_runner.py -q`

## Verification Criteria

### Success Criteria

1. Learning records preserve canonical motion intent and scalar outcome context.
2. Recommendation logic stratifies by backend and application path.
3. No raw frame-level or dense motion payloads are persisted into centralized
   learning storage.
4. Existing evidence-tier safeguards remain intact.

### Failure Criteria

1. Learning depends on transient backend objects instead of canonical persisted
   summaries.
2. Raw frame or dense motion payloads are stored centrally.
3. Recommendation logic mixes skipped and applied runs as identical evidence.
4. The PR adds automatic self-applying motion tuning.

## Risk Assessment

### Low-Risk Areas

- scalar metrics-helper additions

### Medium-Risk Areas with Mitigation

- learning-record schema expansion
  - Mitigation: keep the new data nested and bounded, with focused tests

### High-Risk Areas with Mitigation

- recommendation drift caused by backend-incomparable evidence
  - Mitigation: require backend/application-path stratification before any
    motion recommendation is considered valid

### Rollback Plan

Remove the motion-learning additions while leaving runtime motion behavior and
provenance intact.

## Tech Debt Analysis

### Debt Removed

- absence of a learning loop for the shared motion carrier
- risk that motion recommendations would be based on incomparable backend runs

### Debt Intentionally Deferred

- automatic motion tuning
  - Owner: follow-on PR after empirical learning data exists
- GUI review surfaces for motion diagnostics
  - Owner: follow-on GUI/learning PR after runtime tranche closure

## Documentation Updates

- `docs/SECONDARY_MOTION_POLICY_SCHEMA_v1.md`
- completion-status updates in:
  - `docs/StableNew Roadmap v2.6.md`
  - `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`

## Dependencies

### Internal Module Dependencies

- `PR-VIDEO-236` through `PR-VIDEO-240`
- existing learning record builder and recommendation engine

### External Tools or Runtimes

- none

## Approval & Execution

Planner: GitHub Copilot
Executor: Codex or Copilot
Reviewer: Human + architecture review
Approval Status: Pending

## Next Steps

1. follow-on GUI exposure planning after runtime tranche closure
2. follow-on workflow-native and prompt/native-bias motion planning after real-world evidence exists
