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
- **Mocap or animation files (FBX, BVH, AMC).** These are not accepted. Render a reference video from them first, for example in
  Blender: import the file, add a camera, set the frame range and output FPS, render to FFmpeg video (H.264 in MP4), then
  import the rendered clip and set *Source* to the rendered-mocap category and the original file's license in the notes.
  Pose-driven workflows consume video, so no format conversion is done inside StableNew.
- **StableNew-generated clips.** Use *Add to Motion Library* on a finished clip; the job and artifact identity are kept.

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

Tests: `tests/video/test_pr_vid_motion_lib_353_catalog.py`, `..._handoff.py`, `tests/gui_v2/test_pr_vid_motion_lib_353_panel.py`
(temp directories, a fake inspector, real Tk, a KB-sized clip from CPU-only FFmpeg where a real probe is needed and skipped
without FFmpeg; no runtime, model, GPU or network).
