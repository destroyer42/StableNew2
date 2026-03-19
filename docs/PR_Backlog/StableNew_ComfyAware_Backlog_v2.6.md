# StableNew Comfy-Aware Backlog v2.6

Status: Active subordinate backlog
Updated: 2026-03-18

## Purpose

Extend StableNew's existing video architecture so ComfyUI can act as a managed
execution backend without becoming a second orchestration system.

This backlog starts from current repo truth, not from a hypothetical clean
slate.

## Current Repo Truth

The repo already has the necessary foundation:

- `src/video/video_backend_types.py`
- `src/video/video_backend_registry.py`
- `src/video/animatediff_backend.py`
- `src/video/svd_native_backend.py`
- `PipelineRunner` already builds internal `VideoExecutionRequest` objects
- canonical artifact/history infrastructure already exists

This means the Comfy plan must extend the existing `src/video/` seam rather
than inventing a new top-level video architecture.

## Core Invariants

All Comfy work must preserve:

- NJR as the only outer executable job contract
- queue/runner/history/artifacts owned by StableNew
- `VideoExecutionRequest` as an internal runner-to-backend request, not a new job model
- no Comfy imports outside `src/video/`
- no workflow JSON in GUI/controller/public runtime contracts

## Gating Dependencies

Comfy work is gated behind migration closure work:

- `PR-UNIFY-201-Canonical-Docs-Reset-and-Architecture-Constitution`
- `PR-NJR-202-Queue-Only-Submission-Contract`
- `PR-MIG-204-Delete-Live-Legacy-Execution-Seams`
- `PR-CONFIG-206-Canonical-Config-Unification`
- `PR-VIDEO-207-NJR-Video-Contract-Completion` `(Completed 2026-03-18)`

Do not expand Comfy scope while archive DTO seams and dual-path execution still
exist.

## Active Comfy PR Queue

### `PR-COMFY-208-Workflow-Registry-and-Compiler`

Create StableNew-owned workflow metadata and compilation layers under
`src/video/`.

Required outputs:

- workflow registry
- workflow spec
- deterministic compiler from StableNew-native video intent to backend-ready request

Rules:

- workflow JSON remains backend-internal
- GUI and controllers talk in StableNew-native fields only

### `PR-COMFY-209-Managed-Comfy-Runtime-and-Dependency-Probes`

Add a StableNew-managed local Comfy runtime parallel to WebUI, not inside it.

Required behavior:

- process lifecycle management
- stdout/stderr tails
- health probes
- dependency/model/node checks
- restart discipline

### `PR-COMFY-210-First-Pinned-LTX-Workflow`

Ship one pinned LTX workflow executed through:

`NJR -> Queue -> PipelineRunner -> Video backend registry -> Comfy backend -> Canonical artifacts/history/diagnostics`

Required outputs:

- replayable workflow metadata
- actionable dependency failures
- canonical artifact records

## Future Expansion After First LTX Workflow

These follow after the first managed workflow is stable:

- sequence orchestration for longer clips
- stitching and overlap handling
- interpolation and clip assembly integration
- continuity pack linkage
- story/shot planning linkage

These are roadmap items, not prerequisites for first Comfy integration.

## Done Definition

Comfy integration is successful when:

- switching between native and Comfy backends does not change top-level UI intent surfaces
- NJR still drives all submission and execution
- no Comfy details leak into controller or GUI contracts
- artifacts/history/replay remain canonical and backend-agnostic
