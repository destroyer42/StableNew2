# PR-LEARN-233 - Canonical Discovered Scan Root Fix

Status: Completed 2026-03-20
Priority: MEDIUM
Effort: SMALL
Phase: Learning UX and Scan Consistency
Date: 2026-03-20

## Context & Motivation

The learning tab still uses a weak output-root fallback that can scan the wrong
folder family when routed image and video outputs diverge.

## Goals & Non-Goals

### Goals

1. Make discovered-experiment scanning use the canonical configured output root.
2. Remove dependence on ad hoc `app_state.output_dir` fallback behavior.
3. Add regressions for regular image and routed video scan discovery.

### Non-Goals

1. Do not redesign the learning tab.
2. Do not change recommendation semantics.

## Guardrails

1. Learning remains downstream of canonical artifacts.
2. No queue, runner, or GUI-architecture changes.

## Allowed Files

### Files to Modify

- `src/gui/views/learning_tab_frame_v2.py`
- `src/utils/config.py`
- `tests/learning_v2/**output*`
- `docs/StableNew Roadmap v2.6.md`

### Forbidden Files

- `src/pipeline/**`
- `src/controller/**`

## Implementation Plan

1. Resolve the scan root from canonical config/engine settings.
2. Remove fallback assumptions that point at stale roots.
3. Add discovery regressions and update docs.

## Testing Plan

- targeted learning output-scan tests

## Verification Criteria

### Success Criteria

1. The learning tab discovers runs from the same root the runner uses.

### Failure Criteria

1. Discovery still misses routed image outputs because of stale root fallback.

## Approval & Execution

Planner: ChatGPT/Codex
Executor: Codex
Reviewer: Human
Approval Status: Pending

## Next Steps

- `PR-GUI-234-Reprocess-Surface-Consolidation`

## Implementation Summary

- resolved discovered-review scan roots from canonical configured engine output
  settings instead of `app_state.output_dir`
- normalized route-suffixed output directories back to the base output root
- added targeted regressions for configured route folders and rescan dispatch
