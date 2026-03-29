SECONDARY_MOTION_POLICY_SCHEMA_V1.md

Status: Active
Updated: 2026-03-24

## Purpose

Freeze the first StableNew-owned outer contract for secondary motion before any
backend behavior changes land.

This document is the contract reference for:

- `intent_config["secondary_motion"]`
- runner-owned `secondary_motion_policy`
- transient runtime carriage into SVD, AnimateDiff, and workflow-video backends
- shared secondary-motion provenance summaries and learning-safe scalar context

Rollout status:

- default disabled
- no GUI surface
- no runtime auto-enable path
- backend apply paths active for SVD native, AnimateDiff, and workflow-video

## Canonical Intent Payload

Schema id:

- `stablenew.secondary-motion.v1`

Carrier:

- nested under `intent_config["secondary_motion"]`

Allowed modes:

- `disabled`
- `observe`
- `apply`

Required semantics:

- `secondary_motion` is distinct from `motion_profile`
- `motion_profile` remains the stage/backend-facing motion selection already
  used by existing video paths
- `secondary_motion` is StableNew-owned policy intent above backends

Canonical shape:

```json
{
  "schema": "stablenew.secondary-motion.v1",
  "enabled": true,
  "mode": "observe",
  "intent": "micro_sway",
  "regions": ["hair", "fabric"],
  "allow_prompt_bias": false,
  "allow_native_backend": false,
  "record_decisions": true,
  "seed": 1234,
  "algorithm_version": "v1"
}
```

Field meanings:

- `schema`: versioned carrier id
- `enabled`: feature gate for the job/run
- `mode`: rollout mode; `observe` and `apply` are both valid runtime states
- `intent`: coarse desired motion class, such as `steady`, `micro_sway`, or
  another future planner-recognized label
- `regions`: optional coarse target regions for future use
- `allow_prompt_bias`: future permission bit for prompt mutation; no effect in
  `PR-VIDEO-236`
- `allow_native_backend`: future permission bit for backend-native motion paths
- `record_decisions`: emit policy/observation metadata when true
- `seed`: optional deterministic seed for later engine work
- `algorithm_version`: StableNew planner version label

## Runner-Owned Policy Payload

Schema id:

- `stablenew.secondary-motion-policy.v1`

Carrier:

- `VideoExecutionRequest.context_metadata["secondary_motion_policy"]`
- `PipelineRunResult.metadata["secondary_motion"]`

Canonical policy shape:

```json
{
  "schema": "stablenew.secondary-motion-policy.v1",
  "policy_id": "comfy_video_workflow_observe_v1",
  "enabled": true,
  "backend_mode": "observe_shared_postprocess_candidate",
  "intensity": 0.25,
  "damping": 0.9,
  "frequency_hz": 0.2,
  "cap_pixels": 12,
  "subject_scale": "small",
  "pose_class": "steady",
  "reasons": [
    "stage=video_workflow",
    "backend=comfy",
    "intent=micro_sway",
    "pose=steady",
    "subject_scale=small"
  ],
  "algorithm_version": "v1"
}
```

Field meanings:

- `policy_id`: deterministic planner id for the derived policy class
- `enabled`: whether motion would be considered active for the request
- `backend_mode`: StableNew-owned candidate application path
- `intensity`: bounded normalized strength
- `damping`: bounded stabilization factor
- `frequency_hz`: bounded oscillation/variation target
- `cap_pixels`: absolute cap for later deterministic motion engines
- `subject_scale`: coarse scale band, usually from adaptive-refinement
  subject assessment when available
- `pose_class`: coarse prompt/subject-derived pose label
- `reasons`: short planner rationale list
- `algorithm_version`: planner version used to derive the policy

## Result Metadata Shape

Root carrier:

- `PipelineRunResult.metadata["secondary_motion"]`

Canonical shape:

