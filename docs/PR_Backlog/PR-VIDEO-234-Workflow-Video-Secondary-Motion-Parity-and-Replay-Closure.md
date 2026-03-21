# PR-VIDEO-234 - Workflow Video Secondary Motion Parity and Replay Closure

Status: Specification
Priority: HIGH
Effort: LARGE
Phase: Secondary Motion Backend Rollout
Date: 2026-03-20

## Context & Motivation

### Current Repo Truth

Workflow-video execution already has a StableNew-owned compiler, backend, and
manifest path, but unlike SVD and AnimateDiff it usually produces a final video
artifact without exposing a writable frame directory first. That makes it the
last runtime parity gap for the shared motion layer.

### Specific Problem

The secondary-motion design wants cross-backend parity before any workflow-
native Comfy node work. In the current repo, that means StableNew itself must
support an extract/apply/re-encode path for workflow-video outputs without
leaking workflow internals or requiring a new custom-node dependency.

### Why This PR Exists Now

After SVD and AnimateDiff are proven, workflow-video needs a parity path so the
shared motion carrier and learning summary mean the same thing across all three
existing video backends.

### Reference

- `docs/ARCHITECTURE_v2.6.md`
- `docs/StableNew Secondary Motion Layer Design.md`
- `docs/PR_Backlog/SECONDARY_MOTION_EXECUTABLE_ROADMAP_v2.6.md`
- `docs/PR_Backlog/PR-VIDEO-231-Shared-Secondary-Motion-Engine-and-Provenance-Contract.md`
- `docs/PR_Backlog/PR-VIDEO-233-AnimateDiff-Secondary-Motion-Frame-Pipeline-Integration.md`

## Goals & Non-Goals

### Goals

1. Add a StableNew-owned extract/apply/re-encode helper for workflow-video
   artifacts.
2. Apply the shared deterministic engine to workflow-video outputs when the
   runner policy says `apply` and prerequisites are present.
3. Preserve original workflow output provenance while making the postprocessed
   video the final primary artifact when motion is applied.
4. Stamp the same compact motion summary used by SVD and AnimateDiff into the
   manifest, replay fragment, and container metadata.
5. Keep the path skip-safe: if prerequisites are unavailable, the original
   workflow output remains canonical and the skip reason is recorded.

### Non-Goals

1. Do not add a workflow-native Comfy node or modify the pinned workflow spec in
   this PR.
2. Do not add new dependency-probe requirements in this PR.
3. Do not add GUI controls in this PR.
4. Do not add prompt-bias or native-backend motion modes in this PR.

## Guardrails

1. No Comfy imports may leak outside `src/video/`.
2. The workflow compiler and catalog remain unchanged in this PR; parity must be
   achieved without requiring a new custom node.
3. The extract/apply/re-encode helper lives under `src/video/motion/`, not as a
   new generic pipeline stage.
4. If motion applies, the final primary artifact may change to the re-encoded
   output, but the original workflow output path must be preserved inside the
   detailed motion provenance block.
5. If FFmpeg or other local prerequisites are unavailable, the backend must
   record an explicit skip reason and return the original workflow output.

## Allowed Files

### Files to Create

| File | Purpose |
| ------ | ------- |
| `src/video/motion/secondary_motion_video_reencode.py` | StableNew-owned extract/apply/re-encode helper |
| `tests/video/test_secondary_motion_video_reencode.py` | Helper coverage |

### Files to Modify

| File | Reason |
| ------ | ------ |
| `src/video/comfy_workflow_backend.py` | Apply parity path and preserve canonical provenance |
| `tests/video/test_comfy_workflow_backend.py` | Applied/skip-state assertions |
| `docs/SECONDARY_MOTION_POLICY_SCHEMA_v1.md` | Document workflow-video summary shape |

### Forbidden Files

| File/Directory | Reason |
| ---------------- | ------ |
| `src/video/workflow_catalog.py` | No workflow-spec changes in this PR |
| `src/video/workflow_compiler.py` | No workflow compiler changes in this PR |
| `src/video/comfy_dependency_probe.py` | No new runtime dependency requirement |
| `src/pipeline/pipeline_runner.py` | Runner carrier already exists |
| `src/gui/**` | No GUI work |
| `src/controller/**` | No controller work |

## Implementation Plan

### Step 1: Add the workflow-video parity helper

Create a StableNew-owned helper that extracts frames from a completed video,
applies the shared engine, and re-encodes a final artifact.

Required details:

- resolve FFmpeg using the repo's existing video-tooling paths
- keep the helper under `src/video/motion/`
- preserve both the original video path and the re-encoded final path in the
  detailed result
