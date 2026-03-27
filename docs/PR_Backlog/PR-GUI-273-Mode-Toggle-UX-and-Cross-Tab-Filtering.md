# PR-GUI-273 - Mode Toggle UX and Cross-Tab Filtering

Status: Specification
Priority: HIGH
Effort: LARGE
Phase: GUI Integration + UX Consistency
Date: 2026-03-27

## 2. Context & Motivation

With persisted mode state and resolver wiring in place, this PR delivers the user-facing toggle and dynamic refresh behavior across content-heavy tabs.

## 3. Goals & Non-Goals

### Goals

1. Add a global SFW/NSFW toggle in the app shell (menu or header-level control).
2. Dynamically refresh all content views that present prompts/LoRAs/learnings/outputs/previews/queues/jobs.
3. Ensure mode transitions are instant and consistent without requiring restart.
4. Add clear UI messaging when items are filtered/redacted.

### Non-Goals

1. No architecture-level changes to execution pipeline.
2. No new content generation policy engine.
3. No moderation classifier model training in this PR.

## 4. Guardrails

1. UI should call app-state/controller hooks only; no embedded filtering business logic in widgets.
2. Use resolver output as single source of truth.
3. Preserve existing tab ownership boundaries and avoid cross-tab hidden dependencies.

## 5. Allowed Files

### Files to Create

- `tests/gui_v2/test_content_visibility_toggle_integration.py`

### Files to Modify

- `src/gui/main_window_v2.py`
- `src/gui/views/prompt_tab_frame_v2.py`
- `src/gui/prompt_pack_panel_v2.py`
- `src/gui/widgets/lora_picker_panel.py`
- `src/gui/preview_panel_v2.py`
- `src/gui/panels_v2/queue_panel_v2.py`
- `src/gui/panels_v2/running_job_panel_v2.py`
- `src/gui/panels_v2/history_panel_v2.py`
- `src/gui/views/review_tab_frame_v2.py`
- `src/gui/views/learning_tab_frame_v2.py`
- `src/gui/views/learning_review_panel_v2.py`
- `src/gui/views/photo_optimize_tab_frame_v2.py`
- `src/gui/views/movie_clips_tab_frame_v2.py`
- `src/gui/views/video_workflow_tab_frame_v2.py`

### Forbidden Files

- `src/pipeline/**`
- `src/queue/**`
- `src/randomizer/**`

## 6. Implementation Plan

1. Add shell toggle control (recommended: `View` menu + header indicator) and bind to app-state setter.
2. Subscribe relevant tabs/panels to mode-change event and trigger local refresh methods.
3. Route all list/table/image refresh paths through controller-provided filtered collections.
4. Add lightweight filtered-state banners (e.g., "SFW mode active: some items hidden").
5. Add integration tests validating dynamic updates without restart.

## 7. Testing Plan

### Unit tests

- `pytest tests/gui_v2/test_content_visibility_toggle_integration.py -q`

### Integration tests

- `pytest tests/gui_v2 -q -k "visibility or toggle or history or queue or preview"`

### Journey or smoke coverage

- `pytest tests/journey -q -k "prompt or learning or review"`

### Manual verification

1. Toggle NSFW -> SFW and confirm content lists shrink/redact live.
2. Toggle back and confirm full content returns.
3. Restart app and confirm last mode is retained.

## 8. Verification Criteria

### Success criteria

1. A single toggle controls all listed surfaces.
2. View updates happen live after toggle events.
3. No stale NSFW content remains visible in SFW mode in integrated surfaces.

### Failure criteria

1. Any tab shows stale pre-toggle content until manual reopen.
2. Different tabs apply contradictory filtering.
3. Toggle state is not persisted.

## 9. Risk Assessment

### Low-risk areas

- Header/menu control rendering.

### Medium-risk areas with mitigation

- Multi-tab refresh race/staleness; mitigate with common event subscription pattern in app-state.

### High-risk areas with mitigation

- Legacy tab variants (`*_v1`/older) not wired; mitigate by documenting v2-only support and adding fallback no-op guards.

### Rollback plan

- Keep toggle UI behind one wiring point; disable control while preserving resolver and contracts.

## 10. Tech Debt Analysis

### Debt removed

- Removes need for piecemeal per-tab safety toggles.

### Debt intentionally deferred

- Advanced per-surface policy customization deferred to future PR after baseline convergence.

### Next PR owner

- PR-TEST-274 (Codex Executor)

## 11. Documentation Updates

- Add user-facing note in GUI docs once implementation lands.

## 12. Dependencies

### Internal module dependencies

- `AppStateV2` mode state
- controller resolver APIs
- v2 tabs/panels listed in scope

### External tools or runtimes

- None.

## 13. Approval & Execution

Planner: ChatGPT
Executor: Codex
Reviewer: Human + ChatGPT
Approval Status: Pending

## 14. Next Steps

1. PR-TEST-274 hardening + coverage expansion.
2. Optional follow-up for configurable SFW policy strictness.
