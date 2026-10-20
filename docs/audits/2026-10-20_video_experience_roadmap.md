# Image-to-video experience: assessment and product roadmap

Date: 2026-10-20. Type: Focused assessment (read-only; no generation, GPU probing or runtime change), assessed at
`4c422726`. **Status: accepted by the owner on 2026-10-20 as the reference roadmap for video** (decisions in section 6.1).
It does not supersede `STATUS.md` or `docs/Subsystems/Video/VIDEO_PIPELINE.md`; the code and those files win where they
disagree. Each PR still lands under its own scope and acceptance; protected actions (push to `main`, merge) still need
their own approval.

Evidence labels: **[V]** read in the code at this SHA; **[O]** measured on real output files in `output/`; **[R]** taken
from a per-PR evidence record under `docs/Subsystems/Video/`; **[W]** external (web) and not verified here; **[I]** inference.

---

## 1. Executive summary

Turning an image into a video in StableNew today produces **a 2-3 second clip at low resolution and low bitrate**.
The better backend fails on a configuration gate most of the time, and nothing in the product can make a longer clip.
These are not model limits. Most of the problem is self-inflicted and cheap to fix.

What the real outputs show [O]:

| Output (2026-10-17) | Length | Resolution | Bitrate | Notes |
|---|---|---|---|---|
| Native SVD XT, the "Recommended" preset | **2.0 s** | 768x768 square crop of a portrait image | **598 kbps** | 14 generated frames, RIFE x4 to 56 frames at 28 fps |
| Wan2.2 TI2V-5B via Comfy | 3.4 s | 480x832 | 1.5 Mbps | 81 frames at 24 fps, the maximum the catalog allows |
| Wan-Animate-2 attempts | none | none | none | **4 of 4 refused** before dispatch: `comfy_command` lacks `--disable-pinned-memory` |

Four root causes, in order of value per unit of effort:

1. **The production SVD path is configured against its own model [V].**
   - The VAE decodes 2 frames at a time (`decode_chunk_size=2`), so the temporal decoder cannot keep frames consistent. This is the flicker.
   - Motion is suppressed: motion bucket 48 against the model's operating point of 127, and noise augmentation 0.01.
   - Only 14 frames are generated. `fps` conditioning never reaches the pipeline.
   - The MP4 is encoded with no CRF (x264 default 23), no colour tags, and through the concat demuxer with float frame durations.
   - Each of these is a one-line-to-one-function fix.
2. **The better backend is hard to reach and runs on an under-qualified model choice [V/R/O].**
   - The Wan path needs manual `presets/settings.json` editing. The error message points to an "Engine Settings" field that does not exist.
   - The experimental opt-in resets on every workflow change, readiness is invisible until the job fails in the queue, and you need about 9-10 actions per clip.
   - Model-wise, the video line spent about 16 packages qualifying TI2V-5B, which ran at 480p below its 720p design resolution, and the Animate family, a *motion-transfer* model, not a prompt-directed I2V model.
   - The strongest model class that fits a 12 GB card was **never evaluated**: Wan2.2 I2V-A14B with a 4-step distill LoRA, plus Wan2.2 first-last-frame (FLF2V). Both run on **stock Comfy nodes**, which matches the managed runtime's "no custom nodes" policy.
3. **No length architecture exists.**
   - Every path tops out at about 3.4 s.
   - The multi-segment sequence layer is unreachable: nothing writes `sequence_metadata`.
   - It is also broken: the carry-forward passes an `.mp4` path into `LoadImage`, per-segment length and seed are ignored, and Comfy is restarted cold between segments.
   - Movie Clips is a `-c copy` concat with no transitions, no normalization and a filename sort that overrides the user's order.
4. **Process cost crowded out product.**
   - In the video line about 16 qualification- or adjudication-only packages shipped against about 9 user-facing ones [R].
   - Gates (a 0.30 motion-curve correlation, RAM stop thresholds) were later overturned by the owner's own judgement of the clips.
   - Promotion criteria were never reached, so the opt-in friction is permanent.

**The plan, in one line:** fix SVD and encoding this week (Phase A) and remove the setup and gating friction in parallel
(Phase B). Then add Wan2.2 I2V-A14B and first-last-frame as the quality and motion-control backbone, judged by a reusable
eval kit instead of per-candidate qualification packages (Phase C). Then make clips long by chaining keyframe-anchored
segments into a **Storyboard → Movie** flow (Phase D), and close the loop with best-of-N, video ratings and learned
presets (Phase E).

North-star targets on the current RTX 4070 Ti 12 GB / 32 GB RAM:

| Metric | Today | Phase A/B target | Phase D target |
|---|---|---|---|
| Single-clip length | 2.0 s (SVD), 3.4 s (Wan) | 3.6 s SVD at 24+ fps; 5 s Wan | 10-30 s as a stitched sequence |
| Playback fps | 28 after RIFE x4 of 14 frames; 7 without | ≥24 by default on every path | ≥24 |
| Encode | CRF 23 default, untagged, about 0.6 Mbps at 768² | CRF 14-17, BT.709 tagged, faststart | same |
| Actions from image to playing clip | 5 (SVD), 9-10 + setup (Wan) | ≤3, playback in-app | ≤3 per shot; storyboard ≤1 per keyframe |
| Jobs failing on a preventable config gate | 4 of 5 Comfy jobs (2026-10-17) | 0; refused *before* submit with a fix button | 0 |
| Clip consistency (flicker, identity) | Visible pair-boundary flicker (decode chunk 2) | Decode whole clip; colour-matched segments | Keyframe-anchored (FLF2V) |

