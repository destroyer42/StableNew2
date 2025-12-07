PR-081D-7 — GUI Harness Cleanup Pytest Marker Registration + V2 Entrypoint Tests

Intent
Fix all GUI-harness related test failures, including:

Unknown pytest.mark.gui

Stage cards header test

Tooltip helper test

Stage-checkbox ordering

Entrypoint tests failing with “main_window.tk import error” after V1 removal

Smoke tests that expect V2 GUI entrypoint

This PR is GUI-testing only and does not modify pipeline logic.

Scope & Risk

Risk: Low

Subsystem: GUI V2 test harness + minimal adapter glue

No backend changes

No modifications to forbidden GUI V2 core files (layout, main window) unless patch is trivial

Allowed Files
pytest.ini
tests/gui_v2/*  (all GUI tests)
src/gui/utils/*  (tooltip helper if required)
src/gui/panels_v2/pipeline_config_panel_v2.py  (checkbox order if required)
src/gui/stage_cards_v2/*  (header consistency only)
src/gui/tooltip.py

Forbidden Files
src/gui/main_window_v2.py   (unless trivial import shim)
src/main.py
src/controller/*
src/pipeline/*

Implementation Plan
1. Register pytest GUI marker

Add/modify pytest.ini:

[pytest]
markers =
    gui: GUI-level tests for StableNew V2


This removes ~25 warnings.

2. Implement minimal TooltipHelper show/hide logic

Tests expect:

tooltip.show()
tooltip.hide()


Implement no-ops that still set an internal visible flag.

3. Fix stage-card header test

Ensure each stage card exposes a consistent single header widget:

Adjust StageCardBaseV2 or subclasses to set self.header_label

Guarantee winfo_children() includes exactly one header container

4. Fix pipeline stage checkbox order

Test expects:

Enable txt2img
Enable img2img
Enable ADetailer
Enable upscale


Implement deterministic ordering for checkboxes in PipelineConfigPanelV2.

5. Fix GUI entrypoint tests

Two failing tests:

test_entrypoint_uses_v2_gui.py

test_gui_v2_layout_skeleton.py

Tests expect:

from src.gui.main_window_v2 import StableNewGUI


But V1 imports used:

src.gui.main_window.tk


Add a simple shim in test harness:

# Option A: Provide alias
from src.gui.main_window_v2 import StableNewGUI as StableNewGUIV2


Or (preferable): update tests to import V2 entrypoint directly.

6. Ensure GUI test harness stubs are correct

Make sure DummyPipelineController exposes:

get_current_config()

Minimal methods needed by Pipeline tab wiring tests

Acceptance Criteria
✔ No more PytestUnknownMarkWarning
✔ Tooltip helper tests pass
✔ Stage-card header count tests pass
✔ Checkbox order tests pass
✔ GUI entrypoint tests reference correct V2 imports
✔ Main window V2 smoke tests pass
✔ No modification to main window core logic
Validation Checklist

GUI loads

Layout skeleton test passes

Pipeline tab wiring resolved

Tooltip helper functional

No regressions in V2 UI behavior

🚀 Deliverables

Updated pytest configuration

Updated tooltip helper

Fixed GUI V2 tests and adapters

V2 entrypoint tests passing