# PR-HARDEN-252 - Optional Dependency Capabilities and Startup Probes

Status: Completed 2026-03-29

## Delivered

- one optional-dependency snapshot contract now unifies Comfy workflow probes
  and SVD postprocess capabilities
- startup/bootstrap code can carry that snapshot through the shared app kernel
- diagnostics now surface the optional-dependency capability map

## Validation

- `tests/app/test_optional_dependency_snapshot.py`
- `tests/controller/test_app_controller_diagnostics.py`
