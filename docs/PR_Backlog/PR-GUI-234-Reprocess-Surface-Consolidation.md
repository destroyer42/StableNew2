# PR-GUI-234 - Reprocess Surface Consolidation

Status: Completed 2026-03-20
Priority: MEDIUM
Effort: MEDIUM
Phase: Review/Reprocess UX Cleanup
Date: 2026-03-20

## Context & Motivation

StableNew currently exposes overlapping reprocess controls in the Pipeline
sidebar and the Review tab. The Review tab is already the more capable surface.

## Goals & Non-Goals

### Goals

1. Make `Review` the canonical advanced reprocess surface.
2. Reduce sidebar reprocess to a minimal launcher or remove it.
3. Eliminate duplicated controls and conflicting mental models.

### Non-Goals

1. Do not remove reprocess capability entirely.
2. Do not change canonical replay/history contracts.

## Guardrails

1. Keep one queue-backed reprocess execution path.
2. Do not introduce parallel controller logic for the same behavior.

## Allowed Files

### Files to Modify

- `src/gui/panels_v2/reprocess_panel_v2.py`
- `src/gui/views/review_tab_frame_v2.py`
- `src/controller/**reprocess*`
- `tests/gui_v2/**reprocess*`
- `docs/StableNew Roadmap v2.6.md`

### Forbidden Files

- `src/pipeline/**`
- `src/video/**`

## Implementation Plan

1. Audit the two surfaces and pick Review as the canonical advanced owner.
2. Remove or collapse duplicated sidebar controls.
3. Add UI regressions and update docs.

## Testing Plan

- targeted GUI reprocess tests
- one queue-backed smoke regression

## Verification Criteria

### Success Criteria

1. There is one obvious place for advanced reprocess.

### Failure Criteria

1. Two conflicting reprocess surfaces remain.

## Approval & Execution

Planner: ChatGPT/Codex
Executor: Codex
Reviewer: Human
Approval Status: Pending

## Next Steps

- `PR-GUI-235-Core-Config-to-Base-Generation-and-Recipe-Summary-UX`

## Implementation Summary

- collapsed the Pipeline sidebar reprocess card into a launcher for Review
- marked Review as the canonical advanced reprocess workspace
- removed duplicated sidebar image-selection and stage-selection controls
- added GUI regressions for the launcher handoff and Review workspace ownership
