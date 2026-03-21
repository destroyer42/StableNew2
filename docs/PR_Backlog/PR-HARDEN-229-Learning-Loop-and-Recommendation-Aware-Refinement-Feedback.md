# PR-HARDEN-229 - Learning Loop and Recommendation-Aware Refinement Feedback

Status: Completed 2026-03-20
Priority: HIGH
Effort: MEDIUM
Phase: Adaptive Refinement Evaluation and Tuning
Date: 2026-03-20

## Context & Motivation

### Current Repo Truth

After `PR-HARDEN-228`, StableNew can assess images, apply bounded refinement
behavior, and persist runtime provenance. The final missing layer is local
evaluation and recommendation-aware feedback.

### Specific Problem

The research memo correctly pointed toward learning integration, but it placed
that work before the runtime schema was stable. That would have produced brittle
records and noisy recommendation context.

### Why This PR Exists Now

This PR intentionally lands last so it can build on stable refinement metadata
instead of guessing at it.

### Reference

- `docs/Learning_System_Spec_v2.6.md`
- `docs/REFINEMENT_POLICY_SCHEMA_v1.md`
- `docs/PR_Backlog/ADAPTIVE_REFINEMENT_EXECUTABLE_ROADMAP_v2.6.md`

## Goals & Non-Goals

### Goals

1. Extend learning records with scalar refinement context and quality metrics.
2. Extend recommendation stratification with refinement-aware context.
3. Keep recommendations conservative and aligned with existing evidence tiers.
4. Preserve local-only storage and avoid large binary persistence.
5. Reuse the already-frozen canonical `adaptive_refinement` carrier instead of
   inventing learning-only field names that diverge from runtime provenance.

### Non-Goals

1. Do not implement automatic self-modifying policy tuning in this PR.
2. Do not store image crops, embeddings, or large binary payloads in learning
   records.
3. Do not add GUI automation in this PR.
4. Do not weaken current evidence-tier protections.

## Guardrails

1. Recommendations remain advisory unless the current evidence-tier rules already
   permit automation.
2. Refinement learning metadata must be scalar or short-string fields only.
3. Quality metrics must be cheap and local.
4. No network calls or external services may be introduced.
5. This PR must not add GUI exposure or hidden auto-enable behavior; the series
   remains dark-launched through learning integration.

## Allowed Files

### Files to Create

- `src/refinement/quality_metrics.py`: cheap local refinement-quality metrics
- `tests/refinement/test_quality_metrics.py`: metric coverage
- `tests/learning_v2/test_recommendation_engine_refinement_context.py`:
  recommendation stratification coverage

### Files to Modify

- `src/learning/learning_record_builder.py`: append refinement metadata to
  learning records
- `src/learning/recommendation_engine.py`: add refinement-aware query context
  and stratification
- `src/pipeline/pipeline_runner.py`: pass stable refinement learning context
  into record building
- `tests/learning/test_learning_record_builder.py`: record-builder assertions
- `tests/learning/test_learning_hooks_pipeline_runner.py`: runner learning-hook
  assertions
- `tests/learning_v2/test_recommendation_engine_guards.py`: guard assertions
  for sparse evidence
- `tests/learning_v2/test_recommendation_engine_evidence_tiering.py`:
  evidence-tier regression coverage
- `docs/Learning_System_Spec_v2.6.md`: document refinement-aware learning fields
- `docs/REFINEMENT_POLICY_SCHEMA_v1.md`: cross-reference the learning-facing
  fields

### Forbidden Files

- `src/controller/**`: no controller or GUI work
- `src/video/**`: no backend or video coupling
- `tests/gui_v2/**`: no GUI work

## Implementation Plan

### Step 1: Add cheap local refinement metrics

Required details:

- metric set must remain cheap and local
- v1 metric set should include:
  `face_detected`, `face_count`, `face_area_ratio`, `scale_band`, `pose_band`,
  `policy_id`, `detector_id`, `algorithm_version`
- if OpenCV is available, optionally compute a cheap sharpness metric such as
  Laplacian variance; otherwise return `None` rather than inventing a fallback
  crop artifact

Files:

- create `src/refinement/quality_metrics.py`
- create `tests/refinement/test_quality_metrics.py`

### Step 2: Extend the learning record builder

Required details:

- add refinement context under `LearningRecord.metadata`
- keep the added payload compact and scalar
- do not persist image crops or raw detector frames
- map the learning-facing fields directly from the canonical refinement carrier
  so runtime, manifest, embedded-metadata, diagnostics, and learning surfaces
  stay semantically aligned

Files:

- modify `src/learning/learning_record_builder.py`
- modify `src/pipeline/pipeline_runner.py`
- modify `tests/learning/test_learning_record_builder.py`
- modify `tests/learning/test_learning_hooks_pipeline_runner.py`

### Step 3: Extend recommendation stratification conservatively

Required details:

