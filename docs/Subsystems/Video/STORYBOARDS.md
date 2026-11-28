# Saving and editing Storyboards

In Video Workflow, expand Advanced → Multi-shot sequence. A Storyboard is editable authoring intent; saving it never queues a job.

1. Choose a source image and workflow in the main form. Add 2–12 shots, each with a motion prompt, native frame length and seed intent.
   Blank prompts inherit the form prompt, so the form's Motion prompt may stay empty when every shot has its own; a shot left without a prompt while the form
   prompt is also empty is refused by shot number (an explicitly empty shot prompt is refused too). Blank shot 1 seed inherits the form seed; later blank seeds and explicit `random` resolve only at admission.
2. Enter a Storyboard title, optional notes and clip name. **Save** creates or revises the draft in `%LOCALAPPDATA%/StableNew/storyboards/`.
   **Save As / Duplicate** creates a new Storyboard ID and independent shot IDs. **Rename** changes the title and saves. There is no library-delete action.
3. **Open** selects saved JSON from that library after restart. **Import JSON** validates an external manifest and saves an independent copy.
   **Export JSON** writes a new JSON file and refuses an existing destination. These files link external media; images/videos are not copied or overwritten.
4. Use **Duplicate Shot**, **Remove**, **Move Up** and **Move Down** to edit the ordered draft. Every shot keeps its label, prompt, native frames, seed
   and authored-anchor path/hash. Shot 1 uses the main source image. If a reordered first shot has a keyframe, clear it or move it back; it is never silently ignored.
5. **Preview Sequence Summary** checks source readiness, reports SHA-256 identity, provided versus carried anchors, legal frames, total native frames,
   approximate duration before overlap trims, workflow/version and incompatible controls. It never freezes random seeds or claims a final executable plan.
   Missing files can stay in a saved draft. A changed source/anchor blocks queueing until **Accept Current Media** explicitly records the current bytes;
   save again to retain that acceptance. The button links existing files and never edits them.
6. Reopened drafts retain their exact workflow version. **Use Selected Workflow** explicitly adopts the version currently selected in the main form.
   Experimental authorization is per job and is never restored from a draft. Fun Control/driving-video workflows remain incompatible with sequences.
7. **Queue Sequence** submits the displayed snapshot/order through existing sequence admission to one immutable NJR and one queue row. Refusals are inline,
   before any submission. Later edits affect only the authoring draft. **Unsaved changes** remains visible until the current draft is saved.

If another session saves first, a revision conflict refuses the stale save; reopen or Save As. Malformed or unknown-schema JSON is never rewritten.
An exclusive `.lock` protects concurrent writers. A crash can leave that lock; an operator must verify no writer remains before removing a stale lock.
No legacy `data/story_plans` or `data/continuity` files are migrated, deleted or rewritten.

In Job History, **Create Storyboard from Sequence** reads the job again from the canonical repository and verifies its frozen typed plan.
It opens a new unsaved draft with original-job/plan provenance, without changing or queueing the original job. Missing/changed source files are shown by Preview.
The editor supports homogeneous Comfy sequence plans with standard overlaps and assembly. It precisely refuses frozen settings it cannot express, including native
SVD model/settings, mixed workflows, differing per-shot negatives or custom assembly/color/overlap. Resume and full Replay retain their existing behavior.

## The Storyboard tab: a tree of takes (PR-VID-STORY-380)

The **Storyboard** tab (Motion group, after Video Workflow) grows a scene from finished clips. It is a different thing from
the linear **Storyboard** drafts above (the Multi-shot sequence form under Video Workflow > Advanced): those start from a
still image and stay exactly as they are; the shared word is a known wording overlap until the tab covers the same ground.

