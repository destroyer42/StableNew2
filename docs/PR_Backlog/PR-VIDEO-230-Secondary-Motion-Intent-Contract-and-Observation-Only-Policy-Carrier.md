# PR-VIDEO-230 - Secondary Motion Intent Contract and Observation-Only Policy Carrier

Status: Specification
Priority: HIGH
Effort: MEDIUM
Phase: Secondary Motion Foundation
Date: 2026-03-20

## Context & Motivation

### Current Repo Truth

StableNew already has the correct outer video seam: existing video stages are
executed through `PipelineRunner._execute_video_stage(...)`, which builds a
`VideoExecutionRequest` and dispatches to the registered backend. The runner,
NJR snapshots, and config-layer contract already support nested intent
metadata.

StableNew does not yet have a canonical secondary-motion carrier:

- there is no `intent_config["secondary_motion"]` payload
- there is no StableNew-owned `src/video/motion/` package
- there is no runner-owned motion policy object distinct from the existing
  `motion_profile`
- there is no observation-only planning path that can be validated before any
  backend behavior changes land

### Specific Problem

The design memo correctly places secondary motion above backends, but it did
not first freeze a canonical outer contract. Without that first step, later PRs
would be forced to bury motion intent inside stage config, reuse
`motion_profile` for a second meaning, or create backend-specific metadata
forks.

### Why This PR Exists Now

This PR is the safe starting point for the entire secondary-motion series. It
creates the contract, builder persistence, and runner observation carrier
without mutating frames, prompts, manifests, or backend execution.

### Reference

- `docs/ARCHITECTURE_v2.6.md`
- `docs/GOVERNANCE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/StableNew Secondary Motion Layer Design.md`
- `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`
- `docs/PR_Backlog/SECONDARY_MOTION_EXECUTABLE_ROADMAP_v2.6.md`

## Goals & Non-Goals

### Goals

1. Add a StableNew-owned `src/video/motion/` package for secondary-motion
   contracts and pure policy planning.
2. Define one canonical nested `intent_config["secondary_motion"]` payload.
3. Preserve that nested payload through builder, NJR, queue snapshot, and
   replay snapshot paths without creating a new job model.
4. Add runner observation-only motion planning for video stages and attach the
   derived policy to `VideoExecutionRequest.context_metadata` without changing
   backend behavior.
5. Add AST import-guard coverage that keeps the motion package free of GUI,
   controller, and backend-adapter imports.
6. Add a versioned schema document for the v1 secondary-motion contract.

### Non-Goals

1. Do not mutate frames, prompts, or stage config in this PR.
2. Do not modify manifests, embedded container metadata, or replay fragments in
   this PR.
3. Do not add a new stage type or change canonical stage ordering.
4. Do not add workflow-native Comfy behavior, prompt-bias behavior, or latent
   motion bias in this PR.
5. Do not add GUI controls or controller UX in this PR.

## Guardrails

1. NJR remains the only outer execution contract.
2. `secondary_motion` must live under `intent_config`; do not create a sibling
   NJR field, a backend-only config contract, or a second top-level result
   payload.
3. `motion_profile` keeps its current stage-facing meaning; this PR must not
   reinterpret or overload it.
4. No new video stage types or stage-order changes are allowed.
5. The policy service must remain backend-agnostic and accept plain prompt and
   subject-analysis inputs.
6. If adaptive-refinement subject analysis is unavailable, the runner must emit
   a null-safe observation bundle rather than fail the job.
7. `src/video/motion/` must not import `tkinter`, `src.gui`, `src.gui_v2`,
   `src.controller`, backend adapter modules, or `src.pipeline.executor`.
8. Backend execution behavior must remain unchanged in this PR.

## Allowed Files

### Files to Create

| File | Purpose |
| ------ | ------- |
| `src/video/motion/__init__.py` | Package boundary |
| `src/video/motion/secondary_motion_models.py` | Versioned intent and policy models |
| `src/video/motion/secondary_motion_policy_service.py` | Pure motion policy planner |
| `tests/video/test_secondary_motion_models.py` | Contract round-trip coverage |
| `tests/video/test_secondary_motion_policy_service.py` | Policy-planning coverage |
| `tests/video/test_secondary_motion_layer_imports.py` | AST guard coverage |
| `docs/SECONDARY_MOTION_POLICY_SCHEMA_v1.md` | Active schema document for the v1 motion carrier |

### Files to Modify

