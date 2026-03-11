# PR-GUI-LEARN-033: Stage-Aware Variable System and Resource Selectors

**Status**: 🟡 Specification
**Priority**: HIGH
**Effort**: LARGE
**Phase**: Learning Recovery
**Date**: 2026-03-10

## Context & Motivation
The variable selector currently mixes numeric, resource, and LoRA behaviors in one fragile form. Resource-backed choices do not normalize WebUI resources correctly.

## Goals
1. Make variables stage-aware.
2. Normalize resource display/internal values using the same WebUI resource feed as Pipeline.
3. Show checklist selectors for models, VAEs, samplers, schedulers, and other non-numeric variables.

## Allowed Files
- `src/learning/variable_metadata.py`
- `src/gui/views/experiment_design_panel.py`
- `src/gui/controllers/learning_controller.py`
- `src/learning/variable_selection_contract.py` (new)
- `tests/learning_v2/`, `tests/gui_v2/`

## Forbidden Files
- queue/runner/pipeline execution core

## Implementation Plan
1. Replace flat `config_path` assumptions with stage-aware targets.
2. Normalize resources to display/internal pairs.
3. Filter visible variable choices based on stage capability.
4. Persist selected internal resource names in experiment state.

## Testing Plan
- resource checklist population and normalization
- stage-dependent variable availability
- save/load of selected resource values

## Next Steps
Execute after PR-032.
