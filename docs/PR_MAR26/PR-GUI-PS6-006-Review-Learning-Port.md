# PR-GUI-PS6-006: Port Review + Learning Tabs to PySide6

**Status**: ?? Specification
**Priority**: CRITICAL
**Effort**: LARGE
**Phase**: PySide6 Migration
**Date**: 2026-03-09

## Goals
Port Review/Learning flows, including resume, undo, batch rerun, and prompt modes.

## Allowed Files
- src/gui_qt/views/review_tab_qt.py
- src/gui_qt/views/learning_tab_qt.py
- src/gui/controllers/review_workflow_adapter.py
- src/gui/view_contracts/**
- tests/gui_qt/test_review_learning_parity.py
- docs/PR_MAR26/PR-GUI-PS6-006-Review-Learning-Port.md

## Forbidden Files
- src/pipeline/**
- src/queue/**

## Plan
1. Port UI flows using existing adapters/contracts.
2. Add persistence/resume/undo parity tests.
3. Validate batch rerun parity.

## Tests
- pytest -q tests/gui_qt/test_review_learning_parity.py
- pytest -q tests/integration/test_golden_path_suite_v2_6.py

## Criteria
No behavioral regression in review/learning workflow.
