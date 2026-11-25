# PR-VID-MOTION-420: subject alignment and motion compatibility

Status: **implemented on a feature branch** (Phase 3 of `docs/Subsystems/Video/CONTROLLED_MOTION_ROADMAP.md`). This is a per-PR record: the code and the living docs (`VIDEO_PIPELINE.md`, `MOTION_LIBRARY.md`, `docs/runbooks/motion_alignment.md`, `docs/runbooks/video_eval_kit.md`) win where they differ. **No physical generation was run, no runtime was started, nothing was queued to a GPU.** Spatial preparation is deterministic CPU work; it shows nothing about whether aligned conditioning improves *generated* motion. That is the question the unexecuted campaign in section 8 asks.

Execution class: Standard, difficult bounded cross-file. **Model recommendation:** Claude Code Sonnet 5.5 XHigh; Codex GPT-6.1 Sol XHigh (`docs/AI_MODEL_SELECTION.md`).

## 1. Baseline and prerequisites (verified, not assumed)

| Fact | Evidence |
|---|---|
| Phase 1 (PR-VID-MOTION-400) is accepted and integrated | merged as PR #399 (`c0a837fe` on `main`) |
| Phase 2 (PR-VID-MOTION-410) is **not** integrated | branch `feature/pr-vid-motion-410-motion-eval` has no PR, no CI run and is not an ancestor of `origin/main` |
| This package was built **on the Phase 2 branch tip** | `e2a6520a399aaf225eff4a0991019c8816f2f706` (includes `origin/main` `7db7e0de`), by explicit owner decision on 2026-11-24, as a *provisional* dependency |

Consequences, stated plainly: this branch cannot merge before PR-VID-MOTION-410 does; if 410 changes in review, the evaluation files (`video_eval_motion.py`, `video_eval_integrity.py`, `video_eval_run.py`, the review/report modules) may need a rebase. Phase 2's *physical* pilot (Stage A/B, 15 jobs on `wan_animate2_drive_i2v_v1` 1.2.0) was run on the owner's machine and informs the campaign design (sections 8 and 9); no Phase 2 evidence was invented or reinterpreted, and no alignment default was changed.

## 2. What it is

An explicit, reproducible spatial transform of a driving clip into the source image's frame, applied before the clip enters the existing prepared-motion contract:

`source image + motion asset + window -> Align Motion (inspect, edit, suggest, apply) -> Prepare -> verified aligned clip -> existing production builder -> NJR -> queue`

It adds **no** queue, runner, history, compiler, process or persistence authority. The aligned clip enters a job only as the existing `prepared_motion_source` form key; the NJR schema, the registered workflow graphs, the catalog and the qualification policy are untouched.

## 3. The transform contract (`src/video/motion_alignment.py`)

