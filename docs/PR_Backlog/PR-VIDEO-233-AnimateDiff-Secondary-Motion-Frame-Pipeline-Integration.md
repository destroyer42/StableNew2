# PR-VIDEO-233 - AnimateDiff Secondary Motion Frame Pipeline Integration

Status: Specification
Priority: HIGH
Effort: LARGE
Phase: Secondary Motion Backend Rollout
Date: 2026-03-20

## Context & Motivation

### Current Repo Truth

AnimateDiff already has the right low-level seam for shared secondary motion:
`Pipeline.run_animatediff_stage(...)` writes a deterministic frame directory and
then assembles the final MP4 from those frames. That means the shared engine can
be inserted without changing the outer queue/runner model or inventing a second
video stage.

### Specific Problem

The shared engine from `PR-VIDEO-231` is not yet wired into AnimateDiff. If the
integration is done carelessly, it will either mutate WebUI payload semantics,
redefine `motion_profile`, or make the final video artifact depend on a prompt
rewrite path instead of a deterministic shared postprocess.

### Why This PR Exists Now

After SVD proves the first real runtime path in `PR-VIDEO-232`, AnimateDiff is
the next backend that can adopt the same shared engine with relatively low risk
because its frame directory already exists before encode time.

### Reference

- `docs/ARCHITECTURE_v2.6.md`
- `docs/StableNew Secondary Motion Layer Design.md`
- `docs/PR_Backlog/SECONDARY_MOTION_EXECUTABLE_ROADMAP_v2.6.md`
- `docs/PR_Backlog/PR-VIDEO-231-Shared-Secondary-Motion-Engine-and-Provenance-Contract.md`
- `docs/PR_Backlog/PR-VIDEO-232-SVD-Native-Secondary-Motion-Postprocess-Integration.md`

## Goals & Non-Goals

### Goals

1. Inject a transient AnimateDiff motion-execution block from the runner when
   `secondary_motion.mode=apply`.
2. Run the shared deterministic engine on the written frame directory after
   frame export and before MP4 assembly.
3. Preserve final video-path semantics while recording whether motion was
   applied, skipped, or unavailable.
4. Stamp the canonical motion summary into the AnimateDiff manifest, replay
   fragment, and container metadata.
5. Keep the entire path skip-safe: if motion cannot be applied, AnimateDiff must
   still assemble the original frames into the final artifact.

### Non-Goals

1. Do not add prompt rewriting, motion-LoRA injection, or latent/native-bias
   behavior in this PR.
2. Do not add workflow-video integration in this PR.
3. Do not add GUI controls in this PR.
4. Do not change WebUI payload semantics beyond metadata needed to preserve the
   existing stage result.

## Guardrails

1. User intent remains under `intent_config["secondary_motion"]`.
2. `motion_profile` keeps its current meaning and must not be repurposed.
3. Any runtime motion block injected into AnimateDiff config must be transient
   and must not be written back into NJR config or snapshots.
4. The final MP4 output path remains the canonical primary artifact path.
5. If the motion engine is skipped or unavailable, the original frame directory
   must still be used for encode and the skip reason must be recorded.
6. No prompt mutation is allowed in this PR.

## Allowed Files

### Files to Create

| File | Purpose |
| ------ | ------- |
| `tests/pipeline/test_animatediff_secondary_motion_runtime.py` | Focused AnimateDiff motion coverage |

### Files to Modify

| File | Reason |
| ------ | ------ |
| `src/pipeline/pipeline_runner.py` | Inject transient AnimateDiff motion execution config |
| `src/pipeline/executor.py` | Apply the shared engine between frame write and encode |
| `src/video/animatediff_backend.py` | Extend replay fragment and backend metadata with motion summary |
| `tests/pipeline/test_animatediff_runtime.py` | Frame-assembly assertions |
| `tests/pipeline/test_pipeline_runner.py` | Runner injection assertions |
| `docs/SECONDARY_MOTION_POLICY_SCHEMA_v1.md` | Document AnimateDiff runtime summary shape |

### Forbidden Files

| File/Directory | Reason |
| ---------------- | ------ |
| `src/video/svd_config.py` | No SVD work |
| `src/video/svd_postprocess.py` | No SVD work |
| `src/video/comfy_workflow_backend.py` | No workflow-video work |
| `src/video/workflow_catalog.py` | No workflow changes |
| `src/gui/**` | No GUI work |
| `src/controller/**` | No controller work |

## Implementation Plan

### Step 1: Inject a transient AnimateDiff motion block from the runner

Map the canonical motion policy to a transient runtime-only AnimateDiff config.

Required details:

- perform the mapping in the runner when stage `animatediff` is about to
  execute
- carry only the fields the shared engine needs
- do not persist the transient block back into NJR config or builder outputs

