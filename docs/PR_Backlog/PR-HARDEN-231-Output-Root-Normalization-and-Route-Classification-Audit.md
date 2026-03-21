# PR-HARDEN-231 - Output Root Normalization and Route Classification Audit

Status: Implemented 2026-03-20
Priority: HIGH
Effort: MEDIUM
Phase: Output Routing Hardening
Date: 2026-03-20

## Context & Motivation

Current output routing still relies on heuristics that can confuse route roots
with route-selected folders, which makes regular image runs, AnimateDiff, and
learning discovery harder to reason about.

## Goals & Non-Goals

### Goals

1. Make configured `output_dir` mean only the base root.
2. Strip known legacy route suffixes before route resolution.
3. Drive route choice from canonical job/stage intent instead of folder-name
   guesswork.
4. Add routing regressions for regular image, AnimateDiff, workflow-video, and
   discovered-output scanning.

### Non-Goals

1. Do not redesign the entire output browser UI.
2. Do not change canonical artifact schemas.

## Guardrails

1. Keep NJR, queue, and runner ownership unchanged.
2. Do not move video backend logic out of `src/video/`.
3. Preserve existing output files on disk; normalize future routing logic.

## Allowed Files

### Files to Modify

- `src/state/output_routing.py`
- `src/pipeline/pipeline_runner.py`
- `src/learning/**output*`
- `tests/**output*`
- `docs/StableNew Roadmap v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`

### Forbidden Files

- `src/gui/**`
- `src/controller/**`

## Implementation Plan

1. Normalize configured output roots before route selection.
2. Derive route selection from canonical stage/job intent.
3. Update learning/discovery scanners to use the normalized root.
4. Add route audit tests and update docs.

## Testing Plan

- `pytest tests/learning_v2/test_output_scanner.py tests/state/test_output_routing.py -q`
- targeted pipeline routing regressions

## Verification Criteria

### Success Criteria

1. Regular image runs stop falling into AnimateDiff folders by mistake.
2. Learned/discovered scans resolve the same root the runner writes to.

### Failure Criteria

1. Route classification still depends on stale folder-name heuristics.
2. Existing job families regress to the wrong output subtree.

## Risk Assessment

Medium risk in existing routed-output assumptions. Mitigate with cross-family
regression coverage and no destructive migration.

## Tech Debt Analysis

### Debt Removed

- root-vs-route ambiguity in output configuration

### Debt Intentionally Deferred

- UI surfacing of routing decisions
  - Owner: future UX work

## Documentation Updates

- `docs/StableNew Roadmap v2.6.md`

## Approval & Execution

Planner: ChatGPT/Codex
Executor: Codex
Reviewer: Human
Approval Status: Pending

## Next Steps

- `PR-GUI-232-Pack-Selector-Cleanup-and-Real-Pack-Refresh-Discovery`

## Post-Implementation Summary

- added canonical output-root normalization in `src/state/output_routing.py`
  so trailing route folders like `output/animatediff` are stripped before route
  selection
- updated existing-output classification to prefer manifest metadata before
  folder-name guesses
- added targeted coverage in `tests/state/test_output_routing.py`
- extended `tests/pipeline/test_output_folder_structure.py` to prove a regular
  Pipeline job is not trapped under `output/animatediff/Pipeline`
- verification passed:
  `pytest tests/state/test_output_routing.py tests/pipeline/test_output_folder_structure.py -q`
  -> `12 passed`
- `python -m compileall src/state/output_routing.py tests/state/test_output_routing.py tests/pipeline/test_output_folder_structure.py`
- `pytest --collect-only -q -rs` -> `2580 collected / 0 skipped`