---

## 2. Constraints that shape the plan

**Hardware** (`requirements`/constraints header, PR-VID-110 §2, DIAG-GPU-100 [R]):
- GPU: RTX 4070 Ti, 12,282 MiB, Gen4 x16.
- CPU: i9-13900K.
- RAM: 2x16 GB (about 31.8 GB visible), Windows commit limit 55-64 GB.

What the measured runs show [R]:
- **VRAM is not the binding constraint. Host RAM is.** Comfy offloads to fit. Wan-Animate-2's 16.7 GB int8 UNet ran at 11.5-11.9 GB VRAM peak, but needed `--disable-pinned-memory` to stay out of commit pressure. Commit reached 98% on the one failed run.
- TI2V-5B: 49 frames at 480x832 take about 60 s warm.
- Wan-Animate-2: 39-41 frames take about 160-190 s at 10 steps.

**Stability.** Intermittent GPU device loss has occurred 16 times since 2026-09-07, with no root cause found (DIAG-GPU-100/110). Long jobs therefore need **segment-level checkpointing**: a lost device should cost one segment, not a whole movie. Phase D's design is built for this.

**Architecture invariants are kept.**
- The canonical path stays `Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`.
- `VideoWorkflowNjrBuilder` stays the single Video Workflow NJR builder. Nothing in the GUI calls a backend.
- Published workflow versions stay immutable.
- External Comfy is never adopted.

Where a recommendation conflicts with a written invariant or policy, it is listed as an **owner decision** in section 6, not assumed.

**Policy facts that matter.**
- `AGENTS.md` names native SVD XT the only MVP video backend.
- `VIDEO_PIPELINE.md` invariant 2 forbids run-time-derived inputs. This collides with last-frame chaining.
- Invariant 4 requires a per-job experimental opt-in.
- The audit's stated preconditions for promoting TI2V-5B, P3-3 (containment) and P3-4 (Comfy cancellation), are **already merged** per `STATUS.md`. Promotion is now purely an owner decision.

---

## 3. Findings (ranked by value ÷ effort)

### 3.1 SVD quality is lost in configuration, not the model [V/O]

| # | Finding | Evidence | Effect |
|---|---|---|---|
| S1 | VAE decodes 2 frames per chunk | `svd_controller.py:55` `decode_chunk_size: 2`; GUI presets `svd_tab_frame_v2.py:65,190`; the GUI even warns against larger chunks (`:1275`) | The temporal decoder sees pairs: **flicker at every pair boundary**. Single biggest consistency defect. |
| S2 | Motion suppressed | `svd_controller.py:51-54`: bucket 48, noise 0.01 (model operating point 127 / 0.02) | Near-static clips |
| S3 | Too few frames | 14 frames (XT is tuned for 25); spinbox allows up to 64 | 2 s clips; >25 frames degrades |
| S4 | `fps` conditioning never passed | `svd_service.py:99-111` call kwargs omit `fps` | The model is always conditioned at its default; the UI value only changes export cadence |
| S5 | Encode quality | `src/pipeline/video.py:200-220`: concat demuxer with `1/fps` durations, `-preset <quality>`, no `-crf`, no colour tags, no `+faststart`; `subprocess.run` with a 300 s timeout, not cancellable | **598 kbps at 768²** [O]; possible frame timing jitter [I]; colour shift on BT.709 players [I] |
| S6 | Unreproducible seeds | Blank seed → `generator=None`, recorded `seed: null` [O]; `-1` passed through as a literal seed | A good clip cannot be regenerated or varied |
| S7 | Interpolation default off; old RIFE model | `svd_config.py:182`; no `-m` passed (`svd_postprocess.py:707-709`) | 7 fps playback without RIFE; the older built-in RIFE model [I] |
| S8 | Per-frame face restore and GAN upscale shimmer | CodeFormer detects and aligns per frame (`restoration/codeformer.py:57-72`); upscale x4 model then downsample for x2 (`restoration/upscaler.py:63-74`), after RIFE (2-4x more frames) | Flicker reintroduced by post-processing; wasted compute |
| S9 | Secondary motion is harmful | Whole-frame integer-pixel shift with black edge fill, decaying as `damping**i` (`motion/secondary_motion_engine.py:68-82`) | Judder; recommend retirement |
| S10 | Square crop of portrait sources; EXIF ignored | Real run used 768x768 `center_crop` [O]; no `exif_transpose` in `svd_preprocess.py:93` | Composition loss; sideways phone photos |
| S11 | Post-process disk round-trips | Each stage spawns a fresh worker that re-imports torch, writes and reads all frames as PNG, and copies them again for export | Seconds per stage [I]; not quality-affecting |

### 3.2 Friction and gating [V/O]

