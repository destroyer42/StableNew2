# PR-CONFIG-271 - Content Visibility Mode Contract and Persistence

Status: Specification
Priority: HIGH
Effort: MEDIUM
Phase: GUI + Learning Safety Hardening
Date: 2026-03-27

## 2. Context & Motivation

Current repo truth: UI state persistence exists, but there is no canonical SFW/NSFW mode contract shared across prompt, learning, preview, output, queue, and history surfaces.

This PR exists now because downstream filtering cannot be done safely until the system has a single, persisted source of truth for content-visibility mode and classification metadata interpretation.

References:

- `docs/ARCHITECTURE_v2.6.md`
- `docs/GOVERNANCE_v2.6.md`
- `docs/PR_TEMPLATE_v2.6.md`
- `docs/PR_Backlog/D-NSFW-SFW-001-Content-Visibility-Mode-Discovery.md`

## 3. Goals & Non-Goals

### Goals

1. Define a canonical visibility mode enum (`sfw`, `nsfw`) and metadata classification contract.
2. Add persisted global mode state that survives app restarts.
3. Add app-state notification hooks so tabs can react to mode changes.
4. Add contract-level tests for serialization, defaults, and fallback behavior.

### Non-Goals

1. No per-tab UI toggle yet.
2. No filtering in specific content surfaces yet.
3. No queue/runner execution semantics changes.
4. No model training or recommendation-policy changes.

## 4. Guardrails

1. Preserve NJR -> Queue -> Runner invariants exactly.
2. Treat this PR as contract + state only (no broad UI behavior changes).
3. Do not introduce alternate job payloads or legacy compatibility shims.
4. Queue/runner contracts are explicitly out of scope.

## 5. Allowed Files

### Files to Create

- `src/gui/content_visibility.py`
- `tests/gui_v2/test_content_visibility_contract.py`

### Files to Modify

- `src/gui/app_state_v2.py`
- `src/gui/main_window_v2.py`
- `src/services/ui_state_store.py`

### Forbidden Files

- `src/queue/**`
- `src/pipeline/executor.py`
- `src/pipeline/prompt_pack_job_builder.py`
- `src/controller/job_execution_controller.py`

## 6. Implementation Plan

1. Add `ContentVisibilityMode` enum + classification dataclasses/helpers in `src/gui/content_visibility.py`.
2. Extend `AppStateV2` with `content_visibility_mode` and setter/toggler + listener notifications in `src/gui/app_state_v2.py`.
3. Persist/restore mode in `MainWindowV2` using `UIStateStore` payload section.
4. Add schema-compatible state defaults in `src/services/ui_state_store.py` (non-breaking with existing `2.6` schema payloads).
5. Add tests for defaults, persistence roundtrip, and invalid payload fallback.

## 7. Testing Plan

### Unit tests

- `pytest tests/gui_v2/test_content_visibility_contract.py -q`

### Integration tests

- `pytest tests/gui_v2 -q -k "content_visibility or ui_state"`

### Journey or smoke coverage

- `pytest tests/journey -q -k "state or persistence"`

### Manual verification

1. Set mode to `sfw`.
2. Restart app.
3. Confirm mode restores as `sfw`.

## 8. Verification Criteria

### Success criteria

1. New app state field exists and emits change notifications.
2. Mode survives restart through persisted UI state.
3. Unknown/invalid persisted values fall back deterministically.

### Failure criteria

1. App fails to load older UI state payloads.
2. Mode changes without emitting listeners.
3. Any queue/runner behavior changes.

## 9. Risk Assessment

### Low-risk areas

- Pure data model additions and persistence wiring.

### Medium-risk areas with mitigation

- UI state compatibility; mitigate with fallback defaults and migration-safe reads.

### High-risk areas with mitigation

- None in this PR.

### Rollback plan

- Revert the new mode keys and keep persistence format backward-compatible.

## 10. Tech Debt Analysis

### Debt removed

- Eliminates future need for ad hoc toggle state per tab.

### Debt intentionally deferred

- Surface-specific filtering remains for PR-CTRL-272 and PR-GUI-273.

### Next PR owner

- PR-CTRL-272 (Codex Executor)

## 11. Documentation Updates

- Add/update this PR spec and discovery report references in docs index/backlog listing if needed.

## 12. Dependencies

### Internal module dependencies

- `AppStateV2`
- `MainWindowV2`
- `UIStateStore`

### External tools or runtimes

- None.

## 13. Approval & Execution

Planner: ChatGPT
Executor: Codex
Reviewer: Human + ChatGPT
Approval Status: Pending

## 14. Next Steps

1. PR-CTRL-272: resolver service + query wiring.
2. PR-GUI-273: global toggle placement + tab integrations.
3. PR-TEST-274: full regression and journey hardening.