- reuse the same compact summary shape as the other backends

Files:

- create `src/video/motion/secondary_motion_video_reencode.py`
- create `tests/video/test_secondary_motion_video_reencode.py`

### Step 2: Apply the parity path inside the workflow backend

Teach the workflow-video backend to use the helper when motion is in `apply`
mode.

Required details:

- run the workflow as today and resolve the original output paths first
- inspect `request.context_metadata["secondary_motion_policy"]`
- if motion applies and prerequisites are available, run the parity helper and
  promote the re-encoded artifact to the final primary path
- if motion is skipped or unavailable, preserve the original output as the
  primary artifact

Files:

- modify `src/video/comfy_workflow_backend.py`
- modify `tests/video/test_comfy_workflow_backend.py`

### Step 3: Close replay and provenance semantics

Ensure workflow-video results use the same carrier shape as the other backends.

Required details:

- write the detailed motion block into the StableNew-owned manifest
- embed the compact summary in container metadata for the final artifact
- ensure the replay fragment includes the compact summary and the original
  workflow output path when re-encode occurred
- keep skip reasons explicit

Files:

- modify `src/video/comfy_workflow_backend.py`
- modify `docs/SECONDARY_MOTION_POLICY_SCHEMA_v1.md`

## Testing Plan

### Unit Tests

- `tests/video/test_secondary_motion_video_reencode.py`
- `tests/video/test_comfy_workflow_backend.py`

### Integration Tests

- none beyond backend-level coverage in this PR

### Journey or Smoke Coverage

- optional local workflow-video run if the managed Comfy runtime is available

### Manual Verification

1. Run a workflow-video job with `secondary_motion.mode=apply` and confirm the
   backend either produces a re-encoded final artifact or records an explicit
   skip reason.
2. Confirm the original workflow output path is preserved in detailed motion
   provenance when re-encode occurs.
3. Confirm replay and container metadata use the same compact summary keys as
   SVD and AnimateDiff.

Suggested command set:

- `pytest tests/video/test_secondary_motion_video_reencode.py tests/video/test_comfy_workflow_backend.py -q`

## Verification Criteria

### Success Criteria

1. Workflow-video has a StableNew-owned parity path for shared secondary motion.
2. The backend records the same compact motion summary shape as the other
   backends.
3. Original workflow output provenance survives when re-encode occurs.
4. Missing prerequisites downgrade to explicit skip reasons without failing the
   workflow artifact.

### Failure Criteria

1. The PR requires a new custom Comfy node or workflow-spec change.
2. The final artifact loses traceability back to the original workflow output.
3. Workflow-video invents a backend-specific motion summary shape.
4. Missing local tools cause the job to fail instead of recording a skip.

## Risk Assessment

### Low-Risk Areas

- parity-helper unit coverage once the helper exists

### Medium-Risk Areas with Mitigation

- artifact-path rewrites after re-encode
  - Mitigation: preserve both original and final paths explicitly in the motion
    runtime block and test both cases

### High-Risk Areas with Mitigation

- local-tool brittleness during extract/re-encode
  - Mitigation: treat missing prerequisites as explicit skip states, not hard
    failures

### Rollback Plan

Remove the workflow-video parity helper and backend hook while leaving SVD,
AnimateDiff, and the shared engine intact.

## Tech Debt Analysis

### Debt Removed

- last major backend parity gap for the shared motion carrier
- absence of canonical workflow-video motion provenance

### Debt Intentionally Deferred

- workflow-native Comfy/LTX node integration
  - Owner: follow-on PR after runtime tranche closure
- learning integration
  - Owner: `PR-VIDEO-235`
- GUI exposure
  - Owner: follow-on PR after `PR-VIDEO-235`

## Documentation Updates

- `docs/SECONDARY_MOTION_POLICY_SCHEMA_v1.md`
- completion-status updates in:
  - `docs/StableNew Roadmap v2.6.md`
  - `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`

## Dependencies

### Internal Module Dependencies

- `PR-VIDEO-230` motion contract and runner carrier
- `PR-VIDEO-231` shared engine and provenance helpers
- existing workflow-video backend and managed-runtime path

### External Tools or Runtimes

- FFmpeg, already part of the repo's existing video/export tooling story

## Approval & Execution

Planner: GitHub Copilot
Executor: Codex or Copilot
Reviewer: Human + architecture review
Approval Status: Pending

## Next Steps

1. `PR-VIDEO-235-Learning-and-Risk-Aware-Secondary-Motion-Feedback`
2. follow-on workflow-native Comfy/LTX node planning after runtime tranche closure