| # | Finding | Evidence |
|---|---|---|
| F1 | Comfy is configured by hand; the error names a non-existent settings screen | Messages say "Engine Settings" (`comfy_workflow_backend.py:194-204, 891-902`); `engine_settings_dialog.py` has no Comfy field; default `comfy_command=[]` (`utils/config.py:866-870`); production never reads `config/managed_comfy_runtime.json` (`VIDEO_PIPELINE.md` §4.5). **Caused 4 of 5 Comfy job failures on 2026-10-17** [O]. |
| F2 | No readiness before submit | Flags, endpoint, `/object_info` deps and resource floors run only inside `execute` (`comfy_workflow_backend.py:453-508`); the first-run panel covers only SVD and FFmpeg (`operator_readiness_service.py:227-229`) |
| F3 | Experimental opt-in on every job, reset on every change | All Comfy specs are `experimental`; the checkbox resets on workflow change or restore (`video_workflow_tab_frame_v2.py:888, 956-958, 988`); missing opt-in = error after Queue |
| F4 | Model acquisition is manual | SVD `local_files_only=True` with no download path (`svd_capabilities.py:111-112`); the Comfy bootstrap "downloads no model"; dependency errors list file and SHA but no destination or link |
| F5 | No in-app playback, outputs pane or comparison for Wan | Video Workflow tab has no outputs list; playback is `os.startfile` only (`thumbnail_widget_v2.py:338-359`) |
| F6 | Comfy progress is a seconds counter | `"comfy executing (Ns)"` only (`comfy_workflow_backend.py:1140-1168`); ETA shows "calculating..." forever |
| F7 | Expert-only SVD form | About 28 controls in one column; GFPGAN offered but always refused; raw workflow ids in the picker; disabled camera/depth fields visible |
| F8 | Silent handoff failures | `except Exception: pass` around Send to SVD / Video Workflow / Movie Clips (`job_history_panel_v2.py:455-480`) |
| F9 | Modal "Submitted" dialogs; video tabs last and labelled "- Adv" | `svd_tab_frame_v2.py:1003,1022`; `video_workflow_tab_frame_v2.py:1341`; `main_window_v2.py:383-397` |

### 3.3 Model choice and motion control [R/W/I]

- **TI2V-5B is run below its design point.**
  - The catalog uses 480x832 (`workflow_catalog.py:288-293`). The 5B model with its 16x-compression VAE is a 720p model [W].
  - The recorded defects at 480p fit a model run off-spec: soft or blotchy faces, a magenta cast in the second half, and no locomotion [R: PR-VID-110/150/190]. This has not been tested [I].
  - It remains the fastest Comfy path (about 60 s warm), so it should be re-evaluated at native resolution rather than discarded.
- **The Animate family is the wrong tool for prompt-directed I2V.**
  - It is a character-replacement / motion-transfer model. In prompt mode the records show motion is "subtle and exploratory" and requested turns don't happen (PR-VID-192) [R].
  - Keep it as the *driving-video* specialist. Stop investing in its prompt mode.
- **Never evaluated: Wan2.2 I2V-A14B** (MoE high-noise + low-noise experts) with the lightx2v 4-step distill LoRAs [W].
  - It is the community default for consumer I2V. It runs entirely on stock nodes: `UNETLoader` x2, `LoraLoaderModelOnly` x2, `ModelSamplingSD3`, `WanImageToVideo`, `KSamplerAdvanced` x2, `VAEDecode`.
  - Reported cost on a 24 GB card is about 80-140 s for 81 frames at 640² with the 4-step LoRA [W]. On 12 GB, Comfy offloads to RAM, as it already does for the 16.7 GB Animate-2 UNet [R].
  - Host RAM for two fp8 experts (about 14 GB each [W]) is the real risk. It needs one bounded physical spike.
  - Known trade-off: step-distillation reduces motion dynamics [W]. The common mitigation runs the first high-noise steps without the LoRA [W/I].
- **First-last-frame (FLF2V) is the strongest motion-control lever for an image-first product.**
  - `WanFirstLastFrameToVideo` is a stock Comfy node [W]. The operator *authors the destination frame* with the image pipeline StableNew is already good at: img2img, the SDXL OpenPose ControlNet, or the same seed and character.
  - The model fills the motion between. This also gives identity consistency, because both ends are anchored.
  - The plumbing already exists: `VideoExecutionRequest.end_anchor_path`, LoadImage auto-upload, and a generic compiler [V]. It needs a catalog spec and a form field.
- Rejected candidates: LTX-2.x (32 GB VRAM officially; 44 GB host RAM even with aggressive community setups) and HunyuanVideo-1.5 (14 GB minimum) [R: PR-VID-160A]. These are correct NO-GOs **on 32 GB RAM** and should be revisited after a RAM upgrade (decision D5). LTX-2.x is also the only open model with synchronized audio [W].

### 3.4 Length and continuity [V]

- The longest legal single clip is 81 frames at 24 fps, 3.4 s (`workflow_frame_count.py`, catalog policies).
- **Sequence layer: built, unreachable, broken.**
  - `PipelineRunner._execute_sequence` and `sequence_planner.py` / `sequence_models.py` / `sequence_manifest.py` exist. Policies are `first_frame | last_frame | provided | none`, with overlap and per-segment prompts.
  - Nothing in `src` writes `sequence_metadata`.
  - Carry-forward sets `prior_output_path` to the segment's `.mp4` (`pipeline_runner.py:815-816`) and feeds it to `LoadImage`.
  - Per-segment `frame_count`, `seed`, `workflow_id` and `overlap_frames` are ignored (`:538-557`).
  - `release_owned_runtime_after_job` cold-restarts Comfy between segments (`comfy_workflow_backend.py:455-468`).
  - `execute_segment` has no callers. SVD is excluded from the branch.
- **Continuity packs are labels only.** Nothing reads their anchors.
- **Movie Clips.**
  - Stitching is `-c copy` concat with no scale, pad or fps normalization (`video_export.py:134-182`).
  - `transition_duration` is accepted but unused, and `InterpolationProvider` is a no-op.
  - Sources are re-sorted by filename (`movie_clip_service.py:87`).
  - There is no audio, and it runs outside the queue (`STATUS.md` decision 10).
- **No video rating anywhere.** Learning ratings are keyed by `image_path` (`learning_record.py:210-326`). Experiments share one seed. The batch service drops duplicate sources, so there is no best-of-N.