```json
{
  "intent": { "...": "secondary-motion intent payload" },
  "primary_policy": { "...": "secondary-motion policy payload" },
  "video_stage_policies": [
    {
      "stage_name": "video_workflow",
      "backend_id": "comfy",
      "batch_index": 0,
      "motion_profile": "cinematic",
      "policy": { "...": "secondary-motion policy payload" },
      "prompt_features": {
        "pose_class": "steady",
        "energy": 0.2,
        "camera_locked": true,
        "floating": false
      },
      "subject_summary": {
        "scale_band": "small",
        "pose_band": "steady"
      },
      "input_image_path": "..."
    }
  ]
}
```

Rules:

- the runner remains the only owner of policy derivation
- transient apply-mode stage config may be injected for supported video backends
- prompt text is not mutated by secondary motion rollout
- summaries remain replay-safe and scalar-only outside manifest provenance

## SVD Runtime Carriage

Added in `PR-VIDEO-238`.

Carrier:

- copied SVD runtime config under `postprocess.secondary_motion`

Canonical transient shape:

```json
{
  "enabled": true,
  "mode": "apply",
  "policy_id": "svd_native_apply_v1",
  "intensity": 0.25,
  "damping": 0.9,
  "frequency_hz": 0.2,
  "cap_pixels": 12,
  "regions": ["hair", "fabric"],
  "skip_reason": null,
  "seed": 1234
}
```

Rules:

- this block is runner-injected and backend-local; it is not a second outer job
  carrier
- SVD applies secondary motion as postprocess stage zero before later postprocess
  steps such as upscale
- secondary-motion worker failure is skip-safe and must preserve later SVD
  postprocess execution with `status="unavailable"` and `skip_reason="worker_failed"`

## AnimateDiff Runtime Carriage

Added in `PR-VIDEO-239`.

Carrier:

- copied AnimateDiff runtime config under `secondary_motion`

Canonical transient shape:

```json
{
  "enabled": true,
  "mode": "apply",
  "policy_id": "animatediff_apply_v1",
  "intensity": 0.25,
  "damping": 0.9,
  "frequency_hz": 0.2,
  "cap_pixels": 12,
  "regions": ["hair", "fabric"],
  "skip_reason": "",
  "seed": 1234
}
```

Rules:

- this block is runner-injected and backend-local; it is not a second outer job
  carrier
- AnimateDiff applies secondary motion after frame write and before MP4 assembly
- secondary-motion worker failure is skip-safe and must preserve original frame
  encode with `status="unavailable"` and `skip_reason="worker_failed"`
- compact secondary-motion summaries must be preserved in the stage result,
  replay fragment, and container metadata

## Workflow-Video Runtime Carriage

Completed in `PR-VIDEO-240`.

Carrier:

- copied workflow-video runtime config under `secondary_motion`

Canonical transient shape:

```json
{
  "enabled": true,
  "mode": "apply",
  "policy_id": "workflow_video_apply_v1",
  "intensity": 0.25,
  "damping": 0.9,
  "frequency_hz": 0.2,
  "cap_pixels": 12,
  "regions": ["hair", "fabric"],
  "skip_reason": "",
  "seed": 1234
}
```

Rules:

- this block is runner-injected and backend-local; it is not a second outer job
  carrier
- workflow-video applies secondary motion by extracting frames from the original
  workflow output, running the shared worker, and re-encoding a promoted MP4
- when motion applies, the re-encoded artifact becomes the final primary video
  while the original workflow output path remains preserved in detailed
  provenance and replay metadata as `secondary_motion_source_video_path`
- missing FFmpeg, extraction failure, worker failure, or re-encode failure are
  skip-safe and must preserve the original workflow output with
  `status="unavailable"`
- compact secondary-motion summaries must be preserved in the StableNew-owned
  manifest, replay fragment, and container metadata

## Non-Goals for v1

- no new video stage type
- no backend-specific custom schema
- no Comfy workflow-node integration
- no frame mutation, latent bias, or prompt bias behavior
- no GUI exposure

## Follow-On Owners

- shared engine and provenance closure: `PR-VIDEO-237`
- backend application paths: `PR-VIDEO-238`, `PR-VIDEO-239`, `PR-VIDEO-240` completed
- learning integration: `PR-VIDEO-241` completed

## Shared Provenance Summary Contract

