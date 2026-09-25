# PR-VID-181 — Wan2.2-Animate Upstream-Compatible Real-Driving Pose Adjudication

Status: **`PR-VID-181 — COMPLETE / ACCEPTED / INTEGRATED — ANIMATE_REAL_POSE_LOCAL_MOTION_ONLY`**;
secondary finding **`BACKGROUND_INSTABILITY_CROSS_CASE`**. Qualification only. No production `src/` change, no
backend, no resolver/controller/queue/NJR change, no workflow registration. Start
`main @ 435b6130360201cb958f146bc8e742960268af0d`. Two Animate generations were run (Case A
gesture, Case B locomotion) after the owner's explicit go-ahead; a preprocessing gate preceded them.

## Scope and machine constraint

PR-VID-180 ended `ANIMATE_CHARACTERIZATION_INCONCLUSIVE` because procedural synthetic pose
conditioning failed while detector-derived real-human Case C succeeded. PR-VID-181's adjudication
needs real gesture/locomotion footage converted through Wan2.2-Animate's own whole-body pose
semantics, then two Animate generations at the proven 480×832 envelope.

DIAG-GPU-130 (post-DDR5-5600 black-screen recurrence) stays unresolved by owner decision. Its
conclusion was amended 2026-09-24 (driver-package isolation deprioritized by cross-version
recurrence evidence; next isolation targets the platform baseline, one variable at a time). The
owner subsequently confirmed removal of the RAM XMP profile before the 2026-09-25 07:06:20 ET
reboot; Windows observed both DIMMs at configured 5600 MT/s and 1100 mV. Windows cannot confirm
the firmware toggle, Intel Baseline/Default, timings, or controller state. This remains
XMP-OFF isolation in progress / observation only, not a PASS, fix, or root-cause attribution.
These VID-181 generations preceded the intervention and used the prior machine state. The
owner gave an explicit GPU go-ahead on 2026-09-24, so the package proceeded in two stages:
**(1)** CPU-only preprocessing (no Comfy, A1111 or CUDA; not counted as a DIAG-GPU-120 exposure),
then **(2)** exactly two Animate generations under the unchanged commit-aware safety thresholds.
Machine state at the runs: DDR5-5600 at 1.25 V (XMP not yet removed), uptime 12.1 h, GPU idle
(about 0.9 GB used, 0%, 38 C) with no other GPU process or server before Case A.

## Upstream authority (pinned)

`Wan-Video/Wan2.2 @ 1ea34ff48f87168174e12956e200b1d908b1c5ff` (fetched by SHA into a disposable
directory outside every runtime; `git rev-parse HEAD` verified, and the launcher refuses any other
SHA). Mandatory components used unmodified: `Pose2d` (YOLOv10m detector + ViTPose-H whole-body),
`AAPoseMeta.from_humanapi_meta`, `draw_aapose_by_meta_new`, `resize_by_area`, `get_frame_indices`,
`padding_resize`, `get_face_bboxes`. No renderer was reimplemented.

## Disposable preprocessing environment

