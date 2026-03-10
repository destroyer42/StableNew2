# PR-GUI-PS6-004: PySide6 App Spine (Migration Branch)

**Status**: ?? Specification
**Priority**: HIGH
**Effort**: LARGE
**Phase**: PySide6 Migration
**Date**: 2026-03-09

## Goals
Add Qt bootstrap + shell window using existing state/controller contracts; no cutover.

## Allowed Files
- src/gui_qt/** (new)
- src/app_factory.py
- tests/gui_qt/test_qt_spine_boot.py
- docs/PR_MAR26/PR-GUI-PS6-004-PySide6-App-Spine.md

## Forbidden Files
- src/pipeline/**
- src/queue/**
- src/api/**

## Plan
1. Add `gui_qt` module skeleton and app entry.
2. Construct shell tabs and status surfaces.
3. Attach existing controller APIs through adapters.
4. Add boot/shutdown smoke tests.

## Tests
- pytest -q tests/gui_qt/test_qt_spine_boot.py
- pytest -q tests/integration/test_golden_path_suite_v2_6.py

## Criteria
Qt app boots to idle and shuts down cleanly without affecting Tk path.
