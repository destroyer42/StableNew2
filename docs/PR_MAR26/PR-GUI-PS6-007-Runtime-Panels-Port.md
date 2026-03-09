# PR-GUI-PS6-007: Port Queue/History/Preview/DebugHub to PySide6

**Status**: ?? Specification
**Priority**: HIGH
**Effort**: LARGE
**Phase**: PySide6 Migration
**Date**: 2026-03-09

## Goals
Port runtime event-heavy surfaces and preserve update behavior.

## Allowed Files
- src/gui_qt/panels/**
- src/gui/view_contracts/queue_status_contract.py
- tests/gui_qt/test_runtime_panels_parity.py
- docs/PR_MAR26/PR-GUI-PS6-007-Runtime-Panels-Port.md

## Forbidden Files
- src/pipeline/**
- src/queue/**

## Plan
1. Port queue/history/preview/debug panels.
2. Add high-frequency event replay tests.
3. Validate no UI-thread crashes.

## Tests
- pytest -q tests/gui_qt/test_runtime_panels_parity.py
- pytest -q tests/integration/test_golden_path_suite_v2_6.py

## Criteria
Event rendering parity and stable runtime behavior.
