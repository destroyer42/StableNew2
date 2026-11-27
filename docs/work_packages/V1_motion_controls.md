# V1: direct the shot (task-first motion controls)

Decision record and work package. Status: **accepted**. The owner accepted all eight recommendations D1-D8 on
2026-11-26 ("I accept all", relayed by the orchestrator session `local_ecb8e9b1-c2ce-4303-95cf-308e8cc92d9e`; section 9).
V1-1 and V1-2 are merged. **Re-scoped 2026-11-27** (section 14, owner: "Accept re-scope"): V1-3 is rebuilt on
Wan-Animate-2, V1-4 and V1-5 are deferred and an end-frame slice is added; section 14 wins where it differs from
sections 5 to 10. Way Forward item V1 (owner-accepted 2026-11-25), paired with N8 (phone video
actions) and governed by the N7 focus policy (no new engines; no motion evaluation layers that do not feed V1).

## 1. Problem and decision

**Operator outcome.** The owner can say what the shot should do ("move a little", "follow this walk", "keep going from
here") and get a queued clip without knowing frame counts, driver windows, alignment numbers or engine controls, and can
then try a variation in one step. Today the engines can do this; the controls expose their internals, so experimenting
is slow (owner interview 2026-11-25: "frame counts, pose matching, settings are confusing and slow experimentation").

**Decision to be made.** How to turn the existing motion engines into three task-first intents (prompt-only motion,
follow a driving video, continue a clip) with automatic, visible, overridable choices, without a second build path, a
new engine or more evaluation machinery; and what exactly is missing.

**Decision criteria.** (1) Fewer operator decisions per queued clip; (2) every automatic choice visible with a reason
and overridable (VID-UX-360 rule); (3) the canonical path and admission unchanged; (4) reuse of existing modules over
new ones; (5) the same intent vocabulary serves the desktop and the phone (N8 / RG-140); (6) cost and testability.

## 2. Repository identity and evidence limits

- Repository `destroyer42/StableNew2`, branch `claude/v1-motion-controls-design-ed6477`, start SHA `29fc22c5`
  (`origin/main` was `7bdaefad` at writing; the intervening commits are N1b and do not touch the files this record
  cites). Worktree clean at start.
- Evidence read: `STATUS.md`; `docs/Subsystems/Video/PR-VID-UX-360_Task_First_Video_Workflow_Design.md` (with its
  VID-UX-384 layout section), `PR-VID-MOTION-410_...` section 3.2 (Stage C), `PR-VID-MOTION-420_...`,
  `CONTROLLED_MOTION_ROADMAP.md`, `MOTION_LIBRARY.md` 7.6-7.7, `STORYBOARDS.md` (Storyboard tab);
  `docs/runbooks/motion_alignment.md`; `docs/work_packages/RG-100_phone_review_gateway.md` (RG-140 row); the source
  files cited inline below. Two read-only survey subagents mapped `src/gui` and `src/video`; their key claims were
  spot-checked against source.
- Limits: nothing was run. Every statement about generated motion quality comes from the recorded, mostly unrated
  evidence of MOTION-410 Stage C and the MOTION-420 diagnostic (one or two subjects, one seed). RG-140 (phone actions)
  was in progress in another session with no committed design to read; section 7 states what V1 provides to it.

## 3. What exists today (evidence)

### 3.1 Operator surface

The Video Workflow tab already has a task model (VID-UX-360, `src/video/workflow_tasks.py:22-58`): `animate` ("Animate
from a prompt"), `follow_clip` ("Follow a driving clip"), `sequence`, `batch`. A task picks an eligible engine
(`choose_workflow`, `:125-151`), suggests settings with reasons (`suggest_settings`), and uses pins (`PinTracker`) so an
edited field is never silently re-suggested. The task never reaches the NJR (`workflow_tasks.py:3-4`). VID-UX-384 added
the Create | Evaluate split and the two-pane layout. So V1 **extends an existing task-first layer**; it is not a new UI.

What the owner still has to drive by hand (`src/gui/views/video_workflow_tab_frame_v2.py`, `video_workflow_sections_v2.py`):

| Exposed internal | Where | Why it hurts |
|---|---|---|
| Length as a list of legal frame counts ("N frames (~S s)"), different per engine (A14B 17-121 at 16 fps, Animate and TI2V-5B 17-81 at 24 fps; `workflow_catalog_wan_a14b.py:194-202`, `workflow_catalog_wan_animate2.py:116-123`) | settings block | The operator thinks in seconds; the driver's length plays no part in it (`motion_source_readiness.py:220-227` only reports used/unused frames). |
| Prepare Motion Source: start and end seconds, "Convert to the workflow's frame rate", Prepare / Use original (`video_workflow_motion_prep_panel_v2.py:72-123`) | follow-clip inputs | Optional, start defaults to 0; without conversion a driver plays at output_fps / source_fps of its real speed. |
| Align Motion: a separate 767-line dialog with scale, shift, mirror, marked point pairs, pixel bounds (`motion_alignment_dialog.py:244-275`) | dialog from `AlignmentRow` | Numeric and manual; the runbook needs seven steps. |
| Animate controls: Motion Prompt, Pose Strength 0-10, Pose Start %, Pose End %, Reference Image Strength 0-10 (`workflow_catalog_wan_animate2.py:149-211`) | More settings | No guidance on what values do, beyond display-only text. |
| Full Motion Library management (import, convert, batch convert, harvest, conditioning preview, edit details) inline (`video_workflow_motion_library_panel_v2.py:141-392`) | follow-clip inputs | Library maintenance tools sit in the shot form. |
| Motion readiness and motion guidance panels | right pane | Inspection, not control. |

There is **no video "re-run with tweaks"**: Replay re-submits the stored NJR unchanged
(`src/controller/history_handoff_service.py:54-82`), and Iterate is still-image only
(`src/gui_v2/history_iterate_model.py:75`). **Make Video from a clip uses its thumbnail or first frame**, not the last
(`src/video/video_artifact_helpers.py:214-229`), so "continue" from Video Workflow is a trap today.

### 3.2 Engines and their motion controls

| Engine (status) | Intent | Motion-relevant inputs |
|---|---|---|
| Wan2.2 I2V-A14B 4-step 1.0.0 (approved, Make Video default) | prompt-only, continue | prompt, length (no first/last-frame input, `workflow_catalog_wan_a14b.py:19-21`) |
| Wan2.2 TI2V-5B (approved, 480p and 720p) | prompt-only, continue | prompt, length |
| Wan-Animate-2 driving video 1.2.0 (experimental) | follow a driver | driver, Motion Prompt, pose strength, pose start/end, reference strength |
| Fun Control 5B Canny 1.1.0 (experimental trial) | follow a driver | driver (exact prepared frames, max 49 frames, fixed Canny thresholds) |
| A14B SVI, HunyuanVideo 1.5 (experimental candidates) | prompt-only / sequence | as A14B; frozen by N7 |

So **prompt-only engines have only two motion levers, prompt and length**; driving-video engines add the driver, its
window and alignment, and the Animate controls. Presets therefore mean different things per intent (section 5.4).

### 3.3 Motion machinery

- **Driver window.** `MotionSourceSettings(start_frame, end_frame, fps_conversion)` (`motion_source_plan.py:105-130`);
  the window length always equals the job's frame count (`:70-101`); a short window holds its last frame. Output is a
  lossless, framemd5-verified, content-addressed clip (`motion_source_preparation.py`). It accepts a start offset
  exactly as given; **nothing proposes one**. The Animate graph never seeks (offset must be 0,
  `driving_frame_consumption.py:171-173`), so any start offset goes through preparation.
- **Prepared-driver size.** Only Fun Control sources are downscaled (max edge 832, `motion_source_preparation.py:77-80`).
  A 4K lossless Animate driver reached 107,409,268 bytes and failed upload at Comfy's 104,857,600-byte limit (HTTP 413,
  MOTION-420 diagnostic v2, 2026-11-25); a pre-scaled driver gave a near-identical result (32.5 dB).
- **Pose detection.** A CPU DWPose detector exists, but only for image ControlNet: YOLOX-L plus `dw-ll_ucoco_384.onnx`
  on `onnxruntime` CPU in a contained subprocess worker (`src/conditioning/reference_map/pose.py`, `worker.py:79-88`),
  133 COCO-WholeBody keypoints per person. `PoseProvider.produce` returns only the rendered skeleton, not the keypoints
  (`providers.py:330-352`). Model files are staged from `<webui_root>/models/StableNewAux`. `onnxruntime==1.31.0` and
  `opencv-python` are already pinned in the app environment (`constraints/windows-py314-cu130.txt:54-55`). Nothing in
  `src/video` uses it, and there is **no pose similarity metric** anywhere.
- **Alignment.** One constant uniform scale + shift (+ optional mirror) for every frame, fitted by least squares from
  operator-marked anchor pairs (`motion_alignment.py:174-180, 536-550`), CPU only, Wan-Animate-2 only
  (`motion_alignment_support.py`). The compatibility check is advisory; its start-pose check compares operator-typed
  text (`motion_alignment_compatibility.py:285-296`).
- **Motion Library.** Assets carry free-text tags, `start_pose` / `end_pose` text, intensity, framing, viewpoint
  (`motion_library/models.py:536-587`); one harvested window per asset; no per-frame pose data.
- **Continuation.** Sequences carry the exact last frame forward (`sequence_shots.py`, `sequence_frames.py`). The
  Storyboard tab roots a finished clip job (`StoryboardSubmissionService.create_from_clip(job_id)`,
  `src/controller/storyboard_submission_service.py:160`) and continues from any frame with prompt, negative and seed
  rows, parallel or sequential, engine inherited (`STORYBOARDS.md`). The service is Tk-free. Sequence admission refuses
  engines with operator controls (`sequence_admission.py`), so **Animate driving-video and Fun Control cannot be
  continued**. A14B appears eligible by rule; **no A14B or physical Storyboard continuation has run**
  (`STORYBOARDS.md` acceptance boundary).

### 3.4 Start-pose evidence

- Historical: "a first-frame pose that differs from the source image has produced an unnatural opening"
  (`src/video/workflow_conditioning.py:343-344`, basis historical).
- MOTION-410 Stage C3 (2026-11-25, Animate 1.2.0, 81 frames, one seed): matched versus unmatched start pose. Trace
  correlation favoured matched (0.68 / 0.67 against 0.18 / 0.22), but the owner judged subject B's **unmatched** clip
  the more plausible and subject A's review is incomplete. C3 "neither confirms nor refutes" the opening problem.
- Stage C1 arms (one subject): pose strength 2.0 gave more full-body movement (and a smile the source lacks);
  reference strength 0.5 gave good head and body movement; 1.0 / 1.0 turned the head with little body motion;
  reference 1.3 reduced motion (motion guidance). Walking and travel are unresolved.
- MOTION-420: alignment changed framing and scale, visibly only where the driver's subject scale differed a lot (walk);
  pose and motion transfer looked alike in all four cases. Everything is unrated, N=1 per scenario.

**Consequence for the design:** start-pose matching and alignment are cheap to automate and plausibly useful, but their
benefit is not established. They must be visible, reversible suggestions with the basis recorded, not silent rules, and
V1 must not commission a new evaluation layer to prove them (N7).

## 4. Invariants (binding on every slice)

1. **Canonical path.** Every V1 control writes the existing Video Workflow form state; submission stays
   `get_video_workflow_state` -> `VideoWorkflowController.submit_video_workflow_job` -> `VideoWorkflowNjrBuilder` ->
   `JobService.submit_njrs`. Continue goes through the existing `StoryboardSubmissionService` / sequence builder.
   Re-run creates a new NJR with lineage; no NJR is mutated. No second queue, runner, builder, history or lineage store.
2. **No new engines, workflows, workflow versions or graph changes.** The DWPose detector is an existing CPU
   conditioning tool, reused in its contained worker; it is not a generation engine and never uses the GPU.
3. **Admission unchanged.** `parse_frame_count` still rejects an illegal length; the seconds-to-frames rounding is a
   presentation function whose result (shown to the operator) is the value submitted. Prepared and aligned motion stay
   content-addressed and are re-validated at freeze exactly as today.
4. **Visible, overridable automation.** Each automatic choice shows its value and a one-line reason, and an edited
   field is pinned (VID-UX-360 pins). Warnings, not blocks (N1): a missing pose model or a weak match degrades to the
   plain behaviour with a why-and-fix message; only today's real blocks stay.
5. **Presets are versioned data**, never code paths; they set only controls the chosen engine declares, never bypass
   admission, and a replay uses frozen values, never re-resolves a preset.
6. **No blocking work on the Tk thread.** Pose detection, frame decoding and preparation run on thread-registry workers,
   cancellable and superseded by newer requests (the Harvest and Align patterns).
7. **No new evaluation layer.** V1 adds no eval suite kind, metric family, report or rating column. Checking a V1
   default uses the existing eval kit's ordinary arms, if the owner authorizes a run.
8. **Controller surface.** `video_workflow_controller.py` and `app_controller.py` do not grow; new logic lives in
   Tk-free `src/video` modules, and existing controller mixins gain only thin delegations within ratchets.

## 5. Design

### 5.1 Alternatives considered

| | Design | Verdict |
|---|---|---|
| A (recommended) | **Evolve the VID-UX-360 tasks in place.** Relabel `animate` and `follow_clip`, add `continue_clip`; seconds-first length; presets as a suggestion source through the existing pins; automate the driver window, start pose and alignment inside the follow-driver panel with the raw panels under Advanced; one Tk-free intent module shared with the phone. | Reuses the task model, pins, layout, builder and Storyboard service. Smallest surface that removes the exposed internals. |
| B (minimal) | Relabel lengths in seconds, add presets, move raw panels under Advanced; no automation. | Cheap but leaves the two named pains, start pose and alignment, manual. Kept as slices V1-1 and V1-3's first half. |
| C | A separate "Direct" tab or dialog with its own intent model. | Rejected: a second form state and submission surface beside Video Workflow, duplicate handoffs, and drift from the eval and Storyboard entry points. |
| D | Route every intent through the Storyboard tab (a storyboard per shot). | Rejected for prompt-only and follow-driver: Storyboard sequence admission refuses Animate, and a storyboard is heavier than one clip. Adopted only for continue (5.5). |

### 5.2 Intents

The task selector shows three primary intents, then the existing two as secondary choices. Ids are kept so saved state,
handoffs and tests keep working.

| Intent (label) | Task id | Engines (existing eligibility) | Panel shows |
|---|---|---|---|
| **Prompt-only motion** | `animate` (relabel) | prompt-only engines | prompt, motion preset, duration |
| **Follow a driving video** | `follow_clip` (relabel) | engines with `pose_video` | driver picker, motion preset, duration ("whole movement"), start-pose strip, inline alignment preview, prompt |
| **Continue a clip** | `continue_clip` (new) | the clip's own engine, if sequence-eligible | clip picker, continue-from frame (default last), prompt (prefilled), duration, seed |
| Multi-shot sequence, Many images | `sequence`, `batch` (unchanged) | unchanged | unchanged |

The summary line becomes the one place the engine is named (`A14B 4-step · 3.1 s · Gesture · random seed`, with
**Change**); the Engine picker, seed, smoothing and declared controls sit under **Advanced** (today's *More settings*).
With N1, Queue on a visible experimental warning is the opt-in, so the picker no longer needs to be in view.

### 5.3 Duration, not frame count

A pure function `frames_for_duration(seconds, policy, window=None)` in a new `src/video/motion_intent.py`:

- **Prompt-only and continue.** The operator picks seconds (a short list: about 2, 3, 5 s and the engine's maximum,
  plus Custom); the function returns the nearest legal `4n+1` count inside `[minimum, maximum]` (ties go shorter) and
  the line shows both: `3.1 s · 49 frames at 16 fps`. Above `advisory_above` it shows the existing drift warning.
- **Follow a driver.** Default **Whole movement**: the usable window is the driver's remaining length after the chosen
  start, at the workflow rate; the length is the largest legal count that fits, capped at the engine maximum
  (`Driver 4.2 s from 0.8 s · clip 3.4 s · 81 frames (engine maximum)`). A shorter request trims the window. A driver
  shorter than the engine minimum warns and holds the last frame (existing behaviour).
- **Natural speed by default.** Follow-driver always prepares the driver with `fps_conversion = workflow_rate`, so the
  movement plays at its real speed (D8). *Use original timing* stays under Advanced.

The same function serves the phone (RG-140) so a phone duration tweak resolves identically.

### 5.4 Presets

A preset is versioned data in `src/video/motion_presets.py`: `{preset_id, version, label, intent, duration, prompt
phrase, library tags, engine-capability settings, basis}`. Applying one writes unpinned fields through the existing
`PinTracker` (exactly as `suggest_settings` does); editing a field pins it and the chip reads `Walk (modified)`;
**Reset to preset** clears the pins. A setting the engine does not declare is skipped and the reason line says so.

| Preset | Prompt-only (A14B, TI2V-5B) | Follow a driver (Wan-Animate-2) | Basis shown |
|---|---|---|---|
| **Subtle** | 3 s; motion phrase "subtle natural movement, slight head and shoulder motion, steady camera" | catalog defaults (pose 1.0, reference 1.0); 3 s or whole movement if shorter | catalog defaults |
| **Gesture** | 3 s; phrase "expressive hand and arm gestures, upper body movement" | pose 1.0, reference 0.5; library filter tags `wave`, `gesture`, `arms` | 410 C1: reference 0.5 gave head and body movement (one subject, one seed) |
| **Walk** | 5 s (A14B) / engine max; phrase "walks forward naturally, full body in frame, camera follows" | whole movement; alignment auto-fit on; library tags `walk`; warning "walking is unresolved in tests" | motion guidance (walking unresolved); 420 walk case (alignment kept the subject in frame) |
| **Dance** | engine max; phrase "dances rhythmically, full body movement" | pose 2.0, reference 0.5; whole movement; library tags `dance` | 410 C1: pose 2.0 gave more full-body movement, possible expression bleed (one subject) |

- The **prompt phrase** is a visible, editable *Motion* field under the prompt, composed into the submitted prompt as
  `"<prompt>, <motion>"`; Preview shows the composed text; nothing is inserted silently (D3). For Animate the phrase
  fills the Motion Prompt control instead of the main prompt.
- Values beyond catalog defaults (pose 2.0, reference 0.5) are **observed once, not qualified**, and each preset says so
  in its basis line (D2). Raw Pose Strength, Pose Start/End and Reference Strength stay under Advanced.
- The applied preset `{id, version}` and each automatic choice's basis are recorded as provenance only under
  `extra_metadata["video_workflow"]["motion_intent"]` (D5). Admission and replay ignore them; re-run with tweaks and a
  later Learning pass (roadmap Phase 6) can read them.
- No user-saved presets in V1 (they are roadmap Phase 5, recipes; section 8).

### 5.5 Follow a driving video

Panel order: driver, preset, duration, start pose, alignment, prompt.

1. **Driver picker.** A compact searchable list of Motion Library clips (thumbnail, name, length, start pose text),
   pre-filtered by the preset's tags, plus Browse. *Open Motion Library…* opens the full library (import, convert,
   harvest, edit details) as its own window; those tools leave the shot form.
2. **Automatic window.** Choosing a driver prepares it automatically on a worker: start from 5.5.3, length from 5.3,
   natural speed, and a **size cap** (prepared Animate drivers are scaled to the smallest same-aspect size whose cover
   still contains the workflow's working frame, with a byte check below the Comfy upload limit; the record states the
   scale). This removes the HTTP 413 failure class. A strip shows the first and last prepared frames with
   `Starts 0.8 s · 3.4 s of motion`; *Adjust window…* opens today's Prepare panel under Advanced.
3. **Start pose (automatic, CPU).** See 5.6.
4. **Alignment (inline).** See 5.7.
5. **Prompt** (scene) and the preset's Motion field.

Fun Control (no alignment, max 49 frames) gets the same panel without the alignment step, with its reason.

### 5.6 Start-pose matching

Scope: choose the driver **start frame** whose subject pose is closest to the source image's subject pose, within the
range where the requested length still fits.

- **Keypoints API.** A small addition to `src/conditioning/reference_map`: a function that returns the parsed
  `PosePerson` list from the existing contained DWPose worker instead of only the render (the worker already returns
  keypoints; `providers.py:338-342`). Same models, same CPU provider, same staging, same timeout and cancellation.
- **Sampling.** Candidate starts every ~0.25 s across the admissible range, at most 24 frames, decoded with the existing
  `driving_video_inspection.build_frame_command`. Results cached per `(driver sha256, frame index, detector identity)`
  under the library root, so a driver is analysed once.
- **Metric** (`src/video/start_pose_match.py`, pure): body keypoints 0-16 only (hands and face are noisy and excluded),
  confidence-weighted; each pose normalised by translation to the hip/shoulder centre and scale by torso length;
  distance is the weighted mean joint distance; joints below a confidence floor on either side are dropped and the
  coverage is reported. Single most-prominent person on each side; several people on the driver is a warning.
  Mirroring is evaluated and reported ("closer if mirrored") but never applied automatically (it reverses direction).
- **Decision rule.** If the best candidate beats the clip start by a clear margin, it becomes the suggested start and
  is applied (D1); otherwise the clip start stays. The strip shows source pose, clip-start frame and suggested frame
  side by side with `Closest pose at 1.2 s (score 0.18 vs 0.41 at start)`; **Use clip start** reverts in one click and
  pins it. The chosen start and its basis (`pose-match v1`, scores, coverage) are recorded (D5).
- **Degradation.** Missing DWPose files or WebUI root, no person detected, or low coverage: clip start, with a
  why-and-fix line ("Start-pose matching needs the DWPose files in <folder>; ask Claude to install them"). Never a block.
- **Honesty.** The panel states that a matched start reduces a known risk (unnatural opening) and that its effect on
  the finished clip is not established (3.4).

### 5.7 Inline alignment

The separate dialog becomes the Advanced editor; the panel shows a live overlay instead.

- **Preview.** Source image with the prepared driver's start frame overlaid at the current transform (onion-skin
  slider), plus the existing compatibility advisories as one-line warnings (clipping, scale, position).
