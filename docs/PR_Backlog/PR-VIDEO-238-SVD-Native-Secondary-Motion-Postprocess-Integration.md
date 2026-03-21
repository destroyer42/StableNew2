# PR-VIDEO-238 - SVD Native Secondary Motion Postprocess Integration

Status: Specification
Priority: HIGH
Effort: LARGE
Phase: Secondary Motion Backend Rollout
Date: 2026-03-20

## Context & Motivation

### Current Repo Truth

SVD is the safest first backend for real secondary-motion application because it
already has a typed config model, a structured postprocess pipeline, and a
worker-based frame-processing path. That makes it the lowest-risk place to land
the first real runtime mutation after the shared engine contract is frozen.

### Specific Problem

The shared engine from `PR-VIDEO-237` is not useful to end users until at least
one backend can apply it. SVD is the correct first integration target, but the
repo must not expose a second user-owned config surface under `svd_native`
instead of using the canonical `intent_config["secondary_motion"]` contract.

### Why This PR Exists Now

This PR proves the runtime path on the backend with the strongest existing
postprocess seam, while keeping the outer contract stable and avoiding prompt or
workflow complexity.

### Reference

- `docs/ARCHITECTURE_v2.6.md`
- `docs/StableNew Secondary Motion Layer Design.md`
- `docs/PR_Backlog/SECONDARY_MOTION_EXECUTABLE_ROADMAP_v2.6.md`
- `docs/PR_Backlog/PR-VIDEO-237-Shared-Secondary-Motion-Engine-and-Provenance-Contract.md`

## Goals & Non-Goals

### Goals

1. Extend the SVD typed postprocess config to accept a transient
   `secondary_motion` execution block.
2. Inject the derived motion policy from the runner into a copied SVD stage
   config without mutating the user-owned outer contract.
3. Run secondary motion as SVD postprocess stage zero, before face restore,
   interpolation, and upscale.
4. Record canonical motion provenance in the SVD manifest, replay fragment, and
   container metadata summary.
5. Keep disabled and unavailable states skip-safe and explicitly recorded.

### Non-Goals

1. Do not add AnimateDiff integration in this PR.
2. Do not add workflow-video integration in this PR.
3. Do not add prompt-bias or native-backend motion modes in this PR.
4. Do not add GUI controls in this PR.
5. Do not create a persistent user-owned `svd_native.postprocess.secondary_motion`
   config surface.

## Guardrails

1. User intent remains under `intent_config["secondary_motion"]`.
2. The runner may inject only a transient backend-local execution block into a
   copied SVD stage config.
3. Postprocess order must be:
   `secondary_motion -> face_restore -> interpolation -> upscale` when motion is
   applied.
4. If motion is disabled, not applicable, or unavailable, the SVD artifact must
   still complete and the skip reason must be recorded.
5. SVD inference semantics outside the postprocess path must remain unchanged.

## Allowed Files

### Files to Create

| File | Purpose |
| ------ | ------- |
| `tests/video/test_svd_secondary_motion_integration.py` | Focused end-to-end SVD motion coverage |

### Files to Modify

| File | Reason |
| ------ | ------ |
| `src/pipeline/pipeline_runner.py` | Inject transient SVD motion execution config |
| `src/video/svd_config.py` | Add typed `secondary_motion` postprocess block |
| `src/video/svd_postprocess.py` | Run motion as postprocess stage zero |
| `src/video/svd_postprocess_worker.py` | Accept the shared worker action for SVD |
| `src/video/svd_runner.py` | Stamp manifest and container metadata with canonical motion summary |
| `src/pipeline/executor.py` | Preserve the new SVD runtime metadata in stage results |
| `src/video/svd_native_backend.py` | Extend replay fragment with motion summary |
| `tests/video/test_svd_postprocess.py` | Stage ordering and skip-state assertions |
| `tests/video/test_svd_postprocess_worker.py` | Worker action coverage |
| `tests/video/test_svd_runner.py` | Manifest and container-summary assertions |
| `tests/pipeline/test_svd_runtime.py` | Pipeline SVD runtime assertions |
| `tests/pipeline/test_pipeline_runner.py` | Runner injection assertions |
| `docs/SECONDARY_MOTION_POLICY_SCHEMA_v1.md` | Document applied SVD summary shape |

### Forbidden Files

| File/Directory | Reason |
| ---------------- | ------ |
| `src/video/animatediff_backend.py` | No AnimateDiff work |
| `src/video/comfy_workflow_backend.py` | No workflow-video work |
| `src/video/workflow_catalog.py` | No workflow contract changes |
| `src/gui/**` | No GUI work |
| `src/controller/**` | No controller work |

## Implementation Plan

### Step 1: Extend the typed SVD postprocess contract

Add a transient SVD motion block under the postprocess config.

Required details:

- include the fields the shared engine actually needs:
  `enabled`, `policy_id`, `seed`, `intensity`, `damping`, `frequency_hz`,
  `cap_pixels`, `regions`, and `skip_reason`
- mark it as internal execution state derived from the runner policy, not as a
  new user-facing config surface
- keep validation consistent with the shared engine and summary contract

Files:

- modify `src/video/svd_config.py`

### Step 2: Inject the transient execution block from the runner

Map the canonical motion policy to SVD-local runtime config without mutating the
outer contract.

Required details:

