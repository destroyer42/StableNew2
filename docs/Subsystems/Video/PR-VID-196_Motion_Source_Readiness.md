# PR-VID-196 — Motion Source Readiness & Workflow-Aware Guidance (Video Workflow)

Status: **implemented and source-level verified locally; not pushed, not merged.** Validation is CPU/fake-runtime plus
real FFmpeg/FFprobe on disposable clips. No physical generation was run, so nothing here shows that the added
information improves generated motion. No generation algorithm, sampling default, workflow version, catalog graph,
NJR field or runtime ownership changed; Wan-Animate-2 stays EXPERIMENTAL and per-job opt-in.

Execution profile: Standard, known architecture. Claude Code Sonnet 5.5 High (recommended); Codex GPT-6.1 Sol High
(alternative GPT-5.6 Terra High). Local/Desktop. Start `main @ aed19b81dc5f31c8b6f9f2ac851f76f1e6584e7b`.

## 1. What it is

A read-only **Motion source readiness** section in the Video Workflow tab that helps an operator decide before queueing:

* the **exact prepared source image** (the pixels admission would publish) and the **actual crop rectangle**;
* bounded **driving-video facts** (what the file reports) kept apart from what was **measured** (a few decoded frames);
* **geometry advisories** and a **timing relationship** between the clip and the requested output;
* **workflow-aware motion guidance** that says what is tested, what is declared, what is unresolved and what is
  untested, separately for subject motion, camera motion and identity/background.

It is advisory and display-only. A warning never changes generation intent and never refuses an otherwise valid job; the
prompts are never edited, appended to, normalised or replaced.

## 2. Architecture

No new queue, runner, history, compiler, scheduler, cancellation or process authority. The canonical path

`Intent -> Compiler -> immutable NJR -> JobService -> SQLite Queue/Repository -> PipelineRunner.run_njr -> Handler/Executor -> Artifact/History`

is unchanged. The new surfaces sit beside it and feed nothing into it; a structural test pins that the NJR builder,
experiment service, batch service, controls, frame-count policy, catalog and backend never import them.

| Piece | Module | Role |
|---|---|---|
| Shared transform + exact preview | `src/video/workflow_source_preparation.py` | `transform_declared_workflow_source` (in-memory), `preview_declared_workflow_source`, `cover_crop_box`; `prepare_declared_workflow_source` now calls the same transform |
| Driving-video inspection | `src/video/driving_video_inspection.py` | bounded FFprobe/FFmpeg, typed outcomes, no I/O beyond reading the clip |
| Geometry / timing advisories | `src/video/motion_source_readiness.py` | pure, named thresholds, verified-runtime registry |
| Guidance projection | `src/video/workflow_motion_guidance.py` | pure `spec -> guidance`; deliberately **not** a catalog field |
| Neutral session | `src/gui/view_contracts/video_motion_readiness_contract.py` | selection-generation tokens, bounded workers, view model |
| Tk panel | `src/gui/views/video_workflow_motion_readiness_panel_v2.py` | rendering only |
| Delegation | `src/controller/video_workflow_controller.py` | one projection key + two static delegates |

### Workstream A — source preparation and exact preview

The accepted behaviour is unchanged: EXIF transpose, RGB conversion, declared target selection, LANCZOS cover resize with
a centred crop. It is now one side-effect-free function used by both the queue-time preparation and the preview, so the
two cannot drift. The crop rectangle comes from the same arithmetic that drives the resize: `cover_crop_box` is Pillow's
`ImageOps.fit` crop (centred, no bleed) and the pixels are produced by `Image.resize(box=<that box>)`. Tests pin both
directions in the pinned environment (Pillow 12.3.0): pixel parity with `ImageOps.fit`, pixel *and PNG byte* equality
between the preview and the published prepared PNG, EXIF orientation, source immutability and zero filesystem writes
(including a `Path.mkdir`/`Path.write_bytes`/`Path.replace`/`Image.save` tripwire). Content-addressed names, the eight
`source_preparation` stage-config keys, immutable NJR fields and replay semantics are untouched; the existing
concurrency/publication suite passes unchanged.

### Workstream B — driving-video inspection

