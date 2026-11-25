# Motion Library (PR-VID-MOTION-LIB-353)

A local catalog of motion-reference videos for the Video Workflow tab: import, tag, search, preview, and hand one clip to the
driving-video field. It is a convenience for finding a clip, not a new execution path. Choosing a clip queues nothing; the
operator still previews and submits the job through the normal admission path (`docs/Subsystems/Video/VIDEO_PIPELINE.md` 5.2).

**What this is not.** It is not evidence that any motion transfers well. A catalogued clip says what the operator recorded about
it; whether a workflow can use it is decided by that workflow's own checks, and generation quality is a separate, still
unproven question (Wan-Animate-2 is experimental; see `VIDEO_PIPELINE.md` section 6).

## 1. Operator workflow

1. **Choose the library folder** (Video Workflow tab, Motion Library, *Choose library folder...*). It must be an absolute folder
   outside any Git working tree. Nothing is created until you pick one; the pointer is remembered in
   `%LOCALAPPDATA%\StableNew\motion_library.json`, never in the repository or `presets/`.
2. **Import** with *Import video...* (one file), *Import folder...* (the files directly inside one folder, at most 200, not
   recursive), or **Add to Motion Library** on a finished clip under Recent outputs (keeps the originating job and artifact).
3. **Find** a clip: text search plus filters for tags, source, subject count / human, framing, viewpoint or camera movement,
   intensity, loop suitability, reviewed, visual quality, harvested-only, cadence, "requested motion achieved" and a duration or
   frame range. Rows show a thumbnail, name, length, source and review.
4. **Preview**: selecting a row opens a bounded preview (playback, start / middle / end frames, original fps and size,
   provenance, notes) using the shared Media Inspector, so the content-visibility (SFW / NSFW) policy applies unchanged.
5. **Harvest Motion...** (section 7) cuts the exact frames you want out of a clip, or out of any video, into a new reusable clip.
6. **Use as Driving Video** fills the form's driving-video field and nothing else. Then use *Prepare Motion Source* if you want
   a trimmed or retimed window, preview the job, and queue it yourself.

Every action above is explicit. Importing, tagging, searching and previewing never queue a job, start a runtime, use the GPU,
make an HTTP request or download anything.

## 2. Storage and safety

- **Layout.** `<root>/library.json` (versioned manifest), `<root>/managed/` (content-addressed copies, only when you ask for
  one), `<root>/thumbs/`. It is separate from the job repository and the model registry and decides nothing about what runs.
- **Atomic writes.** Every manifest update is a complete atomic write; a failed write leaves the previous file and the previous
  in-memory state. A corrupt or newer-than-supported manifest is refused and left untouched. Records this version cannot parse
  are kept verbatim and written back.
- **Linked or managed.** *Linked* (default) records the original's path and never touches it. Ticking *Copy into library* makes a
  managed copy staged as `*.partial`, published only after its bytes hash to the expected SHA-256. An interrupted import leaves
  at most a stale `.partial`, which the next open removes; a published copy with no manifest entry is reported, not deleted.
- **Dedup.** A file whose SHA-256 is already catalogued is not added twice; its path is kept on the existing record as an alias
  (bounded). Hashing is chunked and cancellable; a video is never read into memory.
- **Never destructive.** Originals are only opened for reading. The library does not move, rename or delete a user file.
- **Changed or missing files.** Browsing uses a one-`stat` check (present / missing / "timestamp moved"). Selecting a clip for a
  job re-hashes it. A mismatch is *changed* and is never accepted as the original; a moved or renamed file is restored with
  *Relink file...*, which accepts a candidate only if it hashes to the recorded SHA-256 (otherwise import it as a new clip).
  The previous location stays as an alias.
- **Not supported yet.** Removing a clip from the catalog, editing the hash, and bulk re-verification. Hand-edit nothing in
  `library.json`; use *Edit details* for annotations.

## 3. What the handoff verifies

