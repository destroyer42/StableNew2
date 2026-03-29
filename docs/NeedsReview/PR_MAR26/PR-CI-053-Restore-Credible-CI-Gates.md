# PR-CI-053: Restore Credible CI Gates

**Status**: Specification
**Priority**: HIGH
**Effort**: MEDIUM
**Phase**: CI Stabilization
**Date**: 2026-03-11

## Context & Motivation

### Problem Statement
The main CI workflow currently masks lint and test failures with `|| true`, making green CI an unreliable signal.

### Why This Matters
A CI system that cannot fail on real defects cannot enforce governance, testing, or architectural discipline.

### Current Architecture
In `.github/workflows/ci.yml`:
- Ruff failures are masked
- pytest failures are masked

### Reference
- `.github/workflows/ci.yml`
- `docs/GOVERNANCE_v2.6.md`
- `docs/StableNew_Coding_and_Testing_v2.6.md`
- `docs/D-ARCH-004-Codebase-Review-Top10-Issues-and-COAs.md`

## Goals & Non-Goals

### ✅ Goals
1. Remove silent pass-through from required CI gates.
2. Split fast required gates from broader optional coverage where needed.
3. Replace invisible failure masking with explicit quarantine/tracking.

### ❌ Non-Goals
1. Do not make the full suite required immediately if it is not stable.
2. Do not fix unrelated flaky tests in this PR.
3. Do not redesign the app to satisfy CI.

## Allowed Files

### ✅ Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `.github/workflows/ci.yml` | remove masking and split required vs optional jobs | 60 |
| `.github/workflows/journey-tests.yml` | align optional/full coverage strategy if needed | 20 |
| `.github/workflows/journeys_shutdown.yml` | align naming/optional behavior if needed | 20 |
| `docs/StableNew_Coding_and_Testing_v2.6.md` | document required CI gate expectations | 20 |
| `tests/TEST_SURFACE_MANIFEST.md` | reference CI-required subsets if produced by PR-052 | 10 |

### ❌ Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| `src/**` | CI-policy-only PR |
| `tests/**` except manifest references | test fixes belong elsewhere |

## Implementation Plan

### Step 1: Define required gate subset
Select a stable minimum:
- compile/import sanity
- lint
- selected deterministic tests

### Step 2: Remove masking from required gates
Delete `|| true` from the required jobs.

### Step 3: Separate broader coverage
If full coverage is not ready as required, run it as non-blocking but visible, with explicit naming and artifact output.

### Step 4: Document enforcement policy
Update canonical testing docs to describe what must pass before merge.

## Testing Plan

### Unit Tests
- none

### Integration Tests
- validate workflow syntax and dry-run behavior where practical

### Journey Tests
- ensure journey workflows still run independently

### Manual Testing
1. Trigger CI on a branch with a known failing test and confirm CI fails.
2. Trigger CI on a clean branch and confirm required jobs pass.

## Verification Criteria

### ✅ Success Criteria
1. Required CI jobs fail on real lint/test failures.
2. Optional broader jobs remain visible, not silently swallowed.
3. CI policy is documented.

### ❌ Failure Criteria
- required CI still passes with failing tests
- broad coverage remains silently non-blocking without explanation

## Risk Assessment

### Low Risk Areas
✅ Removing obvious failure masking

### Medium Risk Areas
⚠️ Existing flaky tests
- **Mitigation**: restrict the required gate to a stable subset initially

### High Risk Areas
❌ Branches go red immediately due to hidden debt
- **Mitigation**: coordinate with PR-052 test-surface classification first

### Rollback Plan
Restore the prior CI workflow temporarily if the required subset was chosen incorrectly, then tighten again with corrected scope.

## Tech Debt Analysis

## Tech Debt Removed
✅ Restores trust in CI
✅ Makes failure states explicit

## Tech Debt Added
⚠️ None expected if optional/full jobs are clearly separated

**Net Tech Debt**: -2

## Architecture Alignment

### ✅ Enforces Architecture v2.6
Supports the governance requirement that tests and quality gates are meaningful.

### ✅ Follows Testing Standards
Turns documented expectations into real enforcement.

### ✅ Maintains Separation of Concerns
CI policy only; no runtime changes.

## Dependencies

### External
- GitHub Actions

### Internal
- `.github/workflows/ci.yml`
- `docs/StableNew_Coding_and_Testing_v2.6.md`
- test-surface manifest from PR-052

## Timeline & Effort

### Breakdown
| Task | Effort | Duration |
|------|--------|----------|
| required subset selection | 0.5 day | Day 1 |
| workflow update | 0.5 day | Day 1 |
| validation and docs | 0.5 day | Day 2 |

**Total**: 1-2 days

## Approval & Sign-Off

**Planner**: Codex
**Executor**: Codex
**Reviewer**: Rob

**Approval Status**: Pending

## Next Steps

1. Normalize the test surface in PR-052.
2. Remove CI masking and define required gates.
3. Use green CI as a real merge signal again.
