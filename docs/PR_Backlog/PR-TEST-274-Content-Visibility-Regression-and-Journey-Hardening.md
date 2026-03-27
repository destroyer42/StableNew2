# PR-TEST-274 - Content Visibility Regression and Journey Hardening

Status: Specification
Priority: HIGH
Effort: MEDIUM
Phase: Validation + Hardening
Date: 2026-03-27

## 2. Context & Motivation

After PR-CONFIG-271, PR-CTRL-272, and PR-GUI-273, this PR ensures the feature remains stable through deterministic regression and journey coverage.

## 3. Goals & Non-Goals

### Goals

1. Add comprehensive regression tests across state, resolver, and GUI integrations.
2. Add journey tests for end-to-end toggle behavior (persist + dynamic filtering).
3. Add failure-mode tests for missing metadata and mixed legacy records.

### Non-Goals

1. No feature expansion beyond validation.
2. No new architecture or contract changes.

## 4. Guardrails

1. Keep tests deterministic with mocks/fixtures.
2. Avoid live WebUI/network dependencies.
3. Preserve existing CI runtime expectations.

## 5. Allowed Files

### Files to Create

- `tests/journey/test_content_visibility_mode_journey.py`
- `tests/gui_v2/test_content_visibility_mode_persistence.py`
- `tests/learning/test_content_visibility_learning_filters.py`

### Files to Modify

- `tests/controller/test_job_history_service.py`
- `tests/gui_v2/test_main_window_v2.py`
- `tests/gui_v2/test_history_panel_v2.py`
- `tests/gui_v2/test_queue_panel_v2.py`

### Forbidden Files

- `src/**` (except minimal test helper exposure if strictly required)

## 6. Implementation Plan

1. Add fixture data with explicit `sfw`, `nsfw`, and `unknown` classifications.
2. Add GUI tests for runtime toggle propagation and panel refresh.
3. Add journey test covering: set mode -> filter views -> restart -> mode retained.
4. Add negative tests ensuring unknown metadata does not crash and follows fallback policy.

## 7. Testing Plan

### Unit tests

- `pytest tests/controller tests/learning -q -k "visibility"`

### Integration tests

- `pytest tests/gui_v2 -q -k "visibility or sfw or nsfw"`

### Journey or smoke coverage

- `pytest tests/journey/test_content_visibility_mode_journey.py -q`

### Manual verification

- Spot-check prompt, queue, history, learning, preview, and output views after mode toggle.

## 8. Verification Criteria

### Success criteria

1. Full targeted test suite passes.
2. Journey test confirms persistence + live updates.
3. Legacy/missing metadata paths stay stable.

### Failure criteria

1. Flaky timing-dependent tests.
2. Tests requiring live backend processes.
3. Regressions in existing queue/history GUI tests.

## 9. Risk Assessment

### Low-risk areas

- Unit-level resolver/persistence checks.

### Medium-risk areas with mitigation

- GUI test fragility; mitigate using existing harness and deterministic event pumping.

### High-risk areas with mitigation

- Journey breadth can become slow; mitigate by keeping one golden journey and targeted smoke subsets.

### Rollback plan

- Revert only newly added visibility tests if blocking unrelated release work, then re-land in isolated test PR.

## 10. Tech Debt Analysis

### Debt removed

- Adds long-term regression guardrails for safety mode behavior.

### Debt intentionally deferred

- None; this PR should close the feature-series validation loop.

### Next PR owner

- Human/Planner to decide post-hardening enhancements.

## 11. Documentation Updates

- Update roadmap/backlog status lines for PR-CONFIG-271 through PR-TEST-274 completion.

## 12. Dependencies

### Internal module dependencies

- Tests depend on contracts from PR-CONFIG-271 / PR-CTRL-272 / PR-GUI-273.

### External tools or runtimes

- None.

## 13. Approval & Execution

Planner: ChatGPT
Executor: Codex
Reviewer: Human + ChatGPT
Approval Status: Pending

## 14. Next Steps

1. Optional PR for user-configurable strictness profile ("strict SFW" vs "balanced SFW").
2. Optional diagnostics dashboard panel for filtered-content counters.