- Location/type: `C:\Users\rob\qual\vid181\` — a fresh `venv` (Python 3.11.9) plus the upstream
  checkout and checkpoints, entirely outside StableNew `.venv`, Comfy Desktop, Comfy
  `.venv-explicit` and A1111. Nothing was installed into any production environment. It is not in
  Git.
- Packages: `onnxruntime 1.30.0` (CPU build), `torch 2.14.0+cpu`, `numpy 2.4.6`,
  `opencv-python-headless 5.0.0`, `decord 0.6.0`, `moviepy 2.2.1`, `pillow`, `matplotlib`,
  `loguru`, `tqdm`, `huggingface_hub` (checkpoint download only).
- Providers: `onnxruntime.get_available_providers()` = `AzureExecutionProvider`,
  `CPUExecutionProvider`; both detector and pose sessions report exactly
  `["CPUExecutionProvider"]`; `torch.cuda.is_available()` and `torch.cuda.is_initialized()` both
  `False`; `CUDA_VISIBLE_DEVICES=-1` is set by the launcher before any heavy import. The launcher
  aborts if any non-CPU provider is active or CUDA initializes. These values are recorded in every
  case's `preprocess_evidence.json` (workspace, not committed).

## Detector/pose checkpoints

Source: Hugging Face `Wan-AI/Wan2.2-Animate-14B`, revision
`cb93a225fbaf1ca100f54e79da8f994995b689b3`, `process_checkpoint/`. No SAM2, no FLUX, no
replacement-mode or Flux-retargeting assets were acquired or used.

| File | Bytes | SHA-256 |
|---|---:|---|
| `det/yolov10m.onnx` | 61,659,339 | `89b526498a6d55f869a6ab52e3a2eb20ad45b3711c1f7de3dd9ca0b399dfd6d7` |
| `pose2d/vitpose_h_wholebody.onnx/end2end.onnx` | 412,883 | `e5dab9693f9fb437516955c42040ebb13664e66ca49ee7b619dde4a9972fa3e4` |
| `pose2d/vitpose_h_wholebody.onnx/` (directory: `end2end.onnx` + 393 external weight files) | 2,549,362,899 (394 files) | manifest `fa4607dcbc7cf504a879b63a1aa7d73241a3a1715d715da2a69390b96d630b53` |

`vitpose_h_wholebody.onnx` is a directory in the upstream repo; upstream's `SimpleOnnxInference`
resolves it to `end2end.onnx`. The manifest hash is over sorted `relative-path, size, SHA-256`
lines (`tools/qualification/vid181/provenance.py:tree_sha256`).

## Recorded deviations from `preprocess_data.py`

1. Thin launcher (`tools/qualification/vid181/preprocess_launcher.py`) instead of
   `preprocess_data.py`, because upstream `process_pipepline.py` imports diffusers/FLUX and SAM2 at
   module import even in animation mode. It reproduces only the animation-mode,
   `retarget_flag=False` orchestration and calls the pinned upstream functions for every semantic
   step.
2. `resize_by_area(..., divisor=16)` (upstream's own replacement-mode value). The animation-mode
   default of 64 would yield 448×832 for the accepted 480×832 reference. Upstream's
   `calculate_new_size` also raises internally (`check_valid` called with three arguments) and is
   caught by a bare `except`, so the fallback path is what actually sizes the image; floating-point
   rounding there gives **464×832**, not 480×832. The final control therefore has 8 px black side
   padding to reach the frozen 480×832 (scale 1.0, no stretching).
3. The unused `pose2d(frames[:1])` retarget-template call is skipped.
4. **Driving-footage pre-step (new, recorded):** a fixed (non-tracking) crop with the exact 29:52
   aspect of the pose geometry, scaled to 464×832 (`driving_prep.py`). Without it, a 1280×720
   source puts a small figure in a letterboxed landscape pose frame (observed in a first attempt:
   the rendered figure was a tiny stick figure), which would not be a fair Animate control. A fixed
   crop never removes image-space root translation and never stretches pose geometry.
5. Video writing uses upstream's own `moviepy` `ImageSequenceClip.write_videofile`; moviepy can write
   one frame fewer than requested for very short clips (seen on a rejected 20-frame Case B window:
   19 pose frames); the accepted windows read back their full frame counts.

## Official-example smoke gate — PASS

Inputs (pinned checkout): `examples/wan_animate/animate/video.mp4`
(`80f3cfe3786a7f8a94844476448fb45e7e115216ddcdaad14b0b88223be597e7`, 1920×1080, 30 fps, 106
frames) and `image.jpeg` (`8123db8e5c47c3a229c288b4c5245e8ee2ce4378b1c09e92873b75939812eb7b`).
CPU-only run completed (about one minute); detector succeeded on all 106 frames (mean body
keypoint confidence min 0.585, mean 0.625; reference image 0.626).

| Output | SHA-256 | Geometry |
|---|---|---|
| `src_pose.mp4` | `4974f4c5ab8d87a25dd4f4ff739ad768ecf4fa8f6fb3d0a6d1d066f98cae369d` | 832×464, 30 fps, 105 frames read back (moviepy) |
| `src_face.mp4` (evidence only, not consumed) | `8c860307d9c017be835e5bb78d07366b559ce720aea1746474b836e70f27d39f` | 512×512, 30 fps |

Direct inspection of a contact sheet: the output is visibly the upstream Wan pose representation
(colored whole-body limb skeleton, head/eye/ear markers, per-finger hand strokes), not the
PR-VID-170/180 procedural stick figure. No Animate generation was run on this example.

## Real driving footage

Both clips are real single-person stock footage from Mixkit (no AI generation, no skeleton/pose
generator). **License caveat:** the item pages declare the "Stock Video Free License", verified in
the fetched page HTML; the license terms text itself is loaded dynamically by mixkit.co/license and
was **not machine-verified in this session**. Use here is internal local qualification only; the
clips are not committed or redistributed. The product owner should confirm the license terms before
any redistribution or reuse beyond local qualification. Download date 2026-09-23. Selection
history: about 330 Mixkit clips were screened (CPU YOLO person detector plus optical-flow camera
motion: static camera, exactly one person, real lateral travel). Static-camera single-person
lateral walkers are essentially absent from that catalogue, and Pexels/Pixabay block automated
access (HTTP 403); Internet Archive public-domain search returned old films with cuts. A first
walking candidate (#4855) was **rejected** because its camera pans with the subject (no image-space
root translation). Clip #583 was kept, and a first 4.1-4.9 s window of it was **rejected** for
detector glitches (lower-body keypoint confidence min 0.52, one spurious foot line, one dropped
leg) in favour of the 3.0-4.2 s window below (lower-body confidence min 0.89). The rejected-window
outputs are kept in the workspace for comparison.

| | Case A — gesture | Case B — locomotion |
|---|---|---|
| Source | Mixkit #1053 "Woman doing yoga on a deck", `https://mixkit.co/free-stock-video/woman-doing-yoga-on-a-deck-1053/` | Mixkit #583 "Woman doing warm-up exercises", `https://mixkit.co/free-stock-video/woman-doing-warm-up-exercises-583/` |
| Download | `assets.mixkit.co/videos/1053/1053-720.mp4` | `assets.mixkit.co/videos/583/583-720.mp4` |
| Original SHA-256 | `f4d36d3e4948c98f4e9f573b346718e524def852d31bb35f253273521de5f910` | `da49964c6d418ae7a7cc6b8972617d6e35bff588e656d55f67d645974b4cd346` |
| Original | 1280×720, 24 fps, 507 frames | 1280×720, 24 fps, 240 frames |
| Window | 0.5 s + 6.0 s (arm raise from low lunge to overhead, hold, open overhead) | 3.0 s + 1.2 s (silhouetted athlete stepping/jogging left to right across a static frame) |
| Fixed crop | x=490 y=0, 377×676 | x=140 y=20, 377×676 |
| Driving clip SHA-256 (464×832, 24 fps) | `59cf380c7e0076ae649c4bf824cddc18795610af029fb2f61d20f777a67ba024` (144 frames) | `afe3637aa060fd5855d2feb37b58ab81d300252615daa2b0b8f202d8158edce4` (29 frames) |

