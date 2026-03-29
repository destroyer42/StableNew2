# PR-GUI-PS6-009: Cutover to PySide6 Runtime

**Status**: ?? Specification
**Priority**: CRITICAL
**Effort**: MEDIUM
**Phase**: PySide6 Migration
**Date**: 2026-03-09

## Goals
Switch main runtime to PySide6 and retire Tk mainline path.

## Allowed Files
- src/app_factory.py
- src/main.py
- src/gui/** (deprecation/removal scope)
- src/gui_qt/**
- tests/gui_qt/**
- docs/PR_MAR26/PR-GUI-PS6-009-Cutover.md

## Forbidden Files
- src/pipeline/**
- src/queue/**

## Plan
1. Flip entrypoint to Qt host.
2. Remove Tk runtime path from mainline.
3. Keep rollback commit boundary explicit.

## Tests
- full test suite
- pytest -q tests/integration/test_golden_path_suite_v2_6.py

## Criteria
Green suite and no critical regressions in startup/run/stop/close.
