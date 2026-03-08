# Learning Tab PR Series — Master Index

**Status:** PLANNING  
**Created:** 2025-01-XX  
**Series:** PR-LEARN-001 through PR-LEARN-009+

---

## Overview

This document provides a master index of all PRs in the Learning Tab implementation series. Each PR is designed to be atomic, testable, and safe to implement independently (respecting dependencies).

---

## Phase 1: Critical Wiring (BLOCKERS)

These PRs must be completed first. They fix fundamental issues that prevent the Learning Tab from functioning at all.

| PR | Title | Priority | Status | Effort | Dependencies |
|----|-------|----------|--------|--------|--------------|
| [PR-LEARN-001](PR-LEARN-001-Wire-LearningController.md) | Wire LearningController to PipelineController | P0 | DRAFT | 4-6h | None |
| [PR-LEARN-002](PR-LEARN-002-Integrate-ExecutionController.md) | Integrate LearningExecutionController | P0 | DRAFT | 4-6h | PR-LEARN-001 |

**Outcome:** After Phase 1, clicking "Run Experiment" will actually submit jobs to the queue.

---

## Phase 2: Job Completion Integration

These PRs create the closed-loop feedback mechanism where job results flow back to the Learning UI.

| PR | Title | Priority | Status | Effort | Dependencies |
|----|-------|----------|--------|--------|--------------|
| [PR-LEARN-003](PR-LEARN-003-Job-Completion-Hooks.md) | Add Learning Job Completion Hooks | P1 | DRAFT | 3-4h | PR-LEARN-002 |
| [PR-LEARN-004](PR-LEARN-004-Live-Status-Updates.md) | Live Variant Status Updates | P1 | DRAFT | 2-3h | PR-LEARN-003 |
| [PR-LEARN-005](PR-LEARN-005-Image-Result-Integration.md) | Image Result Integration | P1 | DRAFT | 3-4h | PR-LEARN-004 |

**Outcome:** After Phase 2, users see real-time updates as experiments run, and completed variants show actual generated images.

---

## Phase 3: Review & Rating Polish

These PRs complete the user feedback workflow.

| PR | Title | Priority | Status | Effort | Dependencies |
|----|-------|----------|--------|--------|--------------|
| [PR-LEARN-006](PR-LEARN-006-Image-Preview.md) | Image Preview in Review Panel | P2 | DRAFT | 3-4h | PR-LEARN-005 |
| [PR-LEARN-007](PR-LEARN-007-Rating-Persistence.md) | Rating Persistence & Retrieval | P2 | DRAFT | 2-3h | PR-LEARN-005 |

**Outcome:** After Phase 3, users can view image thumbnails and their ratings persist across sessions.

---

## Phase 4: Recommendations & Analytics

These PRs enable intelligent parameter tuning based on user feedback.

| PR | Title | Priority | Status | Effort | Dependencies |
|----|-------|----------|--------|--------|--------------|
| [PR-LEARN-008](PR-LEARN-008-Live-Recommendations.md) | Live Recommendation Display | P2 | DRAFT | 2-3h | PR-LEARN-007 |
| [PR-LEARN-009](PR-LEARN-009-Apply-Recommendations.md) | Apply Recommendations to Pipeline | P3 | DRAFT | 3-4h | PR-LEARN-008 |

**Outcome:** After Phase 4, the system provides actionable parameter suggestions that users can apply with one click.

---

## Future Phases (Not Yet Specified)

### Phase 5: Analytics Dashboard (P3)
- PR-LEARN-010: Analytics charts and visualizations
- PR-LEARN-011: Statistical summaries and trends

### Phase 6: Advanced Experiments (P4)
- PR-LEARN-012: Multi-variable (X/Y) experiments
- PR-LEARN-013: Adaptive learning loop (auto-refinement)

---

## Dependency Graph

```
PR-LEARN-001 ─────┐
                  │
                  v
PR-LEARN-002 ─────┐
                  │
                  v
PR-LEARN-003 ─────┐
                  │
                  v
PR-LEARN-004 ─────┐
                  │
                  v
PR-LEARN-005 ─────┬───────────────┐
                  │               │
                  v               v
           PR-LEARN-006     PR-LEARN-007
                                  │
                                  v
                           PR-LEARN-008
                                  │
                                  v
                           PR-LEARN-009
```

---

## Estimated Total Effort

| Phase | PRs | Estimated Hours |
|-------|-----|-----------------|
| Phase 1 | 2 | 8-12h |
| Phase 2 | 3 | 8-11h |
| Phase 3 | 2 | 5-7h |
| Phase 4 | 2 | 5-7h |
| **Total** | **9** | **26-37h** |

---

## Implementation Order

For fastest path to a working system:

1. **PR-LEARN-001** (4-6h) — Basic wiring
2. **PR-LEARN-002** (4-6h) — Backend integration
3. **PR-LEARN-003** (3-4h) — Completion hooks
4. **PR-LEARN-005** (3-4h) — Image integration *(can skip PR-LEARN-004 temporarily)*
5. **PR-LEARN-007** (2-3h) — Rating persistence
6. **PR-LEARN-008** (2-3h) — Recommendations

This gives you a functional learning system in ~20-26 hours.

---

## Related Documents

- [LEARNING_ROADMAP_v2.6.md](../LEARNING_ROADMAP_v2.6.md) — Full analysis and architecture
- [Learning_System_Spec_v2.5.md](../Learning_System_Spec_v2.5.md) — Schema and API spec
- [ARCHITECTURE_v2.6.md](../ARCHITECTURE_v2.6.md) — System architecture

---

## Notes for Implementers

1. **Test each PR independently** before merging
2. **Run the full test suite** after each phase
3. **Update LEARNING_ROADMAP.md** when PRs complete
4. **Don't skip Phase 1** — everything else depends on it
