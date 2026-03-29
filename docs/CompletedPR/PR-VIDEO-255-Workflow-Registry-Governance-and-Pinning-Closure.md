# PR-VIDEO-255 - Workflow Registry Governance and Pinning Closure

Status: Completed 2026-03-29

## Delivered

- workflow specs now encode governance state and pinned revision explicitly
- only approved, pinned workflows are returned by the canonical registry
- GUI/controller workflow listing now surfaces the governance metadata

## Validation

- `tests/video/test_workflow_registry.py`
- `tests/video/test_workflow_compiler.py`
- `tests/controller/test_video_workflow_controller.py`
