# PR-VID-MOTION-210 — Deterministic Driving-Motion Preparation (Prepare Motion Source)

Status: **implemented and source-level verified.** Validation is CPU only: pure unit tests, real FFmpeg on disposable clips, and a one-off read-only cross-check with the managed Comfy runtime's own PyAV decoder (section 6). No physical generation was run, no runtime was started or restarted, and nothing here shows that a prepared clip improves generated motion. No workflow version, catalog graph, sampler, model, NJR field, queue, runner or runtime ownership changed; Wan-Animate-2 stays experimental and per-job opt-in.

Execution class: Standard, difficult bounded cross-file (no NJR schema change, no new execution contract; see section 7). **Model recommendation:** Claude Code Sonnet 5.5 XHigh (`docs/AI_MODEL_SELECTION.md` row "difficult bounded lifecycle/persistence/concurrency/cross-file PR"); Codex GPT-6.1 Sol XHigh as the alternative; stay in one local session.

## 1. What it is

An **optional** step in the Video Workflow tab. For a workflow that takes a driving video, the operator can *Prepare Motion Source*: choose where in the clip the window starts (and optionally ends), optionally convert the clip to the workflow's declared output rate, and get a StableNew-owned, lossless, content-addressed MP4 that holds **exactly the frames the selected registered workflow will consume**, in order. The panel shows the file's first, middle and last frames, the original and prepared identities, and a plain explanation of what was omitted, repeated, held or never used. The job then freezes the prepared file (and the record of how it was made) instead of the whole original clip.

Leaving everything alone changes nothing: with no preparation the job is byte-for-byte what it was (section 5).

## 2. The contract it implements (verified, not assumed)

