# PR-VID-182 - Wan2.2-Animate Case-B Basic Pose-Retargeting Adjudication

Status: **`COMPLETE - BASIC_RETARGET_PRECONDITION_NOT_MET`**. No upstream retargeting
preprocessing and no Animate generation occurred. This qualification package makes no production
`src/`, backend, controller, resolver, queue, NJR, workflow-registration, or architecture change.

## Execution profile

- Start branch/SHA: `vid/182-animate-case-b-basic-retargeting` at
  `482880223a4d777d91e5220d6221dc6ce34aa393`.
- Execution class: Standard qualification gate; Local/Desktop.
- Model/reasoning recommendation: GPT-5.6 Terra - High. The gate required upstream-source and
  local-artifact adjudication, while its explicit failure path prohibited a GPU workload.
- Controller surface assessment: none. No controller or coordinator code was inspected for change
  or modified.
- Token-efficient validation plan: verify the pinned upstream source and the two frozen input
  hashes, inspect the actual reference and Case-B first frame, document the binary applicability
  decision, and run `git diff --check`. Existing VID-181 source/test/CI evidence remains valid
  because no qualification source changed.

## Question and frozen comparator

The proposed question was whether upstream **basic** pose retargeting could correct PR-VID-181
Case B's ghost-subject/reference-binding failure by changing only `retarget_flag=False` to
`retarget_flag=True`, with `use_flux=False`. The frozen historical comparator is the accepted
VID-181 unretargeted control:

- full upstream pose SHA-256:
  `0b7087eff9bf73dd8d9fe6de64a036aeb275f555d19ff445a766eeb8236e2d4b`;
- final 480x832 / 13-frame / 8-fps control SHA-256:
  `b685a39d3ab374d0b7b05ba287964038b6ab6ebd3bba6ed757138057468a288c`.

It remains a historical comparator only. It was not regenerated or submitted.

## Pinned upstream applicability requirement

The checked-out upstream source is `Wan-Video/Wan2.2 @
1ea34ff48f87168174e12956e200b1d908b1c5ff` (`git rev-parse HEAD` verified). Its animation-mode
guide, `wan/modules/animate/preprocess/UserGuider.md`, states that basic pose retargeting with
`retarget_flag` requires **both** the reference character and the character in the first driving
frame to be in a front-facing, stretched pose. The command-line help independently recommends
`use_flux` when either input is not a standard, front-facing pose. `use_flux` is deliberately out
of scope for this package.

## Exact-input inspection and verdict

| Input | Frozen identity | Observation |
|---|---|---|
| Reference | `reports/vid110/inputs/source_fullbody.png`; SHA-256 `362c86cc83876e340b8927dd54a0f55af1c5fb82c1e9c98d624e67044afa71bb` | The person is front-facing, standing upright, with arms down and legs visible: it satisfies the prerequisite. |
| Case-B driving video | SHA-256 `afe3637aa060fd5855d2feb37b58ab81d300252615daa2b0b8f202d8158edce4`; 464x832, 24 fps, 29 frames | The exact frame 0 was extracted read-only for inspection (derived-frame SHA-256 `54de60010cb33e8226abf8b4efde46b12cdc098cec4c73869968ba0f91f66e68`). It is a lateral-profile silhouette with one knee lifted during a step/jog, arms bent forward, and not a stretched/standard pose. It fails the prerequisite. |

The original Mixkit #583 source SHA-256 remains
`da49964c6d418ae7a7cc6b8972617d6e35bff588e656d55f67d645974b4cd346`; the accepted source
window remains 3.0-4.2 seconds with its fixed crop. Neither was changed.

**Applicability verdict: `BASIC_RETARGET_PRECONDITION_NOT_MET`.** The reference passes, but the
first frame of the exact frozen Case-B driving input fails both required characteristics:
front-facing orientation and stretched/standard pose. The condition is conjunctive, so basic
retargeting is not applicable to this comparator.

No precondition was waived. No calibration frame was prepended, no first frame/source/window/crop
was changed, no source was manipulated, no Flux or SAM2 asset was acquired, and no `face_video`
path was introduced.

## Work not performed

Because the upstream applicability gate failed:

- no `tools/qualification/vid182/` seam, runner, or tests were created;
- no CPU retarget preprocessing ran, including no `get_retarget_pose` call;
- no retargeted `src_pose.mp4`, final frozen control, contact sheet, or `src_face.mp4` exists;
- no Comfy endpoint/process action, A1111 action, or Animate prompt submission occurred;
- no physical generation was submitted, so there is no prompt ID, resource telemetry, output,
  objective metric, visual binding result, or motion-curve correlation for VID-182.

The previously accepted `BACKGROUND_INSTABILITY_CROSS_CASE` finding remains unchanged; VID-182
adds no output evidence to it.

## DIAG-GPU-130

DIAG-GPU-130 remains **`XMP-OFF ISOLATION IN PROGRESS / OBSERVATION ONLY`**. No pre-run machine
gate was needed after the upstream gate failed, and no GPU, stress, or ordinary product-qualification
observation was added. This package makes no stability, fix, or root-cause claim.

## Validation and Git scope

This docs-only result reuses VID-181's accepted source and required-CI evidence. Validation for
this package is the verified pinned upstream SHA, exact frozen input hashes, direct visual input
inspection, and `git diff --check`. No Python source changed, so focused Python tests and Ruff are
not rerun.

No raw footage, derived inspection frame, generated media, controls, telemetry, assets, or
disposable environment is committed.

## Recommended next package (requires product-owner selection)

There is no valid one-variable continuation of **basic** retargeting with this exact Case-B input.
The next package requires an explicit product decision between two materially different paths:

1. an upstream enhanced-retargeting qualification using the exact Case-B source/reference, which
   preserves the direct comparator but adds the separate `use_flux=True` image-editing variable and
   its asset/runtime implications; or
2. a basic-retargeting qualification with a newly selected front-facing, stretched driving first
   frame, which preserves basic retargeting but loses the exact Case-B source comparator.

Neither path is selected or started here.
