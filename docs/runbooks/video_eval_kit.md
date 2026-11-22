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
* A case can instead be a **sequence** of 2-12 segments (section 2.1). It runs as one multi-segment job per arm and is
  rated as one clip: the assembled sequence.

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
  case and the suite, so an arm may not set them. Wan2.2 TI2V-5B 1.2.0 and 1.3.0, the 720p workflow and I2V-A14B 1.0.0 are approved and need no opt-in. A workflow
  that is still experimental (Wan-Animate-2, TI2V-5B 1.0.0 and 1.1.0, the I2V-A14B speed arms 1.1.0-1.3.0) needs `"experimental_opt_in": true` in the arm:
  the suite file is the per-job opt-in, and the queue confirmation names every arm that sets it.
* Admission refuses anything the normal submission would refuse (frame count, missing opt-in, an SVD preflight
  block such as a missing local model).

### 2.1 Sequence cases (VID-A14B-SVI-375)

A case with `segments` instead of `prompt` is a multi-segment sequence:

```json
{"case_id": "walk_then_stop", "image": "images/fullbody.png",
 "segments": [
   {"prompt": "the person walks slowly toward the camera"},
   {"prompt": "the person keeps walking, then slows down"},
   {"prompt": "the person stops and looks into the camera", "frame_count": 49}
 ]}
```