Reuses the repository's resolution convention (`resolve_ffmpeg_executable`; FFprobe beside it, else `PATH`, now exposed
as `container_metadata.resolve_ffprobe_executable`). Bounds, all named constants and tested:

| Bound | Value |
|---|---|
| Probe / per-frame timeout | 10 s each; whole inspection deadline 30 s; cooperative cancel |
| Probe stdout / frame stdout / stderr kept | 64 KiB / 512 KiB (+ FFmpeg `-fs`) / 2 KiB (drained, not stored) |
| Preview frames / edge | at most 3 / at most 160 px (scaled inside FFmpeg, never decoded at source size) |
| Input protocols | `-protocol_whitelist file`; argv list, no shell, `-nostdin` |
| Writes | none; output goes to a pipe |

It reports: stream dimensions (rotation metadata applied, so a phone clip is "portrait"), reported fps (average, with
the base rate used to flag possible variable frame rate), reported frame count, duration, and codec/pixel format.
Estimates are labelled: a missing `nb_frames` becomes "about N (estimated from duration and fps)"; unknown stays
unknown. Missing FFprobe/FFmpeg, corrupt/truncated/empty files, audio-only files, probe timeouts, oversized probe output
and undecodable frames are typed, non-throwing outcomes (partial results are kept).

**Requested output duration** uses the existing workflow policy (`frame_count_policy` / `parse_frame_count` /
`approximate_seconds`); an illegal length is not invented.

### Verified runtime semantics (driving-frame timing)

The pinned ComfyUI node was read, read-only, at both runtime revisions the catalog records (`73c9bad4…` v0.37.0 and
`6b747c04…` v0.38.0; the two installs under the managed-Comfy root). In both, `WanAnimate2ToVideo.execute` does

```
pose_video = pose_video[video_frame_offset:]
pose_video = common_upscale(pose_video[:length] ...)
if pose_video.shape[0] < length:  # hold the last frame
```

and the graph reaches `pose_video` only through `LoadVideo -> GetVideoComponents -> ResizeImageMaskNode` (decoded
frames in order, per-frame centre-crop resize, `video_frame_offset` the literal 0) with `CreateVideo` at a fixed 24 fps.
So generated frame *i* follows driving frame *i*, no frame-rate conversion happens before conditioning, a shorter clip
repeats its last frame, and only the first `length` frames are used. `driving_frame_consumption(spec)` re-derives this
from the spec's own graph and runtime revision (not a name): a changed chain, a non-zero offset or an unlisted revision
makes the timing **unknown** and every derived number `None`. `STABLENEW_VID196_COMFY_SOURCE=<checkout>` re-checks the
node source text and the revision in the optional test.

What is derived, and labelled as arithmetic: frames used/unused, last-frame hold, and `output_fps / driving_fps` as the
speed at which the clip's motion is laid out over the output. The generated motion itself is not measured.

### Workstream C — advisories

Observational only (no subject detection, pose estimation or quality prediction). Each carries a basis (measured from
the image / reported by the file / derived) and, where it has a cut-off, the threshold's name and value:

| Constant | Value | Observation |
|---|---|---|
| `SOURCE_CROP_DISCARD_ADVISORY_FRACTION` | 0.20 | preparation discards that share of the source |
| `DRIVING_CROP_DISCARD_ADVISORY_FRACTION` | 0.20 | centre-crop discards that share of the clip (approximate) |
| `ASPECT_RATIO_DIFFERENCE_ADVISORY_FRACTION` | 0.25 | relative aspect-ratio difference, clip vs prepared frame |
| `DRIVING_UPSCALE_ADVISORY_FACTOR` | 1.5 | the clip is enlarged at least this much |
| `FPS_DIFFERENCE_ADVISORY_FRACTION` | 0.10 | clip rate differs from the declared output rate |

Boundary comparisons tolerate float noise (an exact 20 % discard is flagged). Non-threshold notes: EXIF rotation,
orientation mismatch, clip shorter/longer than the output, possible variable frame rate.

### Workstream D — guidance

