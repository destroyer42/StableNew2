# PR-TEST-052: Test Suite Normalization and Collection Audit

**Status**: Specification
**Priority**: HIGH
**Effort**: MEDIUM
**Phase**: Test Infrastructure Stabilization
**Date**: 2026-03-11

## Context & Motivation

### Problem Statement
The test suite is fragmented across canonical test directories, ignored directories, and root-level ad hoc files that pytest does not collect by default.

### Why This Matters
The effective test surface is unclear, which weakens confidence in regression detection and makes CI signals hard to interpret.

### Current Architecture
Examples:
- `pytest.ini` collects only `tests/`
- root-level `test_*.py` files are outside that surface
- `tests/gui/` is ignored in default pytest config

### Reference
- `pytest.ini`
- root-level `test_*.py`
- `docs/StableNew_Coding_and_Testing_v2.6.md`
- `docs/D-ARCH-004-Codebase-Review-Top10-Issues-and-COAs.md`

## Goals & Non-Goals

### ✅ Goals
1. Classify the entire current test surface into active, quarantine, and archive.
2. Move active tests into canonical locations under `tests/`.
3. Replace silent ignore behavior with explicit quarantine/tracking where needed.
4. Document the intended test hierarchy as it actually exists.

### ❌ Non-Goals
1. Do not fix every flaky test in this PR.
2. Do not rewrite large bodies of test logic unnecessarily.
3. Do not couple this PR to CI enforcement changes beyond preparing for PR-053.

## Allowed Files

### ✅ Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `tests/TEST_SURFACE_MANIFEST.md` | classify active/quarantine/archive test areas | 140 |
| `tests/quarantine/README.md` | explain quarantine rules and exit criteria | 60 |

### ✅ Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `pytest.ini` | replace broad ignores with explicit comments/markers where appropriate | 30 |
| active root-level `test_*.py` files | move into canonical test locations or mark for archive/quarantine | 200 |
| `docs/StableNew_Coding_and_Testing_v2.6.md` | reconcile documented test hierarchy with actual collected structure | 30 |
| `docs/DOCS_INDEX_v2.6.md` | add test-surface manifest if treated as active operator reference | 10 |

### ❌ Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| `src/**` | test-infrastructure-only PR |
| `.github/workflows/**` | CI policy handled in PR-053 |

## Implementation Plan

### Step 1: Audit current test surface
Catalog:
- collected tests
- ignored tests
- root-level tests
- likely obsolete tests

### Step 2: Classify by status
Mark each test area/file as:
- active
- quarantine
- archive candidate

### Step 3: Normalize active tests
Move or rename active tests into canonical `tests/` locations.

### Step 4: Make ignores explicit
If any test area remains excluded, document exactly why and where it will be reintroduced.

## Testing Plan

### Unit Tests
- none

### Integration Tests
- run a collection-only audit and selected normalized suites

### Journey Tests
- none required for this PR

### Manual Testing
1. Run `pytest --collect-only`.
2. Verify active root tests are either moved or explicitly classified.
3. Confirm ignored areas are documented, not silently forgotten.

## Verification Criteria

### ✅ Success Criteria
1. The active test surface is explicitly documented.
2. Active tests no longer live uncollected at repo root.
3. Remaining exclusions are intentional and documented.

### ❌ Failure Criteria
- root test sprawl remains undocumented
- broad ignores remain unexplained

## Risk Assessment

### Low Risk Areas
✅ Manifest/documentation work

### Medium Risk Areas
⚠️ Moving tests without changing behavior
- **Mitigation**: keep moves mechanical and avoid logic edits unless required

### High Risk Areas
❌ Accidentally reactivating unstable tests without quarantine handling
- **Mitigation**: classify first, reactivate later

### Rollback Plan
Restore prior test locations and pytest config if collection changes prove too disruptive.

## Tech Debt Analysis

## Tech Debt Removed
✅ Makes the effective test surface visible
✅ Reduces silent untested areas

## Tech Debt Added
⚠️ Temporary quarantine manifest maintenance

**Net Tech Debt**: -1

## Architecture Alignment

### ✅ Enforces Architecture v2.6
Improves validation discipline without changing runtime behavior.

### ✅ Follows Testing Standards
Directly strengthens the test hierarchy and collection model.

### ✅ Maintains Separation of Concerns
Test infrastructure only.

## Dependencies

### External
- none

### Internal
- `pytest.ini`
- `tests/`
- `docs/StableNew_Coding_and_Testing_v2.6.md`

## Timeline & Effort

### Breakdown
| Task | Effort | Duration |
|------|--------|----------|
| audit and classification | 1 day | Day 1 |
| move/normalize active tests | 1-2 days | Days 2-3 |
| docs and cleanup | 0.5 day | Day 3 |

**Total**: 2-3 days

## Approval & Sign-Off

**Planner**: Codex
**Executor**: Codex
**Reviewer**: Rob

**Approval Status**: Pending

## Next Steps

1. Audit and classify the full test surface.
2. Normalize active tests.
3. Use the resulting manifest to harden CI in PR-053.
