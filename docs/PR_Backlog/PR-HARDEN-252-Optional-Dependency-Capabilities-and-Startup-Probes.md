# PR-HARDEN-252 - Optional Dependency Capabilities and Startup Probes

Status: Completed 2026-03-29

## Purpose

Consolidate optional runtime readiness into one repo-owned capability snapshot
used during startup and diagnostics.

## Delivered

- shared optional-dependency snapshot contract now lives in
  `src/app/optional_dependency_probes.py`
- Comfy workflow dependency probes and SVD postprocess capabilities now publish
  into one normalized capability map
- application diagnostics now surface the optional-dependency snapshot through
  `AppController.get_diagnostics_snapshot()`

## Validation

- `tests/app/test_optional_dependency_snapshot.py`
- `tests/controller/test_app_controller_diagnostics.py`
