# PR-GUI-PS6-001: PySide6 Migration Governance + Readiness Gates

**Status**: Implemented
**Priority**: HIGH
**Effort**: SMALL (1-2 days)
**Phase**: PySide6 Migration
**Date**: 2026-03-09
**Implementation Date**: 2026-03-09

## Context & Motivation

### Problem Statement
Migration has no explicit readiness gates, rollback triggers, or anti-mixed-runtime policy.

### Why This Matters
Without gates, migration can drift and destabilize v2.6 runtime behavior.

### Current Architecture
Tk GUI V2 hosts controller/state; execution path is canonical and must stay unchanged.

### Reference
- docs/ARCHITECTURE_v2.6.md
- docs/StableNew_Coding_and_Testing_v2.6.md
- docs/PR_TEMPLATE_v2.6.md

## Goals & Non-Goals

### ? Goals
1. Define migration governance and gate criteria.
2. Define rollback triggers and release criteria.
3. Document no-mixed-runtime policy.

### ? Non-Goals
1. No GUI behavior/code migration in this PR.
2. No dependency changes.

## Allowed Files

### ? Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| docs/PR_MAR26/PR-GUI-PS6-001-PySide6-Governance-and-Gates.md | PR spec + implementation summary | 220 |

### ? Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| docs/ARCHITECTURE_v2.6.md | add toolkit-host boundary + gate references | 40 |
| docs/StableNew_Coding_and_Testing_v2.6.md | add migration testing gate policy | 35 |
| docs/DOCS_INDEX_v2.6.md | index migration docs | 15 |

### ? Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| src/pipeline/** | Execution architecture must not change |
| src/queue/** | Out of scope |
| src/controller/** | Out of scope for governance-only PR |

## Implementation Plan

### Step 1: Add Governance Sections
Add sections describing migration gates, anti-drift constraints, and rollback triggers.

### Step 2: Add Testing Gate Policy
Require parity test matrix + GP suite for each migration PR.

### Step 3: Document Index Updates
Ensure docs index references this migration program.

## Testing Plan

### Unit Tests
None.

### Integration Tests
Run GP suite as regression baseline.

### Journey Tests
N/A.

### Manual Testing
Review docs for consistency and contradictions.

## Verification Criteria

### ? Success Criteria
1. Governance + testing gate sections are present in canonical docs.
2. No source-code behavior changes.
3. GP suite remains green.

### ? Failure Criteria
Any ambiguity that allows mixed-runtime mainline behavior.

## Risk Assessment

### Low Risk Areas
? Docs updates only.

### Medium Risk Areas
?? Contradictory wording across canonical docs.
- **Mitigation**: cross-doc consistency pass.

### High Risk Areas
? None.

### Rollback Plan
Revert modified docs files.

## Tech Debt Analysis

## Tech Debt Removed
? Lack of explicit migration governance.

## Tech Debt Added
?? None.

**Net Tech Debt**: -1

## Architecture Alignment

### ? Enforces Architecture v2.6
Keeps runtime pipeline untouched and formalizes GUI host boundaries.

### ? Follows Testing Standards
Requires GP regression checks per migration PR.

### ? Maintains Separation of Concerns
Docs only.

## Dependencies

### External
None.

### Internal
Canonical docs only.

## Timeline & Effort

### Breakdown
| Task | Effort | Duration |
|------|--------|----------|
| Governance updates | 2h | same day |
| Consistency pass | 1h | same day |
| Validation | 1h | same day |

**Total**: ~4h

## Approval & Sign-Off

**Planner**: Codex
**Executor**: Codex
**Reviewer**: Rob

**Approval Status**: Pending

## Next Steps

1. Execute PR-PS6-002 (contract extraction completion).
2. Execute PR-PS6-003 (dispatcher abstraction).

## Implementation Summary

**Implementation Date**: 2026-03-09
**Executor**: Codex
**Status**: COMPLETE

### What Was Implemented
1. Added a PySide6 migration governance addendum to `docs/ARCHITECTURE_v2.6.md`.
2. Added migration testing gates to `docs/StableNew_Coding_and_Testing_v2.6.md`.
3. Indexed PySide6 migration program docs in `docs/DOCS_INDEX_v2.6.md`.

### Verification
1. `pytest -q tests/integration/test_golden_path_suite_v2_6.py`