## Pose extraction (upstream path, CPU-only, `retarget_flag=False`)

| | Case A | Case B |
|---|---|---|
| Body-keypoint confidence, per-frame mean (min / mean) | 0.838 / 0.894 | 0.825 / 0.856 (lower-body knees/ankles: min 0.891, mean 0.906) |
| Full upstream `src_pose.mp4` SHA-256 | `8ecc7fff56b60093a4ed224a72e3b1dc0962378a50c6628214daa5b1126f04d9` (464×832, 24 fps, 144 f) | `0b7087eff9bf73dd8d9fe6de64a036aeb275f555d19ff445a766eeb8236e2d4b` (464×832, 24 fps, 29 f) |
| Final control SHA-256 (480×832, 13 f, 8 fps) | `96705f92ddd123ee6f8382f4b5926ceac1366687f4dbfa8683e6f5af146c3cbf` | `b685a39d3ab374d0b7b05ba287964038b6ab6ebd3bba6ed757138057468a288c` |
| Selected source-frame indices | 0, 11, 23, 35, 47, 59, 71, 83, 95, 107, 119, 131, 143 | 0, 2, 4, 7, 9, 11, 14, 16, 18, 21, 23, 25, 28 |
| Adaptation | 8 px black side padding (464→480), scale 1.0 | same |
| `src_face.mp4` SHA-256 (generated; not consumed) | `251ccddf62877eee8aafa52404ab0b51e71a7048fd920e7cd614e7968f738a6a` | `1daef201600fd8e0d4f4705d21993d28764108c683dea851a7f3d1c5aa615012` |

