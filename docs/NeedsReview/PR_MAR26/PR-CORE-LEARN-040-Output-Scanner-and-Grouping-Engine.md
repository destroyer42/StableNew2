# PR-CORE-LEARN-040: Output Scanner and Grouping Engine

**Status**: Specification
**Priority**: HIGH
**Effort**: LARGE
**Phase**: Learning Recovery / Historical Review
**Date**: 2026-03-11

## Context & Motivation

### Problem Statement
StableNew needs a reliable way to scan historical outputs and convert comparable artifacts into discovered-review experiments.

### Why This Matters
This is the core value layer for the feature. If grouping is noisy or expensive, the resulting review workflow will be misleading or unusable.

### Current Architecture
`image_metadata.py` already resolves mixed metadata shapes. The scanner should build on that normalization instead of introducing another metadata parser.

### Reference
- `docs/D-LEARN-003-Auto-Discovered-Review-Experiments.md`
- `src/utils/image_metadata.py`
- `output/*/manifests/*.json`

## Goals & Non-Goals

### Goals
1. Scan manifests first, embedded metadata second.
2. Normalize artifacts into a canonical scan record.
3. Group artifacts by:
   - stage
   - normalized positive prompt
   - normalized negative prompt
   - input-lineage key
4. Require at least 3 artifacts and at least 1 meaningful varying parameter.
5. Persist discovered groups and incremental scan state.

### Non-Goals
1. No Learning UI yet.
2. No recommendation ingestion yet.
3. No queue/history schema changes.
4. No synchronous startup-only blocking scan requirement.

## Allowed Files

### Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `src/learning/output_scan_models.py` | Canonical normalized scan record models | 220 |
| `src/learning/output_scanner.py` | Manifest/image scanner | 320 |
| `src/learning/discovered_grouping.py` | Group-key and candidate grouping engine | 260 |
| `tests/learning_v2/test_output_scanner.py` | Scanner regressions | 260 |
| `tests/learning_v2/test_discovered_grouping.py` | Grouping contract tests | 240 |

### Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `src/utils/image_metadata.py` | Expose any needed normalization helpers without duplicating logic | 40 |
| `src/learning/discovered_review_store.py` | Persist scan results/groups | 80 |

### Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| `src/gui/*` | No UI in this PR |
| `src/pipeline/*` | No pipeline changes |
| `src/queue/*` | No queue changes |
| `src/controller/app_controller.py` | No controller wiring yet |

## Implementation Plan

### Step 1: Add canonical scan record
Normalize each artifact into a record containing:

- stage
- prompts
- model/VAE/sampler/scheduler
- numeric stage knobs
- output path
- manifest path
- input lineage key
- payload hash / dedupe key

### Step 2: Implement manifest-first scan
Scanner order:

1. manifests under `output/*/manifests/*.json`
2. fallback to embedded image metadata when manifest missing

### Step 3: Implement grouping contract
Group by:

- `stage`
- normalized positive prompt
- normalized negative prompt
- input-lineage key

Eligibility:

- `>= 3` artifacts
- at least one varying meaningful field

### Step 4: Persist groups + scan index
Write newly eligible groups to discovered-review store and update the scan index for incremental rescans.

## Testing Plan

### Unit Tests
- manifest normalization across multiple schema shapes
- prompt/stage/input-lineage grouping behavior
- seed-only groups rejected
- dedupe behavior

### Integration Tests
- scan a fixture output tree and persist resulting groups

### Journey Tests
- none in this PR

### Manual Testing
1. Point scanner at a real output subtree.
2. Confirm eligible groups are created.
3. Add new manifest files and confirm incremental scan only ingests new artifacts.

## Verification Criteria

### Success Criteria
1. Scanner produces deterministic normalized records.
2. Groups are not created for weak/seed-only comparisons.
3. Rescans are incremental and do not duplicate artifacts.

### Failure Criteria
- duplicated items in groups
- group eligibility based on seed-only variation
- grouping across different input lineages for image-based stages

## Risk Assessment

### Low Risk Areas
✅ Manifest-first scanning

### Medium Risk Areas
⚠️ Older manifest variability
- **Mitigation**: route through `image_metadata.py` normalization helpers

⚠️ Performance on large output trees
- **Mitigation**: scan index and manifest-first strategy

### High Risk Areas
❌ Incorrect grouping semantics
- **Mitigation**: explicit grouping-contract tests with real sample manifests

### Rollback Plan
Revert scanner/grouping/store integration without affecting Learning UI.

## Tech Debt Analysis

## Tech Debt Removed
✅ Centralizes manifest normalization instead of ad hoc historical parsing later

## Tech Debt Added
⚠️ None if normalization stays centralized

**Net Tech Debt**: -1

## Architecture Alignment

### Enforces Architecture v2.6
This PR is purely post-execution discovery logic.

### Follows Testing Standards
Adds normalization and grouping contract coverage.

### Maintains Separation of Concerns
Scanner/grouping are isolated from UI and controller concerns.

## Dependencies

### External
- none

### Internal
- `src/utils/image_metadata.py`
- `src/learning/discovered_review_store.py`

## Timeline & Effort

### Breakdown
| Task | Effort | Duration |
|------|--------|----------|
| Scan models + scanner | 1 day | Day 2 |
| Grouping engine | 1 day | Day 3 |
| Tests + store integration | 1 day | Day 3 |

**Total**: 2-3 days

## Approval & Sign-Off

**Planner**: Codex
**Executor**: Codex
**Reviewer**: Rob

**Approval Status**: Pending

## Next Steps

1. Implement scanner/grouping.
2. Integrate Learning UI inbox in PR-041.