| File | Reason |
| ------ | ------ |
| `src/pipeline/config_contract_v26.py` | Add canonical `secondary_motion` intent key and extractor helper |
| `src/pipeline/job_builder_v2.py` | Preserve motion intent through builder-produced NJRs |
| `src/pipeline/prompt_pack_job_builder.py` | Preserve motion intent through prompt-pack flows |
| `src/pipeline/cli_njr_builder.py` | Preserve motion intent through CLI-produced NJRs |
| `src/pipeline/job_requests_v2.py` | Add a typed motion-intent carrier only if current builder flow requires it |
| `src/pipeline/pipeline_runner.py` | Emit observation-only motion planning metadata for video stages |
| `tests/pipeline/test_config_contract_v26.py` | Canonicalization assertions |
| `tests/pipeline/test_job_builder_v2.py` | Builder persistence assertions |
| `tests/pipeline/test_prompt_pack_job_builder.py` | Prompt-pack persistence assertions |
| `tests/pipeline/test_cli_njr_builder.py` | CLI persistence assertions |
| `tests/pipeline/test_pipeline_runner.py` | Observation-only runner assertions |
| `docs/DOCS_INDEX_v2.6.md` | Register the schema doc once created |

### Forbidden Files

| File/Directory | Reason |
| ---------------- | ------ |
| `src/pipeline/executor.py` | No backend execution changes in this PR |
| `src/video/animatediff_backend.py` | No backend behavior change |
| `src/video/svd_native_backend.py` | No backend behavior change |
| `src/video/comfy_workflow_backend.py` | No backend behavior change |
| `src/video/svd_runner.py` | No manifest or runtime mutation yet |
| `src/gui/**` | No GUI work |
| `src/controller/**` | No controller UX work |

## Implementation Plan

### Step 1: Define the canonical motion carrier

Create the v1 motion contract models under `src/video/motion/`.

Required details:

- define `SecondaryMotionIntent` with at least:
  `schema`, `enabled`, `mode`, `intent`, `regions`, `allow_prompt_bias`,
  `allow_native_backend`, `record_decisions`, `seed`, `algorithm_version`
- define `SecondaryMotionPolicy` as the runner-owned derived plan with at least:
  `policy_id`, `enabled`, `backend_mode`, `intensity`, `damping`,
  `frequency_hz`, `cap_pixels`, `subject_scale`, `pose_class`, and `reasons`
- keep the policy model serializable and backend-agnostic
- define explicit rollout modes: `disabled`, `observe`, `apply`

Files:

- create `src/video/motion/secondary_motion_models.py`
- create `src/video/motion/secondary_motion_policy_service.py`
- create `tests/video/test_secondary_motion_models.py`
- create `tests/video/test_secondary_motion_policy_service.py`

### Step 2: Add one canonical intent-config entry point

Extend config canonicalization so `secondary_motion` survives normalization.

Required details:

- add `secondary_motion` to `_INTENT_TOP_LEVEL_KEYS`
- add a focused helper such as `extract_secondary_motion_intent(...)`
- preserve nested payloads as deep copies; do not flatten motion fields into
  execution config or backend options
- keep the contract separate from the existing `motion_profile`

Files:

- modify `src/pipeline/config_contract_v26.py`
- modify `tests/pipeline/test_config_contract_v26.py`

### Step 3: Preserve the contract through builder paths

Make current NJR builders preserve the nested motion intent.

Required details:

- keep the data inside `intent_config`
- do not create a second outer DTO or a new stage-specific config root
- update `job_requests_v2.py` only if the current builder flow needs a typed
  carrier to hold the nested payload

Files:

- modify `src/pipeline/job_builder_v2.py`
- modify `src/pipeline/prompt_pack_job_builder.py`
- modify `src/pipeline/cli_njr_builder.py`
- modify `src/pipeline/job_requests_v2.py` only if required
- modify the builder tests listed above

### Step 4: Add runner observation-only planning for video stages

Teach the runner to emit a motion observation bundle when a video stage is
about to execute, without changing backend behavior.

Required details:

- perform the planning inside `PipelineRunner._execute_video_stage(...)` or a
  helper it calls, not in GUI/controller code
- feed the planner: prompt text, negative prompt, stage name, backend id, and
  any available subject-analysis summary from the adaptive-refinement contract
- attach the derived plan to `request.context_metadata["secondary_motion_policy"]`
- write an observation-only summary to `result.metadata["secondary_motion"]`
- do not mutate prompt text, negative prompt text, stage config, frame paths,
  or output artifacts in this PR

Files:

- modify `src/pipeline/pipeline_runner.py`
- modify `tests/pipeline/test_pipeline_runner.py`

### Step 5: Add architecture guard coverage and schema documentation

