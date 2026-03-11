# PR-GUI-LEARN-034: LoRA Experimentation Rebuild

**Status**: 🟡 Specification
**Priority**: HIGH
**Effort**: MEDIUM
**Phase**: Learning Recovery
**Date**: 2026-03-10

## Context & Motivation
LoRA testing currently relies on a brittle snapshot of stage-card config and does not cleanly support comparison vs strength sweep workflows.

## Goals
1. Discover current LoRAs from prompt/runtime metadata reliably.
2. Support one-LoRA strength sweep and multi-LoRA comparison.
3. Prevent stuck UI state when changing away from LoRA variables.

## Allowed Files
- `src/gui/views/experiment_design_panel.py`
- `src/gui/controllers/learning_controller.py`
- `src/learning/lora_variable_service.py` (new)
- LoRA learning tests

## Implementation Plan
1. Build a dedicated LoRA variable service.
2. Merge prompt-derived and runtime-config LoRA sources.
3. Normalize LoRA selection state for persistence.

## Testing Plan
- LoRA discovery
- strength sweep generation
- comparison generation
- mode switching stability

## Next Steps
Execute after PR-033.
