# Video eval kit

Status: living runbook (PR-VID-EVAL-320). The roadmap context is `docs/audits/2026-10-20_video_experience_roadmap.md`
(Phase C, decision D3: one or two standing authorizations per eval-kit batch, with a budget of a few generations).

The eval kit answers one question the same way every time: **is this arm better than the baseline on the same
images, prompts and seed?** It replaces one-off qualification packages. A candidate model, sampler change or
graph revision gets one eval run, a contact sheet and the owner's rating.

## 1. What a run is

* A **suite** (`stablenew.video-eval-suite.v1`, a JSON file you keep next to its images) lists **cases**
  (one source image plus a prompt) and **arms** (one way to make a clip: a native SVD configuration or a Video
  Workflow form). It also fixes one seed and names the baseline arm.
* **Queue eval suite...** (Video Workflow tab, Eval suite section) builds one job per case per arm with the
  production builders (`SVDController.build_admitted_njr`, `VideoWorkflowNjrBuilder`), shows the plan, and after
  you confirm admits every job in **one** `JobService.submit_njrs` call. All or nothing: if any case cannot be
  built under any arm, nothing is queued and every reason is listed.
* The jobs are ordinary jobs. They run, cancel, retry, replay and appear in History like any other. Eval
  membership is only in `<output>/video_eval/<run_id>/run.json` (`stablenew.video-eval-run.v1`), written at
  admission and removed if admission fails.
* At most 64 jobs per run.

## 2. Writing a suite

```json
{
  "schema": "stablenew.video-eval-suite.v1",
  "suite_id": "core-v1",
  "description": "Eight sources that exercise faces, bodies, scenes and camera motion.",
  "seed": 1234,
  "baseline_arm": "svd_recommended",
  "cases": [
    {"case_id": "portrait_turn", "image": "images/portrait.png", "prompt": "she slowly turns her head toward the camera and smiles", "tags": ["face"]},
    {"case_id": "knight_walk", "image": "images/knight.png", "prompt": "the knight walks forward through the snow", "tags": ["body", "locomotion"]},
    {"case_id": "harbor_pan", "image": "images/harbor.png", "prompt": "the camera pans slowly right across the harbor at dusk", "tags": ["scene", "camera"]}
  ],
  "arms": [
    {"arm_id": "svd_recommended", "label": "SVD XT recommended", "backend": "svd_native", "svd": {}},
    {"arm_id": "svd_more_motion", "label": "SVD XT bucket 160", "backend": "svd_native",
     "svd": {"inference": {"motion_bucket_id": 160, "noise_aug_strength": 0.04}}},
    {"arm_id": "wan_ti2v", "label": "Wan2.2 TI2V-5B", "backend": "video_workflow",
     "form": {"workflow_id": "wan22_ti2v_5b_i2v_v1", "workflow_version": "1.2.0", "frame_count": 81}}
  ]
}
```

Rules the loader enforces (`src/video/video_eval_suite.py`):

* Ids are 1-48 lowercase letters, digits, `_` or `-`, unique within the suite.
* `image` is relative to the suite file (or absolute). Add `image_sha256` to pin the exact bytes; a pinned image
  that changed is refused. Unpinned images are still hashed at load and re-checked at admission.
* `svd` is merged over the SVD tab's default configuration (`SVDController.build_default_config`). Without a
  `preprocess.target_width` the target follows each source's aspect, like the tab's Match Source Aspect.
* `form` is merged over the Video Workflow tab's default form. The prompt, negative prompt and seed come from the
  case and the suite, so an arm may not set them. Wan2.2 TI2V-5B 1.2.0 is approved and needs no opt-in. A workflow
  that is still experimental (Wan-Animate-2, TI2V-5B 1.0.0 and 1.1.0) needs `"experimental_opt_in": true` in the arm:
  the suite file is the per-job opt-in, and the queue confirmation names every arm that sets it.
* Admission refuses anything the normal submission would refuse (frame count, missing opt-in, an SVD preflight
  block such as a missing local model).

A good suite covers what has failed before: a face that must stay the same person, a body that must move
(locomotion has been the weak point), a wide scene with camera motion, a close-up with fine detail, and a busy
background. Eight cases by three arms is 24 jobs, an evening of local generation.

## 3. Reading the results

When the jobs finish, **Build eval report...** and choose the run folder. The report is written next to
`run.json` and opens in the browser:

| File | Content |
|---|---|
| `index.html` | Cases as rows, arms as columns; every clip loops beside its numbers and any flags. Prompts are hidden in SFW mode. |
| `metrics.json` | `stablenew.video-eval-report.v1`: each cell's state, measurements, flags and the per-arm means. |
| `ratings.csv` | One row per clip for your rating (`rating_1_to_5`, `requested_action`: achieved, partially_achieved, not_achieved or cannot_assess, `notes`). Rebuilding the report keeps every rating already typed for the same job. |

Rebuild the report at any time; unfinished jobs show as queued or running.

The numbers (`src/video/video_eval_metrics.py`) are measured on the bounded review preview (the first 120 frames,
at most 256 px) and are identical on every machine:

| Metric | Meaning |
|---|---|
| `motion` | Mean absolute luma change between consecutive frames (% of full scale). Near 0 is a frozen clip. |
| `jitter_ratio` | Second temporal difference over twice the first: about 0 for steady motion, 1 for frame-to-frame alternation. |
| `brightness_flicker` | Second difference of whole-frame brightness (% of full scale). |
| `color_drift` | RGB distance between the mean colour of the first and last frames (0-255). |
| `sharpness_retention` | Detail at the end divided by detail at the start; below 1 means detail was lost. |

Flags compare each arm with the baseline on the same case: less than half its motion, jitter ratio more than 0.15
higher, more than twice its brightness flicker, colour drift more than 10 higher, sharpness retention more than
0.15 lower. **Flags mark a clip worth a look; they do not rank arms.** High motion does not mean the requested
action happened. The owner's rating is the decision (roadmap section 5: the owner's eye is the gate, metrics are
guardrails).

## 4. Deciding

* An arm is promotion-worthy when its ratings beat the baseline on the cases that matter and it carries no flag
  the owner considers a regression. Record the run id, the arms and the decision in the promoting PR.
* For a one-control question on one image (for example reference strength), use the Video Workflow one-variable
  experiment and its Review Experiment window instead (PR-VID-QUALITY-211).
