# PR-GUI-232 - Pack Selector Cleanup and Real Pack Refresh Discovery

Status: Completed 2026-03-20
Priority: HIGH
Effort: MEDIUM
Phase: PromptPack UX Cleanup
Date: 2026-03-20

## Context & Motivation

The Pipeline sidebar still exposes a legacy empty text field in the pack
selector area, and refresh behavior does not clearly rediscover the full set of
real PromptPack files.

## Goals & Non-Goals

### Goals

1. Remove the empty legacy pack text field from the sidebar.
2. Make refresh rediscover actual PromptPack files on disk.
3. Support JSON-backed prompt packs during discovery, or formally unify on one
   supported format if the repo already guarantees that.
4. Add GUI regressions for pack discovery and refresh.

### Non-Goals

1. Do not redesign PromptPack authoring.
2. Do not change NJR building semantics.

## Guardrails

1. Keep PromptPack -> Builder -> NJR flow unchanged.
2. Do not add hidden GUI state.
3. Preserve existing controller ownership; no runner changes.

## Allowed Files

### Files to Modify

- `src/gui/sidebar_panel_v2.py`
- `src/utils/prompt_packs.py`
- `src/utils/file_io.py`
- `tests/gui_v2/**pack*`
- `tests/utils/**pack*`
- `docs/StableNew Roadmap v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`

### Forbidden Files

- `src/pipeline/**`
- `src/controller/app_controller.py`

## Implementation Plan

1. Remove the legacy empty entry field and tighten labels/empty states.
2. Make refresh perform real PromptPack rediscovery across supported formats.
3. Add GUI and utility regressions for refresh behavior.

## Testing Plan

- targeted GUI pack-selector tests
- targeted PromptPack discovery tests

## Verification Criteria

### Success Criteria

1. Users can see actual packs without confusing empty text controls.
2. Refresh discovers newly added packs reliably.

### Failure Criteria

1. Refresh still misses supported pack formats.
2. Legacy empty-field behavior remains exposed.

## Approval & Execution

Planner: ChatGPT/Codex
Executor: Codex
Reviewer: Human
Approval Status: Pending

## Next Steps

- `PR-LEARN-233-Canonical-Discovered-Scan-Root-Fix`

## Implementation Summary

- removed the legacy empty prompt entry from the Pipeline sidebar pack selector
- made prompt-pack discovery scan `.json`, `.txt`, and `.tsv`
- taught shared pack reading to render structured JSON slot content for preview
  and prompt counting
- added regressions for JSON pack discovery and sidebar refresh behavior