* **Coordinate system** `stablenew.alignment-frame.v1`: continuous pixel-edge coordinates, origin top-left, y down. The *target frame* is the prepared source image's size `W x H`; the driver's *display frame* is its stored frame with rotation applied, `dw x dh`. Operator numbers are in these spaces, never viewport pixels.
* **Order** `stablenew.alignment-transform.v1`: (1) baseline cover placement `c = max(W/dw, H/dh)`, centred (what the workflow's own resize does to an unaligned clip); (2) optional horizontal mirror of the driver's pixels; (3) **uniform** scale `s` about the target centre; (4) translation `(tx, ty)` in target pixels. The placed driver is the rectangle `left = (W - dw*c*s)/2 + tx`, `top = (H - dh*c*s)/2 + ty`; `aligned(t) = s * original(t) + translation` for every frame `t`.
* **Bounds, refused not clamped:** `0.25 <= s <= 4`, `|tx| <= W`, `|ty| <= H`, finite numbers only, at least one visible target pixel. Values are rounded to 4 (scale) and 2 (translation) decimals; the requested and the resolved numbers are both recorded.
* **Raster resolution:** the visible part of the placement is rounded to whole target pixels (an edge moves at most half a pixel) and the source box that fills it is computed from those integers (`Image.resize(size, LANCZOS, box=...)`). Uncovered pixels take the constant fill `constant_gray_128`; nothing is generated, extended or inpainted.
* **Mirror** reverses motion direction and swaps left/right. It is chosen only by the operator, disclosed whenever on, and never changes a prompt.
* **Anchors** (`fit_anchors`): operator-marked pairs, source points in target pixels and driver points in driver display pixels. A deterministic closed-form least-squares fit of `a = s*b + t0` over the baseline-mapped driver points (no rotation, no per-axis scale): `s = sum(b~.a~)/sum(|b~|^2)` on mean-centred points. One pair fixes position only (scale 1); two or more fix both. Named thresholds: spread `ANCHOR_MIN_SPREAD_FRACTION` 0.05 (below it the points are degenerate and the fit is refused), `ANCHOR_SCALE_CONFLICT_RATIO` 1.25, `ANCHOR_RESIDUAL_WARNING_FRACTION` 0.03. Insufficient, degenerate, invalid or out-of-range input is refused with a reason; conflicting scales and large residuals are warnings with the residual shown. A suggestion is a proposal: nothing changes until the operator accepts it, and adjusting by hand afterwards makes the numbers the operator's own.
* **Reframing as a crop** (`intent_from_frame_region`): "frame this region of the driver" expressed as the same constant transform (cover semantics).
* **Envelope inspection** (`inspect_envelope`): maps only the subject bounds the operator entered under the one constant transform and reports how many of the frames that covers. Sampled frames are never presented as the whole window.
* **Record** `stablenew.motion-alignment.v1` (`ResolvedAlignment.to_record`): versions, target and driver sizes, requested and resolved numbers, placement, destination, source box, fill, resampling, boundary report, anchors/fit provenance and `transform_sha256` (a digest of the resolved geometry, equal for equal geometry however the numbers were chosen). `alignment_from_record` re-resolves a stored record and refuses any disagreement, so a hand-edited or newer-algorithm record is never trusted and an old one is never recomputed.

## 4. Preparation (`src/video/motion_alignment_preparation.py`)

Reuses `MotionSourceSettings` / `build_frame_plan` (the Phase 1 exact-frame planner), the bounded cancellable process runner, the content-addressed `prepared_driving_videos/` directory and its stale-temporary rules.

1. Probe the clip; resolve the target (the prepared source image, the same `transform_declared_workflow_source` admission uses) and the transform; plan the frames; `framemd5` the window (count and identity).
2. Decode only the planned *unique* source frames once, in display orientation, to private PNGs (a lossless hand-off).
3. `transform_frame` each unique frame once and write the planned output frames.
4. One lossless RGB encode (`libx264rgb -qp 0`, no metadata, bit-exact flags).
5. **Verify**: decode the file and require every frame's `framemd5` to equal the fingerprint of the in-memory declared transform of its selected source frame. A mismatch, wrong count, wrong size, a rotation tag, a changed source, or any process failure keeps nothing.
6. Hash, publish atomically under `<sha256>.mp4` (an identical earlier result is reused, never rewritten; earlier preparations are never deleted) and record everything.

Cancellation, deadlines (`DEADLINE_SECONDS`), the 256 MB output cap and process containment are the Phase 1 mechanisms. Added bounds: 9 MP per decoded driving frame, at most 96 distinct source frames, one RGB encode; a preview decodes at most 12 frames and about 60 MP (first and last always kept) and holds them only so an edit re-renders without another decode.

**What the verification does and does not prove.** The published file equals the declared transform of the selected source frames, frame for frame, exactly (decoded RGB fingerprints). It is *not* an independent re-implementation of the transform: the geometry itself is validated by tests that measure a moving synthetic subject in the *decoded output* and compare it with the mathematics (within 1.5 px), and the preview, which calls the same `transform_frame`, is compared with the published frames pixel for pixel. The unaligned path keeps its stronger "output equals source frames" check, unchanged.

**Honest labels in the record:** `processing.lossless` is `false` (the derivative is not pixel-identical to the source), `lossless_encoding` is `true`, `source_frame_identity` is `transformed`, `resampling` is `lanczos`, `color_handling` states that FFmpeg's default YUV-to-RGB conversion is stored losslessly, and the pixels are display-oriented with no rotation tag.

**Effective conditioning geometry.** `alignment_support(spec)` (`motion_alignment_support.py`) offers alignment only where the pinned graph's single resize is `ResizeImageMaskNode` "scale dimensions", centre crop, `area`, to the frozen `target_width x target_height`. A clip prepared at exactly that size has equal aspect (no crop: `comfy_center_crop_offsets(W,H,W,H) == (0,0)`, a transcription of `comfy/utils.py::common_upscale`, read on 2026-11-24 from the local ComfyUI install) and an equal-size `area` interpolation averages one pixel per output pixel, so the workflow's own resize is the identity and the alignment is the only spatial step. The *pinned* runtime revisions were not re-read for this package and no torch call was made against them; `STABLENEW_VID196_COMFY_SOURCE` is the existing hook for that check. Supported today: Wan-Animate-2 driving video (`wan_animate2_drive_i2v_v1`, catalog 1.2.0). Refused with a stated reason: Fun Control Canny (the frames become edges before the resize, so a border introduced by alignment would become edges of its own), prompt-only workflows and any graph whose resize differs. A changed graph fails closed.

## 5. Admission, dispatch and replay

* `VideoWorkflowNjrBuilder.freeze_shared_inputs` routes an aligned record to `validate_aligned_record` (the unaligned call is untouched and still guarded by the Phase 1 structural tests). It refuses an unsupported workflow and re-verifies: schema, contract (workflow id/version/length), plan consistency, the transform re-resolved from the record, geometry against both files, the original driver's path and hash, the derivative's content address and hash.
* `freeze_inputs` then binds the clip to **one source image**: the source file's hash, the prepared reference's hash and its dimensions must equal the record's. A different or edited source is refused before anything is built. A batch therefore admits an aligned clip only for the one source it was made for (all-or-none, unchanged); another source needs its own alignment.
* The job freezes the derivative as `pose_video_path`/`pose_video_sha256` (so Phase 1's dispatch and replay checks apply unchanged) and the full record under `motion_source_preparation`; history metadata adds a short `alignment` summary. The original asset's Motion Library identity stays bound to the original hash; the derivative has its own.
* `verify_aligned_dispatch` (backend, both entry points) re-checks at execution: the frozen clip is the record's derivative, the record re-resolves under its recorded transform version, the target equals the frozen reference geometry, and the reference image hashes as recorded. Replay and "Check inputs" use the frozen derivative via `frozen_input_checks`; they never recompute an alignment from current settings or a newer algorithm (a different `transform_version` is an explicit refusal).
* A stale, failed, cancelled, unprepared or running alignment contributes a blocker to the form, never the unaligned clip.

## 6. Operator experience

The compatibility panel (`motion_alignment_compatibility.py`) reuses the existing readiness advisories (crop, upscaling, rotation, timing) and the workflow's recorded guidance, computed once from the preview's own measurements, beside the operator's reported annotations and the derived geometry, and always lists what is not known. `Align Motion...` sits under the driving-motion preparation panel and opens one non-modal workspace (`motion_alignment_dialog.py`; all rules in the toolkit-neutral `MotionAlignmentSession`): source and driving frames side by side or as an overlay with adjustable opacity, original or aligned motion, first/middle/last and further inspection frames with stepping and bounded playback, the target-frame boundary and the placed-driver rectangle with fill, anchor markers, geometry and compatibility text. Previewing, editing and suggesting never queue a job, start a runtime or change what the form submits; only **Apply and prepare** does, and a status word (Not applied, Editing, Preparation required, Preparing, Verified, Stale, Failed or unsupported) says where it stands. The content-visibility policy gates every decode.

## 7. Evaluation integration (Phase 2 contract, no second framework)

* A case may declare `motion.alignment` (`scale`, `translate_x`, `translate_y`, `mirror`, `note`; strict, needs `preparation.mode: workflow_prepared`). An arm chooses `form.motion_alignment`: `none` (default) or `case`. The alignment is not part of the motion's identity (`record_identity` is unchanged).
* `MotionFacts` gains `alignment` and `temporal_plan_sha256`; `settings()` carries both. `classify_pair` has a new `ALIGNMENT` comparison kind: when the *only* differences are the alignment and the derivative hashes it expects, the pair is **verified comparable** ("only the declared spatial alignment differs"). A different temporal selection, seed, driver, motion prompt or any other control is not accepted as part of the intervention (incomparable, or a disclosed non-separable multi-setting comparison). Cross-subject groups disclose per-subject alignments and never generalize them.
* The run service checks the compiled NJR against the arm's request (an alignment is never dropped, invented or altered to make an arm queueable); `driving_context_sha256` binds ratings to the frozen alignment (an unaligned job's digest is byte-for-byte what it was), so earlier ratings never silently apply. The review role, the report and the preview summary state the frozen parameters and say a preview is not evidence of success. `duplicate_case_for_source` drops the alignment (another subject must be aligned for itself).
* Existing Phase 2 suites, ratings and reports are unchanged: all 172 existing 410 tests pass without modification.

## 8. The unexecuted campaign

Templates (placeholders only; operators bind their own media and replace each case's alignment with the one they accepted for that exact pair): `docs/runbooks/examples/video_eval_motion_alignment_{pilot,diagnostic,full}.suite.json` -- 2, 8 and 16 jobs; four scenarios (position, scale, locomotion, start pose), two subjects each, arms `unaligned` and `aligned`, seed 420, `wan_animate2_drive_i2v_v1` 1.2.0 at 49 frames, per-job experimental opt-in. The pilot nests in the diagnostic sample which nests in the full design.

**Future owner authorization must name:** the suite file and its SHA-256; every bound image and driving-video SHA-256; the workflow and version (`wan_animate2_drive_i2v_v1` 1.2.0, experimental opt-in recorded per job); the stage (pilot 2 jobs, then diagnostic 8, then full 16, each only after the previous is accepted); the budget; the resource constraints; and the stop conditions. Planning figures from the Phase 2 pilot, not a fresh benchmark: 229-311 s per job at 49 frames (about 10 minutes for the pilot), whole-GPU VRAM peak about 11.8 GB of 12.28 GB, host RAM minimum 15.3 GB, GPU near 83 C; the managed Comfy must launch with `--disable-pinned-memory`, readiness floors 10,000 MiB available VRAM and 16 GB available RAM, 1,200 s history timeout, runtime released after the run. **Stop on:** a GPU device loss or quarantine, a resource-guard refusal, two consecutive failed jobs, any changed-input or incomparable finding in the report, content that must not be shown, or the stage budget exhausted. Resampling is part of the intervention (the unaligned path lets the graph's `area` resize act on the full-resolution frame; the aligned path Lanczos-resizes first); an *identity-alignment* arm (`scale 1`, no shift) would separate resampling from placement if the pilot warrants it.

## 9. Known limitations and unresolved decisions

* **Physical motion-transfer behavior is unverified.** Geometric alignment cannot correct an anatomical pose difference, a viewpoint difference or missing body parts, and is not retargeting.
* Phase 2 is an unmerged dependency (section 1). Decision for the owner: merge 410 first, then this branch.
* The aligned derivative is 8-bit RGB (FFmpeg's default YUV-to-RGB conversion, stored losslessly); the decoder that feeds ComfyUI may convert slightly differently. `libx264rgb` is required in the FFmpeg build; without it preparation fails with a typed `ffmpeg_failed` and keeps nothing.
* Limits: 9 MP per driving frame, 96 distinct source frames, 17-81 frames (the workflow's policy), 256 MB output. A window needing more is refused with a message.
* The pinned runtime's resize identity was argued from the pinned graph and the runtime arithmetic and tested on the arithmetic's transcription, not measured on the pinned runtime (section 4).
* Compatibility advisories are only as good as the reported annotations; they are advisory, name their basis and thresholds, and never block.
* A multi-source batch needs one alignment per source; a batch with one alignment is refused for every other source.
* The suite editor preserves `motion.alignment` and `form.motion_alignment` as written but offers no dedicated fields for them yet (JSON authoring).

## 10. Controller Surface Assessment

`VideoWorkflowController` stays at 259 physical lines (the PR-VID-194 guard is below 260): the new surface is the mixin `src/controller/video_motion_alignment_controller.py` (about 100 lines, delegation only; geometry, fitting, compatibility and media work live in typed `src/video/` services). `AppController` and every ratcheted controller ceiling are untouched. `video_workflow_tab_frame_v2.py` (a view, not a ratcheted controller) gains one host, one row and the submission merge (about 85 lines); Tk code reads inputs and renders, and holds no preparation or persistence logic.

## 11. Evidence

| Suite | What it shows |
|---|---|
| `tests/video/test_pr_vid_motion_420_alignment.py` (pure) | identity/translation/scale/mirror/order, known anchors, residuals, refusals, invalid and non-finite values, portrait/landscape/square, frame-region intent, envelope, record round trip and tamper |
| `tests/video/test_pr_vid_motion_420_prepare.py` (real FFmpeg) | exact verification, trajectory preservation across frames, mirror reversal, plan-decided frame order and holds, EXIF source, rotated driver, preview == publication, reuse, hygiene, cancellation, atomic-publication failure, tamper |
| `tests/video/test_pr_vid_motion_420_admission.py` | support from the declared graph, freeze, source binding, staleness refusals, dispatch and replay, Fun Control refusal |
| `tests/video/test_pr_vid_motion_420_eval.py` | declaration, arm validation, integrity classification, ratings binding, a real aligned-versus-unaligned plan and admission, refusals, templates, editor duplicate |
| `tests/gui_v2/test_pr_vid_motion_420_alignment_ui.py` | session lifecycle and staleness, stale-worker suppression, real Tk workspace and tab merge, end to end |