Added in `PR-VIDEO-237`.

Summary schema id:

- `stablenew.secondary-motion-summary.v1`

Detailed provenance schema id:

- `stablenew.secondary-motion-provenance.v1`

Compact summary carrier:

- manifest detailed blocks via `secondary_motion.summary`
- replay descriptor `secondary_motion`
- diagnostics descriptor `secondary_motion`
- public video container metadata payload `secondary_motion`

Compact summary shape:

```json
{
  "schema": "stablenew.secondary-motion-summary.v1",
  "enabled": true,
  "status": "observe",
  "policy_id": "comfy_video_workflow_observe_v1",
  "application_path": "policy_observation_only",
  "intent": {
    "mode": "observe",
    "intent": "micro_sway"
  },
  "backend_mode": "observe_shared_postprocess_candidate",
  "skip_reason": "observe_only",
  "metrics": {
    "intensity": 0.25,
    "cap_pixels": 12
  }
}
```

Rules:

- compact summaries carry scalar metrics only
- full frame-level details stay in manifest-only provenance blocks
- replay and diagnostics descriptors must not embed raw frame data

## Learning Context Shape

Completed in `PR-VIDEO-241`.

Learning record carrier:

- `LearningRecord.metadata["secondary_motion"]`

Recommendation stratification keys:

- `backend_id`
- `policy_id`
- `application_path`
- `status`

Canonical learning context shape:

```json
{
  "enabled": true,
  "status": "applied",
  "backend_id": "comfy",
  "policy_id": "workflow_motion_v1",
  "application_path": "video_reencode_worker",
  "backend_mode": "apply_shared_postprocess_candidate",
  "intent_mode": "apply",
  "intent_label": "micro_sway",
  "skip_reason": "",
  "regions_applied": 2,
  "frames_in": 16,
  "frames_out": 16,
  "frame_count_delta": 0,
  "applied_frame_count": 12,
  "applied_frame_ratio": 0.75,
  "applied_motion_strength": 0.25,
  "quality_risk_score": 0.1875,
  "intensity": 0.25,
  "damping": 0.9,
  "frequency_hz": 0.2,
  "cap_pixels": 12,
  "avg_abs_dx": 1.0,
  "avg_abs_dy": 0.3,
  "max_abs_dx": 2,
  "max_abs_dy": 1
}
```

Rules:

- learning consumes canonical result metadata and manifest summaries only
- stored motion learning context remains scalar-only and bounded
- no raw frame paths, masks, dense flow fields, or binary motion payloads may
  be persisted into centralized learning storage
- recommendation and evidence matching must stratify by `backend_id`,
  `policy_id`, `application_path`, and `status`
- unavailable or skipped motion runs may inform diagnostics, but they must not
  be treated as positive tuning evidence for applied-motion recommendations

Applied backend closure delivered across:

- `PR-VIDEO-238`: SVD postprocess stage zero via worker-backed frame directory
- `PR-VIDEO-239`: AnimateDiff between frame write and encode
- `PR-VIDEO-240`: workflow-video extract/apply/re-encode promotion path

Detailed manifest provenance shape:

```json
{
  "schema": "stablenew.secondary-motion-provenance.v1",
  "intent": { "...": "secondary-motion intent payload" },
  "policy": { "...": "secondary-motion policy payload" },
  "apply_result": { "...": "engine or worker apply-result payload" },
  "summary": { "...": "secondary-motion summary payload" }
}
```

## Learning-Safe Summary Contract

Delivered in `PR-VIDEO-241`.

Learning records may persist a compact secondary-motion context derived from the
summary contract. Allowed retained fields are scalar-only:

- `enabled`
- `status`
- `policy_id`
- `application_path`
- `backend_mode`
- `intent_mode`
- `intent_label`
- `skip_reason`
- bounded scalar metrics such as `regions_applied`, `frames_in`, `frames_out`

Rules:

- no raw frame paths in centralized learning summaries
- no dense motion vectors or per-frame displacement payloads in learning data
- recommendation context may stratify by policy id and application path, but
  evidence-tier safeguards remain unchanged