Chosen from what the spec declares (workflow family, a bound `pose_video`, and the operator controls the version
actually exposes): Wan2.2 TI2V-5B prompt-directed; Wan-Animate-2 prompt mode; Wan-Animate-2 driving-video mode;
anything else is an explicit "no guidance" state. Basis vocabulary: *pinned runtime*, *declared*, *tested (one sample)*,
*tested, not delivered*, *untested*. Evidence is PR-VID-150 (structured sequential prompting materially improved a
local gesture on one source/seed; the same style produced no stepping) and PR-VID-192 §§2, 4, 5, 8 (prompt mode skips
the pose branch; separate motion prompt removed the duplicate subject but the driven locomotion was not delivered in
any arm; reference strength 1.3 reduced motion; the negative prompt is inert at CFG 1.0). Walking/locomotion is shown
as **unresolved**, never as a limitation of the model. The function takes only a spec, so it cannot see a prompt.

### Workstream E — GUI

The panel sits in the scrolled Video Workflow body (row 6; the rows below shifted by one) and is hidden until a workflow
supplies readiness data. The exact preview and the probe run on bounded `ThreadRegistry` workers
(`BackgroundWorkRunner`/`TkUiDispatcher`, the PR-VID-194 pattern); every widget read happens before a worker starts and
every update on the Tk thread. Staleness: each channel (source, driving video) has a selection-generation token bumped on
every change; at most one worker per channel runs; a changed selection cancels the running probe and the newest
selection starts when the old worker returns, so a completed worker can never overwrite a newer selection; teardown
cancels the probe and discards late results. Input changes are debounced (300 ms) and de-duplicated by key.

## 3. Compatibility and invariants

* Existing `source_preparation`, NJR fields, content-addressed prepared names and replay: unchanged (tests above).
* Catalog: no spec, graph or version changed; digests of all nine registered comfy specs, recorded from `main`, are
  pinned by a test. Guidance is a separate module, not a spec field.
* One-variable experiment gate, batch all-or-none admission and single `submit_njrs` call: unchanged and re-asserted with
  readiness traffic in between. Experimental opt-in remains mandatory and non-persistent.
* The workflow projection gains exactly one key, `motion_readiness`; every existing key is preserved.

## 4. Controller surface assessment

`VideoWorkflowController` is not a ratcheted controller (new-controller limit 600 physical lines) and PR-VID-194 guards it
below 260 lines: 239 → 257 lines (+18: three imports, one projection key, two static delegates
`preview_motion_source` / `inspect_driving_video`). It builds no payload and owns no preparation or inspection logic.
`AppController` (ceiling 7421) is not touched; the ratchet reports `4 ratcheted` with no growth.

## 5. Validation

| Suite | Cases |
|---|---|
| `tests/video/test_pr_vid_196_source_preview.py` | 32 — parity, PNG equality, crop box, EXIF, no writes, errors |
| `tests/video/test_pr_vid_196_driving_video_inspection.py` | 39 — parsing, commands, orchestration, bounded processes, real FFmpeg fixtures |
| `tests/video/test_pr_vid_196_readiness_and_guidance.py` | 34 (+1 optional) — thresholds, timing, verification, guidance, isolation, spec digests |
| `tests/video/test_pr_vid_196_workflow_integrity.py` | 6 — frozen NJR, admission, projection keys, experiment/batch unchanged |
| `tests/gui_v2/test_video_workflow_motion_readiness_ui.py` | 24 — session staleness, Tk thread marshalling, hidden/unsupported, wrapping, real clip |
| existing | `test_workflow_source_preparation.py`, PR-VID-190/192/194/200, controller and tab suites unchanged and green |

Real clips are generated by the installed FFmpeg into `tmp_path` and skipped when FFmpeg is absent.

## 6. Known limitations

* **Source-level validation only.** Whether any of this changes generated motion is unmeasured; no physical run.
* Guidance is a single-sample evidence summary (one source, clip and seed); it will go stale if new evidence lands and
  must then be updated deliberately.
* The driving-clip crop discard is approximate (cover arithmetic matching the graph's centre-crop; ComfyUI's own resize
  was not re-implemented). Non-square pixel aspect is reported, not applied.
* Frame counts are the container's report (or an estimate); the clip is not decoded end to end by design.
* Timing is stated only for revisions in `VERIFIED_POSE_FRAME_CONSUMPTION_REVISIONS`; a new managed runtime must be
  re-read and added deliberately.
* The panel does not yet persist or export anything and offers no "use this crop" action by design.
