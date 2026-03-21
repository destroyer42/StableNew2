SECONDARY_MOTION_POLICY_SCHEMA_V1.md

Status: Active
Updated: 2026-03-21

## Purpose

Freeze the first StableNew-owned outer contract for secondary motion before any
backend behavior changes land.

This document is the contract reference for:

- `intent_config["secondary_motion"]`
- runner-owned observation-only `secondary_motion_policy`
- metadata-only policy carriage through video-stage execution
- shared secondary-motion provenance summaries after `PR-VIDEO-237`

Dark-launch status:

- default disabled
- no GUI surface
- no runtime auto-enable path
- no backend behavior changes in v1 contract freeze

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
- `mode`: rollout mode; `observe` and `apply` are valid, but v1 only observes
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

Observation-only v1 shape:

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

- no manifests or container metadata are changed in `PR-VIDEO-236`
- no prompt text, stage config, or backend options are mutated in
  `PR-VIDEO-236`
- this carrier is metadata-only and replay-safe

## Non-Goals for v1

- no new video stage type
- no backend-specific custom schema
- no Comfy workflow-node integration
- no frame mutation, latent bias, or prompt bias behavior
- no GUI exposure

## Follow-On Owners

- shared engine and provenance closure: `PR-VIDEO-237`
- backend application paths: `PR-VIDEO-238`, `PR-VIDEO-239`, `PR-VIDEO-240`
- learning integration: `PR-VIDEO-241`

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
