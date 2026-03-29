# PR-VIDEO-255 - Workflow Registry Governance and Pinning Closure

Status: Completed 2026-03-29

## Purpose

Close the workflow-registry rollout by making governance state and pinned
revision explicit parts of the canonical workflow registry contract.

## Delivered

- workflow specs now carry `governance_state`, `pinned_revision`, and
  `governance_notes`
- workflow registry lookup now rejects non-approved or unpinned workflows
- video workflow controller surfaces governance metadata to the GUI-facing
  workflow list

## Validation

- `tests/video/test_workflow_registry.py`
- `tests/video/test_workflow_compiler.py`
- `tests/controller/test_video_workflow_controller.py`
