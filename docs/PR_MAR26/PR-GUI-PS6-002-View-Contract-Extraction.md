# PR-GUI-PS6-002: Complete View-Contract Extraction

**Status**: Implemented
**Priority**: HIGH
**Effort**: MEDIUM (1 week)
**Phase**: PySide6 Migration
**Date**: 2026-03-09

## Context & Motivation
### Problem Statement
Remaining Tk views still embed behavior logic and status derivation.
### Why This Matters
Qt port speed depends on toolkit-agnostic contracts.
### Current Architecture
Contracts exist for some Review/Learning/Prompt/Queue surfaces, but not all.
### Reference
- docs/PR_MAR26/PR-MAR26-UI-REFRESH-001-Migration-Accelerator.md

## Goals & Non-Goals
### ? Goals
1. Reach full contract coverage for selected GUI surfaces.
2. Move non-render logic out of widget classes.
3. Add contract parity tests.
### ? Non-Goals
1. No Qt runtime code yet.
2. No controller architecture changes.

## Allowed Files
### ? Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| src/gui/view_contracts/*.py | Missing contract modules | 300 |
| tests/gui_v2/test_*_view_contracts.py | Contract tests | 250 |
| docs/PR_MAR26/PR-GUI-PS6-002-View-Contract-Extraction.md | PR spec | 180 |
### ? Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| src/gui/views/*_tab_frame_v2.py | Use contracts only | 220 |
| src/gui/panels_v2/*.py | Remove duplicated display logic | 180 |
### ? Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| src/pipeline/** | Out of scope |
| src/queue/** | Out of scope |
| src/api/** | Out of scope |

## Implementation Plan
### Step 1
Inventory all remaining non-contract logic in GUI surfaces.
### Step 2
Extract logic into view contracts/adapters.
### Step 3
Add parity tests for each contract.
### Step 4
Run GP + targeted GUI tests.

## Testing Plan
- pytest -q tests/gui_v2/test_*_view_contracts.py
- pytest -q tests/integration/test_golden_path_suite_v2_6.py

## Verification Criteria
### ? Success Criteria
1. Each targeted surface uses contract functions for state derivation.
2. Contract tests pass.
3. GP suite unchanged.
### ? Failure Criteria
Widget-specific business logic persists in targeted surfaces.

## Risk Assessment
?? Regression in subtle view behavior.
- **Mitigation**: baseline snapshots + focused tests.

## Tech Debt Analysis
**Net Tech Debt**: -2

## Architecture Alignment
No execution-path changes.

## Dependencies
Internal GUI modules only.

## Timeline & Effort
~3-5 days.

## Approval & Sign-Off
Planner/Executor: Codex; Reviewer: Rob

## Next Steps
PR-PS6-003

## Implementation Summary

**Implementation Date**: 2026-03-09
**Executor**: Codex
**Status**: COMPLETE

### What Was Implemented
1. Added `src/gui/view_contracts/pipeline_layout_contract.py`.
2. Updated `src/gui/views/pipeline_tab_frame_v2.py` to use contract functions for:
   - minimum window geometry normalization
   - visible stage ordering
3. Updated `src/gui/view_contracts/__init__.py` exports.
4. Added `tests/gui_v2/test_pipeline_view_contracts.py`.

### Verification
1. `pytest -q tests/gui_v2/test_pipeline_view_contracts.py tests/gui_v2/test_prompt_view_contracts.py tests/gui_v2/test_queue_view_contracts.py`
2. `pytest -q tests/integration/test_golden_path_suite_v2_6.py`
