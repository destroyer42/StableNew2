# PR-ARCH-246 - Architecture Enforcement Expansion and Import Guards

Status: Specification
Priority: HIGH
Date: 2026-03-29

## Scope

- guard controller-to-GUI import bans in core paths
- guard archive/reference import bans
- guard controller-side Tk imports and direct widget mutation
- guard backend-runtime imports so they stay behind the controller port layer

## Repo Truth

This scope is now delivered in code by:

- `tests/system/test_architecture_enforcement_v2.py`
- `tests/safety/test_controller_core_no_gui_imports.py`
- `tests/safety/test_no_archive_python_modules_under_src.py`

## Validation

- `pytest tests/system/test_architecture_enforcement_v2.py tests/safety/test_controller_core_no_gui_imports.py tests/safety/test_no_archive_python_modules_under_src.py -q`

