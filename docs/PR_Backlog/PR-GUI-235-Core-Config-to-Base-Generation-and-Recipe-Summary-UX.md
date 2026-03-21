# PR-GUI-235 - Core Config to Base Generation and Recipe Summary UX

Status: Specification
Priority: MEDIUM
Effort: LARGE
Phase: Pipeline UX Cleanup
Date: 2026-03-20

## Context & Motivation

The current `Core Config` card is legacy-feeling, overlaps with stage-local
controls, and hides precedence. Pipeline presets also require memorized names
instead of readable summaries.

## Goals & Non-Goals

### Goals

1. Replace `Core Config` with a clearer `Base Generation` card.
2. Make stage cards own only stage-specific overrides.
3. Rename presets to `Saved Recipes` and show human-readable summaries.
4. Make config precedence visible.

### Non-Goals

1. Do not replace presets with learning-driven automation yet.
2. Do not rewrite the GUI toolkit.

## Guardrails

1. Preserve canonical config layering and GUI adapter ownership.
2. Do not add hidden override precedence.
3. Reuse existing controller/config services where possible.

## Allowed Files

### Files to Modify

- `src/gui/**core*config*`
- `src/gui/**recipe*`
- `src/controller/app_controller_services/gui_config_service.py`
- `src/gui/config_adapter_v26.py`
- `tests/gui_v2/**core*`
- `tests/gui_v2/**recipe*`
- `docs/StableNew Roadmap v2.6.md`

### Forbidden Files

- `src/pipeline/runner*`
- `src/video/**`

## Implementation Plan

1. Rename and narrow the base-generation surface.
2. Move stage-specific fields out of the base card.
3. Present saved recipe summaries alongside names.
4. Add GUI regressions for precedence visibility and recipe summaries.

## Testing Plan

- targeted GUI config/recipe tests
- persistence regression coverage

## Verification Criteria

### Success Criteria

1. Users can understand what is base generation vs stage override.
2. Saved recipes are usable without memorizing names.

### Failure Criteria

1. Hidden precedence remains.
2. Base/stage configuration ownership becomes less clear.

## Approval & Execution

Planner: ChatGPT/Codex
Executor: Codex
Reviewer: Human
Approval Status: Pending

## Next Steps

- secondary-motion tranche `PR-VIDEO-236` onward
