# PR-VID-192 — Animate-2 Control Truth & Motion Experimentability

Status: **implemented locally; controlled GPU experiment NOT run (blocked, see §8); pending publication and
required GitHub CI.** Stacked on PR-VID-191 (`bc10a66`, evidence-frozen and untouched). No new queue, runner,
compiler, history, experiment or process authority; the canonical path
(`Intent -> Compiler -> immutable NJR -> JobService -> SQLite Queue/Repository -> PipelineRunner.run_njr ->
Handler/Executor -> Artifact/History`) and the pinned ComfyUI v0.37.0 runtime are unchanged.

## 1. Control-truth audit of exact PR-VID-191

The GUI showed a disabled `Motion = gentle` selector for Animate-2. Verified against `bc10a66` by submitting both
workflows through the real controller with `motion_profile="gentle"` in the form and inspecting the frozen NJR and
the graph sent to Comfy:

| # | Question | Answer |
|---|---|---|
| 1 | Does either workflow declare `motion_profile`? | **No.** Neither spec's `declared_input_names` contains it; `form_visibility.motion_profile` is False. |
| 2 | Did `gentle` enter the NJR? | **No.** The stage config has no `motion_profile` key and `gentle` appears nowhere in the serialized job. |
| 3 | Did it enter the compiled Comfy graph? | **No.** |
| 4 | Any Animate-2 node input it could map to? | **No.** `WanAnimate2ToVideo` has no such input. The selector was an inert, disabled UI default. |
| 5 | Text feeding character/background conditioning | The single form `prompt` -> main positive `CLIPTextEncode` (node 5): a mixed appearance-and-action prompt. |
| 6 | Text feeding `positive_pose` | **Nothing was wired.** The pinned node defaults `positive_pose` to `positive`, so the pose branch received the appearance/action prompt (the qualified PR-VID-184 graph used a separate motion-only prompt, node 612). |
| 7 | Negative conditioning | The stock Wan negative, verbatim. **It has no effect on sampling** (see §5). |
| 8 | Fixed vs selectable | Selectable: seed, frame count, prompts (and the driving video in drive mode). Fixed at the node defaults: pose strength 1.0, pose window 0-1, reference strength 1.0, offset 0, and lcm/simple, 10 steps, shift 5, cfg 1. |

`gentle` never affected Animate-2, so no redesign stop was triggered.

## 2. Pinned ComfyUI v0.37.0 truth (execution authority)

Read from `comfy_extras/nodes_wan.py` and `comfy/ldm/wan/model_animate2.py` at revision `73c9bad4` (the pinned
qualification install); upstream documentation is context only. No ComfyUI upgrade is required.

| `WanAnimate2ToVideo` input | Available | Default | Range / step | Semantics (pinned source) | Exposed |
|---|---|---|---|---|---|
| `positive_pose` | yes (optional conditioning) | `positive` | - | Prompt for the pose-video branch, "describing the motion rather than the character". | **Motion Prompt** (drive) |
| `pose_strength` | yes | 1.0 | 0.0-10.0 / 0.01 | Scales the pose video's influence; 1.0 is trained behavior; 0.0 mutes but does not fully remove it. | **Pose Strength** (drive) |
| `pose_start_percent` | yes | 0.0 | 0.0-1.0 / 0.01 | Sampling fraction where pose influence starts; outside the window the pose branch is skipped. | **Pose Start %** (drive) |
| `pose_end_percent` | yes | 1.0 | 0.0-1.0 / 0.01 | Where it ends; start must not exceed end (the node raises). | **Pose End %** (drive) |
| `reference_image_strength` | yes | 1.0 | 0.0-10.0 / 0.01 | How strongly frames attend to the reference latent; independent of the pose branch. | **Reference Image Strength** (drive and prompt) |
| `continue_motion` | yes (optional image) | none | last 1 frame used | Previous motion sequence, for clip extension. | not exposed (needs chained clips) |
| `video_frame_offset` | yes | 0 | >= 0 | Frames to seek into the pose video; errors if it consumes the whole clip. | not exposed (follow-up) |

