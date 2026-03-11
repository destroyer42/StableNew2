# PR-GUI-LEARN-035: Experiment Form and Layout Overhaul

**Status**: Implemented
**Priority**: HIGH
**Effort**: MEDIUM
**Phase**: Learning Recovery
**Date**: 2026-03-10

## Context & Motivation
The Learning form was cluttered, poorly grouped, and visually inconsistent with the rest of the dark-mode UI.

## Goals
1. Bring Learning form styling into the dark-mode UI system.
2. Reorganize the form into clear sections.
3. Fix poor layout issues such as `Images per Variant`.
4. Auto-generate suggested experiment name and description strings.

## Allowed Files
- `src/gui/views/experiment_design_panel.py`
- `src/gui/views/learning_tab_frame_v2.py`
- `src/gui/views/learning_plan_table.py`
- `src/learning/experiment_naming.py`
- related GUI tests

## Implementation Summary
1. Added experiment identity generation in `src/learning/experiment_naming.py`.
2. Updated `ExperimentDesignPanel` to:
   - dark-theme prompt editing controls
   - show stage helper text
   - suggest experiment names and descriptions
   - surface a live summary preview
   - clean up the `Images per Variant` layout
3. Added regression coverage for generated identity behavior.

## Validation
- `tests/gui_v2/test_experiment_design_panel_stage_contract.py`
- `tests/learning_v2/test_experiment_naming.py`