---

## 4. Roadmap

Five phases. A and B are independent and can run in parallel lanes immediately. C depends on B1 (runtime autoconfig)
and owner decisions D2-D4. D depends on A2 (encoder) and C2 (FLF2V). E can start after A.

Sizes: **S** ≤1 day of agent work, **M** 1-3 days, **L** 3+ days. Class per `AGENTS.md` §3. Model recommendations per
`docs/AI_MODEL_SELECTION.md` (Claude Code / Codex).

### Phase A: make what exists look good (no new models, no owner decision needed except A5)

| PR | Title and scope | Class / size | Acceptance | Model recommendation |
|---|---|---|---|---|
| **PR-VID-QUAL-300** | **SVD conditioning truth and defaults.** <ul><li>Pass `fps` to the pipeline.</li><li>Default `decode_chunk_size = num_frames`, with a halving retry on CUDA OOM, recorded in the manifest.</li><li>Defaults: 25 frames, motion bucket 110, noise aug 0.02.</li><li>Clamp frames to ≤25 for XT and ≤14 for base `img2vid`.</li><li>xt-1-1 locks its card-prescribed conditioning (bucket 127, fps 6).</li><li>Freeze a concrete seed at submit (blank or -1 = random, then recorded).</li><li>`exif_transpose`; alpha composited on a neutral background.</li><li>Presets rewritten around these, and "Recommended" stops square-cropping portrait sources.</li></ul> Files: `svd_controller.py`, `svd_config.py`, `svd_service.py`, `svd_preprocess.py`, `svd_tab_frame_v2.py`. | Standard / M | Fake-pipeline tests assert `fps`, `decode_chunk_size` and a concrete seed reach the call; OOM retry halves once then fails loudly; replay of an old NJR keeps its frozen values (defaults only change *new* configs) | Sonnet 5.5 High / GPT-6.1 Sol High |
| **PR-VID-ENC-301** | **One high-quality, cancellable encoder for every video path.** <ul><li>Replace the concat demuxer with `image2` input at `-framerate`.</li><li>Encoder settings: `libx264 -crf 16 -preset slow` (operator choice: Fast / Balanced / Archival = CRF 20 / 16 / 12, plus lossless).</li><li>BT.709 matrix, primaries and transfer tags; `+faststart`.</li><li>Run through `run_bounded()` with the cancel token.</li><li>GIF via `palettegen`/`paletteuse`.</li><li>Same encoder for SVD export, Movie Clips and segment assembly.</li></ul> Files: `src/pipeline/video.py`, `src/video/video_export.py`, `assembly_service.py`. | Standard / M | Real-FFmpeg test on KB-sized clips verifies frame count, fps, CRF, colour tags; cancel test kills the encoder; provenance remux still verifies | Sonnet 5.5 High / GPT-6.1 Sol High |
| **PR-VID-SMOOTH-302** | **Smooth by default.** <ul><li>RIFE on by default when resolvable: x2 for ≥14 fps sources, x4 below.</li><li>Pass an explicit modern RIFE model (`-m rife-v4.x`), detected next to the executable.</li><li>Auto-detect `rife-ncnn-vulkan` in the configured tools folder and show a "Locate RIFE" button when missing.</li><li>Make interpolation a backend-neutral video post-process, so Comfy outputs (Wan A14B is 16 fps) can use it too.</li></ul> Files: `svd_postprocess.py`, `svd_capabilities.py`, `comfy_workflow_backend.py` (post-process hook only). | Standard / M | Effective export fps ≥24 by default with RIFE present, unchanged without it; model flag present in the recorded command | Sonnet 5.5 High / GPT-6.1 Sol High |
| **PR-VID-LOOP-303** | **Loop and ping-pong export** (`frames + frames[-2:0:-1]`) and an "extend by looping to N seconds" option. Cheap perceived length for ambient shots. | Narrow / S | Frame-sequence tests; manifest records the export mode | Sonnet 5.5 Medium / GPT-6.1 Sol Medium |
| **PR-VID-POST-304** | **Stop post-processing from reintroducing flicker.** <ul><li>CodeFormer: EMA-smooth landmarks and affine transforms across frames; default fidelity 0.85.</li><li>Upscale: choose an x2 model for x2, and run it *before* RIFE.</li><li>Remove the GFPGAN option (always refused today).</li></ul> | Standard / M | Synthetic-landmark test shows smoothed transforms; upscale runs on N, not N×RIFE, frames | Sonnet 5.5 High / GPT-6.1 Sol High |
| **PR-VID-POST-305** | **Retire secondary motion** (owner decision D8): the harmful whole-frame shift. Keep historical records readable, refuse an enabled stage with a readable message, using the AnimateDiff retirement pattern. | Standard / S | Old NJRs load; enabled intent refused before dispatch | Sonnet 5.5 Medium / GPT-6.1 Sol Medium |

Expected effect of A1-A3 together [I]: about 3.6 s SVD clips at ≥24 fps, without pair-boundary flicker, at 3-5x the
bitrate. Visibly better than the current output with zero new models.

### Phase B: make it easy (parallel with A)