Prevent the new subsystem from accreting forbidden imports and freeze the v1
schema in docs.

Required details:

- implement the guard test using the AST-walk pattern already used elsewhere in
  the repo
- block `tkinter`, `src.gui`, `src.gui_v2`, `src.controller`, backend adapter
  modules, and `src.pipeline.executor` from the motion package
- document dark-launch status explicitly: default disabled, no GUI surface, no
  runtime auto-enable path

Files:

- create `tests/video/test_secondary_motion_layer_imports.py`
- create `docs/SECONDARY_MOTION_POLICY_SCHEMA_v1.md`
- modify `docs/DOCS_INDEX_v2.6.md`

## Testing Plan

### Unit Tests

- `tests/video/test_secondary_motion_models.py`
- `tests/video/test_secondary_motion_policy_service.py`
- `tests/video/test_secondary_motion_layer_imports.py`
- `tests/pipeline/test_config_contract_v26.py`
- `tests/pipeline/test_job_builder_v2.py`
- `tests/pipeline/test_prompt_pack_job_builder.py`
- `tests/pipeline/test_cli_njr_builder.py`

### Integration Tests

- `tests/pipeline/test_pipeline_runner.py`

### Journey or Smoke Coverage

- none in this PR; backend behavior must remain unchanged

### Manual Verification

1. Build an NJR through the main builder path with `secondary_motion` present in
   the input.
2. Confirm the nested payload survives canonicalization and snapshotting.
3. Execute a video-stage NJR through a fake backend and confirm the derived
   policy appears in `request.context_metadata` and `result.metadata` without
   mutating output behavior.

Suggested command set:

- `pytest tests/video/test_secondary_motion_models.py tests/video/test_secondary_motion_policy_service.py tests/video/test_secondary_motion_layer_imports.py tests/pipeline/test_config_contract_v26.py tests/pipeline/test_job_builder_v2.py tests/pipeline/test_prompt_pack_job_builder.py tests/pipeline/test_cli_njr_builder.py tests/pipeline/test_pipeline_runner.py -q`

## Verification Criteria

### Success Criteria

1. `secondary_motion` survives canonicalization and builder serialization.
2. The nested intent remains distinct from `motion_profile`.
3. The runner can emit observation-only motion planning metadata for video
   stages without changing backend behavior.
4. The motion package is guarded against GUI, controller, and backend-adapter
   imports.

### Failure Criteria

1. Motion intent is stored in execution config or backend options instead of
   `intent_config`.
2. The PR introduces a new stage type or changes stage ordering.
3. Backend output behavior changes in this PR.
4. The motion package imports GUI/controller/backend runtime code.

## Risk Assessment

### Low-Risk Areas

- new contract and schema files
- builder persistence tests

### Medium-Risk Areas with Mitigation

- runner observation-only planning
  - Mitigation: keep it metadata-only and test with fake backends

### High-Risk Areas with Mitigation

- semantic confusion with `motion_profile`
  - Mitigation: freeze a separate `secondary_motion` contract and document the
    distinction in the schema doc

### Rollback Plan

Remove the motion extractor and runner observation path while keeping the repo
free of backend behavior changes.

## Tech Debt Analysis

### Debt Removed

- absence of a canonical outer contract for secondary motion
- risk of overloading `motion_profile` with a second meaning

### Debt Intentionally Deferred

- shared deterministic engine and provenance helpers
  - Owner: `PR-VIDEO-231`
- backend runtime integration
  - Owner: `PR-VIDEO-232`, `PR-VIDEO-233`, `PR-VIDEO-234`
- learning integration
  - Owner: `PR-VIDEO-235`
- GUI exposure
  - Owner: follow-on PR after `PR-VIDEO-235`

## Documentation Updates

- `docs/SECONDARY_MOTION_POLICY_SCHEMA_v1.md`
- `docs/DOCS_INDEX_v2.6.md`
- completion-status updates in:
  - `docs/StableNew Roadmap v2.6.md`
  - `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`

## Dependencies

### Internal Module Dependencies

- config-layer canonicalization
- NJR builders and snapshots
- runner video dispatch
- adaptive-refinement prompt/subject-analysis summaries as optional inputs only

### External Tools or Runtimes

- none

## Approval & Execution

Planner: GitHub Copilot
Executor: Codex or Copilot
Reviewer: Human + architecture review
Approval Status: Pending

## Next Steps

1. `PR-VIDEO-231-Shared-Secondary-Motion-Engine-and-Provenance-Contract`
2. `PR-VIDEO-232-SVD-Native-Secondary-Motion-Postprocess-Integration`