On *Use as Driving Video* the session re-hashes the file and checks the **selected workflow**'s declared contract: it must accept
a driving video, and the clip's fps and frame count are compared with what that workflow consumes. A refusal names the workflow;
the library never picks another one. Advisories (for example "shorter than the shortest length offered") are display-only.
Only the driving-video field is filled. The clip's identity (`asset_id` + SHA-256) rides with the form as
`motion_library_asset` and is included on a submission only while the field still holds that path. Changing the field, the
workflow or the clip invalidates the binding and any earlier preview; a stale binding fails closed.

At admission `VideoWorkflowNjrBuilder` freezes `{path, sha256}` of the driving video as before and additionally checks that the
binding's hash equals the **original** clip's hash (the prepared clip's hash when Prepare Motion Source is used, which remains
authoritative for what is consumed). A mismatch refuses the job. The identity is recorded under
`extra_metadata["video_workflow"]["motion_library_asset"]`; it is provenance, not an input to generation.

## 4. Importing from outside StableNew

The library accepts **rendered video files only** (`.mp4 .webm .mov .mkv`). There is no scraping and no downloader.

- **Owner-recorded, stock or other source.** Obtain the clip yourself under terms you are entitled to use, save it locally,
  import it, and fill *Source*, *Source reference*, *Source URL (text only)* and *Usage terms* in Edit details. The URL is a note; it is
  never fetched. Do not commit third-party media to Git.
- **Mocap or animation files (FBX, BVH).** The library itself still accepts rendered video only. **Convert Motion**
  (PR-VID-MOTION-354, section 4.1) renders such a file to an MP4 with a Blender you installed yourself, then adds the result to
  this library with its derivation recorded. ASF/AMC are reported as unsupported. You can still render a reference video yourself
  in any tool and import it as above; set *Source* to the rendered-mocap category and note the original file's license.
- **StableNew-generated clips.** Use *Add to Motion Library* on a finished clip; the job and artifact identity are kept.

### 4.1 Convert Motion (Blender, CPU only)

The **Convert Motion** button in the Motion Library opens a non-modal dialog. Nothing in it queues a job, starts Comfy or uses the
GPU; it runs one contained Blender child per explicit action (bounded time, output and process tree, Cycles on the CPU, scripts
and add-ons disabled, private empty Blender user folders, no network). StableNew never downloads or installs Blender; choose
your own `blender.exe` (4.2 or newer); the dialog verifies only the file you pick (`--version`) and remembers it. (The engine's
`discover_blender` can also search `STABLENEW_BLENDER`, `PATH` and Program Files, but no button calls it yet.)

- **Supported sources.** FBX with mesh and animation (rendered as that character); animation-only FBX with a known rig (Mixamo,
  Rokoko) rendered as a skeleton, or onto a reference character only when every needed bone name matches exactly (no guessing,
  renaming or automated retargeting, otherwise refused with the reason); BVH as a skeleton render. FBX/BVH are scanned by header
  only before anything is imported.
- **Profiles.** Character reference, high-contrast silhouette, skeleton reference (a skeleton view, *not* an OpenPose map).
  Cameras: front, side, three-quarter; static by default, optional tracking; root motion is preserved unless you opt out.