| PR | Title and scope | Class / size | Acceptance | Model recommendation |
|---|---|---|---|---|
| **PR-VID-UX-310** | **Managed Comfy autoconfiguration.** <ul><li>Production reads `config/managed_comfy_runtime.json` (today only the verifier does) and derives the launch command from the managed install root plus `launch_policy.required_flags`.</li><li>Add a "Video runtime" section to Engine Settings: Detect managed install / Use external endpoint / Verify. It shows missing required flags and offers **Add required flags** as an explicit operator action.</li><li>Fix the error text to name the real screen.</li><li>An operator-set external `comfy_command` is still honored and never adopted.</li></ul> | Standard / M | The 2026-10-17 configuration (desktop Comfy, no flag) shows the problem in settings and a one-click fix; external endpoints are still refused for flags they cannot prove | Sonnet 5.5 High / GPT-6.1 Sol High |
| **PR-VID-UX-311** | **Readiness before submit.** <ul><li>Read-only readiness strip on the Video Workflow tab: launch flags, endpoint or managed install, `/object_info` dependency probe (when a runtime is up), resource floors, model files present with SHA.</li><li>Queue is disabled with the reason inline.</li><li>Add a Comfy row to `OperatorReadinessService`.</li></ul> Runs on a worker thread and never starts Comfy by itself. | Standard / M | Each gate has a test asserting the strip shows it and Queue is disabled; no `queue_prompt` and no process start from the probe | Sonnet 5.5 High / GPT-6.1 Sol High |
| **PR-VID-UX-312** | **Model asset assistant.** <ul><li>SVD: an explicit "Download model" action, with a note on the gated Hugging Face licence and token.</li><li>Comfy workflows: "Download missing files", fetching each pinned file to the declared models folder and verifying SHA-256 before use.</li><li>Shows sizes first and is cancellable.</li></ul> | Standard / M, **security review** (network, filesystem, untrusted downloads) | Hash mismatch deletes the partial and refuses; nothing downloads without a click; offline tests with a fake hub | Sonnet 5.5 High + Opus 5.5 High security review / GPT-6.1 Sol High + GPT-6 Astra High |
| **PR-VID-UX-313** | **One "Make video" entry and a simpler form.** <ul><li>A single action on Review, History and Pipeline thumbnails opens the video workspace with the image loaded and the recommended backend preselected.</li><li>Basic / Advanced split: Basic = preset, motion amount, length, prompt.</li><li>Display names in the workflow picker; hide undeclared camera, depth and ControlNet sections.</li><li>Surface handoff errors (F8); non-modal "Queued: view in queue" toast instead of modal dialogs.</li></ul> | Standard / M–L, controller surface assessment required (`AppController` ratchet) | GUI tests on the handoff and Basic/Advanced visibility; controller ceilings not raised | Sonnet 5.5 High / GPT-6.1 Sol High |
| **PR-VID-UX-314** | **In-app preview and recent outputs.** <ul><li>A looping preview widget that decodes frames with `imageio-ffmpeg` at preview size on a worker thread and marshals them to Tk.</li><li>"Recent outputs" on the Video Workflow tab, reusing the SVD tree.</li><li>Open, Reveal, Send to Movie / Storyboard.</li></ul> | Standard / M | No GUI-thread decode; bounded memory; widget tests with a tiny generated clip | Sonnet 5.5 High / GPT-6.1 Sol High |
| **PR-VID-UX-315** | **Real Comfy progress.** <ul><li>Subscribe to the Comfy websocket `progress`/`executing` events for this prompt id only.</li><li>Show phase labels (starting runtime, probing, loading models, sampling n/N, decoding, saving) and an ETA from step times.</li><li>Falls back to the current liveness counter if the socket fails.</li></ul> | Standard / M | Fake socket tests; liveness watchdog behaviour unchanged | Sonnet 5.5 High / GPT-6.1 Sol High |
| **PR-VID-GOV-316** | **Opt-in policy implementation** (after owner decision D1). If TI2V-5B is promoted: governance change only. Either way: the opt-in checkbox stops resetting on restore, and Queue is disabled with an inline reason instead of an error after the click. | Narrow / S | Invariant 4 tests adjusted only as the decision directs | Sonnet 5.5 Medium / GPT-6.1 Sol Medium |

### Phase C: a better model and real motion control

