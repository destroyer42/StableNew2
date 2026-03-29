# PR-TEST-VIDEO-003: Movie Clips Journeys and Documentation

**Status**: Specification
**Priority**: MEDIUM
**Effort**: SMALL
**Phase**: Video MVP
**Date**: 2026-03-11

## Context & Motivation

### Problem Statement
Once the Movie Clips tab exists, it needs regression coverage and canonical documentation so it does not become another isolated feature path with unclear behavior.

### Why This Matters
The repo already has partial legacy video ideas. The MVP needs a clearly documented, tested scope to avoid accidental drift toward a pipeline-stage implementation.

### Current Architecture
Movie Clips MVP is intended to remain a post-processing UI/service feature, not a stage-chain feature.

### Reference
- `docs/D-VIDEO-002-Movie-Clips-Tab-MVP-Discovery.md`
- `docs/PR_MAR26/PR-GUI-VIDEO-001-Movie-Clips-Tab-Spine-and-Selection.md`
- `docs/PR_MAR26/PR-CORE-VIDEO-002-Clip-Build-Service-and-Controller.md`

## Goals & Non-Goals

### Goals
1. Add journey-level coverage for the Movie Clips MVP.
2. Document the user workflow and architecture boundary.
3. Record future work boundaries relative to AnimateDiff.

### Non-Goals
1. No feature expansion.
2. No queue or pipeline stage changes.
3. No AnimateDiff implementation.

## Allowed Files

### Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `tests/journeys/test_movie_clips_mvp.py` | End-to-end smoke for tab/service flow | 200 |
| `docs/Movie_Clips_Workflow_v2.6.md` | Canonical user/developer workflow doc | 180 |

### Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `docs/DOCS_INDEX_v2.6.md` | Index new Movie Clips workflow doc | 20 |
| `tests/gui_v2/test_movie_clips_tab_v2.py` | Final regression additions | 60 |

### Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| `src/pipeline/` | No pipeline expansion in docs/test PR |
| `src/queue/` | No queue expansion in docs/test PR |

## Implementation Plan

### Step 1: Add journey coverage
Cover:

- load source images
- build clip
- verify output artifact
- verify manifest

### Step 2: Add workflow doc
Document:

- supported source modes
- output location semantics
- settings meaning
- architecture boundary versus AnimateDiff

### Step 3: Update docs index
Point `DOCS_INDEX_v2.6.md` at the new workflow doc.

## Testing Plan

### Unit Tests
- none new beyond prior PRs

### Integration Tests
- clip build smoke with mocked or real FFmpeg availability checks

### Journey Tests
- Movie Clips tab end-to-end MVP path

### Manual Testing
1. Load a folder.
2. Build a clip.
3. Reopen app and confirm settings restore.
4. Confirm docs match actual UX.

## Verification Criteria

### Success Criteria
1. Journey test passes.
2. Workflow doc reflects actual implementation.
3. Docs index points to Movie Clips documentation.

### Failure Criteria
- docs describe pipeline-stage semantics that do not exist
- journey test requires unstable environment assumptions

## Risk Assessment

### Low Risk Areas
✅ Documentation

### Medium Risk Areas
⚠️ Journey stability if FFmpeg is absent
- **Mitigation**: structure tests to allow a mocked execution path where required

### High Risk Areas
❌ None

### Rollback Plan
Revert doc additions and journey tests if they prove unstable.

## Tech Debt Analysis

## Tech Debt Removed
✅ Prevents undocumented drift between MVP tab semantics and future AnimateDiff ambitions

## Tech Debt Added
⚠️ None expected

**Net Tech Debt**: -1

## Architecture Alignment

### Enforces Architecture v2.6
Keeps Movie Clips documented as post-processing, not as an alternate generation path.

### Follows Testing Standards
Adds journey coverage and docs harmonization.

### Maintains Separation of Concerns
Documentation explicitly preserves the line between clip assembly and future motion generation.

## Dependencies

### External
- `ffmpeg` or mocked subprocess path in tests

### Internal
- Movie Clips UI and service from PR-VIDEO-001 and PR-VIDEO-002

## Timeline & Effort

### Breakdown
| Task | Effort | Duration |
|------|--------|----------|
| Journey tests | 0.5 day | Day 3 |
| Workflow docs + docs index | 0.5 day | Day 3 |

**Total**: 1 day

## Approval & Sign-Off

**Planner**: Codex
**Executor**: Codex
**Reviewer**: Rob

**Approval Status**: Pending

## Next Steps

1. Implement journey coverage after PR-001 and PR-002 land.
2. Keep AnimateDiff work in a separate planned series.
3. Revisit queue-backed clip processing only after MVP proves useful.