- **From Video Workflow (V1-6):** **Continue this clip** (Recent outputs, Job History) queues one take from a finished clip's last frame without opening this tab. It extends the Storyboard that holds the clip, or creates one titled *Continued: …*; everything below then applies to it (`docs/Subsystems/Video/VIDEO_PIPELINE.md` section 4).
- **Start (PR-VID-STORY-IMPORT):** **New from clip or image…** opens a non-modal picker with **Browse for video clip…** and
  **Browse for still image…** (no job id is typed). The clip browser is the operating system's file dialog; it opens in the
  output root's `movie_clips` folder (the output root itself, or the home folder, when that is missing), filters `*.mp4` and
  `*.MP4`, and can go to any folder or drive. Cancel changes nothing. The chosen file's full path is in the read-only box
  (hover shows it all); the filename suggests the title until you type your own. Picking only reads and inspects the file
  (on a worker); nothing is created, queued or changed until **Create**.
  - *A clip StableNew made.* The file is matched to its job only by repository evidence: its resolved path is recorded as
    the output of exactly one completed job. A file name or partial path is never used, and two jobs recording the same
    path is reported as ambiguous. That job's verified root preparation is used unchanged: native generated frames (a
    smoothed/RIFE clip enters as its real frames at the workflow's fps, with the one-line note), workflow id/version,
    integrity checks and governance. If it refuses (for example the native frames are gone), the refusal is shown in the
    dialog and **Import the encoded MP4 as media** appears as a separate, explicit choice; it never bypasses the refusal
    on its own.
  - *Any other MP4* (another application's, or one moved out of the output folder). The picker shows filename, resolution,
    frame rate, duration, frame count and that it has no StableNew provenance, and offers only workflows whose declared
    frame rate and size can take it: a blocker (for example too few frames) disables Create with the reason. A needed
    conversion (a centred cover resize to the workflow's size, keeping every Nth frame, relabelling a rate within 0.2 percent)
    is described first and must be ticked before Create; nothing is cropped, stretched or interpolated silently. The root
    is `storyboards/<id>/root/`: the decoded frames (basis `decoded`, never claimed native), `root_cut.json` and
    `import_record.json` (source path and SHA-256, probe facts, conversion parameters, decoder), published atomically from a
    staging folder with every file hash-pinned. The whole clip is the root cut and can be continued from any frame. The tree
    file marks the root `origin: external` with `source_path`, `source_sha256`, and the hashes of the record and manifest;
    there is no job id. Older Storyboard files carry none of these fields and open unchanged. The original MP4 is only
    read. If the file changed between picking and Create, Create is refused. Limits: the existing decoder's 400 frames.
  - Refusals appear inline in the picker, and nothing is partially published. A still image keeps the existing route.
- **Shot columns:** one column per depth; cards show a thumbnail, label, prompt excerpt and the status read back from the
  repository, with Keep and Drop marks (a dropped take is hidden until **Show dropped (N)**; no file is moved or deleted).
- **Thumbnails / Viewer switches:** two independent check boxes (default on), saved as presentation preferences in the
  application's UI state file (`storyboard_media`), not in any Storyboard or job. Thumbnails off: cards are text only, no
  image is loaded, and a load that was in flight cannot bring one back. Viewer off: playback stops, no frame is rendered or
  requested, the Continue panel takes the space, and the slider, frame stepping, the readout (which keeps naming the
  continuation target) and **Continue from this frame** still work. Showing either again keeps the selection, frame, marks and
  target. Neither switch affects integrity checks, Resume/Replay or queued work.
- **Viewer:** plays the selected take's whole stitched cut from its frame PNGs, with a slider that has a tick at every
  join, frame stepping, and a readout such as `frame 226 / 234 · A1b frame 78 of 81`. **Continue from this frame**
  can start from any frame; a frame inside an earlier shot branches from the take that owns it.
- **Continue panel:** 1-6 rows under persistent headers (row number, Positive Prompt, Negative Prompt, Seed, Remove) on one
  grid, so columns stay aligned as rows are added, removed or the window is resized; the two prompt columns take the width.
  A blank negative prompt uses the storyboard's own negative prompt when it has one, else the workflow's default (the hint
  under the rows says which). Seed is **Random** (a seed is drawn when the row is queued; this is the default) or **Fixed**
  (a whole number 0-2147483647, the existing seed contract; anything else is refused inline before anything is submitted).
  Hovering the headers, the seed controls and Parallel/Sequential explains them. **Parallel** queues one single-clip job per row; **Sequential**
  queues one chained job. The engine line is inherited and read-only. **Preview** submits nothing. A take whose frames are
  missing or changed cannot be continued (its existing stitched MP4 still plays). **Write with AI…** is present and disabled
  with its reason.
- **Compare these side by side** plays the finished siblings' own clips in synchronized playback (no ratings).
  **Export cut…** reveals the stitched MP4 or sends it to Movie Clips; a take without a video says `not encoded` and offers
  Resume; a middle take of a chain names the chain file and the timecode where the take ends. Failed or cancelled cards
  offer **Resume** and **Replay** through the existing sequence controller; a replay becomes a new sibling take.
- **Entry from other tabs:** **Continue in Storyboard** opens a finished clip's job in this tab as a new storyboard root. It
  is a button in Job History (also in its context menu, enabled for a completed job with a recorded video) and in the
  Video Workflow tab's Recent outputs list, which is where Make Video results appear (enabled for the selected clip). Both
  call `route_job_to_storyboard` (`src/gui/controllers/video_workspace_handoff.py`), which selects the tab and starts the
  root; nothing is queued. A job the tab cannot root (not a completed Comfy video job, a missing frame) is refused in the
  tab's status line.

Acceptance boundary: deterministic tests only (Tk-free contract and projection tests, Tk tests with a fake service and real
PNG frames, the gate). **On hardware:** only the V1-6 harness run of 2026-11-28 (A14B 1.0.0 continuation takes with stitched cuts, unrated; `docs/work_packages/V1_motion_controls.md` section 15). **NOT TESTED:** live use of the tab.
Rob's first live use is the demonstration: one clip, three parallel takes, then one take continued with a two-row
sequential run. Nothing here is a qualification claim.

## Proposed later contract: verified suffix regeneration

This is a follow-up proposal, not an implemented capability or an authorization to change execution ownership.

Editing any shot and queueing currently creates a new complete sequence. No prior segment or checkpoint is substituted or rewritten.
A future bounded contract would identify the first changed shot, freeze a new NJR/plan and verify all reused prefix evidence against the parent ledger,
including original plan digest, content hashes, exact boundaries and parent lineage. It must explicitly record reuse in the new job's own ledger.
With a carried anchor, every descendant depends on its preceding final frame and must be regenerated after an ancestor changes.
An independently authored image anchor could establish a new conditioning boundary only after its identity and all suffix inputs are verified; being a
provided anchor alone cannot prove outputs reusable. The existing strict resume contract is not an editor for a changed plan.
Checkpoint ownership, `JobRepository`, `JobService.submit_njrs` and `PipelineRunner.run_njr` remain authoritative. Product/architecture approval and
deterministic refusal tests must precede any such implementation.