| PR | Title and scope | Class / size | Acceptance | Model recommendation |
|---|---|---|---|---|
| **PR-VID-EVAL-320** | **Video eval kit: one reusable harness instead of per-candidate qualification packages.** <ul><li>A fixed suite of about 8 sources (portrait character, full body, landscape, close-up face, action pose, animal, product, scene) with prompts.</li><li>Submitted as one queued batch through the canonical path.</li><li>Offline metrics from the outputs (OpenCV only): motion magnitude (optical flow), temporal flicker (warp error), colour drift against the first frame, sharpness, duration, fps, bitrate.</li><li>An HTML contact sheet with side-by-side loops and a rating sheet.</li><li>**The owner's rating plus "no metric regressions" is the promotion gate.** Metrics inform the decision; no single metric blocks it.</li></ul> | Standard / L | Deterministic metric tests on synthetic clips; runs on the canonical path; no CI GPU | Sonnet 5.5 High / GPT-6.1 Sol High |
| **PR-VID-WAN-321** | **Wan2.2 I2V-A14B + 4-step distill catalog spec** (stock nodes only, experimental).<ul><li>Graph: high- and low-noise fp8 experts, lightx2v LoRAs via `LoraLoaderModelOnly`, `WanImageToVideo`, two `KSamplerAdvanced` passes.</li><li>Steps 2+2, or 2 un-distilled high-noise + 2 distilled low-noise as a "dynamic" control. Native 16 fps; 81 frames; 480p and 720p profiles; RIFE x2 to 32 fps from PR-VID-SMOOTH-302.</li><li>Declared resource readiness and required launch flags.</li><li>**Preceded by one bounded physical spike** (decision D3): about 3 runs at 480p and 720p, measuring peak VRAM, commit and min free RAM against the current 32 GB.</li></ul> | Standard / M (spec) + spike | Version-pinning, compiler and `_FakeComfy` tests; spike recorded in a half-page note, not a multi-PR adjudication | Sonnet 5.5 High / GPT-6.1 Sol High |
| **PR-VID-FLF-322** | **First-last-frame (keyframe) motion control.** <ul><li>Catalog spec using stock `WanFirstLastFrameToVideo` on the A14B graph, binding `end_anchor_path`.</li><li>Form: an "End frame (optional)" picker, plus **"Create end frame…"**, which queues an ordinary img2img / OpenPose ControlNet image job from the start frame with the motion prompt, so the end frame is authored with the image tools.</li><li>Source preparation applies the identical crop to both anchors.</li></ul> | Standard / M | Both anchors frozen with SHA at admission; replay verifies both; refusal when the anchor aspect cannot be prepared | Sonnet 5.5 High / GPT-6.1 Sol High |
| **PR-VID-WAN-323** | **TI2V-5B at its native resolution.** <ul><li>New catalog version with 704x1280 / 1280x704 profiles and fps-correct 24 fps output.</li><li>A sampler setting arm (cfg, shift) for the colour cast.</li><li>Evaluated with the eval kit against A14B. Keep it as the "fast draft" backend if it holds up.</li></ul> | Narrow / S + eval run | New version only; old versions untouched | Sonnet 5.5 Medium / GPT-6.1 Sol Medium |
| **PR-VID-WAN-324** | **Frames out, StableNew encodes.** New graph versions end in `SaveImage` (PNG frames) instead of `SaveVideo` (`format/codec auto`, about 1.5 Mbps [O]), so every Comfy clip gets the PR-VID-ENC-301 encoder and RIFE. Also enables exact last-frame extraction for Phase D. | Standard / M | Output localization handles frame sets; manifest lists frames and the encoded file | Sonnet 5.5 High / GPT-6.1 Sol High |
| **PR-VID-GOV-325** | **Promotion of the winner** (decision D2): <ul><li>Change the chosen workflow's governance state.</li><li>Make it the default in "Make video".</li><li>Update `AGENTS.md`, `STATUS.md` and `VIDEO_PIPELINE.md` §1.1 to name the accepted production video backends.</li><li>Retire Animate-2 *prompt* mode from the picker (driving mode stays experimental).</li></ul> | Architectural / S (docs + governance) | Owner approval recorded; replay of old jobs unchanged | Opus 5.5 High / GPT-6 Astra High |

### Phase D: length and continuity, from Storyboard to Movie

| PR | Title and scope | Class / size | Acceptance | Model recommendation |
|---|---|---|---|---|
| **PR-VID-SEQ-330** | **Repair and wire the sequence layer** (decision D7).<ul><li>Extract the exact last frame (a PNG from PR-VID-WAN-324 frames, or FFmpeg for SVD) and record its SHA in the segment provenance.</li><li>Pass per-segment frame count, seed and workflow through a typed `stage_config_overrides`.</li><li>Keep the owned Comfy warm until the last segment.</li><li>Colour and histogram match each segment to segment 0's first frame; trim overlap frames.</li><li>Include `svd_native` in the sequence branch.</li><li>**Checkpointing:** completed segments are durable artifacts, so a failed or device-lost segment n can be retried from n without redoing 0..n-1 (retry creates a new NJR with lineage, on the canonical path).</li></ul> | **Architectural** / L | Runner tests prove a PNG (not an mp4) reaches `LoadImage`, per-segment values apply, Comfy release only after the last segment, and retry-from-segment lineage; replay re-verifies derived frames by hash | Opus 5.5 High (design) → Sonnet 5.5 XHigh (impl) / GPT-6 Astra High → GPT-6.1 Sol XHigh |
| **PR-VID-SEQ-331** | **Storyboard → Movie (flagship).** <ul><li>An ordered storyboard of shots. Each shot is a keyframe image (from Review, History or a PromptPack batch), a motion prompt, a length and an optional end keyframe.</li><li>Consecutive keyframes become **FLF2V segments with the `provided` policy**, so every boundary is an authored image: no drift, consistent identity.</li><li>Shots without an end keyframe use last-frame carry.</li><li>One admission (`submit_njrs`) per storyboard; the final assembly step uses PR-VID-ASM-332.</li><li>Storyboards persist as versioned JSON next to PromptPacks.</li></ul> | Standard–Architectural / L | Storyboard JSON round-trip and schema tests; a fake backend produces an ordered stitched output; reorder and replace a shot then re-render only that shot | Sonnet 5.5 XHigh / GPT-6.1 Sol XHigh |
| **PR-VID-ASM-332** | **Assembly v2, on the queue** (decision D6).<ul><li>Respect user order (remove the filename sort; add reorder controls).</li><li>Accept videos in Add; normalize with `scale`+`pad`+`fps`.</li><li>`xfade` transitions using `transition_duration`; per-clip durations; optional audio track (`-shortest`, fade out).</li><li>The ENC-301 encoder.</li><li>Movie Clips becomes a queued CPU workload with an NJR, history and cancel.</li></ul> | Architectural (queue scope) / M–L | Mixed-resolution and mixed-fps inputs produce one valid file; history shows the assembly job; cancel works | Sonnet 5.5 High / GPT-6.1 Sol High |

### Phase E: choose, learn, polish

