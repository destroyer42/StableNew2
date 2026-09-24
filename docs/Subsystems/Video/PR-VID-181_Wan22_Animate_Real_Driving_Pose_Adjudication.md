# PR-VID-181 — Wan2.2-Animate Upstream-Compatible Real-Driving Pose Adjudication — Preprocessing Gate

Status: **`PREPROCESSING_GATE_PASS / GPU ADJUDICATION BLOCKED BY DIAG-GPU-130`** (Case B re-sourced
to a cleaner window; residual caveats recorded below). Qualification only. No production `src/` change, no backend, no
resolver/controller/queue/NJR change, no workflow registration. Start
`main @ 435b6130360201cb958f146bc8e742960268af0d`. **No Animate generation was run; Animate
capability is not classified by this package.**

## Scope and machine constraint

PR-VID-180 ended `ANIMATE_CHARACTERIZATION_INCONCLUSIVE` because procedural synthetic pose
conditioning failed while detector-derived real-human Case C succeeded. PR-VID-181's adjudication
needs real gesture/locomotion footage converted through Wan2.2-Animate's own whole-body pose
semantics, then two Animate generations at the proven 480×832 envelope.

DIAG-GPU-130 (post-DDR5-5600 black-screen recurrence) is the active machine authority.
Its conclusion was amended 2026-09-24: NVIDIA driver-package isolation is deprioritized by
cross-version recurrence evidence, and the next isolation targets the platform baseline, one
variable at a time. Deliberate high-load Animate/Comfy/A1111 generation is **not** authorized
until the owner authorizes it against DIAG-GPU-130's then-current state. This
package therefore did **preprocessing only**: CPU-only pose extraction, source acquisition and
provenance, deterministic control preparation, tests and documentation. Comfy, A1111 and CUDA were
never started or initialized, and preprocessing is not counted as a DIAG-GPU-120 exposure.

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

## Frozen future Animate inference (unchanged; not run)

`tools.qualification.vid170.graph.CharacterizationSpec` at 480×832: Q3_K_M transformer, same
UMT5/VAE/CLIP Vision, reference `reports/vid110/inputs/source_fullbody.png`
(`362c86cc83876e340b8927dd54a0f55af1c5fb82c1e9c98d624e67044afa71bb`), 13 frames, 8 fps, 20 steps,
cfg 1.0, shift 5.0, `uni_pc`/`simple`, seed 1733123036, official prompt, `pose_video` present,
`face_video` absent. `tools/qualification/vid180/run.py` is unchanged; the two new controls would
need a small VID-181 runner (not authorized or written here).

## Validation

`tests/tools/test_vid181_preprocessing_gate.py` (20 tests): pinned upstream/checkpoint identity;
CPU provider forced by contract (CUDA disabled before heavy imports); production environment
prefixes (StableNew `.venv`, Comfy, `.venv-explicit`, WebUI, A1111) rejected, including through the
launcher entry point before any work; unpinned upstream checkout rejected; deterministic tree/file
hashing; frame selection equal to the PR-VID-160C convention; final adaptation deterministic at
480×832 / 13 f / 8 fps and letterbox-without-stretch for other geometry; undecodable input
rejected; driving crop exact 29:52 aspect and filter shape; future Animate spec frozen with
`face_video` excluded. Together with the reused VID-170/175/180 suites: 73 passed. Ruff clean;
`git diff --check` clean. Physical preprocessing evidence lives in the workspace, not the repo, and
detector accuracy is not unit-tested with mocks.

## Architecture effect

None. Qualification tooling only (`tools/qualification/vid181/`). No StableNew, Comfy or A1111
environment changed; no production dependency added; no queue, history, resolver, controller or
runner authority created.

## Classification and remaining block

**`PREPROCESSING_GATE_PASS / GPU ADJUDICATION BLOCKED BY DIAG-GPU-130`.** Animate motion capability
is **not** classified. The two Animate generations (real-human gesture, real-human locomotion at
480×832, inference frozen, `face_video` absent) remain the adjudicating experiment.

Remaining blocks before that experiment: (1) DIAG-GPU-130 remains unresolved by owner decision (2026-09-24): the owner plans to remove the RAM XMP profile at the next reboot and report any recurrence for monitoring/investigation, and has **not** authorized Animate generation - an explicit owner go-ahead is still required before any GPU run; (2) resolved: the Mixkit license was confirmed acceptable by the owner for this personal-use testing (2026-09-24) and the Case B control (silhouetted step/jog, 1.2 s) was accepted as the locomotion control; (3) a thin VID-181 runner over `vid170.graph`/`vid160b`/`vid160c` must be added at
that time.

## Docs / Git

New: this report, `tools/qualification/vid181/` (`provenance.py`, `preprocess_launcher.py`,
`driving_prep.py`, `finalize.py`), `tests/tools/test_vid181_preprocessing_gate.py`. Not committed:
detector checkpoints, raw/trimmed/cropped footage, pose videos, the disposable environment and the
upstream checkout. Not integrated to `main` without product-owner review.
