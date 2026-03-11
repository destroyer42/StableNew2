# PR-GUI-LEARN-036: Review Pane Redesign and Rating Model Upgrade

**Status**: Implemented
**Priority**: HIGH
**Effort**: LARGE
**Phase**: Learning Recovery
**Date**: 2026-03-10

## Context & Motivation
The prior Learning review pane was too small, too light-themed, and too simplistic to support reliable review and learning.

## Goals
1. Expand and dark-theme the review pane.
2. Add larger image viewing and better metadata display.
3. Upgrade rating to support structured sub-scores and context-sensitive categories.

## Allowed Files
- `src/gui/views/learning_review_panel.py`
- `src/gui/controllers/learning_controller.py`
- `src/learning/rating_schema.py`
- related tests

## Implementation Summary
1. Added `src/learning/rating_schema.py` for context-aware rating categories and blended aggregate scoring.
2. Reworked `LearningReviewPanel` to:
   - use dark-mode text and list surfaces
   - enlarge preview images
   - show stage information in metadata
   - collect context flags and stage-relevant sub-scores
3. Extended `LearningController.record_rating(...)` to persist structured rating details while preserving aggregate compatibility.
4. Tagged review-tab-derived feedback separately from experiment ratings to support downstream analytics.

## Validation
- `tests/learning_v2/test_learning_review_panel_controller_resolution.py`
- `tests/learning_v2/test_rating_schema.py`
- `tests/learning_v2/test_recommendation_display.py`