- **Output.** 24 FPS, exact frame count and geometry verified before publication, no audio, no silent trim, pad or speed change
  (the length follows the selected workflow's own legal lengths). A frozen plan with a canonical digest is shown first.
- **Provenance and reuse.** Each result is a folder (`<library>/conversions/converted/...`) holding the MP4 and `provenance.json`
  (source SHA-256, derivative SHA-256, Blender version, script version, rig, window, FPS, transform, camera, geometry, warnings),
  published atomically. A verified identical result is reused instead of re-rendered. *Add to Motion Library* imports it with a
  derivation record that keeps the original file's identity apart from the derivative's; derivation text is searchable and
  survives restart. Previews and unverified folders cannot be added.
- **Existing MP4s** need no conversion and are never re-encoded: import them as in section 1. The Motion Library panel's **Preview Conditioning...**
  button shows the same advisory preview for any usable selected clip, and the conversion dialog offers it for a result.
- **Preview Conditioning** is an advisory CPU Canny preview (first/middle/last frames) of what a Fun Control graph would see,
  centre-cropped to the generation shape like the pinned node. It is labeled *approximate* (not verified against the node's
  source or recorded vectors), shows bounded heuristic warnings, calls no Comfy and changes no job.

### 4.2 Batch Convert Motion and failure diagnostics (PR-VID-MOTION-356)

**Batch Convert Motion...** converts a folder of FBX/BVH files one at a time through the same contained CPU Blender path, as an
offline asset operation: it creates no NJR, queue entry or job and starts no GPU, model or Comfy. It scans recursively within bounds
(5,000 files, 8 levels, 256 MiB each; links not followed), shows a dry-run inventory (to convert, already converted, duplicates,
not eligible with reasons, ZIP files that need extraction by the operator, videos to import) with a storage range, and requires
an explicit confirmation of file count, destination and disk budget. A three-file sample can run first. Outputs go only under
`<library>/conversions/converted`, are published atomically, are registered in this library (tagged `batch-converted`) and are
skipped when a verified identical result exists. Originals are never modified, no result overwrites different bytes, and nothing is
retried automatically. Cancellation stops the Blender process tree and the remaining files; a summary report is written under
`<library>/conversions/batch-reports`.

Failed conversions are classified (asset, rig, renderer capability, crash, memory, timeout, output verification, encode, launch,
changed input, storage, refused plan) and reported in the dialog with Copy report / Open report folder. Reports are redacted,
bounded (25 files, 4 MiB) and live in a per-user folder outside the repository. The original "exit code 1" on long clips was
Blender's per-frame progress output exceeding the captured-output cap and the process layer killing the child; that output is now
kept as a bounded tail.

Operator procedure: `docs/runbooks/motion_conversion.md`. Design record and limits: `PR-VID-MOTION-354_Motion_Conversion_and_Fun_Qualification.md`.

## 5. Limits and cost

- Folder import stops after 200 files; names are capped at 120 characters, notes at 2000, tags at 40 of 40 characters, aliases at
  50 per clip, and the manifest at 64 MiB.
- Filtering is in memory and never opens a video. Hashing, inspection and decoding run on bounded workers owned by the existing
  thread registry; a newer request cancels and supersedes an older one, and results that arrive stale are dropped.
- Preview frames are small bounded stills from the existing decoder; no custom player and no new subprocess manager.

## 6. Where the code is

| Concern | Module |
|---|---|
| Records, vocabulary | `src/video/motion_library/models.py` |
| Manifest, recovery, managed copies | `src/video/motion_library/store.py` |
| Import (file, folder, History clip) | `src/video/motion_library/importer.py` |
| Verification, relink, hashing | `verification.py`, `relink.py`, `hashing.py` |
| Search, snapshot | `search.py`, `snapshot.py` |
| Handoff decision | `handoff.py` |
| Library root pointer | `config.py` |
| Controller commands | `src/controller/video_motion_library_controller.py` (mixin on `VideoWorkflowController`) |
| Toolkit-neutral session | `src/gui/view_contracts/motion_library_contract.py` |
| Tk browser | `src/gui/views/video_workflow_motion_library_panel_v2.py` |
| Derivation record (PR-VID-MOTION-354) | `src/video/motion_library/derivation.py` |
| Conversion engine (scan, plan, Blender child, publication, archive extraction, conditioning preview) | `src/video/motion_conversion/` |
| Convert Motion session / dialog / controller seam | `src/gui/view_contracts/motion_conversion_contract.py`, `src/gui/views/motion_conversion_dialog.py`, `src/controller/video_motion_conversion_controller.py` |
| Batch conversion, failure diagnostics | `src/video/motion_conversion/batch.py`, `diagnostics.py`, `src/gui/view_contracts/motion_batch_contract.py`, `src/gui/views/motion_batch_dialog.py` |
| Read-only asset inventory | `tools/motion_asset_inventory.py` |
| Harvested motion assets (PR-VID-MOTION-400) | section 7.9 |

Tests: `tests/video/test_pr_vid_motion_354_*.py`, `tests/controller/test_pr_vid_motion_354_conversion_controller.py`,
`tests/gui_v2/test_pr_vid_motion_354_convert_dialog.py`, `tests/video/test_pr_vid_motion_356_*.py`, `tests/gui_v2/test_pr_vid_motion_356_batch_dialog.py` (a fake Blender that obeys the real command-line contract; no Blender is
needed), and `tests/video/test_pr_vid_motion_lib_353_catalog.py`, `..._handoff.py`, `tests/gui_v2/test_pr_vid_motion_lib_353_panel.py`
(temp directories, a fake inspector, real Tk, a KB-sized clip from CPU-only FFmpeg where a real probe is needed and skipped
without FFmpeg; no runtime, model, GPU or network).

### 6.1 Suitability versus demonstrated transfer (PR-VID-MOTION-410)

An asset's **Good for motion driving** flag, motion label, "motion achieved" and reuse notes are the operator's statements about a clip; they are never evidence that the motion transfers. What happened when a clip drove another subject is recorded only by an eval run (`docs/runbooks/video_eval_kit.md` section 9): the asset id and SHA-256 travel in the case, and the report's per-asset summary counts attempts, completions, rated results, action achievement, subject attachment, critical identity breaks, distinct source subjects and seeds, each with its denominator. Nothing aggregates those results back into the library: an operator-selected flag and observed outcomes stay separate, a missing review is not a failure, and no flag, rank or recommendation changes automatically. Automated recommendation belongs to a later roadmap phase.

## 7. Harvested motion assets (PR-VID-MOTION-400)

**Harvest Motion** cuts the part of an existing video that contains the movement you want into a new, reusable Motion Library
clip. It is an offline asset operation: it builds no NJR, queues nothing, starts no runtime and uses no GPU. The roadmap is
`docs/Subsystems/Video/CONTROLLED_MOTION_ROADMAP.md`; the operator procedure is `docs/runbooks/motion_harvesting.md`.

### 7.1 Three things, three lifecycles

| Thing | What it is | Authority |
|---|---|---|
| **Original source** | The video you started from (a generated clip, a Movie Clips file, a library clip). Read-only; hashed, never rewritten. | Its own bytes. |
| **Harvested motion asset** | A Motion Library clip holding exactly the chosen frames. Workflow-independent: it carries no generation length and no engine. | Its own SHA-256 plus a `HarvestRecord`. |
| **Prepared driving source** | The 210 *Prepare Motion Source* output for one workflow, version and length. | The 210 contract, unchanged. |

A harvested asset is applied through the existing **Use as Driving Video**. Harvesting never changes the selected workflow,
never turns on an experimental opt-in and never weakens a qualification or Fun Control block; whether a workflow can use the
clip is still decided by that workflow's own checks.

### 7.2 The harvest engine

`src/video/motion_library/harvest.py` reuses the 210 preparation engine with a *harvest contract* (the output length is the
window, not a generation length): bounded, cancellable FFmpeg; lossless H.264 (`-qp 0`); per-frame `framemd5` verification of what
was written; rotation metadata preserved; content-addressed atomic publication. The result is copied into `<root>/managed/`
(hash-verified) and cataloged. Staging lives in `<root>/harvest_staging/` and is removed after each run.

- **Windows are frame numbers**, 0-based, `[start, end)` with the end excluded. **Set End after Current** therefore makes the
  current frame the last frame included. Times convert to the nearest frame with exact rational arithmetic
  (`floor(t * rate + 1/2)`), so 24, 30, 60 and 30000/1001 fps never drift.
- **Native cadence is the default**: every selected frame is kept at the source rate. **Convert to 24 fps** is an explicit
  choice that resamples by time (output frame `j` takes source offset `floor(j * rate / 24 + 1/2)`, ties to the later frame) and
  states how many frames were omitted or repeated. Neither changes how fast the motion plays.
- **Nothing is held or padded.** A reusable asset contains only real frames. The workflow timing preview in the workspace is a
  display-only view of what Prepare Motion Source would later do for the selected workflow; it never edits the asset.
- **Refused, with a reason:** variable-frame-rate sources (re-encode them at a constant rate first), an unknown frame rate (use
  frame numbers), an empty or out-of-range window, and a window longer than the bounds in 7.8.
- **Reuse before re-encode.** An identical cut (same original SHA-256, frames and cadence) whose published file still verifies is
  returned as *reused*; no second encode happens. Identical derivative bytes keep one identity (existing dedup) and the outcome
  says which requested details were not applied to the existing asset.
- **Cancellation** stops FFmpeg and publishes nothing; a failed manifest write leaves no orphan copy.

### 7.3 What is recorded

`MotionAsset.harvest` (`HarvestRecord`, `stablenew.motion-harvest.v1`) holds the original's SHA-256, name and last known path;
the exact start and exclusive end frame; cadence; the original's frame rate, count, size and rotation; what was requested
(frames or seconds); the derivative's frames, rate and size; omitted and repeated frames; the frame digest; the tool and method;
warnings; the creation time; and the lineage fields below. The manifest stays at **schema version 1**: every new field is
optional, a manifest written before this change loads unchanged, fields this build does not know are kept and written back, and
a record this build cannot read is kept verbatim in `unparsed` and reported. There is no migration.

A missing original is *shown* ("original not found at the recorded path") and never blocks the derivative: the clip verifies
on its own bytes. The detail pane says so, with the frames, cadence and original name.

### 7.4 Lineage: how much is known about where the video came from

| State | Meaning |
|---|---|
| `verified` | The completed History job names this exact artifact path **and** its recorded SHA-256 equals the file about to be cut. |
| `recorded` | History names this artifact but kept no SHA-256, so the bytes are not independently verified. |
| `path_only` | Only the file's location is known: an imported file, a different artifact of the job, a hash that no longer matches, or a job that was not found or did not complete. |
| `none` | Nothing is claimed. |

A job id is only ever a *claim* made by the surface that opened the workspace; `open_harvest_source` checks it against History.
Identity is never inferred from a file name, a folder, a timestamp or a similar prompt. A harvest from a library clip passes that
clip's lineage on without strengthening it.

### 7.5 The workspace and its entry points

The **Harvest Motion** window is one non-modal window per Video Workflow tab (`motion_harvest_dialog.py`; rules in the
toolkit-neutral `MotionHarvestSession`). It shows the shared bounded player, a frame scrubber with `-10 / -1 / +1 / +10` steps,
the exact first, middle and last frames of the original and of the selected window, numeric start and end (frames or seconds),
**Set Start to Current**, **Set End after Current**, **Reset to full video**, the cadence choice, duration and frame counts, the
advisory workflow timing, an optional side-by-side with the form's source image (orientation check only), the classification form
and **Save as Motion Asset**. Several windows may be saved from one source. All hashing, probing, decoding and FFmpeg work runs on
workers owned by the thread registry; a newer seek, window or source cancels and supersedes the older request, results that
arrive after that or after closing are dropped, and closing the window cancels a running harvest.

Entry points (each hands over one exact file plus a claim, and never submits anything):

| Surface | Handoff |
|---|---|
| Video Workflow, Recent outputs | **Harvest Motion...** on the selected clip; claims the clip's job (verified by History and SHA-256). |
| Job History | **Harvest Motion** (button and menu) on a completed job with a recorded video file; claims the job. |
| Movie Clips | **Harvest Motion...** on one selected video in the clip list; path-based (the list names files, not jobs). |
| Motion Library | **Harvest Motion...** on a verified clip; to start from a video that is not in the library, import it first. |
| Storyboard | **Harvest Motion...** in *Export cut* for an encoded take, through the same guard as *Send to Movie Clips*; path-based (the stitched cut is a derived file). |

*Add to Motion Library* on Recent outputs is unchanged. A video the current content filter hides is neither opened nor previewed
(checked again on every render, so switching the filter blanks previews at once). A missing, unsupported or unreadable file is
refused with a readable reason.

### 7.6 Classification

*Edit details* and the workspace share one field list: name, motion label, direction, subject kind and count, framing,
viewpoint, camera movement, intensity, start and end pose, loop, review status, **visual quality**, **requested motion
achieved** (not judged, yes or no), **good for motion driving**, known defects, reuse conditions, tags, source and usage terms,
and notes. These are **separate operator opinions**. None of them is evidence that the motion transfers to another subject, and
the detail pane says so. Search and filters cover motion label, defects, reuse conditions, the original's name, start and end pose,
cadence, visual quality, harvested-only and achieved-only. There is no AI metadata.

### 7.7 Applying a harvested asset

Use as Driving Video fills the driving-video field exactly as for any clip. The binding `{asset_id, sha256}` is unchanged and a
harvested asset adds an optional, provenance-only `derived_from` (`original_sha256`, `start_frame`, `end_frame`, `cadence`; no path)
recorded under `extra_metadata["video_workflow"]["motion_library_asset"]`. It decides nothing at admission: a swapped or changed
file still fails closed on the asset hash.

### 7.7.1 Alignment derivatives are not library assets (PR-VID-MOTION-420)

A harvested or imported asset is reusable across source images. An **aligned** clip (Align Motion) is a derivative of one asset *for one source image*: it is a prepared driving input under `prepared_driving_videos/`, never a library entry, and it is not added to the library automatically. The asset keeps its identity and bytes; a job that used an alignment records the asset's `{asset_id, sha256}` against the *original* hash and the aligned clip's own hash beside it. The alignment is not stored on the asset, does not change its suitability, annotations or any recommendation, and is never offered for another subject: evidence from one aligned subject says nothing about another until it is shown. The asset's annotations (subject kind and count, framing, viewpoint, camera movement, direction, start pose) are *reported* statements and are shown, as such, in the Align Motion compatibility panel.

### 7.8 Limits

- Lossless derivatives are large; the existing 256 MiB cap on a prepared file applies, so long windows at high resolution are refused.
- Native windows are capped at 2,400 output frames and 20,000 source frames; **Convert to 24 fps** is capped at 90 output frames
  (an FFmpeg expression-length limit, stated in the refusal).
- Frame previews and the scrubber are exact; playback uses the shared bounded preview and may not show the whole video.
- Not in this phase: motion fidelity scoring, subject alignment, alternative conditioning, recipes or learning (roadmap phases 2-8).

### 7.9 Where the code is

| Concern | Module |
|---|---|
| Window and cadence arithmetic | `src/video/motion_library/harvest_window.py` |
| Engine, outcomes, description | `src/video/motion_library/harvest.py` |
| Lineage resolution | `src/video/motion_library/harvest_lineage.py` |
| Source opening, exact frame previews | `src/video/motion_library/harvest_service.py` |
| Advisory workflow timing | `src/video/motion_library/harvest_workflow_preview.py` |
| Toolkit-neutral session | `src/gui/view_contracts/motion_harvest_contract.py` |
| Tk window, window owner | `src/gui/views/motion_harvest_dialog.py`, `src/gui/views/video_workflow_harvest_host.py` |
| Controller seam | `VideoMotionLibraryControllerMixin`: `open_harvest_source`, `preview_harvest_frames`, `harvest_motion_window`, `harvest_workflow_timing` |
| Cross-tab handoff | `route_video_to_motion_harvest` in `src/gui/controllers/video_workspace_handoff.py` |

Tests: `tests/video/test_pr_vid_motion_400_harvest.py` (real FFmpeg: exact frames at 16, 24, 30, 60 and 30000/1001 fps, cadence,
reuse, refusals, cancellation), `tests/video/test_pr_vid_motion_400_lifecycle.py` (manifest compatibility, lineage, search,
driving handoff and submission, controller seam), `tests/gui_v2/test_pr_vid_motion_400_workspace.py` (session, exact previews,
Tk window) and `tests/gui_v2/test_pr_vid_motion_400_handoffs.py` (every entry point, editor, filters). CPU-only FFmpeg clips of a
few KB; no runtime, model, GPU or network.
