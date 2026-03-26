# PR-TEST-280 - Full-Suite Collection Recovery and Test Hygiene

Status: Specification
Priority: HIGH
Effort: SMALL
Phase: Post-UX / Test Trust Recovery
Date: 2026-03-26

## Context & Motivation

### Current Repo Truth

Targeted regression suites for pipeline, video, learning, review, and most GUI
surfaces are currently green, but the full test suite cannot be collected.

`pytest --collect-only -q` currently fails with an import-file mismatch because
two test modules share the same basename:

- `tests/refinement/test_prompt_intent_analyzer.py`
- `tests/unit/test_prompt_intent_analyzer.py`

### Specific Problem

The branch cannot claim trustworthy regression status while full pytest
collection is broken. This failure is not a stale test. It is a real test-suite
hygiene defect.

### Why This PR Exists Now

`D-016` identified test trust restoration as the highest-value immediate next
step. Without successful suite collection, every later branch review remains
partially compromised.

### Reference

- `docs/ARCHITECTURE_v2.6.md`
- `docs/GOVERNANCE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/Research Reports/D-016-Branch-Review-Since-2026-03-22-2205.md`

## Goals & Non-Goals

### Goals

1. Restore successful `pytest --collect-only -q`.
2. Remove the duplicate module-name collision around prompt-intent-analyzer
   tests.
3. Leave both prompt-intent-analyzer test surfaces intact if they cover
   materially different behavior.
4. Add one focused regression guard so future duplicate-basename collisions are
   less likely.

### Non-Goals

1. Do not rewrite prompt-intent-analyzer runtime behavior in this PR.
2. Do not refactor the prompting/refinement architecture in this PR.
3. Do not merge unrelated stale-test cleanup into this PR.
4. Do not widen this into a full test-suite modernization sweep.

## Guardrails

1. Preserve the canonical `PromptPack -> Builder -> NJR -> Queue -> Runner`
   architecture untouched.
2. No runtime execution-path files may change unless they are required for test
   import or naming hygiene, which is not currently expected.
3. NJR, queue, runner, and GUI runtime contracts are out of scope.
4. If a test is renamed or moved, preserve its behavioral intent rather than
   silently deleting coverage.

## Allowed Files

### Files to Create

| File | Purpose |
| ------ | ------- |
| `tests/**/test_*prompt_intent_analyzer*_*.py` | Replacement file if rename-by-create is cleaner than in-place move |

### Files to Modify

| File | Reason |
| ------ | ------ |
| `tests/refinement/test_prompt_intent_analyzer.py` | Rename or adjust to eliminate module collision |
| `tests/unit/test_prompt_intent_analyzer.py` | Rename or adjust to eliminate module collision |
| `pytest.ini` | Only if a minimal collection-safe naming or import-mode adjustment is genuinely required |
| `docs/Research Reports/D-016-Branch-Review-Since-2026-03-22-2205.md` | Optional note if the exact remediation differs materially from the discovery assumption |

### Forbidden Files

| File/Directory | Reason |
| ---------------- | ------ |
| `src/**` | No runtime changes belong in this PR |
| `docs/StableNew Roadmap v2.6.md` | Not a docs-harmonization PR |
| `docs/ARCHITECTURE_v2.6.md` | No architecture changes |
| `src/pipeline/**` | No pipeline/runtime changes |
| `src/gui/**` | No GUI work |

## Implementation Plan

### Step 1: Reproduce and document the collection failure

Confirm the current failure mode and capture the exact duplicate-basename
collision.

Files:

- modify no files unless a tiny test comment is warranted later

Tests:

- run `pytest --collect-only -q`

### Step 2: Remove the duplicate module-name collision

Rename one or both prompt-intent-analyzer test files so pytest no longer
imports them under the same module name.

Required details:

- preserve both behavioral scopes if both are still valuable
- prefer a filename-level fix over global pytest import-mode churn
- avoid deleting coverage unless the two files are actually redundant

Files:

- modify `tests/refinement/test_prompt_intent_analyzer.py`
- modify `tests/unit/test_prompt_intent_analyzer.py`
- create a renamed replacement test file if needed

Tests:

- rerun `pytest --collect-only -q`

### Step 3: Add a focused hygiene guard

If practical, add a small test or repo-local convention note that reduces the
chance of future duplicate test basenames in high-value directories.

Files:

- modify `pytest.ini` only if absolutely necessary
- otherwise keep the guard local to test-file naming/comments

Tests:

- rerun `pytest --collect-only -q`
- run the affected prompt-intent-analyzer tests directly

## Testing Plan

### Unit Tests

- `pytest tests/refinement -q`
- `pytest tests/unit -q`

### Integration Tests

- none beyond collection verification

### Journey or Smoke Coverage

- `pytest --collect-only -q`

### Manual Verification

1. Confirm collection completes without import-file mismatch errors.
2. Confirm both prompt-intent-analyzer test scopes still execute.
3. Confirm no unrelated runtime files were touched.

## Verification Criteria

### Success Criteria

1. `pytest --collect-only -q` succeeds.
2. The prompt-intent-analyzer test coverage remains present and runnable.
3. No runtime architecture or execution-path files changed.

### Failure Criteria

1. Full-suite collection still errors.
2. Coverage is “fixed” by deleting a valuable test surface without justification.
3. The PR expands into unrelated GUI, pipeline, or docs work.

## Risk Assessment

### Low-Risk Areas

- test-file renames and collection verification

### Medium-Risk Areas with Mitigation

- accidental coverage loss during rename
  - Mitigation: run both affected test groups directly after the rename

### High-Risk Areas with Mitigation

- global pytest configuration churn
  - Mitigation: only touch `pytest.ini` if a file-rename solution is
    insufficient

### Rollback Plan

- revert the test-file rename/config tweak and restore the prior filenames if
  the chosen fix causes broader collection regressions

## Tech Debt Analysis

### Debt Removed

- duplicate test-module basename collision blocking full collection

### Debt Intentionally Deferred

- broader stale-test cleanup outside the collection blocker
  - next PR owner: follow-on hygiene work after `PR-TEST-280`

## Documentation Updates

- no canonical docs should change in this PR
- optional: append a short remediation note to
  `docs/Research Reports/D-016-Branch-Review-Since-2026-03-22-2205.md` if the
  final cause/fix materially differs from the discovery write-up

## Dependencies

### Internal Module Dependencies

- pytest test discovery under `tests/`

### External Tools or Runtimes

- `pytest`

## Approval & Execution

Planner: Codex
Executor: Codex
Reviewer: Human
Approval Status: Pending

## Next Steps

1. `PR-HARDEN-281-ADetailer-Stability-Closure-and-Request-Local-Pinning-Rollback`
2. `PR-POLISH-282-Canonical-Roadmap-Video-Status-Harmonization`