Files:

- modify `src/pipeline/pipeline_runner.py`
- modify `tests/pipeline/test_pipeline_runner.py`

### Step 2: Apply shared motion between frame write and video encode

Insert the shared engine into the AnimateDiff frame pipeline.

Required details:

- write the original frame directory first
- if motion application is enabled and available, run the shared engine on that
  frame directory and use the returned frame set for encode
- if motion application is skipped or unavailable, continue with the original
  frame set
- preserve ordering, frame count semantics, and output video naming

Files:

- modify `src/pipeline/executor.py`
- modify `tests/pipeline/test_animatediff_runtime.py`
- create `tests/pipeline/test_animatediff_secondary_motion_runtime.py`

### Step 3: Stamp canonical provenance into the AnimateDiff result

Ensure manifests, container metadata, and replay fragments carry the same motion
summary shape used by SVD.

Required details:

- record the detailed motion block in the AnimateDiff manifest
- embed the compact summary in container metadata
- extend the backend replay fragment and raw stage metadata with the same
  compact summary
- preserve `applied`, `skipped`, and `unavailable` statuses explicitly

Files:

- modify `src/pipeline/executor.py`
- modify `src/video/animatediff_backend.py`
- modify `docs/SECONDARY_MOTION_POLICY_SCHEMA_v1.md`

## Testing Plan

### Unit Tests

- `tests/pipeline/test_animatediff_runtime.py`
- `tests/pipeline/test_animatediff_secondary_motion_runtime.py`

### Integration Tests

- `tests/pipeline/test_pipeline_runner.py`

### Journey or Smoke Coverage

- optional local AnimateDiff run if the WebUI/runtime is available

### Manual Verification

1. Run an AnimateDiff job with `secondary_motion.mode=apply` and confirm the
   runner injects a transient motion block without changing prompt payloads.
2. Confirm MP4 assembly uses transformed frames when motion applies and original
   frames when it is skipped.
3. Confirm the manifest, replay fragment, and container metadata carry the same
   compact motion summary.

Suggested command set:

- `pytest tests/pipeline/test_animatediff_runtime.py tests/pipeline/test_animatediff_secondary_motion_runtime.py tests/pipeline/test_pipeline_runner.py -q`

## Verification Criteria

### Success Criteria

1. AnimateDiff can apply the shared engine after frame write and before encode.
2. The final primary artifact path remains stable.
3. AnimateDiff records the canonical motion summary across manifest, replay, and
   container surfaces.
4. Skip and unavailable states still produce the expected video artifact.

### Failure Criteria

1. Prompt or WebUI payload semantics are changed in this PR.
2. The runtime path introduces a second output-contract shape.
3. AnimateDiff fails the job when motion is skipped or unavailable.
4. The PR overloads `motion_profile` with secondary-motion meaning.

## Risk Assessment

### Low-Risk Areas

- replay-fragment and metadata extension once the summary helper exists

### Medium-Risk Areas with Mitigation

- frame-directory bookkeeping
  - Mitigation: keep explicit tests for original-frame and transformed-frame
    encode paths

### High-Risk Areas with Mitigation

- accidental prompt mutation or WebUI payload drift
  - Mitigation: keep this PR postprocess-only and assert no prompt rewrite path
    is used

### Rollback Plan

Remove the AnimateDiff motion path while leaving SVD and the shared engine
intact.

## Tech Debt Analysis

### Debt Removed

- absence of a second runtime backend for the shared motion engine
- lack of AnimateDiff motion provenance in canonical video artifacts

### Debt Intentionally Deferred

- workflow-video parity integration
  - Owner: `PR-VIDEO-234`
- learning integration
  - Owner: `PR-VIDEO-235`
- prompt/native-bias experimentation
  - Owner: follow-on PR after runtime tranche closure

## Documentation Updates

- `docs/SECONDARY_MOTION_POLICY_SCHEMA_v1.md`
- completion-status updates in:
  - `docs/StableNew Roadmap v2.6.md`
  - `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`

## Dependencies

### Internal Module Dependencies

- `PR-VIDEO-230` motion contract and runner carrier
- `PR-VIDEO-231` shared engine and provenance helpers
- existing AnimateDiff runtime in `src/pipeline/executor.py`

### External Tools or Runtimes

- existing AnimateDiff/WebUI runtime

## Approval & Execution

Planner: GitHub Copilot
Executor: Codex or Copilot
Reviewer: Human + architecture review
Approval Status: Pending

## Next Steps

1. `PR-VIDEO-234-Workflow-Video-Secondary-Motion-Parity-and-Replay-Closure`
2. `PR-VIDEO-235-Learning-and-Risk-Aware-Secondary-Motion-Feedback`
