# PR-GUI-PS6-005: Port Prompt + Pipeline Tabs to PySide6

**Status**: ?? Specification
**Priority**: CRITICAL
**Effort**: LARGE
**Phase**: PySide6 Migration
**Date**: 2026-03-09

## Goals
Port Prompt/Pipeline surfaces using view contracts and existing controller entrypoints.

## Allowed Files
- src/gui_qt/views/prompt_tab_qt.py
- src/gui_qt/views/pipeline_tab_qt.py
- src/gui_qt/widgets/**
- src/gui/view_contracts/**
- tests/gui_qt/test_prompt_pipeline_parity.py
- docs/PR_MAR26/PR-GUI-PS6-005-Prompt-Pipeline-Port.md

## Forbidden Files
- src/pipeline/**
- src/queue/**

## Plan
1. Implement Qt prompt editor + pipeline controls.
2. Bind to current controller APIs only.
3. Add parity tests against contract outputs.

## Tests
- pytest -q tests/gui_qt/test_prompt_pipeline_parity.py
- pytest -q tests/integration/test_golden_path_suite_v2_6.py

## Criteria
Equivalent state transitions and controller calls vs Tk surfaces.