- plan secondary motion in the runner using the contract from `PR-VIDEO-236`
- when stage `svd_native` is executing and motion is in `apply` mode, merge a
  copied `postprocess.secondary_motion` block into the stage config sent to the
  backend
- do not write this transient block back into NJR config or snapshots

Files:

- modify `src/pipeline/pipeline_runner.py`
- modify `tests/pipeline/test_pipeline_runner.py`

### Step 3: Run motion as SVD postprocess stage zero

Wire the shared engine into the structured SVD postprocess flow.

Required details:

- execute secondary motion before face restore, interpolation, and upscale
- reuse the shared worker/action contract from `PR-VIDEO-237`
- propagate `applied`, `skipped`, and `not_applicable` states into the SVD
  postprocess metadata block

Files:

- modify `src/video/svd_postprocess.py`
- modify `src/video/svd_postprocess_worker.py`
- modify `tests/video/test_svd_postprocess.py`
- modify `tests/video/test_svd_postprocess_worker.py`

### Step 4: Stamp canonical provenance into SVD outputs

Ensure the final artifact surfaces the shared motion summary.

Required details:

- record the detailed motion block in the SVD run manifest
- embed the compact summary in container metadata
- extend the backend replay fragment and raw stage metadata with the same
  summary keys
- preserve skip reasons when the stage did not apply motion

Files:

- modify `src/video/svd_runner.py`
- modify `src/pipeline/executor.py`
- modify `src/video/svd_native_backend.py`
- modify `tests/video/test_svd_runner.py`
- modify `tests/pipeline/test_svd_runtime.py`
- create `tests/video/test_svd_secondary_motion_integration.py`
- modify `docs/SECONDARY_MOTION_POLICY_SCHEMA_v1.md`

## Testing Plan

### Unit Tests

- `tests/video/test_svd_postprocess.py`
- `tests/video/test_svd_postprocess_worker.py`
- `tests/video/test_svd_runner.py`
- `tests/video/test_svd_secondary_motion_integration.py`

### Integration Tests

- `tests/pipeline/test_svd_runtime.py`
- `tests/pipeline/test_pipeline_runner.py`

### Journey or Smoke Coverage

- optional manual local SVD run if the runtime is available

### Manual Verification

1. Run an SVD job with `secondary_motion.mode=apply` and confirm the derived
   transient block exists only in runtime config, not in the outer NJR intent.
2. Confirm postprocess ordering is motion first, then face restore,
   interpolation, and upscale.
3. Confirm the SVD manifest, replay fragment, and container metadata all carry
   the same compact motion summary.

Suggested command set:

- `pytest tests/video/test_svd_postprocess.py tests/video/test_svd_postprocess_worker.py tests/video/test_svd_runner.py tests/video/test_svd_secondary_motion_integration.py tests/pipeline/test_svd_runtime.py tests/pipeline/test_pipeline_runner.py -q`

## Verification Criteria

### Success Criteria

1. SVD can apply shared secondary motion as postprocess stage zero.
2. The outer user contract remains under `intent_config["secondary_motion"]`.
3. SVD outputs record the canonical motion summary across manifest, replay, and
   container metadata surfaces.
4. Disabled and unavailable paths complete successfully with explicit skip
   reasons.

### Failure Criteria

1. A new user-facing SVD-only motion config surface is introduced.
2. Postprocess ordering becomes nondeterministic.
3. Motion failure kills the SVD artifact path instead of recording a skip or
   unavailable state.
4. SVD invents a backend-specific summary shape.

## Risk Assessment

### Low-Risk Areas

- typed config additions
- shared-engine reuse once wired

### Medium-Risk Areas with Mitigation

- postprocess ordering changes
  - Mitigation: explicit ordering assertions in postprocess tests

### High-Risk Areas with Mitigation

- accidental promotion of transient runtime config into a user-facing SVD knob
  - Mitigation: keep the execution block runner-injected only and document that
    rule in the schema doc and tests

### Rollback Plan

Remove the SVD integration path while keeping the shared engine and outer motion
contract intact for the later backend PRs.

## Tech Debt Analysis

### Debt Removed

- lack of a first real runtime backend for the shared motion engine
- absence of canonical motion provenance in SVD artifacts

### Debt Intentionally Deferred

- AnimateDiff integration
  - Owner: `PR-VIDEO-239`
- workflow-video parity integration
  - Owner: `PR-VIDEO-240`
- learning integration
  - Owner: `PR-VIDEO-241`

## Documentation Updates

- `docs/SECONDARY_MOTION_POLICY_SCHEMA_v1.md`
- completion-status updates in:
  - `docs/StableNew Roadmap v2.6.md`
  - `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`

## Dependencies

### Internal Module Dependencies

- `PR-VIDEO-236` motion contract and runner carrier
- `PR-VIDEO-237` shared engine and provenance helpers
- existing SVD config, postprocess, and runner modules

### External Tools or Runtimes

- SVD runtime already required for `svd_native`

## Approval & Execution

Planner: GitHub Copilot
Executor: Codex or Copilot
Reviewer: Human + architecture review
Approval Status: Pending

## Next Steps

1. `PR-VIDEO-239-AnimateDiff-Secondary-Motion-Frame-Pipeline-Integration`
2. `PR-VIDEO-240-Workflow-Video-Secondary-Motion-Parity-and-Replay-Closure`
