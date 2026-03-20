# Refinement Policy Schema v1

Status: Active subsystem schema  
Updated: 2026-03-20

## Purpose

Define the canonical v1 contract for StableNew adaptive refinement.

This schema is dark-launch only in the `PR-HARDEN-224..229` series:

- default disabled
- no GUI exposure
- no hidden auto-enable path

The canonical carrier is one nested `adaptive_refinement` block reused across:

- `intent_config`
- runner metadata
- manifests
- embedded image metadata
- diagnostics
- learning context

Later PRs may extend the payload, but must not fork it into parallel schemas.

## Intent Contract

Top-level location:

`intent_config["adaptive_refinement"]`

Required v1 fields:

- `schema`: `stablenew.adaptive-refinement.v1`
- `enabled`: boolean
- `mode`: one of `disabled`, `observe`, `adetailer`, `full`
- `profile_id`: stable policy profile id
- `detector_preference`: detector id preference such as `null` or `opencv`
- `record_decisions`: boolean
- `algorithm_version`: stable algorithm version label

Example:

```json
{
  "adaptive_refinement": {
    "schema": "stablenew.adaptive-refinement.v1",
    "enabled": true,
    "mode": "observe",
    "profile_id": "auto_v1",
    "detector_preference": "null",
    "record_decisions": true,
    "algorithm_version": "v1"
  }
}
```

## Decision Carrier

Canonical carrier key:

`adaptive_refinement`

The initial decision bundle shape is:

```json
{
  "schema": "stablenew.refinement-decision.v1",
  "algorithm_version": "v1",
  "mode": "observe",
  "policy_id": null,
  "detector_id": "null",
  "observation": {},
  "applied_overrides": {},
  "prompt_patch": {},
  "notes": []
}
```

Observation-mode runner metadata in `PR-HARDEN-225` is emitted as:

```json
{
  "adaptive_refinement": {
    "intent": {
      "schema": "stablenew.adaptive-refinement.v1",
      "enabled": true,
      "mode": "observe",
      "profile_id": "auto_v1",
      "detector_preference": "null",
      "record_decisions": true,
      "algorithm_version": "v1"
    },
    "prompt_intent": {
      "intent_band": "portrait",
      "requested_pose": "unknown",
      "wants_face_detail": false,
      "wants_full_body": false,
      "wants_profile": false,
      "wants_portrait": false,
      "has_people_tokens": false,
      "has_lora_tokens": false,
      "positive_embedding_count": 0,
      "positive_chunks": [],
      "negative_chunks": [],
      "conflicts": [],
      "context": {}
    },
    "decision_bundle": {
      "schema": "stablenew.refinement-decision.v1",
      "algorithm_version": "v1",
      "mode": "observe",
      "policy_id": "observe_only_v1",
      "detector_id": "null",
      "observation": {
        "prompt_intent": {},
        "subject_assessment": {
          "detector_id": "null",
          "image_path": null,
          "detection_count": 0,
          "primary_detection_index": null,
          "scale_band": "no_face",
          "pose_band": "unknown",
          "notes": ["assessment_unavailable", "no_face_detected"]
        }
      },
      "applied_overrides": {},
      "prompt_patch": {},
      "notes": []
    }
  }
}
```

In `PR-HARDEN-225`, this block is metadata-only:

- no manifest mutation
- no embedded-image-metadata mutation
- no executor payload mutation
- no stage-config mutation

## Series Constraints

- `PR-HARDEN-224`: contract only, no runtime behavior change
- `PR-HARDEN-225`: observation only, no stage mutation
- `PR-HARDEN-226`: detector enrichment only, with per-image caching and timeout/fallback
- `PR-HARDEN-227`: ADetailer-only actuation
- `PR-HARDEN-228`: text-token prompt patching plus bounded upscale policy
- `PR-HARDEN-229`: scalar learning and recommendation context only

## v1 Prompt Patch Limits

When `PR-HARDEN-228` lands, v1 prompt patches are limited to plain text-token operations:

- `add_positive`
- `remove_positive`
- `add_negative`
- `remove_negative`

They must not mutate:

- LoRA tags
- embedding tokens
- textual inversion names
- weighted prompt syntax

## v1 Provenance Rule

Runner metadata, manifests, embedded image metadata, diagnostics, and learning
must reuse the same semantic fields carried inside `adaptive_refinement`.

No PR in this series may introduce a second refinement-only provenance block for
one subsystem.
