# PR-DOCS-050: Canonical Documentation Reconciliation

**Status**: Specification
**Priority**: HIGH
**Effort**: MEDIUM
**Phase**: Governance and Documentation Cleanup
**Date**: 2026-03-11

## Context & Motivation

### Problem Statement
Canonical docs currently contain active contradictions and stale references, including mismatches between the docs index, subsystem specs, and coding standards.

### Why This Matters
Documentation drift undermines governance. Agents and humans cannot reliably follow the canon if active documents disagree.

### Current Architecture
Examples:
- `docs/DOCS_INDEX_v2.6.md` still points Learning Tier 3 to `v2.5`
- `docs/Subsystems/Learning/Learning_System_Spec_v2.6.md` already exists
- `docs/StableNew_Coding_and_Testing_v2.6.md` mandates Pydantic everywhere, but the current codebase does not use it

### Reference
- `docs/DOCS_INDEX_v2.6.md`
- `docs/Subsystems/Learning/Learning_System_Spec_v2.6.md`
- `docs/StableNew_Coding_and_Testing_v2.6.md`
- `docs/GOVERNANCE_v2.6.md`
- `docs/D-ARCH-004-Codebase-Review-Top10-Issues-and-COAs.md`

## Goals & Non-Goals

### ✅ Goals
1. Remove active contradictions among canonical docs.
2. Establish a document ownership and precedence map for active canon.
3. Add a contradiction checklist for future doc-changing PRs.

### ❌ Non-Goals
1. Do not rewrite every historical document.
2. Do not archive large swaths of docs in this PR.
3. Do not change implementation behavior here.

## Allowed Files

### ✅ Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `docs/Canonical_Document_Ownership_v2.6.md` | ownership, precedence, and contradiction map | 120 |

### ✅ Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `docs/DOCS_INDEX_v2.6.md` | fix active canonical references | 40 |
| `docs/GOVERNANCE_v2.6.md` | clarify source-of-truth hierarchy and active doc names | 30 |
| `docs/StableNew_Coding_and_Testing_v2.6.md` | reconcile unrealistic/contradictory standards | 40 |
| `docs/Subsystems/Learning/Learning_System_Spec_v2.6.md` | ensure consistency with active index and recommendation policy language | 20 |
| `docs/PR_TEMPLATE_v2.6.md` | add a contradiction-check item if needed | 20 |

### ❌ Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| `src/**` | docs-only reconciliation PR |
| `tests/**` | docs-only reconciliation PR |

## Implementation Plan

### Step 1: Reconcile active canonical references
Fix the docs index and governance references so active subsystem specs point to the correct v2.6 documents.

### Step 2: Align standards with reality
Where canonical docs currently demand patterns that the repo does not actually enforce, rewrite them into realistic, enforceable standards or mark them as future-state.

### Step 3: Add ownership map
Create a short active-document ownership guide stating:
- canonical source
- subsystem owner
- archive status rules

### Step 4: Add contradiction checklist
Require doc-changing PRs to verify:
- no duplicate active source
- no stale version reference
- no implementation/doc contradiction introduced knowingly

## Testing Plan

### Unit Tests
- none

### Integration Tests
- none

### Journey Tests
- none

### Manual Testing
1. Read the docs index from top to bottom and confirm it no longer contradicts active subsystem docs.
2. Confirm the canonical hierarchy references only active documents.

## Verification Criteria

### ✅ Success Criteria
1. Active canonical docs no longer contradict one another on the reviewed points.
2. A document ownership map exists.
3. Future PRs have a clear contradiction-check path.

### ❌ Failure Criteria
- stale v2.5 references remain where v2.6 canon exists
- standards remain knowingly impossible to enforce

## Risk Assessment

### Low Risk Areas
✅ Documentation updates

### Medium Risk Areas
⚠️ Rewording standards that contributors relied on informally
- **Mitigation**: prefer clarifying enforceable reality over aspirational language

### High Risk Areas
❌ Introducing new contradictions
- **Mitigation**: review the full affected doc chain in one pass

### Rollback Plan
Revert the reconciliation PR and restore prior docs if a material governance mistake is found.

## Tech Debt Analysis

## Tech Debt Removed
✅ Reduces canonical contradiction debt
✅ Clarifies which docs are actually active

## Tech Debt Added
⚠️ None expected

**Net Tech Debt**: -2

## Architecture Alignment

### ✅ Enforces Architecture v2.6
This PR clarifies and protects the canon itself.

### ✅ Follows Testing Standards
Docs-only PR; validation is review-based.

### ✅ Maintains Separation of Concerns
No implementation changes.

## Dependencies

### External
- none

### Internal
- active canonical docs only

## Timeline & Effort

### Breakdown
| Task | Effort | Duration |
|------|--------|----------|
| contradiction audit | 0.5 day | Day 1 |
| doc edits | 0.5 day | Day 1 |
| ownership/checklist additions | 0.5 day | Day 2 |

**Total**: 1-2 days

## Approval & Sign-Off

**Planner**: Codex
**Executor**: Codex
**Reviewer**: Rob

**Approval Status**: Pending

## Next Steps

1. Reconcile active canonical documents.
2. Use the updated canon to guide the remaining cleanup PRs.
3. Continue with agent-instruction consolidation in PR-051.
