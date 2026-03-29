# PR-CLEANUP-LEARN-045: Runtime Artifact Version Control Hygiene

**Status**: Specification
**Priority**: HIGH
**Effort**: SMALL
**Phase**: Post-Learning Recovery Review
**Date**: 2026-03-11

## Context & Motivation

### Problem Statement
Recent commits merged mutable runtime artifacts and user-local state into `main`, including Learning experiment session files, Photo Optomize assets, and UI state JSON. These are not stable fixtures and should not be versioned.

### Why This Matters
Tracked runtime artifacts create merge churn, leak user-local content, and make tests/reviews harder because repository state becomes polluted by transient data. This also increases the chance of accidental regressions caused by stale local state being treated as canonical.

### Current Architecture
The application persists session/runtime data under `data/learning/experiments`, `data/photo_optimize/assets`, and `state/*.json`, but [`.gitignore`](c:/Users/rob/projects/StableNew/.gitignore) does not currently exclude all of these newer mutable roots.

### Reference
- `.gitignore`
- `data/learning/experiments/`
- `data/photo_optimize/assets/`
- `state/ui_state.json`
- `docs/PR_MAR26/PR-CLEANUP-LEARN-038-Tech-Debt-Removal-and-Contract-Cleanup.md`

## Goals & Non-Goals

### ✅ Goals
1. Stop versioning mutable runtime/session artifacts that should remain local.
2. Preserve any intentionally needed sample data by moving it into explicit fixtures or docs examples.
3. Ensure future PRs cannot accidentally reintroduce these artifacts easily.
4. Leave runtime paths unchanged so application behavior does not regress.

### ❌ Non-Goals
1. Do not redesign storage locations in this PR.
2. Do not change how Learning or Photo Optomize persist at runtime.
3. Do not alter output/manifest generation behavior.
4. Do not migrate old user-local data automatically.

## Allowed Files

### ✅ Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `tests/fixtures/README_runtime_artifacts.md` | Document what belongs in fixtures vs runtime data | 40 |

### ✅ Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `.gitignore` | Ignore mutable runtime/session artifact roots | 20 |
| `docs/StableNew_Coding_and_Testing_v2.6.md` | Clarify that runtime artifacts must not be committed | 20 |
| `docs/DOCS_INDEX_v2.6.md` | Index any new hygiene note if needed | 10 |

### ✅ Files to Remove From Version Control
| Path Pattern | Reason |
|--------------|--------|
| `data/learning/experiments/**` | Mutable session/runtime data |
| `data/photo_optimize/assets/**` | User-local imported/generated photo assets |
| `state/ui_state.json` | Mutable local UI state |
| other mutable `state/*.json` files if they are not intentionally shared fixtures | Repo hygiene |

### ❌ Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| `src/**` | No runtime logic changes are allowed in this cleanup PR |
| `tests/**` except explicit fixture docs | Do not rewrite tests while doing repo hygiene |
| `output/**` | Already ignored; out of scope |

## Implementation Plan

### Step 1: Classify runtime vs fixture data
Audit currently tracked files under:
- `data/learning/experiments`
- `data/photo_optimize/assets`
- `state/`

Decide which files are true runtime artifacts and which, if any, should be preserved as explicit fixtures.

**Modify**:
- none yet

### Step 2: Harden ignore rules
Update `.gitignore` so these runtime/session roots are ignored going forward.

Be explicit rather than broad. Ignore mutable data roots, not all `data/**`.

**Modify**:
- `.gitignore`

### Step 3: Remove tracked runtime artifacts from version control
Remove the tracked mutable files from the repository while preserving them locally where appropriate.

Important:
- this is a repository hygiene operation, not a deletion of user data
- if any sample file is genuinely needed for tests/docs, move it to an explicit fixture/example location before removal

**Modify**:
- repository index state only

### Step 4: Document the rule
Add a short explicit rule to canonical docs: runtime/session data must not be committed unless promoted to a named fixture/example asset with a clear purpose.

**Modify**:
- `docs/StableNew_Coding_and_Testing_v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`

## Testing Plan

### Unit Tests
- none

### Integration Tests
- none required for logic

### Journey Tests
- none

### Manual Testing
1. Launch the app and confirm Learning/Photo Optomize still create and use local runtime data normally.
2. Confirm git status stays clean after normal runtime activity except for intentionally local ignored files.
3. Confirm no required test fixture was accidentally removed.

## Verification Criteria

### ✅ Success Criteria
1. Mutable runtime/session artifacts are no longer tracked in git.
2. `.gitignore` prevents those artifacts from reappearing in normal workflows.
3. No production runtime path changes are required.
4. No tests/docs lose needed fixture coverage.

### ❌ Failure Criteria
- runtime data still appears as tracked changes after normal use
- needed sample data is removed without replacement
- source code changes sneak into this cleanup PR

## Risk Assessment

### Low Risk Areas
✅ `.gitignore` updates: isolated and reversible

### Medium Risk Areas
⚠️ Removing tracked files that may have been implicitly relied upon
- **Mitigation**: explicitly verify whether each tracked file is runtime-only or fixture-worthy before removal

### High Risk Areas
❌ Accidental fixture loss
- **Mitigation**: move any genuinely needed samples into `tests/fixtures` or `docs/examples` before cleanup

### Rollback Plan
Restore the removed tracked files from the cleanup commit if any were incorrectly classified, then re-run with narrower ignore rules.

## Tech Debt Analysis

## Tech Debt Removed
✅ Removes repository pollution from user-local sessions and generated artifacts
✅ Establishes a clearer boundary between runtime data and fixtures

## Tech Debt Added
⚠️ None expected

**Net Tech Debt**: -2

## Architecture Alignment

### ✅ Enforces Architecture v2.6
This PR does not alter execution architecture; it cleans repository hygiene around runtime persistence.

### ✅ Follows Testing Standards
Protects determinism by keeping transient state out of version control.

### ✅ Maintains Separation of Concerns
Runtime persistence remains a runtime concern, not a source-controlled artifact set.

## Dependencies

### External
- none

### Internal
- `.gitignore`
- `docs/StableNew_Coding_and_Testing_v2.6.md`

## Timeline & Effort

### Breakdown
| Task | Effort | Duration |
|------|--------|----------|
| Audit tracked artifacts | 0.25 day | Day 1 |
| Ignore rule update + cleanup | 0.25 day | Day 1 |
| Documentation update | 0.25 day | Day 1 |

**Total**: 0.5-1 day

## Approval & Sign-Off

**Planner**: Codex
**Executor**: Codex
**Reviewer**: Rob

**Approval Status**: Pending

## Next Steps

1. Clean tracked runtime/session artifacts from the repo.
2. Verify the app still persists locally as expected.
3. Continue with rating-detail analytics integration in PR-CORE-LEARN-046.