- add refinement-aware context keys without bypassing current evidence-tier
  logic
- keep adaptive-refinement recommendations manual-only until the existing
  recommendation engine already considers the evidence strong enough

Files:

- modify `src/learning/recommendation_engine.py`
- create `tests/learning_v2/test_recommendation_engine_refinement_context.py`
- modify `tests/learning_v2/test_recommendation_engine_guards.py`
- modify `tests/learning_v2/test_recommendation_engine_evidence_tiering.py`

### Step 4: Update the learning docs

Files:

- modify `docs/Learning_System_Spec_v2.6.md`
- modify `docs/REFINEMENT_POLICY_SCHEMA_v1.md`

## Testing Plan

### Unit Tests

- `tests/refinement/test_quality_metrics.py`
- `tests/learning/test_learning_record_builder.py`

### Integration Tests

- `tests/learning/test_learning_hooks_pipeline_runner.py`
- `tests/learning_v2/test_recommendation_engine_refinement_context.py`
- `tests/learning_v2/test_recommendation_engine_guards.py`
- `tests/learning_v2/test_recommendation_engine_evidence_tiering.py`

### Journey or Smoke Coverage

- one end-to-end path that produces a learning record from a refinement-enabled
  run

### Manual Verification

1. Execute a refinement-enabled run that produces a learning record.
2. Confirm the record contains only scalar refinement metadata.
3. Confirm recommendation outputs remain conservative when evidence is sparse.

Suggested command set:

- `pytest tests/refinement/test_quality_metrics.py tests/learning/test_learning_record_builder.py tests/learning/test_learning_hooks_pipeline_runner.py tests/learning_v2/test_recommendation_engine_refinement_context.py tests/learning_v2/test_recommendation_engine_guards.py tests/learning_v2/test_recommendation_engine_evidence_tiering.py -q`

## Verification Criteria

### Success Criteria

1. Learning records preserve compact refinement context.
2. Recommendation stratification understands refinement bands and policy ids.
3. Evidence-tier protections remain intact.
4. No image crops or large binary payloads are stored.
5. Learning uses the same stable refinement semantics already emitted by the
   runtime instead of inventing parallel names or derived meanings.

### Failure Criteria

1. The PR stores image crops or large binary artifacts in learning records.
2. Recommendation automation becomes more permissive without strong evidence.
3. Refinement context is too unstable or too large to replay safely.
4. Learning metadata forks the meaning or naming of refinement fields away from
   the runtime/manifest contract.

## Risk Assessment

### Low-Risk Areas

- metric helpers and scalar metadata additions

### Medium-Risk Areas With Mitigation

- recommendation-context growth
  - Mitigation: add focused tests around evidence-tier behavior and sparse-data
    guards

### High-Risk Areas With Mitigation

- overconfident or noisy recommendation output
  - Mitigation: preserve manual-only behavior unless the existing engine already
    considers the evidence strong enough

### Rollback Plan

Remove refinement-specific learning metadata and revert recommendation context to
the prior fields while keeping the runtime refinement feature intact.

## Critical Appraisal and Incorporated Corrections

1. Weakness: the research memo tried to connect learning before runtime schema
   stability. Incorporated correction: this PR lands last.
2. Weakness: the memo implied richer metrics without retention constraints.
   Incorporated correction: this PR stores scalar metrics only and forbids image
   crops.
3. Weakness: the memo pointed toward auto-tuning too quickly. Incorporated
   correction: this PR preserves current evidence-tier protections and keeps the
   new recommendations conservative.
4. Weakness: the memo did not explicitly require learning to reuse the same
   runtime refinement semantics.
   Incorporated correction: this PR requires learning fields to be mapped from
   the canonical `adaptive_refinement` carrier.

## Tech Debt Analysis

### Debt Removed

- missing local evaluation and recommendation context for adaptive refinement

### Debt Intentionally Deferred

- GUI surfacing of refinement recommendation context
  - Owner: future GUI follow-on after this series
- policy auto-tuning beyond existing recommendation tiers
  - Owner: future learning-specific planning work

## Documentation Updates

- update `docs/Learning_System_Spec_v2.6.md`
- update `docs/REFINEMENT_POLICY_SCHEMA_v1.md`
- update `docs/StableNew Roadmap v2.6.md` when the PR is complete so the tranche
  status stays current

## Dependencies

### Internal Module Dependencies

- `src/learning/learning_record_builder.py`
- `src/learning/recommendation_engine.py`
- stable refinement metadata from `PR-HARDEN-228`

### External Tools or Runtimes

- none; OpenCV remains optional even for metrics

## Approval & Execution

Planner: GitHub Copilot / ChatGPT planning surface
Executor: Copilot or Codex
Reviewer: Rob
Approval Status: Pending

## Next Steps

1. Execute `PR-HARDEN-229`.
2. Plan the first GUI-facing adaptive refinement controls only after this PR is
   stable.