Frame selection is the accepted evenly-spaced `numpy.linspace` convention (identical to
PR-VID-160C/170/175/180); no frame was hand-picked.

### Visual pose-preflight (direct inspection of full and final contact sheets)

- **Case A — PASS.** The upstream representation clearly contains the gesture: arms swing up from
  a low lunge, hold overhead with visible finger strokes, then open into a V. Full-body legs and
  head markers are present. The first frame's detection is folded/noisy (start of the crouch).
- **Case B — PASS.** The final pose shows a clean, consistent skeleton in all 13 frames (no
  spurious limb lines, no dropped legs; lower-body keypoint confidence min 0.891), alternating leg
  progression with growing knee lift, and monotonic left-to-right root translation: the rendered
  bounding-box center moves 0.29 → 0.69 of the frame width (0.40 of the width) with the figure at
  about 0.59 of the canvas height; the camera is static. Residual caveats: the source is a
  silhouette against the sky (dark figure, no clothing/face detail — the detector still tracked it
  well), the motion is a warm-up step/jog with accelerating cadence rather than a plain walk, and
  the window is 1.2 s. The defining motions (alternating steps, foot/leg progression, root
  translation) are all present. The final control hash reproduced exactly when the window was
  re-run from scratch.

## Retarget and face policy

`retarget_flag=False` (default, no Flux, no basic retargeting) — a bounded deviation from
upstream's recommendation for differing body proportions, chosen to isolate the
detector/representation variable. `src_face.mp4` was generated by upstream animation preprocessing
and **preserved as evidence but not consumed**: the future Animate graph stays frozen without
`face_video` (tested).

## Animate generations (executed)

Configuration (frozen, identical to PR-VID-175/180 except the pose control):
`tools.qualification.vid170.graph.CharacterizationSpec` at 480×832 — Q3_K_M transformer, same
UMT5/VAE/CLIP Vision, reference `reports/vid110/inputs/source_fullbody.png`
(`362c86cc83876e340b8927dd54a0f55af1c5fb82c1e9c98d624e67044afa71bb`), 13 frames, 8 fps, 20 steps,
cfg 1.0, shift 5.0, `uni_pc`/`simple`, seed 1733123036, official prompt, `pose_video` present,
`face_video` absent. `tools/qualification/vid181/run.py` refuses a control whose SHA-256 differs
from the frozen value (A `96705f92…`, B `b685a39d…`), submits exactly one prompt per invocation,
and has no retry path or `face_video` path.

Order: pre-run gate, Case A, return to idle (GPU 0.9 GB / 1%, no Comfy process, no
display/WHEA/kernel-power events), Case B. Exactly **two** generations, no retries, no Case C rerun.

| | Case A — gesture | Case B — locomotion |
|---|---|---|
| prompt_id | `02a8b059-8379-4eb5-9b05-569124defebd` | `f067ae15-9d6c-4ccb-b7bf-5275d5c24ff0` |
| status / safety stop | `completed` / none | `completed` / none |
| wall seconds | 129.3 | 127.2 |
| VRAM peak (headroom of 12,282 MiB) | 11,389 MiB (893) | 11,324 MiB (958) |
| physical RAM available, min | 2.83 GB | 4.17 GB |
| commit peak / min headroom (limit 63.76 GB) | 77.17% / 14.55 GB | 77.28% / 14.49 GB |
| swap used, max | 0.69 GB | 0.69 GB |
| temperature peak / power peak | 77 C / 236.3 W | 79 C / 239.1 W |
| teardown | clean (`managed_comfy_owned`, no errors) | clean |

Both runs sit well inside every PR-VID-160C threshold and are lighter on commit than PR-VID-175
Case C (81.72% / 11.66 GB) and PR-VID-180 A/B (about 81.5% / 11.8 GB). After both runs: GPU idle,
no display, WHEA, kernel-power or bugcheck events in the following 40 minutes. This is one
observation-only DIAG-GPU-120 exposure per run (two total); not a stability PASS.

### Objective proxies (corroborating only; background hallucination contaminates optical flow)

