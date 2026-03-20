# PR-COMFY-208 - Workflow Registry and Compiler

Status: Completed 2026-03-19

## Purpose

Add the first StableNew-owned Comfy/LTX contract layer under `src/video/`
without introducing a managed Comfy runtime yet.

This PR keeps NJR as the only outer job model and treats workflow metadata and
compilation as backend-internal video concerns.

## What Changed

### New workflow contract layer

Added:

- `src/video/workflow_contracts.py`
- `src/video/workflow_catalog.py`
- `src/video/workflow_registry.py`
- `src/video/workflow_compiler.py`

This introduces:

- `WorkflowSpec`
- `WorkflowDependencySpec`
- `WorkflowInputBinding`
- `WorkflowOutputBinding`
- `CompiledWorkflowRequest`
- `WorkflowRegistry`
- `WorkflowCompiler`

### Built-in pinned metadata-only workflow

Registered a first pinned metadata contract:

- `ltx_multiframe_anchor_v1`

This spec declares:

- Comfy as the backend id
- multi-frame anchor video capability tags
- StableNew-native inputs such as start anchor, end anchor, mid anchors,
  prompts, and motion profile
- explicit dependency declarations

No workflow JSON was introduced into GUI/controller/public runtime contracts.

### Internal request seam extension

Extended `VideoExecutionRequest` with optional workflow-ready fields:

- `start_anchor_path`
- `end_anchor_path`
- `mid_anchor_paths`
- `motion_profile`
- `workflow_id`
- `workflow_version`
- `workflow_inputs`
- `backend_options`

Existing native backends remain compatible because these fields are additive and
optional.

### Deterministic compilation

`WorkflowCompiler` now deterministically converts:

`WorkflowSpec + VideoExecutionRequest -> CompiledWorkflowRequest`

Behavior:

- required bindings fail fast with clear errors
- paths normalize to strings
- compiled inputs/outputs preserve declared binding order
- backend payloads include workflow id/version, inputs, outputs, and dependency
  snapshot data

### Config-contract follow-on

Updated `src/pipeline/config_contract_v26.py` so derived `backend_options` can
carry a future `video_workflow` config block under the canonical `video`
backend-options namespace.

### Adjacent hardening fix

While landing the new tests, a real circular-import edge surfaced through
`src.pipeline.__init__`.

Fix:

- converted `src/pipeline/__init__.py` to lazy exports instead of eager package
  imports

This is a safe packaging cleanup and does not change runtime execution
semantics.

## Tests

Added:

- `tests/video/test_workflow_registry.py`
- `tests/video/test_workflow_compiler.py`

Updated:

- `tests/pipeline/test_config_contract_v26.py`

Verification:

- `pytest tests/video/test_workflow_registry.py tests/video/test_workflow_compiler.py tests/pipeline/test_config_contract_v26.py tests/video/test_video_backend_registry.py tests/pipeline/test_video.py -q`
- `pytest --collect-only -q` -> `2370 collected / 1 skipped`
- `python -m compileall src/pipeline/__init__.py src/video src/pipeline/config_contract_v26.py tests/video/test_workflow_registry.py tests/video/test_workflow_compiler.py tests/pipeline/test_config_contract_v26.py tests/video/test_video_backend_registry.py tests/pipeline/test_video.py`

## Architectural Result

StableNew now has a proper workflow metadata and compiler layer for the Comfy
tranche, while preserving the current invariants:

- NJR remains the outer executable contract
- `VideoExecutionRequest` remains an internal runner/backend seam
- no Comfy imports leak outside `src/video/`
- no workflow JSON leaks outside `src/video/`

## Deferred To Next PRs

Owned by `PR-COMFY-209`:

- managed local Comfy runtime
- health checks and dependency probes
- backend supervision lifecycle

Owned by `PR-COMFY-210`:

- actual execution of the pinned LTX workflow through the queue/runner/backend
  path
- replay/diagnostics enrichment for real Comfy-backed runs

Next planned PR: `PR-COMFY-209`
