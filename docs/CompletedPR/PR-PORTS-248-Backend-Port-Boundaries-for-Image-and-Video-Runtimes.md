# PR-PORTS-248 - Backend Port Boundaries for Image and Video Runtimes

Status: Completed 2026-03-29

## Delivered

- controller-owned runtime ports now include image-runtime client/runner factories and a video workflow-registry port
- default concrete adapters live in `src/controller/ports/default_runtime_ports.py`
- `AppController`, `PipelineController`, and `VideoWorkflowController` now consume those ports instead of importing concrete backend/runtime classes directly
- architecture enforcement now ensures concrete backend imports stay behind the controller port layer

## Validation

- `tests/controller/test_runtime_ports_contract.py`
- `tests/controller/test_runtime_backend_port_wiring.py`
- `tests/system/test_architecture_enforcement_v2.py`

