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
   intensity, loop suitability, reviewed, and a duration or frame range. Rows show a thumbnail, name, length, source and review.
4. **Preview**: selecting a row opens a bounded preview (playback, start / middle / end frames, original fps and size,
   provenance, notes) using the shared Media Inspector, so the content-visibility (SFW / NSFW) policy applies unchanged.
5. **Use as Driving Video** fills the form's driving-video field and nothing else. Then use *Prepare Motion Source* if you want
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
- **Existing MP4s** need no conversion and are never re-encoded: import them as in section 1. (The dialog's conditioning preview
  is offered for a quick or full conversion result; `ConversionWorkbench.conditioning_preview` also accepts any local MP4, but
  no library-browser button calls it yet.)
- **Preview Conditioning** is an advisory CPU Canny preview (first/middle/last frames) of what a Fun Control graph would see,
  centre-cropped to the generation shape like the pinned node. It is labeled *approximate* (not verified against the node's
  source or recorded vectors), shows bounded heuristic warnings, calls no Comfy and changes no job.

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
| Read-only asset inventory | `tools/motion_asset_inventory.py` |

Tests: `tests/video/test_pr_vid_motion_354_*.py`, `tests/controller/test_pr_vid_motion_354_conversion_controller.py`,
`tests/gui_v2/test_pr_vid_motion_354_convert_dialog.py` (a fake Blender that obeys the real command-line contract; no Blender is
needed), and `tests/video/test_pr_vid_motion_lib_353_catalog.py`, `..._handoff.py`, `tests/gui_v2/test_pr_vid_motion_lib_353_panel.py`
(temp directories, a fake inspector, real Tk, a KB-sized clip from CPU-only FFmpeg where a real probe is needed and skipped
without FFmpeg; no runtime, model, GPU or network).