| PR | Title and scope | Class / size | Acceptance | Model recommendation |
|---|---|---|---|---|
| **PR-VID-BEST-340** | **Best-of-N and pick-the-winner.** <ul><li>"Make 4 variants" freezes N random seeds through `freeze_inputs` and admits them atomically via `ExperimentAdmissionService`.</li><li>A side-by-side looping grid with a Pick winner button that feeds the storyboard shot.</li><li>Experiment arms get the same grid.</li></ul> | Standard / M | N distinct frozen seeds; one admission; GUI grid tests | Sonnet 5.5 High / GPT-6.1 Sol High |
| **PR-VID-LEARN-341** | **Video ratings in Learning.** <ul><li>Ratings keyed by artifact path (not only `image_path`), rendered with the preview widget.</li><li>Video experiments appear in Learning Review.</li><li>Recommendations (motion amount, steps, LoRA arm, cfg/shift) flow back as presets through the existing Recommendations selector.</li></ul> | Standard / M–L | Rating persistence and migration-free forward compatibility tests | Sonnet 5.5 High / GPT-6.1 Sol High |
| **PR-VID-PERF-342** | **Throughput.** <ul><li>One post-process worker per job (not per stage), with frames piped to FFmpeg.</li><li>VRAM-aware SVD CPU offload (off at ≥16 GB).</li><li>A queue *advisory* that groups adjacent video jobs to avoid WebUI/SVD/Comfy residency thrash; it never reorders without consent.</li></ul> | Standard / M | Timing harness on fake stages; no queue-order change without an explicit operator action | Sonnet 5.5 High / GPT-6.1 Sol High |
| **PR-VID-CAM-343** | **Camera control (later).** Evaluate stock Comfy Wan camera nodes or a Fun-Camera model with the eval kit; if it passes, add a declared `camera_preset` spec (the dormant camera plumbing in the builder becomes live, or is deleted if it fails). | Standard / M + eval | Eval-kit verdict decides keep or delete | Sonnet 5.5 High / GPT-6.1 Sol High |
| **PR-VID-AUDIO-344** | **Audio (later, after decision D5).** Re-evaluate LTX-2.x (synchronized audio) once RAM allows it; until then, audio is the assembly music track from PR-VID-ASM-332. | Spike | Eval-kit run | Opus 5.5 High / GPT-6 Astra High |

### Dependency graph and lanes

```
Lane 1 (quality):  QUAL-300 ─┬─ ENC-301 ─┬─ SMOOTH-302 ── LOOP-303
                             │           └─ POST-304 ── POST-305
Lane 2 (ease):     UX-310 ── UX-311 ── UX-312 ;  UX-313 ── UX-314 ── UX-315 ;  GOV-316 (after D1)
Lane 3 (models):   EVAL-320 ─┬─ WAN-321 (spike, D3/D4) ── FLF-322 ─┐
                             ├─ WAN-323                            ├─ GOV-325 (D2)
                             └─ WAN-324 ───────────────────────────┘
Lane 4 (length):   [ENC-301 + WAN-324 + FLF-322] ── SEQ-330 (D7) ── SEQ-331 ── ASM-332 (D6)
Lane 5 (learn):    [UX-314] ── BEST-340 ── LEARN-341 ;  PERF-342 ;  CAM-343 ;  AUDIO-344 (D5)
```

**First three packages, recommended:**
1. PR-VID-QUAL-300 + PR-VID-ENC-301, as one coherent "SVD looks right" package.
2. PR-VID-UX-310, which removes the failure class behind 4 of 5 recent Comfy jobs.
3. PR-VID-EVAL-320, which is the measuring stick everything in Phase C depends on.

---

## 5. Process changes that make this roadmap cheaper

1. **One eval kit, not one package per candidate.**
   - A candidate model, sampler change or graph revision is judged by one eval-kit batch, about 8 clips per arm.
   - The record is a contact sheet, the metric table and the owner's rating, about half a page.
   - This replaces the 110→185 pattern (16 packages, 1-3 generations each, guards later overturned).
2. **The owner's eye is the gate; metrics are guardrails.**
   - PR-VID-185 already demoted the motion-curve gate after it disagreed with the owner's PASS. Make that the rule up front.
3. **Retry budgets, not single-shot runs.**
   - A physical spike authorizes a small run budget (for example up to 6 generations) rather than 1-3 with no retries. Several past packages ended at a precondition and needed a follow-up package.
4. **Promotion has a finish line.**
   - "Experimental" means "not yet rated on the eval kit", not "never". A workflow that passes the kit and the owner's rating is promoted in a governance-only PR.
5. **Requalification on a new Comfy runtime does not mint a graph version.**
   - Audit P4-6 proposes separating qualification records from graph versions. This roadmap does not depend on it, but it stops 1.0.0/1.1.0/1.2.0-style duplicates.

---

## 6. Owner decisions