- **Auto-fit.** With keypoints from 5.6, anchor pairs (head, shoulders, hip centre, feet) are formed automatically and
  passed to the existing `fit_anchors`; the alignment record's "how the numbers were chosen" names the basis
  `detected (DWPose, pose-match v1)` instead of operator points. Requires a small extension of the anchor provenance in
  `motion_alignment.py` (today anchors are by definition operator-reported).
- **Default.** Choices are **As is**, **Fit automatically** and **Adjust…** (today's dialog). Recommended default: Fit
  automatically when the compatibility check flags a scale or position mismatch above its existing thresholds, As is
  otherwise (D4). Apply-and-prepare happens on Queue's preflight, on a worker, with the existing statuses
  (Preparing, Verified, Stale); a stale or failed alignment still stops submission with its reason.

### 5.8 Continue a clip

- **Entry.** The intent panel takes a clip from Recent outputs (selected), Job History, the phone (RG-140) or Browse
  (an external MP4 through the existing Storyboard import). The *Continue in Storyboard* buttons stay.
- **Panel.** The clip's last frame (default) with a scrubber for *Continue from*, the prompt prefilled from the clip's
  job, the preset's Motion field, duration (5.3), seed Random. Engine inherited and shown read-only on the summary line.
- **Submission.** A Tk-free facade `continue_clip(job_id | clip, frame, prompt, duration, seed)` composes the existing
  `StoryboardSubmissionService.create_from_clip` (or reuses the clip's existing storyboard root) and one sequential
  `ContinueRequest`. The continuation is therefore a take in a Storyboard, visible and further continuable in the
  Storyboard tab (D6). Result clip appears in Recent outputs.
- **Limits.** Driving-video engines cannot be continued (sequence admission); the panel says so and offers
  *Continue as prompt-only motion* with an approved engine from the clip's last frame (that is a normal prompt-only
  job with the last frame as source). End-frame control (N24, FLF2V) stays later.
- **Fixes the trap.** *Make Video* on a clip keeps its current meaning, but the panel and the phone use the true last
  frame (`sequence_frames` carry rule), never the thumbnail.

### 5.9 Re-run with tweaks (pairs with N8)

- **Intent snapshot.** `src/video/motion_intent.py` reconstructs, from a completed video job's frozen NJR and its
  `motion_intent` provenance, an intent snapshot: intent, prompt and motion phrase, preset id, duration in seconds,
  driver binding and window start, alignment choice, engine, seed. Older jobs without provenance reconstruct with the
  preset shown as *none* and duration from frames.
- **Tweak vocabulary** (typed, bounded; the same set the phone gateway may send): `prompt` (length-bounded), `motion`
  phrase, `preset`, `duration_seconds`, `seed` (new random by default), `more_motion` / `less_motion` (one step along the
  preset ladder Subtle -> Gesture -> Dance for driver engines; for prompt-only it changes only the phrase).
- **Desktop.** Recent outputs and Job History gain **Re-run with tweaks…**: opens Video Workflow on the intent panel
  filled from the snapshot, with every value pinned and a new random seed; Queue builds a new NJR through the normal
  `VideoWorkflowNjrBuilder`, whose source is the existing `njr_compiler.history_lineage(parent)` (`HISTORY_REPLAY`,
  `parent_job_id`) with a content-free variation marker, the precedent set by the still-image *Regenerate with Changes*
  (`src/pipeline/history_variation_compiler.py`, PR-HISTORY-610A). Unlike 610A it rebuilds through the video builder
  instead of copying the frozen recipe, because a duration, start or preset tweak needs fresh driver preparation; the
  builder accepting a lineage source is a small plumbing change inside V1-2.
- **Driver re-runs** reuse the frozen prepared clip when the window is unchanged; a changed duration or start
  re-prepares from the original driver if its bytes still verify, otherwise the tweak is refused with the reason.

### 5.10 What moves behind Advanced or Show experimental

| Surface | V1 placement |
|---|---|
| Engine picker, seed, RIFE, negative prompt, declared Animate controls | **Advanced** (summary line names the engine) |
| Prepare Motion Source panel (start/end seconds, fps conversion, Use original) | **Advanced** (*Adjust window…*); automatic by default |
| Align Motion dialog (scale, shift, mirror, point pairs, bounds, full compatibility panel) | **Advanced** (*Adjust…* from the inline preview) |
| Motion readiness panel and Motion guidance text | header chip and a *Tips* link; full panel under Advanced (VID-UX-384 rule unchanged) |
| Motion Library management (import, Convert Motion, Batch Convert, Harvest, Edit details) | its own window via *Open Motion Library…* |
| Preview Conditioning (MOTION-430 effective-driver preview), conditioning inspection, driving-representation and multi-engine comparison kinds | **Show experimental** (in Motion Library and Evaluate) |
| Eval kit, Compare one control, Rate & review | unchanged in the **Evaluate** view |
| HunyuanVideo 1.5, A14B SVI and CK arms, superseded versions, Animate-2 prompt mode | **Show experimental** (N13; V1 consumes N13's switch, does not build it) |
| Preview Frozen Plan | unchanged (shown only where the workflow declares it) |

N7 focus: MOTION-430 physical stages, further 410/420 stages and roadmap Phases 5-8 stay paused unless a V1 slice
needs a specific piece; the eval kit stays as the way to check a V1 default when the owner asks.

## 6. Missing pieces (gaps)

| Gap | Needed by | Size |
|---|---|---|
| G1 seconds-first length function and driver-window length (`frames_for_duration`) | all intents | small, pure |
| G2 preset data, application through pins, provenance record | prompt-only, follow | small-medium |
| G3 automatic preparation with natural speed and a prepared-driver size cap (+ record field for the scale) | follow | medium |
| G4 keypoints API on the existing DWPose worker; frame sampling; pose cache | start pose, auto-fit | medium |
| G5 start-pose metric, ranking and decision rule | start pose | small-medium, pure |
| G6 detected-anchor provenance in alignment; inline overlay widget | inline alignment | medium |
| G7 `continue_clip` facade over the Storyboard service; last-frame source rule | continue, N8 | small-medium |
| G8 intent snapshot from a job, tweak vocabulary, re-run handoff with lineage | re-run, N8 | medium |
| G9 compact driver picker; library tools moved to their own window | follow | medium (GUI) |

## 7. Pairing with N8 / RG-140

V1 owns the **intent layer**; RG-140 owns the phone transport, grants, caps, receipts and UI. V1 provides, Tk-free and
tested: `frames_for_duration`, the preset table, the intent snapshot, the tweak vocabulary (5.9) and `continue_clip`.
A phone "re-run with tweaks" is an outbox request `{job_id, tweaks}`; on the PC, RG-140's admission resolves it with
the V1 snapshot and the normal builder, so a phone tweak and a desktop tweak produce identical NJRs. A phone "continue
clip" is `{job_id, prompt?, duration?}` through `continue_clip`. If RG-140 lands its phone actions first, it should
call these functions once they exist rather than reconstruct jobs itself (hand-over note for the RG-140 session).

## 8. Exclusions

- No new engine, workflow version, graph change, model download, LoRA, end-frame control (N24) or camera control.
- No new eval suite kind, metric, report, rating column or qualification claim; no promotion change.
- No user-saved presets or recipes (Phase 5), no motion Learning (Phase 6), no controlled-motion storyboards (Phase 7).
- No continuation of driving-video engines; no per-frame tracking, retargeting or pose-conditioned generation.
- No change to admission, `parse_frame_count`, the NJR schema, replay, queue or history authorities.
- No phone UI or transport (RG-140).

## 9. Owner decisions

**Accepted 2026-11-26.** The owner accepted every recommendation below as written ("I accept all"; the owner's only
exceptions in that exchange concerned RG-140, not V1). Each slice implements the recommended option.

| # | Decision | Accepted (the recommendation) |
|---|---|---|
| D1 | Start-pose matching: apply the best match automatically (one-click *Use clip start*), or only suggest it? | Apply automatically when it beats the clip start by a clear margin; always shown, recorded and reversible. Evidence is ambiguous (C3), so the strip says its effect is unproven. |
| D2 | Presets may use observed-once values beyond catalog defaults (pose 2.0, reference 0.5, from 410 C1), labelled "observed once, not qualified". This relaxes VID-UX-360's "no new tuning numbers". | Yes (N1 / N7: warn and let it run). |
| D3 | Prompt-only presets add a visible, editable motion phrase composed into the submitted prompt. | Yes; never hidden, shown in Preview. |
| D4 | Inline alignment default: fit automatically from detected keypoints when a scale or position mismatch is flagged, as is otherwise. | Yes. |
| D5 | Record the preset id/version and each automatic choice's basis in job provenance (amends VID-UX-360's "a task never reaches the NJR"; admission and replay ignore it). | Yes; it is what makes re-run with tweaks and later Learning possible. |
| D6 | Continue a clip from Video Workflow or the phone creates or extends a Storyboard (the one lineage store), visible in the Storyboard tab. | Yes. |
| D7 | Slice order (section 10): prompt-only first, desktop re-run with tweaks second, then follow-driver, start pose, inline alignment, continue. | Approve as listed; V1-2 and V1-6 also unblock RG-140. |
| D8 | Follow-driver always prepares the driver: natural speed (convert to the workflow rate) and a size cap below the Comfy upload limit, by default. | Yes; *Use original timing* stays under Advanced. |

## 10. Slices in value order

Each slice is one PR, Standard class unless noted, deterministic tests plus one live-app operator check by the owner
(screen-driven per the owner default). No slice needs a GPU run to merge; any physical check of a V1 default is an
optional owner-authorized eval-kit run.

| Slice | Outcome | Main files | Acceptance (tests) | Model (Claude Code; Codex) |
|---|---|---|---|---|
| **V1-1 Prompt-only panel** | Intent labels; seconds-first duration; Subtle/Gesture/Walk/Dance presets for prompt-only engines with the Motion field; engine and raw settings under Advanced; summary line. | new `src/video/motion_intent.py` (G1), `src/video/motion_presets.py` (G2); `workflow_tasks.py`; `video_workflow_task_panel_v2.py`, `video_workflow_sections_v2.py` | legal-count rounding per policy incl. ties, min/max, advisory; preset application respects pins and skips undeclared controls; composed prompt equals Preview; submitted state for unchanged choices equals today's; provenance record present and ignored by admission/replay | Sonnet 5.5 High; GPT-6.1 Sol High |
| **V1-2 Re-run with tweaks (desktop) + shared vocabulary** | Recent outputs / History *Re-run with tweaks…*; intent snapshot; typed tweaks; lineage. | `motion_intent.py` (G8); `video_workflow_njr_builder.py` (lineage source only); `video_workspace_handoff.py`; `history_handoff_service.py` (thin) | snapshot round-trip from NJRs with and without provenance; each tweak's bounds; new NJR with `HISTORY_REPLAY` lineage and a variation marker, original unchanged; unchanged-tweak re-run differs from Replay only by seed and lineage; driver re-run reuse vs re-prepare vs refusal | Opus 5.5 High; GPT-6 Astra High |
| **V1-3 Follow-driver panel** | Driver picker with preset tags; automatic natural-speed preparation with size cap; whole-movement length; Animate presets; library tools in their own window; Prepare panel under Advanced. | `motion_source_plan.py`, `motion_source_preparation.py` (G3); `video_workflow_motion_library_panel_v2.py`, new compact picker view (G9); tab layout | window length from driver and policy; conversion default; size cap stays below the upload limit and records scale; prepared record re-validates at freeze; Fun Control path unchanged; no blocking work on Tk thread | Opus 5.5 High; GPT-6 Astra High |
| **V1-4 Start-pose matching** | Automatic start frame with the side-by-side strip and *Use clip start*. | `src/conditioning/reference_map/providers.py` (keypoints API, G4); new `src/video/start_pose_match.py` (G5); pose cache | metric on synthetic keypoint sets (translation/scale invariance, confidence floor, mirror reported not applied); margin rule; degradation paths (no models, no person, low coverage) warn and fall back; cancellation/supersession; recorded basis | Opus 5.5 High; GPT-6 Astra High |
| **V1-5 Inline alignment** | Overlay preview, auto-fit from detected anchors, As is / Fit / Adjust…; dialog becomes the Advanced editor. | `motion_alignment.py` (detected-anchor basis, G6); new inline widget; `video_workflow_alignment_host.py` | auto-fit equals `fit_anchors` on the same pairs; basis recorded; mismatch-triggered default; stale/failed still blocks submit; dialog parity | Opus 5.5 High; GPT-6 Astra High |
| **V1-6 Continue a clip** | `continue_clip` task and facade over the Storyboard service; last-frame default; driver-engine fallback to prompt-only. | new facade in `src/controller/` or `src/video/` (G7); task panel; `storyboard_submission_service.py` (no behaviour change) | facade builds the same NJR as the Storyboard tab for the same inputs; last frame not thumbnail; driving-engine clip offers prompt-only fallback; external MP4 path uses existing import refusals | Sonnet 5.5 High; GPT-6.1 Sol High |

Rough size: V1-1 and V1-6 about 1-2 days of agent work each, the others about 2-3; about 15-25M cache-read and
150-250k output per slice at the recommended models (order of magnitude, from N1 and VID-UX-384).

## 11. Self-critique (one assessor, not an independent review)

- **Weakest assumption: start-pose matching is worth automating.** C3 does not show matched starts winning, and the
  owner preferred one unmatched clip. Why proceed anyway: the cost is CPU-only and reversible, the only recorded
  observation of failure is an unnatural opening from mismatched poses, and the alternative is the owner reversing
  clips in ffmpeg by hand (410 section 3.1). What would invalidate it: an owner sitting (N14) where matched starts look
  no better across a few drivers; then D1 flips to "suggest only" and V1-4 shrinks to the strip. V1-4 is deliberately
  after V1-1 to V1-3, which pay off regardless.
- **DWPose reuse depends on a configured WebUI root and staged model files.** If they are absent on the owner's machine,
  V1-4 and V1-5's auto-fit degrade to manual. The slice must check the owner's install first (read-only) and, if the
  files are missing, propose staging them, not silently add a second copy.
- **Presets for prompt-only engines are mostly prompt wording.** Their value rests on the phrase, which is untested
  wording; the motion guidance module deliberately never inserts text. D3 makes the composition visible, which is the
  safeguard; if the owner declines D3, prompt-only presets reduce to duration and the table collapses to two rows.
- **Continue on A14B is unexercised.** Sequence admission accepts it by rule, but no physical Storyboard or A14B
  continuation has run. V1-6 cannot claim continue works on hardware until the owner's first live use; its PR says so.
- **Scope pressure.** Re-run with tweaks (V1-2) overlaps RG-140. Keeping the intent layer here and the transport there
  avoids two job-reconstruction implementations, but needs the two sessions to agree on the tweak vocabulary first.

## 12. Execution class, start state and stop conditions

- Execution class (this record): Standard, design only. Slices: Standard; V1-4 and V1-5 touch `src/conditioning` and
  the alignment record, still within existing authorities (no `AGENTS.md` change). D5 amends a VID-UX-360 design rule,
  not an architecture invariant.
- Task start 2026-11-26T15:17:25Z (10:17:25 -05:00), session `claude:f02490e7-00fb-4820-b726-f4cf94c788a8` plus two
  read-only survey subagents in the same session stream; started by `local_ecb8e9b1-c2ce-4303-95cf-308e8cc92d9e`.
- Model for this record: Claude Code Opus 5.5 (effort as set by the session); Codex equivalent GPT-6 Astra High.
- Stop conditions for any slice: a needed change to admission, the NJR schema, the queue, replay or `AGENTS.md`; a new
  engine, workflow version or model download; a new evaluation layer; a controller ratchet that would have to rise;
  any physical GPU run without the owner's exact authorization; RG-140 and V1 disagreeing on the tweak vocabulary.

## 13. Documentation impact (per slice, when it lands)

- `docs/Subsystems/Video/PR-VID-UX-360_Task_First_Video_Workflow_Design.md`: tasks, presets, Advanced placement, D5.
- `docs/Subsystems/Video/VIDEO_PIPELINE.md` section 4 (operator surface); `MOTION_LIBRARY.md` (picker and window);
  `docs/runbooks/motion_alignment.md` (inline preview, detected anchors); `STORYBOARDS.md` (continue entry points).
- `STATUS.md`: one line in the video capability paragraph when V1-1 lands; no PR narrative. `docs/CODEX_MAP.md`: rows
  for `motion_intent.py`, `motion_presets.py`, `start_pose_match.py`. Generated code map regenerated per slice.

## 14. Re-scope accepted 2026-11-27

**Owner acceptance (chat, 2026-11-27): "Accept re-scope"** (relayed by the orchestrator session
`local_ecb8e9b1-c2ce-4303-95cf-308e8cc92d9e`). Research basis: the 2026-11-27 value assessment notes (not committed):
Wan-Animate-2 consumes a driving video directly, with no pose extraction or skeleton preprocessing; the stock
`WanFirstLastFrameToVideo` node is in the managed ComfyUI and the neutral contract already declares an `end_anchor`
control that no catalog workflow uses. Neither has been run on this machine by this record.

**Slice order.** V1-1 (merged), V1-2 (merged), then:

| Slice | Outcome | Acceptance |
|---|---|---|
| **A. Follow a driver** (V1-3 rebuilt) | Task-first panel on Wan-Animate-2: source image, driver clip, duration in seconds, preset, Queue. The driving video goes in directly (no pose files, no alignment dialog). Length from the duration and the driver; the window is trimmed and prepared automatically at natural speed with a size cap (D8). Engine settings under Advanced. | A driver clip is queued from the panel in under five steps and the panel shows no frame counts. Same compiler, NJR, `JobService` path. |
| **B. End frame (A14B)** | Start image plus end image gives the clip between them, through the stock first-and-last-frame node, as a new catalog workflow id, **experimental until rated**. Offered to continue a clip only if that falls out cheaply, otherwise noted for V1-6. | The new workflow compiles with both images bound; Queue warns and records the opt-in; no other workflow's graph changes. |
| V1-6 Continue a clip | unchanged (5.8) | unchanged |

**Deferred (not cancelled): V1-4 start-pose matching and V1-5 inline alignment**, with their gaps G4, G5, G6 and
sections 5.6 and 5.7. Align Motion stays the existing manual dialog under Advanced. **D1** (apply the best start pose
automatically) and **D4** (fit alignment automatically) have no effect while those slices are deferred; they are not
reversed. D2, D3, D5, D6 and D8 stand. D7's slice order is replaced by the table above.

**Supersedes sections 4.2 and 8** only as far as slice B: one new workflow id and version using a stock ComfyUI node
on the installed A14B experts. No new engine, model, download, custom node or evaluation layer.

**Slice B as built.** Continuing a clip toward a chosen end image did not fall out cheaply: multi-shot sequences and Storyboard takes refuse end anchors (`unsupported_controls`), so it is **noted for V1-6**. The workflow uses A14B 1.0.0's two sizes (480x832 / 832x480), not the unmeasured VID-FRAME full-picture sizes; a crop of either picture above 5% warns.

**Not in slice A** (left for later, not silently dropped): the compact tag-filtered driver picker (G9) and a separate
Motion Library window; the library stays inline behind a button.