Two facts decide the workflows' honesty. **`apply_pose = pose_latents is not None`**: with no driving video the
whole pose branch is skipped, so `positive_pose`, `pose_strength` and the pose window are inert in prompt mode; only
the reference strength and the main text matter there. And `reference_strength` is passed to every block regardless
of the pose branch, so it is a real control in both modes.

## 3. Operator surface: before and after

| Surface | Before (PR-VID-191) | After (PR-VID-192, `@1.1.0`) |
|---|---|---|
| Motion selector | Disabled `gentle` shown, implies a setting | **Hidden** for any workflow that does not declare `motion_profile` |
| Drive: prompt field | "Prompt" (mixed appearance and action) | **Appearance / Background Prompt** |
| Drive: motion text | none (pose branch reused the prompt) | **Motion Prompt** -> `positive_pose` |
| Drive: numeric controls | none (fixed) | **Pose Strength**, **Pose Start %**, **Pose End %**, **Reference Image Strength**, shown with defaults and ranges |
| Prompt mode | "Prompt Motion", implied prompt-directed movement | **Reference Image + Prompt (subtle motion)**, described as exploratory: no driving video, so the pose branch is skipped; only Reference Image Strength is offered |
| Negative prompt | unexplained | help states it has no effect at CFG 1.0 |
| Effective settings line | motion only for LTX-style specs | lists every control, marks changed values, shows `pose_prompt=custom` or `same as prompt` |

Prompt mode is kept (owner: do not delete it merely because motion is subtle): its defensible role is an exploratory,
prompt-conditioned reference animation with a real strength control, described as such.

Design: controls are declared per spec (`backend_defaults["operator_controls"]` + a matching input binding reading
`stage_config.operator_controls.<name>`), like frame count and seed. `src/video/workflow_controls.py` validates and
freezes them (rejecting, never clamping; unknown controls are refused); the controller only calls it; the catalog
builds the graph; the compiler binds the exact node inputs. Generic `gentle/balanced/dynamic` presets were **not**
created: no controlled evidence yet supports deterministic numeric mappings, and any future preset must resolve to
explicit frozen numbers in the NJR. `@1.0.0` stays registered and byte-identical (pinned by hash in tests) so
PR-VID-191 jobs replay against the identical graph; the UI offers only the newest version.

## 4. Prompt mappings (drive `@1.1.0`)