| Metric | A (181) | B (181) | A (180 synthetic) | B (180 synthetic) | C (175 reused) |
|---|---|---|---|---|---|
| `local_motion_px` | 3.347 | 3.498 | 0.532 | 2.152 | 2.804 |
| `camera_drift_px` | 0.135 | 0.206 | 0.016 | 0.247 | 0.251 |
| `motion_area_fraction` | 0.604 | 0.575 | 0.170 | 0.453 | 0.628 |
| `temporal_jitter` | 4.432 | 3.199 | 0.732 | 5.948 | 6.611 |
| `identity_hist_mean` / `min` | 0.353 / 0.197 | 0.324 / 0.278 | 0.248 / 0.208 | 0.498 / 0.305 | 0.549 / 0.308 |
| control→output motion-curve correlation | **0.419** | **-0.132** | -0.089 | 0.005 | 0.398 |

The motion-curve correlation is a timing/motion-energy proxy, not skeletal adherence. Case A now
correlates with its control about as well as Case C did (0.42 vs 0.40, versus -0.09 for the
synthetic control); Case B does not (-0.13), which is consistent with the direct observation below.

### Human visual rubric (raw 1–5, not averaged; full 13-frame sheets plus full-resolution frames)

| Criterion | Case A (gesture) | Case B (locomotion) |
|---|---|---|
| Identity retention | 3 — dark hair, dark leggings with a teal waistband and white/blue sneakers stay consistent with the reference; the reference's navy tee is replaced by a skin/purple sports-top look and accessories (wrist bands) appear, i.e. appearance leakage from the driving footage; face only partly visible | 4 — from frame 5 a figure clearly matching the reference (navy tee, navy leggings, teal/white shoes) is present in every frame |
| Face stability | 2 — face visible in a few frames, not stable | 2 — the face region has garbled rectangular artifacts |
| Anatomy | 4 — credible lunge and overhead arm raise; later frames (10–12) blur/double a limb | 3 for the static figure (torso print artifacts); 1 for the moving figure |
| Driving-motion adherence (subject) | 4 — arms rise, hold overhead, then open, in the control's order; correlation 0.42 | **1 — the reference-identity figure is essentially static (arms at sides, feet planted) for the whole clip** |
| Root translation / locomotion | n/a | **1 — no stepping or translation of the reference subject.** A separate, blurred, differently dressed figure (dark top, grey legs) performs the knee-lift stepping and moves left to right, i.e. the control's motion appears on a second, hallucinated figure rather than on the subject |
| Temporal coherence | 3 — smooth through the hold; frame 0 is a discontinuous seated pose and frames 10–12 degrade | 2 — static figure stable, moving figure and background unstable |
| Subject framing | 4 — full body stays in frame | 3 — subject stays in frame but occupies the left side while the action is elsewhere |
| Background stability | 1 — severe hallucination (white/purple blocks, a second pair of legs top right) | 1 — severe hallucination plus the ghost figure |
| Overall usefulness | 3 — gesture is genuinely transferred to a recognisable person, with clothing drift and artifacts | 1 — the decisive locomotion behaviour is not delivered to the subject |

Gates: **gesture — PASS** (with appearance drift); **locomotion — FAIL** (planted subject, motion
on a ghost figure); **identity — partial** (A drifts in clothing, B keeps the reference look but
does not move); **background — FAIL**, recorded separately.

## Comparison and interpretation

**Versus PR-VID-180 (procedural synthetic controls).** Case A went from total failure (no
recognisable subject, all-1 rubric, correlation -0.09) to a clear gesture transfer onto a
recognisable person (correlation 0.42). With the inference graph and settings unchanged, the
conditioning representation/provenance was therefore a material cause of PR-VID-180's gesture
failure, and Animate's gesture capability at this envelope is viable. Case B shows the **same
failure pattern** as PR-VID-180 B — a static reference-like figure plus a separate blurred moving
figure — now with a valid upstream-derived control. The representation confound therefore does
**not** explain the locomotion failure by itself; the locomotion-specific weakness is not resolved
by better pose conditioning at this envelope. This is not strict one-variable causality: the raw
motion, source footage and control geometry differ between the two packages.

**Versus PR-VID-150 (TI2V-5B, `local_motion_viable_locomotion_weak`).** Case B did not solve the
planted-feet/root-translation gap: the subject is planted. Animate does carry the stepping motion
onto a second figure, which shows the pose signal is being used but not bound to the reference
identity.

