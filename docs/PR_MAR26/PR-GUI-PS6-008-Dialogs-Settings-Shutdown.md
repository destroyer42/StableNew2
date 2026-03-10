# PR-GUI-PS6-008: Port Dialogs + Settings + Shutdown Wiring

**Status**: ?? Specification
**Priority**: HIGH
**Effort**: MEDIUM
**Phase**: PySide6 Migration
**Date**: 2026-03-09

## Goals
Port modal dialogs/settings and ensure deterministic shutdown with WebUI manager.

## Allowed Files
- src/gui_qt/dialogs/**
- src/gui_qt/settings/**
- src/app_factory.py
- tests/gui_qt/test_dialogs_and_shutdown.py
- docs/PR_MAR26/PR-GUI-PS6-008-Dialogs-Settings-Shutdown.md

## Forbidden Files
- src/pipeline/**
- src/queue/**

## Plan
1. Implement modal/dialog flows.
2. Port settings surfaces.
3. Validate shutdown lifecycle with managed processes.

## Tests
- pytest -q tests/gui_qt/test_dialogs_and_shutdown.py
- pytest -q tests/integration/test_golden_path_suite_v2_6.py

## Criteria
No hangs/deadlocks/orphaned process regressions.