| Question | Answer | Evidence |
|---|---|---|
| Which driving frames does generated frame *i* use? | Driving frame *i*, in decode order from the start of the file; `video_frame_offset` is the literal 0; only the first `length` frames are used; a shorter clip holds its last frame. | PR-VID-196 section 2 and `src/video/driving_frame_consumption.py` (decided from the spec's own graph and runtime revision). Re-read on the managed ComfyUI v0.38.0 checkout: `WanAnimate2ToVideo.execute` (`pose_video[video_frame_offset:]`, `[:length]`, last-frame hold) and the optional `STABLENEW_VID196_COMFY_SOURCE` test passes. |
| Is the frame rate converted before conditioning? | No. `CreateVideo` is a fixed 24 fps and nothing in the pose chain resamples. A clip at another rate is laid out at `output_fps / clip_fps` of its speed unless the operator converts it. | Same. |
| What happens to size and crop? | The graph's `ResizeImageMaskNode` ("scale dimensions", `crop` centre, `area`) resizes every frame to the prepared source image's target size. Preparation does not touch geometry, so that node remains the only spatial step and one prepared clip serves every source of a batch. | `src/video/workflow_catalog_wan_animate2.py` template nodes 18-21; ComfyUI `common_upscale`. |
| Which lengths are legal? | The workflow's own policy (Wan-Animate-2: 17 to 81, 4n+1, 24 fps). Illegal lengths are refused, never rounded. | `src/video/workflow_frame_count.py`. |
| How does LoadVideo decode? | Frames in order through PyAV; rotation metadata is applied by the consumer (`frame.rotation`); no frame-rate handling. | `comfy_api/latest/_input_impl/video_types.py` `get_components_internal`. |

Preparation is only offered when `driving_frame_consumption(spec).verified` is true, so it fails closed for a changed graph or an unverified runtime revision.

## 3. Design

| Piece | Module | Role |
|---|---|---|
| Verified consumption rule | `src/video/driving_frame_consumption.py` | Moved verbatim out of `motion_source_readiness` (which re-exports it) so the job-affecting path never imports the display-only advisories. |
| Pure plan | `src/video/motion_source_plan.py` | `MotionSourceContract` (from the registered spec and chosen length), `MotionSourceSettings`, `FramePlan`, `build_frame_plan`, the FFmpeg filter chain, and the operator explanation. Exact integer arithmetic; no I/O. |
| Preparation | `src/video/motion_source_preparation.py` | Bounded FFmpeg orchestration, verification, atomic content-addressed publication, record, and `validate_prepared_record` (admission-time re-verification). |
| Reused inspection | `src/video/driving_video_inspection.py` | The one probe/preview implementation (PR-VID-196). Two additive extensions: `DrivingVideoFacts.fps_rational` (the exact rate as FFprobe wrote it) and `inspect_driving_video(positions=...)` (exact preview seeks). |
| Admission | `src/video/video_workflow_njr_builder.py` | The single NJR construction path. `freeze_shared_inputs` verifies and freezes an optional `prepared_motion_source` form key; batch and one-variable experiments therefore get it for free. |
| Backend provenance | `src/video/comfy_workflow_backend.py` | `_driving_video_provenance` copies the record into the run manifest. No execution change. |
| Controller | `src/controller/video_workflow_controller.py` | One delegate, `prepare_motion_source`. |
| GUI | `src/gui/view_contracts/video_motion_prep_contract.py`, `src/gui/views/video_workflow_motion_prep_panel_v2.py` | Toolkit-neutral session and the Tk panel, hosted by the tab (the tab only supplies the form snapshot and merges the session's extra form keys). |

### 3.1 The plan

* `none` (default): consumed frame *j* is source frame `start + j`. The prepared file keeps the clip's own rate, so nothing is resampled and the explanation states the resulting speed (`24 / clip_fps`).
* `workflow_rate`: output frame *j* is at `j / output_fps` seconds after the window start and takes the **nearest** source frame in time, a tie taking the later one: `offset_j = floor(j * clip_fps / output_fps + 1/2)`, computed with exact fractions from the rate FFprobe reports (so 30000/1001 is exact). Faster clips omit frames, slower clips repeat them. A clip that may be variable frame rate is refused for conversion and still allowed without it.
* An optional exclusive `end` bounds the window. When the window or the clip runs out the last available frame is held to the requested length, and the explanation says exactly which output frames those are.
* Seconds are converted to a source frame with the clip's exact rate (nearest frame); the record keeps both the request and the resolved frames.

### 3.2 The file

`libx264 -qp 0` (lossless) in the clip's own pixel format (8-bit and 10-bit 4:2:0, 4:2:2 and 4:4:4 are kept unchanged; `nv12`, `p010` and alpha variants map to their colour planes; anything else is refused), `-threads 1`, bit-exact flags, no audio, no metadata, stored orientation and the display-rotation metadata kept (so the consumer turns it exactly as it would the original), colour range/matrix tags kept. The unique source frames are chosen by `select`, each is stamped with the output slot where it first appears (exact integer ticks), `fps` repeats a frame until the next slot, and one stamped clone of the last frame guarantees FFmpeg's end-of-stream handling never decides the result. Published as `<output>/prepared_driving_videos/<sha256>.mp4`, atomically, never overwritten with different content.

### 3.3 Verification at every step

1. **While preparing:** the window is decoded once with `framemd5` to learn how many frames really exist and each frame's fingerprint, and the plan is built from that truth. After encoding, the file is decoded again and **every output frame must equal the frame the plan selected**. A mismatch, a wrong count, a lost rotation tag, an oversize result or a source that changed meanwhile keeps nothing. (This check caught an FFmpeg `fps` end-of-stream difference during development; the sentinel frame above is the fix.)
2. **At admission:** `validate_prepared_record` re-hashes the original and the prepared bytes, checks the record is content-addressed, and that it was made for this clip, workflow, version and length. Anything else is refused with a reason and nothing is built, queued or written. For batch and experiments the original and prepared files are also re-hashed at the moment of admission (`verify_unchanged` / `verify_shared_unchanged`).
3. **At dispatch and replay:** the job's `pose_video_path` is the prepared file and `pose_video_sha256` its hash, so the existing backend check (`_verify_driving_video_source`) and replay check (`frozen_input_checks`) apply unchanged.

## 4. What is recorded

`config["video_workflow"]["motion_source_preparation"]` (schema `stablenew.motion-source-preparation.v1`) carries: the **original** (path, SHA-256, size, display size, rotation, rate, frame count and its basis, codec, pixel format), the **derived** file (path, SHA-256, size, frame count, size, rotation, pixel format, rate, and a SHA-256 over the decoded per-frame fingerprints), the **settings** (resolved start/end frames, conversion, and the operator's request), the **contract** (workflow id, version, length, rate, runtime revision, consumption rule), the **plan** (the source frame behind each consumed frame, window frames, held frames), and **processing** (tool and version, codec, arguments, selection method, verification). `extra_metadata["video_workflow"]["motion_source_preparation"]` repeats the two identities and the settings for history; the Comfy run manifest repeats the full record. Unprepared jobs have none of these keys.

## 5. Compatibility

* **Existing jobs:** an unprepared Animate-2 driving job and a TI2V job built on this branch are byte-identical (config, extra metadata, input paths) to the same build at `70c30947` (one-off comparison; also pinned by `test_an_unprepared_job_is_exactly_what_it_always_was`, which fixes the exact key set). No NJR field, workflow version, catalog graph (the nine spec digests test still passes) or persisted-job format changed; the new keys live in the free-form stage config and metadata mappings.
* **Controller ceilings:** `VideoWorkflowController` is 259 physical lines (PR-VID-194 guard: below 260; was 257). The unused `_mapping_dict` helper was removed to make room; `AppController` and the ratcheted controller ceilings are untouched.
* **Advisories stay display-only** (`motion_source_readiness`, `workflow_motion_guidance`): no job-affecting module imports them (structural tests). The job-affecting path imports `driving_frame_consumption`, `motion_source_plan` and `motion_source_preparation`.
* **Batch and experiments** keep their all-or-none admission and single `submit_njrs` call; a prepared clip is source-independent and is shared by every job.

## 6. Evidence

* `tests/video/test_pr_vid_motion_210_plan.py` — 41: contract per registered spec, exact arithmetic and hand-checked index tables for 12/24/25/30/30000-1001/36/48/60 fps, windows, holds, filter-chain goldens, explanation text, purity.
* `tests/video/test_pr_vid_motion_210_preparation.py` — 51: real FFmpeg fixtures; independently decoded frames equal the planned source frames for eight clip rates, windows, holds, seconds on a 29.97 fps timeline, 8-bit and 10-bit formats, rotation, determinism (same record, same bytes, file not rewritten), exact thumbnail frames, size and frame caps, every process-failure path, mismatch/rotation-loss/source-change refusals, cancellation with a real child process that must not survive, stale-temporary hygiene, bounded and whitelisted commands, and `validate_prepared_record` tamper cases.
* `tests/video/test_pr_vid_motion_210_admission.py` — 17: both identities in the frozen job, compiler binding, dispatch and replay re-verification, unchanged default, refusals leave no job and no source PNG, batch and experiment sharing and tamper refusal, preview/queue agreement by path, bytes and decoded content, structural isolation.
* `tests/gui_v2/test_video_workflow_motion_prep_ui.py` — 34: session staleness/blocking/cancel/late-result rules, Tk panel visibility, a failed/running/cancelled/stale preparation never admits a job (single, batch and experiment), worker off the Tk thread with rendering on it, teardown cancels.
* The 801 existing `tests/video` cases, the existing video GUI suites and the PR-VID-196 suites pass unchanged.
* **One-off, read-only, CPU:** the managed ComfyUI v0.38.0 environment's PyAV (the decoder `LoadVideo` uses; no torch, no Comfy process) decoded the original and the prepared clip for plain, BT.709 TV-range, BT.601 PC-range and rotated sources: the prepared frames are bit-identical to the planned source frames (colour tags preserved). The first version, which baked the rotation in with FFmpeg's autorotate, was **not** identical to what Comfy produces for a rotated clip (chroma siting) and was replaced by keeping the rotation metadata.

## 7. Boundaries and stop conditions checked

No NJR schema change (free-form mappings only), no new workflow execution contract (the backend still receives `pose_video_path` + hash), no persisted-job incompatibility (above), no new queue/compiler/runner/history/process authority (a structural test pins that the new modules name none), no model or sampler change, no prompt rewriting, no physical run.

## 8. Known limitations and residual risk

* **Source-level validation only.** Whether a prepared clip changes generated motion is unmeasured.
* **Lossless means large.** The prepared file is capped at 256 MB; a roughly 1080p window of the longest legal length fits, a 4K window does not and is refused with a message (cap and 40-megapixel frame limit are named constants). Spatial downscaling in preparation was deliberately not added: it would be a second resampling step ahead of the graph's own, and per-source geometry would stop one clip serving a whole batch. Owner decision if 4K phone clips matter.
* **Upload time.** The existing Comfy client uploads with a 30 s timeout; a file near the cap on loopback is expected to fit, but it was not exercised against a real runtime.
* **Decode cost.** Reaching a late window decodes from the start of the clip (frame accuracy over speed); each FFmpeg pass is bounded at 120 s and the whole preparation at 420 s.
* **FFmpeg dependence.** The commands use `-fps_mode`, so FFmpeg 5.1 or newer is needed; an older build fails with a typed `ffmpeg_failed` message and nothing is kept. The plan and the verification are FFmpeg-version independent in outcome (a differing build fails the frame check instead of producing different frames), but byte-identical files across runs were shown for one build (9.0.1) only.
* **Prepared files accumulate** under the output folder (same as `prepared_video_sources`); queued jobs reference them, so no pruning was added.
* **Rate conversion is nearest-frame**, not blended or motion-compensated, and is refused for suspected variable-frame-rate clips.
* The submit action still hashes the original and the prepared clip on the Tk thread, exactly like the existing driving-video freeze; decoding, FFmpeg and preview work are all on workers.
* `-format_whitelist` (mp4/mov/matroska/webm) limits the new passes only; the PR-VID-196 inspector keeps its own protocol whitelist and extension-agnostic demuxer choice.

## 9. Controller Surface Assessment

`VideoWorkflowController` is not a ratcheted controller (new-controller limit 600 lines) and stays below the PR-VID-194 guard of 260 lines: 257 to 259 (+1 import, +1 delegate net of one removed helper). It builds no payload and owns no preparation logic; `AppController` (ceiling 7421) is not touched.

## 10. Token-efficient validation plan

Focused CPU tests first (the four new files plus the PR-VID-194/196/BATCH-200 and tab suites), then `python tools/ci/run_pr_gate.py` once. The optional pinned-source check is run with `STABLENEW_VID196_COMFY_SOURCE=<managed v0.38.0 source>`.