**Versus PR-VID-110/VACE and Case C.** Identity is partly retained under real-motion-derived pose
input (A keeps hair/legwear/shoes; B keeps the full reference look), but A shows clothing leakage
from the driving subject, so identity is usable rather than clean.

**Caveats that limit the locomotion verdict:** one generation, one seed, one control that is a
1.2 s silhouetted step/jog whose skeleton starts left of the reference position and travels right
(the reference stands near the centre); `retarget_flag=False` (upstream recommends retargeting for
differing proportions; not tested); `face_video` absent. These are recorded, not resolved here.

## Decision

**`ANIMATE_REAL_POSE_LOCAL_MOTION_ONLY`** — gesture A transfers; locomotion B still fails true
stepping/root translation of the subject. Secondary: **`BACKGROUND_INSTABILITY_CROSS_CASE`**
(now observed in all five cases: PR-VID-175 C, PR-VID-180 A/B and PR-VID-181 A/B) — a material
independent quality defect requiring separate mitigation/adjudication, not yet declared a
production NO-GO.

## Validation

`tests/tools/test_vid181_preprocessing_gate.py` (20 tests): pinned upstream/checkpoint identity;
CPU provider forced by contract (CUDA disabled before heavy imports); production environment
prefixes (StableNew `.venv`, Comfy, `.venv-explicit`, WebUI, A1111) rejected, including through the
launcher entry point before any work; unpinned upstream checkout rejected; deterministic tree/file
hashing; frame selection equal to the PR-VID-160C convention; final adaptation deterministic at
480×832 / 13 f / 8 fps and letterbox-without-stretch for other geometry; undecodable input
rejected; driving crop exact 29:52 aspect and filter shape; future Animate spec frozen with
`face_video` excluded. `tests/tools/test_vid181_runner.py` (11 tests): only A/B runnable, frozen control hashes enforced (mismatch/missing refused, exact bytes accepted), spec frozen with `face_video` excluded and A/B graphs differing only by pose asset, external-Comfy refusal, exactly-one-submission/no-retry, evidence persistence, owner-only teardown, safety thresholds unchanged. Together with the reused VID-170/175/180 suites: 73 passed before the runner tests, 84 with them. Ruff clean;
`git diff --check` clean. Physical preprocessing evidence lives in the workspace, not the repo, and
detector accuracy is not unit-tested with mocks.

StableNew Actions run `36001972330`: required Python 3.11 and 3.12 jobs passed. The informational
broader configured suites retain the known `Run broader configured suite (Xvfb)` failures. VID-181
qualification source is unchanged since that run; this integration reuses that green required-CI
evidence. No GPU workload was run for this closeout.

## Architecture effect

None. Qualification tooling only (`tools/qualification/vid181/`). No StableNew, Comfy or A1111
environment changed; no production dependency added; no queue, history, resolver, controller or
runner authority created.

## Subsequent basic-retarget applicability result

`PR-VID-182 — Wan2.2-Animate Case-B Basic Pose-Retargeting Adjudication` subsequently found
**`BASIC_RETARGET_PRECONDITION_NOT_MET`** before preprocessing or GPU work. Pinned upstream basic
retargeting requires both the reference and first driving frame to be front-facing and stretched;
the frozen Case-B frame 0 is a lateral-profile, high-knee step/jog silhouette. No source/window/
crop/reference change, Flux, `face_video`, retargeted control, or Animate generation occurred.
See `PR-VID-182_Wan22_Animate_Basic_Pose_Retargeting_Adjudication.md`. Gesture-only experimental
use remains supported by Case A subject to clothing drift and background defects; Animate is not
promoted for locomotion on this evidence.

## Docs / Git

New: this report, `tools/qualification/vid181/` (`provenance.py`, `preprocess_launcher.py`,
`driving_prep.py`, `finalize.py`, `run.py`), `tests/tools/test_vid181_preprocessing_gate.py`,
`tests/tools/test_vid181_runner.py`. Not committed: detector checkpoints, raw/trimmed/cropped
footage, pose and generated videos, telemetry, the disposable environment and the upstream
checkout (`reports/` is git-ignored). Integrated to `main` with product-owner acceptance and
fast-forward-only main integration. Exactly two generations and no retries occurred; no
production, Comfy-configuration or A1111 change.
