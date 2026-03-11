# PR-GUI-LEARN-035: Experiment Form and Layout Overhaul

**Status**: 🟡 Specification
**Priority**: HIGH
**Effort**: MEDIUM
**Phase**: Learning Recovery
**Date**: 2026-03-10

## Context & Motivation
The Learning form is cluttered, poorly grouped, and visually inconsistent with the rest of the dark-mode UI.

## Goals
1. Bring Learning form styling into the dark-mode UI system.
2. Reorganize the form into clear sections.
3. Fix poor layout issues such as `Images per Variant`.
4. Auto-generate suggested experiment name/description strings.

## Allowed Files
- `src/gui/views/experiment_design_panel.py`
- `src/gui/views/learning_tab_frame_v2.py`
- `src/gui/views/learning_plan_table.py`
- related GUI tests

## Implementation Plan
1. Split the experiment form into sections.
2. Replace default-looking controls with tokenized dark-mode surfaces.
3. Add generated naming/description helpers.
4. Improve plan-table labeling and stage visibility.

## Testing Plan
- layout smoke tests
- name/description generation tests
- stage switching display tests

## Next Steps
Execute after PR-034.