| # | Decision | Recommendation | Unblocks |
|---|---|---|---|
| D1 | Experimental opt-in policy | Promote Wan2.2 TI2V-5B to `approved` now: the audit preconditions P3-3 and P3-4 are merged. Keep the per-job opt-in for the rest, but make it non-resetting with an inline-disabled Queue. | GOV-316, removes F3 |
| D2 | Accepted production video backends | Amend `AGENTS.md` / `STATUS.md` from "SVD XT only" to "SVD XT plus approved Comfy workflows"; SVD becomes the fast/offline fallback. Decide after the eval-kit verdict. | GOV-325 |
| D3 | Physical run authorization for the eval kit and spikes | One standing authorization per eval-kit batch with a run budget, rather than per package | WAN-321, WAN-323, FLF-322, CAM-343 |
| D4 | Model downloads | About 30-40 GB for the Wan2.2 A14B fp8 experts, lightx2v LoRAs and VAE [W]; pinned by SHA in the catalog | WAN-321, FLF-322 |
| D5 | **Hardware: RAM 32 → 64 GB** (PR-VID-184 option B) | Highest value per cost in this document [I]. Host RAM, not VRAM, is the binding constraint for every 14B-class model on this card. It removes the commit-pressure failure mode (98% at the one Animate-2 failure) and reopens LTX-2.x (audio) and HunyuanVideo-1.5. | Headroom for WAN-321, AUDIO-344 |
| D6 | Movie Clips outside the queue (`STATUS.md` decision 10) | Make assembly a queued CPU workload. Storyboard → Movie needs assembly inside the canonical path anyway. | ASM-332, SEQ-331 |
| D7 | Run-time-derived carry-forward frame (`VIDEO_PIPELINE.md` invariant 2) | Allow a derived input when it is extracted deterministically from a parent artifact *of the same job* and recorded with its SHA; replay re-verifies it. `provided`-policy storyboards (FLF2V) avoid derivation entirely. | SEQ-330 |
| D8 | Retire secondary motion and the GFPGAN option | Retire both (readable history, refused when enabled) | POST-304, POST-305 |

### 6.1 Owner decisions recorded 2026-10-20

| # | Decision | Implemented by |
|---|---|---|
| D1 | **Yes.** Promote Wan2.2 TI2V-5B to `approved`. | PR-VID-GOV-316 |
| D2 | **Yes.** Approved Comfy workflows are production video backends alongside native SVD XT. `AGENTS.md`, `STATUS.md` and `VIDEO_PIPELINE.md` change in the implementing PR, not before. | PR-VID-GOV-316 / PR-VID-GOV-325 |
| D3 | **Yes.** One or two standing authorizations per eval-kit batch, with a budget of a few generations as needed. | PR-VID-EVAL-320 and the Phase C spikes |
| D4 | **Yes.** Model downloads are allowed, pinned by SHA-256 in the catalog. | PR-VID-UX-312, PR-VID-WAN-321 |
| D5 | Not decided (hardware). | — |
| D6 | **Yes.** Movie Clips assembly becomes a queued workload (resolves `STATUS.md` decision 10). | PR-VID-ASM-332 |
| D7 | **Yes.** Segment chaining may use a frame extracted from the previous segment of the same job, recorded with its SHA-256 and re-verified on replay. | PR-VID-SEQ-330 |
| D8 | **Yes.** Retire secondary motion and the GFPGAN option (readable history, refused when enabled). | PR-VID-POST-304, PR-VID-POST-305 |

Packages authorized on 2026-10-20: PR-VID-QUAL-300 (delivered together with PR-VID-ENC-301 as the first package),
PR-VID-UX-310 and PR-VID-EVAL-320.

---

## 7. Risks and counter-hypotheses

- **"A14B will not fit 32 GB RAM."**
  - Plausible: two fp8 experts total about 28 GB [W].
  - Counter-evidence: a 16.7 GB int8 UNet already runs with pinned memory off at 52-57% commit [R].
  - Falsifier: the WAN-321 spike. Mitigations: `--cache-none`-style unloading between experts [W/I], 480p first, or D5.
- **"The distill LoRA kills motion."**
  - Known trade-off [W]. WAN-321 ships a "dynamic" arm (un-distilled high-noise steps), and the eval kit decides.
- **"FLF2V produces morphs instead of motion when the end frame is too different."**
  - Likely for large pose changes [I]. Mitigation: shorter shots, OpenPose-guided end frames that keep identity and background, and a mid-anchor later.
- **"SVD changes alter existing presets and replay."**
  - Defaults change only for new configs. Frozen NJRs replay exactly. Tests pin this.
- **Device loss on long sequences.**
  - SEQ-330 checkpointing bounds the loss to one segment. The existing GPU-loss quarantine still stops the queue.
- **Licensing.**
  - Wan2.2 is Apache-2.0 [W]. SVD is under the Stability community licence [W]. lightx2v LoRA licence must be checked before WAN-321 [I].
  - LTX-2.x is free under $10M revenue [W]. Record each in the catalog spec.
- **Scope creep into the image pipeline.**
  - "Create end frame…" (FLF-322) submits an ordinary image job; it adds no new image path.

---

## 8. Coverage and gaps

- **Read:**
  - `VIDEO_PIPELINE.md` and the video evidence records.
  - `src/video/`, the video branches of the runner and stage handlers, both video controllers.
  - The SVD, Video Workflow, Movie Clips, History and Review GUI surfaces; `src/learning` touchpoints.
  - Real outputs in `output/SVD` and `output/movie_clips` (2026-10-17).
- **Not done (by policy):**
  - No generation, GPU probe, Comfy start or model download.
  - External model facts [W] come from third-party pages and need confirmation against official model cards before WAN-321.
- **Not verified:**
  - Exact Comfy stock-node names and inputs for `WanFirstLastFrameToVideo` / `WanImageToVideo` on the pinned ComfyUI 0.38.0. WAN-321 must check `/object_info` on the managed runtime first.
  - Visual quality claims for SVD fixes are [I] until the eval kit runs.

## 9. Docs impact when work lands

`VIDEO_PIPELINE.md` (§§1.1, 3.2, 4.2, 5, 7, 9, 12) changes with each PR. `STATUS.md` changes for supported capabilities,
open decisions D1/D2/D6/D7 and the backend sentence. `AGENTS.md` §2 changes only with D2.