| Operator field | Graph node -> input | Notes |
|---|---|---|
| Appearance / Background Prompt | node 5 `CLIPTextEncode` -> `WanAnimate2ToVideo.positive` | character, background, viewpoint; not the action |
| Motion Prompt | node 23 `CLIPTextEncode` -> `positive_pose` | motion only; empty freezes the appearance prompt explicitly (the node's own default) |
| Negative Prompt | node 6 -> `negative` | unchanged stock string; inert at cfg 1.0 |
| Pose Strength / Start % / End % / Reference Strength | `pose_strength`, `pose_start_percent`, `pose_end_percent`, `reference_image_strength` | typed floats; defaults equal the pinned node defaults |

## 5. Negative-prompt audit

The stock Wan negative (137 characters) was compared with the qualified PR-VID-184 graph (identical) and audited by
purpose: exposure/colour (garish tones, overexposed, overall grey); **stillness** (static, still, motionless frame);
overlay/style (subtitles, style, artwork, painting, frame); quality (blurry details, worst/low quality, JPEG
artifacts); anatomy (ugly, mutilated, extra fingers, badly drawn hands/face, deformed, disfigured, malformed limbs,
fused fingers, three legs); scene (cluttered background, many people in background); direction (walking backwards).

Findings: (a) the stillness terms *push against* static output, so a strong negative cannot be blamed for suppressing
motion; (b) **more decisively**, at `cfg = 1.0` ComfyUI's `sampling_function` sets the uncond to `None`
(`comfy/samplers.py:610`), so the negative conditioning is not used at all in this graph. The default is unchanged and no
one-variable negative comparison was run: it would compare identical sampling. It would only become meaningful if the
qualified CFG were changed, which is outside this package.

## 6. Provenance and replay

Every effective control round-trips: form -> frozen `stage_config.operator_controls` in the immutable NJR ->
compiler -> exact Comfy inputs -> manifest, container metadata and result. The backend adds `operator_controls` and a
self-contained `control_record` (workflow id/version/pinned revision, qualified graph hash, ComfyUI version/revision,
source-image path and SHA-256 of the reference actually conditioned on, prompts, seed, controls, driving-video
path/SHA-256) for jobs that carry controls or a driving video. The NJR snapshot -> hydrate path is tested to keep every
control and compile to the identical graph. The admission-frozen driving-video hash guard is unchanged.

## 7. Motion-source corpus (qualification only)

Not a product library and not `AssetRegistry`. `tools/qualification/vid192/` holds `motion_corpus.py` (probe, hash,
validate, refuse third-party media inside the repo, no absolute local paths), tracked `corpus_annotations.json` and the
generated `corpus_inventory.json`. No media is committed (`/reports/` is git-ignored; the third-party clip lives under
the machine-local qualification root).

| Asset | Frames | Source / license | Motion (visually verified) | Notes |
|---|---:|---|---|---|
| `mot192_locomotion_high_knee_39f` | 39 | Mixkit #583 stock, **internal qualification only** | high-knee run drill, lateral translation, side view | the frozen PR-184/191 driving clip; sha `d761eb58...`; do not share |
| `mot192_locomotion_high_knee_60f` | 60 | same source, longer window | as above, sprint transition | same use limit |
| `mot192_arm_raise_overhead_49f` | 49 | StableNew-generated | arms raise to the head | the prompted turn did not occur |
| `mot192_arm_wave_late_49f` | 49 | StableNew-generated | right-arm wave, last ~12 frames only | red-tinted hand |
| `mot192_arm_wave_a_49f` | 49 | StableNew-generated | clean right-hand wave | magenta colour drift |
| `mot192_arm_raise_wave_b_49f` | 49 | StableNew-generated | raise, wave, lower; head follows | wrist blur, colour drift |
| `mot192_weight_shift_sway_c_49f` | 49 | StableNew-generated | weight shift/arm sway, feet planted | the prompted steps did not occur |

Each entry records ID, SHA-256, provenance/license status, dimensions, fps, frame count, duration, subject count, body
visibility, camera movement, occlusion, motion tags, intensity and start/end-pose notes. **Honest limits:** this is 7
sources but only 2 distinct real-human clips (one source), and the synthetic clips carry generation artifacts that a
driving clip would transfer. **Gaps with no legitimate local source:** side step, in-place turn, squat/stand, and a
moderate-speed walk. Excluded on purpose: `wan2.2-ti2v-5b_user_i2v_prompt.mp4` (shows an identifiable child, a private
individual), skeleton/pose-render clips (not RGB humans) and Animate-2 outputs (second generation). Filling the gaps needs
owner-created or freshly generated footage; no third-party download was made.

## 8. Controlled experiment (designed, harnessed, NOT run)

`tools/acceptance/vid190_queue_recycling_acceptance.py --suite animate2_controls` freezes one reference
(`source_fullbody.png`), the frozen 39-frame driving clip, seed 19103, 41 frames and the PR-VID-191 appearance prompt,
and changes one variable per arm: **A0** PR-VID-191 baseline (`@1.0.0`, `positive_pose` unconnected); **A1** + the
qualified motion-only prompt at default strengths; **A2** = A1 + pose strength 1.5; **A3** = A1 + reference-image
strength 1.3 (targets the duplicate-subject issue). Deterministic tests prove the arms differ by exactly one variable and
are admissible.

**Why it was not run.** On 2026-09-30 the machine could not satisfy the qualified condition, and StableNew's own
preflight independently refused: the owner's A1111 (`launch.py`, external) held the GPU (10.9 GB used, 1.05 GB free at
100 % utilization; 3.7 GB free at the preflight moment), the endpoint guard reported it `occupied`, host RAM available was
10.65 GB against the 16 GB floor, and the configured Comfy command lacked `--disable-pinned-memory`. StableNew never
adopts or stops an external runtime, so nothing was started. To run it: close A1111, launch the qualification ComfyUI with
`--disable-pinned-memory` via the local overrides, set `STABLENEW_VID191_DRIVING_CLIP`, then run the suite.

