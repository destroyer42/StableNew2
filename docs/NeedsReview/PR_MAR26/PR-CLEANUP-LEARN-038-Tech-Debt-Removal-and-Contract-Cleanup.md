# PR-CLEANUP-LEARN-038: Tech Debt Removal and Contract Cleanup

**Status**: Implemented
**Priority**: MEDIUM
**Effort**: MEDIUM
**Phase**: Learning Recovery
**Date**: 2026-03-10

## Context & Motivation
The Learning subsystem still had contract drift and a missing canonical subsystem document after the earlier recovery PRs.

## Goals
1. Tighten Learning record and recommendation contracts.
2. Remove nondeterministic behavior from experiment-store listing.
3. Close documentation drift for the Learning subsystem.

## Allowed Files
- learning subsystem files touched by PR-031 through PR-037
- learning docs and tests only

## Implementation Summary
1. Tightened recommendation and record contracts around explicit record kinds.
2. Made experiment-store ordering deterministic when timestamps collide.
3. Added the canonical learning subsystem spec at `docs/Subsystems/Learning/Learning_System_Spec_v2.6.md` to eliminate missing-doc drift from the docs index.

## Validation
- targeted learning regression suite
- `tests/integration/test_golden_path_suite_v2_6.py`