* 2-12 segments, each with its own `prompt` and an optional `frame_count` (otherwise the arm's `frame_count`). A
  sequence case may not also set a case-level `prompt`; `negative_prompt` applies to every segment.
* Each arm builds **one** job through the sequence admission path (`build_sequence_job`, PR-VID-SEQ-330): segment 0
  starts from the case image, each later segment carries the previous segment's exact last frame, and the segments are
  assembled inside the job. Admission refuses what a sequence cannot run (a workflow without a frame-count policy, RIFE
  smoothing, operator controls, an experimental workflow without the arm's opt-in).
* Seeds are fixed: segment *i* uses the suite seed **+ i** under every arm. The manifest records each job's
  `segment_seeds` and its total frame count.
* Sequence cases need Video Workflow arms; a suite that mixes them with a `svd_native` arm is refused.
* One job is one clip in the report: the job's primary video is the assembled sequence, so a row in `ratings.csv` rates
  the whole sequence. Judge seams as well as identity; `segment_seam` is a failure category for a visible jump where
  one segment hands over to the next. The numbers still measure only the first 120 frames of the preview (the page
  says so), which for three 81-frame segments is the first segment and part of the second.
* Pair verification checks the whole sequence: the stored plan must have the case's segment count, every segment's
  prompt and every segment's seed, otherwise the pair is incomparable.

A good suite covers what has failed before: a face that must stay the same person, a body that must move
(locomotion has been the weak point), a wide scene with camera motion, a close-up with fine detail, and a busy
background. Eight cases by three arms is 24 jobs, an evening of local generation.

## 3. Reading the results

When the jobs finish, **Build eval report...** and choose the run folder. The report is written next to
`run.json` and opens in the browser:

| File | Content |
|---|---|
| `index.html` | Cases as rows, arms as columns. Each case shows its hash-verified source image; every clip loops beside its numbers, flags, your ratings and its difference from the baseline. A summary and a readiness banner sit above the grid. Prompts, notes and the source image are hidden in SFW mode; the clips themselves are not content-screened. |
| `metrics.json` | `stablenew.video-eval-report.v1`: each cell's state, measurements, flags, clip digest, the per-arm means and an `identity_assessment` block (cell states, comparisons, per-arm summaries, readiness, source checks). It never contains your notes. |
| `ratings.csv` | One row per clip for your review (section 4). Rebuilding keeps every row, value and unknown column already there. |

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

## 4. Reviewing identity and continuity (PR-VID-QUALITY-351)

Open `index.html`, watch each clip beside its case's source image (and the original clip file for fine detail: the
page's numbers use a downscaled preview of the first 120 frames), then fill in that clip's row in `ratings.csv` and
rebuild. Blank means *not assessed*, never zero or pass.

| Column | Values |
|---|---|
| `rating_1_to_5` | Overall quality (optional). |
| `requested_action` | `achieved`, `partially_achieved`, `not_achieved`, `cannot_assess`. Independent of identity. |
| `source_fidelity_1_to_5` | Does the generated subject still resemble the original image? **Required.** |
| `subject_stability_1_to_5` | Does that same subject stay recognizable through the whole clip? **Required.** |
| `temporal_continuity_1_to_5` | Smooth and coherent over time, not flickering, freezing or morphing. |
| `anatomy_integrity_1_to_5` | Faces, clothing, proportions and important objects stable and plausible. |
| `scene_stability_1_to_5` | Background coherent. |
| `critical_identity_break` | `yes`, `no`, `cannot_assess`. **Required** as yes or no for a complete review. |
| `failure_categories` | Any of `face_or_identity_drift`, `clothing_or_appearance_change`, `body_proportion_change`, `important_object_change`, `subject_disappearance`, `scene_background_drift`, `temporal_flicker`, `motion_freeze`, `segment_seam` (sequence cases), `other`, separated by `;`. |
| `first_failure_seconds` | Optional time you actually saw the first failure in the original clip. |
| `notes` | Free text. |
| `artifact_sha256` | Filled in by the report; see below. |

Scores: **5** stable and convincing, no meaningful defect; **4** minor imperfection, identity preserved; **3**
noticeable issue but still interpretable; **2** major inconsistency that materially reduces usefulness; **1** severe
failure, no longer trustworthy. A critical break is a different face, a central object turning into another object
without the requested action causing it, substantially changed identifying features, or the subject disappearing or
being replaced. An intended rotation, expression change, occlusion or camera move is not a break just because pixels
differ. A frozen but stable clip is `requested_action = not_achieved`, not a success; a lively clip of a different
subject has a critical break.

**Evidence identity.** The report writes `artifact_sha256` (the digest of the clip bytes) into each row that has no
judgment yet. A judgment is only counted while that digest equals the clip's current digest.

* If the clip file is replaced, the row becomes **STALE_ARTIFACT**: your numbers stay in the file, but they are not
  counted. To review the new clip, watch it, then type `rebind` in `artifact_sha256` and rebuild.
* Rows rated before this column existed are **legacy / artifact identity unverified**: kept, shown for reference, not counted. Re-review
  path: watch the current clip, confirm or change the values, type `rebind` in `artifact_sha256`, rebuild.
* The report never rewrites an existing digest by itself.

**Source image.** The recorded source path is hashed and compared with the manifest's `image_sha256`. A missing file is
**UNAVAILABLE**; a changed file is **INCOMPARABLE** and is not shown. No other file is ever substituted.

**Per-cell state:** UNREVIEWED, PARTIAL (something required is missing or invalid), REVIEWED, IDENTITY_CONCERN (you
answered `yes`), LEGACY_UNVERIFIED, STALE_ARTIFACT, UNAVAILABLE (no playable clip or source), INCOMPARABLE.

**Baseline comparison.** For each case and candidate arm the report compares only counted, complete reviews, and only when the
pair is a **verified controlled pair**: the stored NJRs of both jobs agree with the manifest on job id, backend, seed, source
image and (for Video Workflow arms) prompt. If the snapshots are missing or lack a fact the pair is **not fully verified** and
yields no comparison; a contradiction (another seed, source, prompt, backend or job) makes it **incomparable**. Differences are
points on the 1-5 anchors, shown per dimension, with requested action, critical break and numeric flags alongside. A candidate
two or more points below the baseline on source fidelity or subject stability, or a new critical break, is a *material*
regression.

**Readiness** (per candidate arm, then overall; a review aid, never approval, ranking or promotion):

* `IDENTITY CONCERNS`: a counted critical identity break, or a material regression.
* `INSUFFICIENT EVIDENCE`: not every case has a verified, fully reviewed comparison.
* `READY FOR OWNER REVIEW`: every case does, and no critical break is recorded. The decision is still yours.

**Safety of the file.** If `ratings.csv` is malformed (bad CSV or UTF-8, duplicate rows, a row longer than the header,
over 5 MiB), the build stops with an error and writes nothing; fix or move the file. The first rebuild of an older layout
copies it to `ratings.csv.legacy-<time>.bak`. If the file changes while a report is being built, nothing is overwritten.
Rows for jobs no longer in the run, and any columns this version does not know, are kept.

**Later physical qualification.** Whether identity actually improved with a workflow or setting is answered only by a separate,
owner-reviewed physical run (named workflow versions, cases and sources, baseline and candidate settings, number of generations,
expected VRAM/RAM, runtime state, device monitoring, stop conditions for device loss, and what result would justify a change).
This tooling makes no generation and starts no runtime.

### Review in the paired Operator Site

StableNew enables Operator Site pairing at Windows startup and shares the configured Output folder and visible
PromptPacks with its paired private Site. Open **Operator Site** in the header to see the selected folder.
Use **Change output folder…** to grant a different folder, **Stop sharing output** to revoke that grant, or
**Disconnect** to revoke pairing for this app session. You can close the pairing dialog and keep StableNew running.

On the PC, start StableNew once using its normal launcher to register the Windows Operator link for your account.
Then select **Connect StableNew** on the private Site. Accept the browser prompt to open StableNew and allow local
network access if prompted. The link checks for an existing StableNew instance, starts it with the normal launcher
if it is stopped, and pairs automatically. Use **Pair manually** if your browser blocks the link.
Active use or video playback in the Windows Site tab renews its pairing. The library retries brief connection
interruptions while that pairing is valid. After a StableNew restart or an expired pairing, choose
**Reconnect StableNew** and approve the Windows link if prompted.

For a paired phone, use **Compare evaluation pairs** to review a case with synchronized A/B playback and reveal
the workflows after saving both judgments. **Refresh report on Windows** uses the same builder described in
section 3. See the [Operator Site guide](stablenew_operator_site.md) for phone enrollment, video Preview and
queue receipts. When using **Connect via PC browser tab**, keep the connected Site tab open on Windows.

Open **Video Review** on the Site. It selects the newest usable report and opens the first clip that still needs
review. The run dropdown opens earlier reports. **Save & next** writes the judgment into the run’s existing
\`ratings.csv\` after verifying both the clip and the source. Rebuild the report in StableNew to refresh its readiness
and comparison metrics. If the CSV changed or is open in an editor, the Site keeps the current draft visible until
the operator resolves the conflict. Without pairing, use **Open StableNew output folder** or import
\`run.json\`, \`metrics.json\` and \`ratings.csv\` together. Download and apply the CSV explicitly in file-import mode.

**Output Library** uses the same grant. Switch between images and videos, or search by filename, metadata tag,
recorded positive prompt, or seed. Select two images to compare them, or save the selection as an album. Album
references and image scores are stored under \`<Output>/.stablenew-library\`. Image scores are gallery observations.
Opening, editing, or rating an album leaves the original media intact. Moved or replaced files show as unavailable
until the operator updates the album.

The library shows files progressively while it indexes metadata. Images from **Pipeline** appear first. Videos
from **movie_clips** and **SVD** appear first in the Videos view. Use **Source folder** to select Pipeline, Learning,
Reprocess, movie_clips, SVD, video_eval, or other Output folders. Nested folders are included. **Video Review** uses
the reports in video_eval for clip evaluation and CSV ratings.

Indexing is bounded to 100,000 media files and 250,000 filesystem entries. Prompt, tag, and seed indexing has a
separate 128 MiB metadata budget. A visible limit or scan error preserves available results. **Refresh Output**
restarts a completed or failed scan. Filename browsing and image previews are available while metadata is indexed.
The paired Site resumes scan refreshes when the operator returns to the library. Original media stays in Output.

Image previews support PNG, JPEG and WebP up to 32 MiB. Browser-compatible MP4 and WebM video can use the paired
playback path up to 512 MiB, with hosted responses delivered in ranges. Other recognized video formats remain
visible in the library for local playback. The Site reports when the host is unavailable, the media changed, or a
preview exceeds its limit.

## 5. Deciding

* An arm is promotion-worthy when its ratings beat the baseline on the cases that matter and it carries no flag
  the owner considers a regression. Record the run id, the arms and the decision in the promoting PR.
* For a one-control question on one image (for example reference strength), use the Video Workflow one-variable
  experiment and its Review Experiment window instead (PR-VID-QUALITY-211).

## 6. Three-engine example suite (VID-CLIP-370)

`docs/runbooks/examples/video_eval_three_engines.suite.json` is a ready-to-edit suite that compares three engines on
identical cases (same images, prompts, seed and a frame count of 81). Its image names are synthetic placeholders: copy the
file next to your own images and change `image` (and, ideally, pin `image_sha256`) before queueing.

| Arm | Workflow | Governance | What it tests |
|---|---|---|---|
| `ti2v_480p` (baseline) | `wan22_ti2v_5b_i2v_v1` 1.3.0 | approved | The current production engine at 480x832 / 832x480. |
| `ti2v_720p` | `wan22_ti2v_5b_i2v_720p_v1` 1.0.0 | approved (VID-CLIP-372) alternate | The same graph at 704x1280 / 1280x704, the model's 720p design point. |
| `a14b_480p` | `wan22_i2v_a14b_4step_v1` 1.0.0 | approved since VID-CLIP-372, the Make Video default | Wan2.2 I2V-A14B with the lightx2v 4-step LoRAs at 480x832 / 832x480. |

* No arm needs the experimental opt-in any more. The picker offers all three engines as separate approved entries (A14B is
  the default; TI2V-5B 480p and the 720p workflow are listed beside it).
* The execution-time GPU guard still applies to every arm. The A14B arm needs the six pinned files (two experts, two
  LoRAs, the UMT5 encoder and the Wan 2.1 VAE; names and SHA-256 in `docs/Subsystems/Video/PR-VID-WAN-321F_Feasibility.md`
  and the catalog) and a managed Comfy launched with `--disable-pinned-memory`. A missing file refuses the job before
  anything is dispatched. Nothing is downloaded for you.
* Frame rates differ by engine (TI2V-5B 24 fps, A14B native 16 fps), so 81 frames is a different clip length per arm.
  Compare motion and identity, not duration.
* This only queues and measures. It makes no claim that either candidate is better: that needs a separately authorized
  physical run and your ratings (sections 4 and 5). As of this writing no physical eval has been run.

## 7. A14B speed-arm example suite (VID-A14B-SPEED-374)

`docs/runbooks/examples/video_eval_a14b_speed_arms.suite.json` compares the approved I2V-A14B 4-step 1.0.0 (baseline)
with its three experimental speed arms on eight identical cases (same images, prompts, seed 374 and 81 frames): a turn
around, a walk toward the camera, a close-up face, a wave, a side step, wind in hair and clothing, a laugh and a landscape
sit-down. 8 cases x 4 arms = 32 jobs. Its image names are synthetic placeholders: copy the file next to your own images
(for example the VID-CLIP-371 Stage 2 full-body sources, which stay private and are not in the repository) and change
`image`, ideally pinning `image_sha256`. Nothing is queued until you choose **Queue eval suite...** and confirm the plan.

| Arm | Version | What changes against 1.0.0 |
|---|---|---|
| `a14b_base` (baseline) | 1.0.0, approved | Nothing: the promoted graph. |
| `a14b_ck_attention` | 1.1.0, experimental | One `ModelAttentionBackend` ("comfy kitchen attention", INT8) per expert. Refused before dispatch if ComfyUI does not offer that option. |
| `a14b_merged` | 1.2.0, experimental | lightx2v merged scaled-fp8 4-step experts, no LoRA nodes. Needs the two pinned 15 GB files in `models/diffusion_models`. |
| `a14b_gpu_te` | 1.3.0, experimental | UMT5 text encoder on the GPU instead of the CPU; expected near pixel-identical, so compare speed first. |

* The three candidate arms set `"experimental_opt_in": true`; the queue confirmation names them.
* Versions never share a warm ComfyUI process (the warm hold keys on workflow id and version), so each change of arm
  in the queue is a cold start. Compare generation time per arm from the job records, not across arm changes alone.
* This only queues and measures. Whether any arm is faster without losing quality is your rating's call (sections 4
  and 5); no physical run has been made.

## 8. A14B SVI 2.0 sequence example suite (VID-A14B-SVI-375)

`docs/runbooks/examples/video_eval_a14b_svi_sequence.suite.json` compares plain last-frame carry with Stable Video
Infinity 2.0 on eight three-segment sequence cases (a walk that stops, a full turn and back, a close-up face, a wave
then point, side steps, wind in hair, sit down and stand up, picking up a cup). Seed 372, so segments use 372, 373 and
374 (the WAN-BENCH-373 SVI rerun's seeds); 81 frames per segment; the same negative prompt on every case (it matters at
CFG 1.5 and is ignored at CFG 1). 8 cases x 4 arms = 32 jobs, 96 segment generations. Its image names are synthetic
placeholders: copy the file next to your own images and change `image`, ideally pinning `image_sha256`.

| Arm | Workflow | What it tests |
|---|---|---|
| `plain_carry` (baseline) | `wan22_i2v_a14b_4step_v1` 1.0.0, approved | The promoted graph with plain last-frame carry: no SVI, no reference pad. |
| `svi_derived` | `wan22_i2v_a14b_svi` 1.0.0, experimental | Our derived copies of the official bf16 SVI LoRAs (key prefix only), CFG 1.5. |
| `svi_kijai` | `wan22_i2v_a14b_svi` 1.1.0, experimental | Kijai's fp16 repack of the same LoRAs, CFG 1.5. Compare with `svi_derived` for adapter source. |
| `svi_derived_cfg1` | `wan22_i2v_a14b_svi` 1.2.0, experimental | The derived LoRAs at CFG 1.0. Compare with `svi_derived` for CFG. |

* The three SVI arms set `"experimental_opt_in": true`; the queue confirmation names them.
* Every SVI segment pads its image conditioning with segment 0's prepared source (`ref_pad_image`) while starting from
  the carried frame. Readiness refuses a ComfyUI whose `WanImageToVideo` lacks that input, and a job whose adapter files
  are not in `models/loras` (names and SHA-256 in the catalog). Nothing is downloaded for you.
* Each arm change is a cold start (the warm hold keys on workflow id and version); a sequence keeps its own process warm
  across its segments.
* This only queues and measures. Whether SVI holds identity better, and which adapter or CFG to keep, is your rating's
  call (sections 4 and 5); no physical run has been made through StableNew.
