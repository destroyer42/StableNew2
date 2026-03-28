# PR-CTRL-272 - Content Visibility Resolver and Selector Wiring

Status: Completed 2026-03-27
Priority: HIGH
Effort: LARGE
Phase: Controller + Data Selection Hardening
Date: 2026-03-27

## 2. Context & Motivation

After PR-CONFIG-271 introduces canonical mode state, the system still needs one resolver path so all content selectors apply the same filtering/redaction rules.

This PR introduces the central resolver and wires it into controller/query surfaces where content lists are assembled.

References:

- `docs/PR_Backlog/D-NSFW-SFW-001-Content-Visibility-Mode-Discovery.md`
- `docs/ARCHITECTURE_v2.6.md`

## 3. Goals & Non-Goals

### Goals

1. Create a canonical resolver service that evaluates mode + item metadata.
2. Route prompt/LoRA/history/learning selector paths through resolver logic.
3. Add optional redaction formatting for prompt text and metadata fields in SFW mode.
4. Add deterministic tests for allow/block/redact decisions.

### Non-Goals

1. No UI menu implementation yet.
2. No queue/runner payload mutation.
3. No runtime stage policy changes.

## 4. Guardrails

1. Resolver decides visibility only; execution logic remains unchanged.
2. No alternate data stores or parallel metadata formats.
3. Keep decision points centralized; avoid per-view forks.
4. Queue, runner, and NJR schema are out of scope.

## 5. Allowed Files

### Files to Create

- `src/controller/content_visibility_resolver.py`
- `tests/controller/test_content_visibility_resolver.py`

### Files to Modify

- `src/controller/app_controller.py`
- `src/controller/job_history_service.py`
- `src/gui/prompt_workspace_state.py`
- `src/gui/widgets/lora_picker_panel.py`
- `src/learning/discovered_review_store.py`
- `src/learning/output_scanner.py`

### Forbidden Files

- `src/queue/**`
- `src/pipeline/executor.py`
- `src/pipeline/pipeline_runner.py`

## 6. Implementation Plan

1. Implement resolver with APIs like `is_visible()`, `redact_text()`, `filter_collection()`.
2. Wire controller history/list endpoints to use resolver results based on `app_state.content_visibility_mode`.
3. Wire prompt/LoRA selectors through resolver-based filtering (using existing metadata tags where present).
4. Wire learning discovered-item scans/stores to emit or consume visibility classification fields.
5. Add regression tests for edge cases: unknown rating, missing metadata, mixed-tag payloads.

## 7. Testing Plan

### Unit tests

- `pytest tests/controller/test_content_visibility_resolver.py -q`

### Integration tests

- `pytest tests/controller tests/learning -q -k "visibility or redact or nsfw or sfw"`

### Journey or smoke coverage

- `pytest tests/journey -q -k "history or review"`

### Manual verification

1. Switch to SFW mode.
2. Confirm NSFW-tagged records are hidden/redacted in controller-fed lists.

## 8. Verification Criteria

### Success criteria

1. One shared resolver is used by controller/query paths.
2. SFW mode hides/redacts NSFW-tagged entries deterministically.
3. NSFW mode restores full visibility.

### Failure criteria

1. View-specific custom filtering bypasses resolver.
2. Missing metadata crashes list rendering.
3. Queue/runner behavior changes.

## 9. Risk Assessment

### Low-risk areas

- Pure filtering for non-execution list surfaces.

### Medium-risk areas with mitigation

- Metadata sparsity: add conservative fallback and explicit tests.

### High-risk areas with mitigation

- History/read paths used widely; mitigate with additive wrappers and regression suites.

### Rollback plan

- Gate resolver wiring behind isolated helper calls; revert helper usage without schema churn.

## 10. Tech Debt Analysis

### Debt removed

- Prevents duplicated NSFW checks across UI files.

### Debt intentionally deferred

- Final UX polish and explicit user messaging deferred to PR-GUI-273.

### Next PR owner

- PR-GUI-273 (Codex Executor)

## 11. Documentation Updates

- Update discovery cross-links if resolver API names differ from this spec.

## 12. Dependencies

### Internal module dependencies

- `AppController`
- `JobHistoryService`
- prompt and learning selectors/stores

### External tools or runtimes

- None.

## 13. Approval & Execution

Planner: ChatGPT
Executor: Codex
Reviewer: Human + ChatGPT
Approval Status: Executed

## 14. Next Steps

1. PR-GUI-273 for cross-tab UX wiring.
2. PR-TEST-274 for full-system hardening.

## 15. Post-Implementation Summary

- added the shared resolver in `src/controller/content_visibility_resolver.py`
- wired app-controller pack discovery, history service, prompt redaction, LoRA
  filtering, and discovered-review metadata normalization through the resolver
- added deterministic coverage in
  `tests/controller/test_content_visibility_resolver.py`
- focused verification passed:
  `pytest -q tests/controller/test_content_visibility_resolver.py`