**CPU-only supporting evidence that was possible.** The frozen PR-VID-184S scorer on the existing PR-VID-191 baseline
clip (driving mode, duplicate figure) reports `ghost_actor_persistence = 28` of 39 frames (pass <= 2),
`motion_curve_correlation = 0.042`, `identity_hist_mean = 0.967`, `root_translation_fraction = 0.443` (direction
matches). This objectively confirms the ghost artifact; it does not say which variable fixes it.

**Owner evidence still needed:** the four outputs and their ratings (motion amount, action adherence, identity, face,
limbs/anatomy, temporal coherence, background stability, duplicate/ghost subject, overall usefulness), where owner visual
judgment is authoritative and the frozen metrics are supporting. The duplicate-subject result stays
`EXECUTION_PASS / PRODUCT_QUALITY_PARTIAL` until then.

## 9. Adjacent read-only findings (nothing installed or changed)

**AnimateDiff -> ready for bounded qualification, SDXL/Hotshot-XL only.** The live A1111 advertises the `animatediff`
script for txt2img and img2img (read-only GET); the extension is installed; the one visible motion module is
`mm_sdxl_hs.safetensors` (Hotshot-XL), which StableNew's `animatediff_models.py` already recognizes; the checkpoints are
SDXL. No SD1.5 motion module is present and the ControlNet extension is absent. No generation was attempted.

**Learning follow-on.** `src/learning` is image-experiment centric (freeze/plan/execution/store); video appears only in the
record builder. First-class support is therefore its own package, not a small extension: a bounded `video_workflow`
Learning experiment that varies one declared `operator_controls` value at a time, submits through the existing controller
path, reads `control_record` and the rating dimensions above, and stores results in the existing experiment store. No
parallel experiment database, runner, queue or history. Start after the control schema is accepted.

**SVD follow-on.** Do not change SVD here and do not treat it as a directed-body-motion backend. Recommend reducing it to a
small number of evidence-backed target-hardware presets and characterizing 14-frame motion-bucket/noise trade-offs.

## 10. Validation

`tests/video/test_pr_vid_192_animate2_controls.py` (27): baseline `@1.0.0` byte-identical; both versions registered and the
UI offers the newest; a stray `gentle` never enters the NJR or graph; exact node mapping for every control; empty motion
prompt frozen explicitly; prompt mode exposes only the real control and rejects pose controls; defaults/ranges equal the
pinned node (and the real ComfyUI source when `STABLENEW_VID184_COMFY_SOURCE` is set); invalid controls rejected before
admission; TI2V gains nothing; the controller builds no payload; provenance, `control_record` and replay; fail-closed compile;
driving hash still admission-frozen. `tests/tools/test_vid192_qualification.py` (16): corpus contract, license flags, no
absolute paths, inventory completeness, one-variable experiment arms, arm admissibility. Two GUI tests cover the panel.
Ruff, mypy on the new modules, and the local dual-version CI-equivalent gate are reported in the completion record;
required GitHub CI is pending (Actions minutes unavailable).

## 11. Architecture and controller assessment

`VideoWorkflowController` gained 10 lines: it calls the neutral helper, freezes the result and forwards the projection; it
builds no backend payload (asserted by a test). The controller-surface ratchet is unchanged (4 ratcheted). The generic
`operator_controls` mechanism is bounded (declared numeric/text inputs beside frame count and seed), not a new video-control
architecture. No process, lifecycle or cancellation authority changed; `--disable-pinned-memory` remains required.
