# PR-PORTS-248 - Backend Port Boundaries for Image and Video Runtimes

Status: Specification
Priority: HIGH
Date: 2026-03-29

## Scope

- expand controller-owned runtime ports beyond the narrow NJR summary contracts
- move controller-side image runtime client/runner creation behind StableNew-owned ports
- move controller-side video workflow registry lookup behind a StableNew-owned port
- keep direct backend imports isolated to the controller port adapter layer

## Delivered Slice

- expanded `src/controller/ports/runtime_ports.py` with image-runtime and workflow-registry protocols
- added `src/controller/ports/default_runtime_ports.py` as the only controller-side concrete adapter layer
- wired `src/controller/app_controller.py`, `src/controller/pipeline_controller.py`, and `src/controller/video_workflow_controller.py` through the new ports

## Validation

- `pytest tests/controller/test_runtime_ports_contract.py tests/controller/test_runtime_backend_port_wiring.py -q`

