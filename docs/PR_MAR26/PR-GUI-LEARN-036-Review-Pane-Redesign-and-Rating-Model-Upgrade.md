# PR-GUI-LEARN-036: Review Pane Redesign and Rating Model Upgrade

**Status**: 🟡 Specification
**Priority**: HIGH
**Effort**: LARGE
**Phase**: Learning Recovery
**Date**: 2026-03-10

## Context & Motivation
The current Learning review pane is too small, too light-themed, and too simplistic to support reliable review and learning.

## Goals
1. Expand and dark-theme the review pane.
2. Add resizable image viewing and better metadata display.
3. Upgrade rating to support structured sub-scores and context-sensitive categories.

## Allowed Files
- `src/gui/views/learning_review_panel.py`
- `src/gui/controllers/learning_controller.py`
- `src/learning/learning_record.py`
- `src/learning/rating_schema.py` (new)
- related tests

## Implementation Plan
1. Rebuild the panel layout.
2. Persist structured rating details alongside aggregate rating.
3. Surface context-aware sub-scores when appropriate.

## Testing Plan
- rating save/override tests
- review restore tests
- image navigation and display tests

## Next Steps
Execute after PR-035.
