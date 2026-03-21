# PR-VIDEO-237 - Shared Secondary Motion Engine and Provenance Contract

Status: Specification
Priority: HIGH
Effort: LARGE
Phase: Secondary Motion Core Runtime
Date: 2026-03-20

## Context & Motivation

### Current Repo Truth

After `PR-VIDEO-236`, StableNew has a frozen outer motion contract and a runner
observation carrier, but there is still no reusable motion engine and no shared
provenance helper that later backends can adopt verbatim.

If backend integrations land before the shared engine and summary contract,
SVD, AnimateDiff, and workflow-video will each be forced to invent their own
frame-mutation and manifest-shaping logic.

### Specific Problem

The motion design depends on a deterministic shared postprocess, but the repo
currently has no StableNew-owned frame engine, no worker contract reusable by
both in-memory and frame-directory consumers, and no canonical motion summary
for manifests, replay fragments, and container metadata.

### Why This PR Exists Now

This PR isolates the algorithm and provenance work before any backend wiring.
That keeps `PR-VIDEO-238` through `PR-VIDEO-240` focused on backend-specific
integration instead of re-arguing the engine contract.

### Reference

- `docs/ARCHITECTURE_v2.6.md`
- `docs/GOVERNANCE_v2.6.md`
- `docs/StableNew Secondary Motion Layer Design.md`
- `docs/PR_Backlog/SECONDARY_MOTION_EXECUTABLE_ROADMAP_v2.6.md`
- `docs/PR_Backlog/PR-VIDEO-236-Secondary-Motion-Intent-Contract-and-Observation-Only-Policy-Carrier.md`

## Goals & Non-Goals

### Goals

1. Add a StableNew-owned deterministic motion engine reusable by both
   frame-directory and in-memory backends.
2. Add a shared worker contract for frame-directory execution that later SVD,
   AnimateDiff, and workflow-video integration can call without forking logic.
3. Define one canonical motion provenance helper that produces:
   a detailed manifest block, a compact replay summary, and a compact container
   metadata summary.
4. Extend replay/diagnostics and container metadata helpers so they can carry
   the shared motion summary without backend-specific code paths.
5. Add deterministic unit tests for clamp behavior, skip reasons, and summary
   serialization.

### Non-Goals

1. Do not wire the engine into SVD, AnimateDiff, or workflow-video in this PR.
2. Do not add workflow-native Comfy nodes or workflow-catalog changes in this
   PR.
3. Do not add learning integration in this PR.
4. Do not add GUI exposure in this PR.
5. Do not require new hard computer-vision runtimes in this PR.

## Guardrails

1. The engine must remain StableNew-owned under `src/video/motion/`.
2. The baseline engine path must be deterministic and must not require OpenCV,
   torch, or external model downloads.
3. The worker contract must reuse the same engine and summary helpers as the
   in-memory path.
4. Container metadata remains compact; full motion details stay in manifests.
5. Replay and diagnostics helpers may surface only the compact summary, not raw
   frame-level data.
6. This PR must not change backend execution behavior yet.

## Allowed Files

### Files to Create

| File | Purpose |
| ------ | ------- |
| `src/video/motion/secondary_motion_engine.py` | Shared deterministic frame-mutation engine |
| `src/video/motion/secondary_motion_worker.py` | Worker entrypoint and payload contract for frame-directory execution |
| `src/video/motion/secondary_motion_provenance.py` | Shared manifest/replay/container-summary builders |
| `tests/video/test_secondary_motion_engine.py` | Engine determinism and clamp coverage |
| `tests/video/test_secondary_motion_worker.py` | Worker payload and directory round-trip coverage |
| `tests/video/test_secondary_motion_provenance.py` | Provenance-shape coverage |
| `tests/pipeline/test_result_contract_v26.py` | Replay/diagnostics summary coverage |

### Files to Modify

| File | Reason |
| ------ | ------ |
| `src/video/motion/__init__.py` | Export the new engine/provenance helpers |
| `src/video/container_metadata.py` | Accept the compact motion summary in public video payloads |
| `src/pipeline/result_contract_v26.py` | Surface the compact motion summary in replay/diagnostics descriptors |
| `tests/video/test_container_metadata.py` | Container-summary assertions |
| `docs/SECONDARY_MOTION_POLICY_SCHEMA_v1.md` | Freeze the shared summary shapes |

### Forbidden Files

| File/Directory | Reason |
| ---------------- | ------ |
| `src/pipeline/pipeline_runner.py` | No backend wiring yet |
| `src/pipeline/executor.py` | No backend wiring yet |
| `src/video/animatediff_backend.py` | No backend integration yet |
| `src/video/svd_native_backend.py` | No backend integration yet |
| `src/video/comfy_workflow_backend.py` | No backend integration yet |
| `src/video/svd_runner.py` | No backend integration yet |
| `src/gui/**` | No GUI work |
| `src/controller/**` | No controller work |

## Implementation Plan

### Step 1: Add the shared deterministic engine

Create a StableNew-owned engine that can operate on both in-memory frames and
frame directories.

Required details:

- accept a `SecondaryMotionPolicy` and deterministic seed
- enforce pixel-displacement, velocity, and boundary clamps
- return a structured `apply_result` with at least:
  `status`, `policy_id`, `application_path`, `frames_in`, `frames_out`,
  `seed`, `regions_applied`, `skip_reason`, and a small scalar metric bundle
- treat `disabled`, `observe`, and `not_applicable` as first-class statuses

Files:

- create `src/video/motion/secondary_motion_engine.py`
- create `tests/video/test_secondary_motion_engine.py`

### Step 2: Add the shared worker contract

Create a directory-oriented worker entrypoint that reuses the same engine.

Required details:

- read a JSON-serializable payload from the caller
- load a deterministic frame sequence from an input directory
- write the transformed sequence to an output directory
- emit the same `apply_result` shape as the in-memory path
- do not add backend-specific logic to the worker

Files:

- create `src/video/motion/secondary_motion_worker.py`
- create `tests/video/test_secondary_motion_worker.py`

### Step 3: Freeze one provenance helper contract

Add shared helper functions that backends later call instead of inventing their
own motion payloads.

Required details:

- generate a detailed manifest block for the run artifact
- generate a compact replay fragment summary
- generate a compact container metadata summary
- keep the summary fields stable across all backends:
  `enabled`, `status`, `policy_id`, `application_path`, `intent`,
  `backend_mode`, `skip_reason`, and scalar metrics only

Files:

- create `src/video/motion/secondary_motion_provenance.py`
- create `tests/video/test_secondary_motion_provenance.py`
- modify `docs/SECONDARY_MOTION_POLICY_SCHEMA_v1.md`

### Step 4: Extend container metadata and result descriptors

Allow the existing result/metadata surfaces to carry the compact summary.

Required details:

- extend `build_public_media_payload(...)` so video container metadata can carry
  a bounded `secondary_motion` summary
- extend replay/diagnostics descriptor builders so they pass through the same
  compact summary when a backend later emits it
- do not introduce backend-specific branches into these shared helpers

Files:

- modify `src/video/container_metadata.py`
- modify `src/pipeline/result_contract_v26.py`
- modify `tests/video/test_container_metadata.py`
- create `tests/pipeline/test_result_contract_v26.py`

## Testing Plan

### Unit Tests

- `tests/video/test_secondary_motion_engine.py`
- `tests/video/test_secondary_motion_worker.py`
- `tests/video/test_secondary_motion_provenance.py`
- `tests/video/test_container_metadata.py`
- `tests/pipeline/test_result_contract_v26.py`

### Integration Tests

- none in this PR; backend wiring is deferred

### Journey or Smoke Coverage

- none

### Manual Verification

1. Run the shared engine on a tiny deterministic frame set twice and confirm
   identical output summary for the same seed.
2. Run the worker against a temp input directory and confirm the output
   directory and summary payload match the in-memory path semantics.
3. Build a compact summary and confirm it round-trips through container-metadata
   and replay-descriptor helpers without bloating the payload.

Suggested command set:

- `pytest tests/video/test_secondary_motion_engine.py tests/video/test_secondary_motion_worker.py tests/video/test_secondary_motion_provenance.py tests/video/test_container_metadata.py tests/pipeline/test_result_contract_v26.py -q`

## Verification Criteria

### Success Criteria

1. The shared engine is deterministic for a fixed seed and policy.
2. The worker path and in-memory path emit the same summary shape.
3. The compact summary survives container-metadata and replay/diagnostics helper
   serialization.
4. No backend files are touched in this PR.

### Failure Criteria

1. The engine requires new hard CV/model dependencies.
2. The worker invents a second summary shape.
3. Shared helpers leak raw frame data into container metadata or replay
   descriptors.
4. Backend execution code changes in this PR.

## Risk Assessment

### Low-Risk Areas

- new motion-engine and provenance files

### Medium-Risk Areas with Mitigation

- container metadata growth
  - Mitigation: keep the summary compact and verify truncation behavior in tests

### High-Risk Areas with Mitigation

- engine instability before backend rollout
  - Mitigation: land determinism and skip-state tests before any backend calls
    it

### Rollback Plan

Remove the shared engine and provenance helper files while leaving the outer
contract from `PR-VIDEO-236` intact.

## Tech Debt Analysis

### Debt Removed

- absence of a shared deterministic motion engine
- risk that each backend would invent its own motion manifest shape

### Debt Intentionally Deferred

- SVD integration
  - Owner: `PR-VIDEO-238`
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

- `PR-VIDEO-236` motion models and policy service
- container metadata helpers
- replay/diagnostics descriptor builders

### External Tools or Runtimes

- none required for the baseline engine path

## Approval & Execution

Planner: GitHub Copilot
Executor: Codex or Copilot
Reviewer: Human + architecture review
Approval Status: Pending

## Next Steps

1. `PR-VIDEO-238-SVD-Native-Secondary-Motion-Postprocess-Integration`
2. `PR-VIDEO-239-AnimateDiff-Secondary-Motion-Frame-Pipeline-Integration`
