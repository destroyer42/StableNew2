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

- **Start:** **New from clip or image…** takes a completed StableNew Comfy video job id or a still image plus the workflow.
  A smoothed (RIFE) clip enters as its real generated frames at the workflow's own fps, with a one-line note. Root
  refusals appear in the status line, never as dialogs.
- **Shot columns:** one column per depth; cards show a thumbnail, label, prompt excerpt and the status read back from the
  repository, with Keep and Drop marks (a dropped take is hidden until **Show dropped (N)**; no file is moved or deleted).
- **Viewer:** plays the selected take's whole stitched cut from its frame PNGs, with a slider that has a tick at every
  join, frame stepping, and a readout such as `frame 226 / 234 · A1b frame 78 of 81`. **Continue from this frame**
  can start from any frame; a frame inside an earlier shot branches from the take that owns it.
- **Continue panel:** 1-6 rows (positive, negative, seed). **Parallel** queues one single-clip job per row; **Sequential**
  queues one chained job. The engine line is inherited and read-only. **Preview** submits nothing. A take whose frames are
  missing or changed cannot be continued (its existing stitched MP4 still plays). **Write with AI…** is present and disabled
  with its reason.
- **Compare these side by side** plays the finished siblings' own clips in synchronized playback (no ratings).
  **Export cut…** reveals the stitched MP4 or sends it to Movie Clips; a take without a video says `not encoded` and offers
  Resume; a middle take of a chain names the chain file and the timecode where the take ends. Failed or cancelled cards
  offer **Resume** and **Replay** through the existing sequence controller; a replay becomes a new sibling take.
- **Entry from other tabs:** `route_job_to_storyboard` (`src/gui/controllers/video_workspace_handoff.py`) is in place. The
  **Continue in Storyboard** buttons in Job History, Recent outputs and the Make Video result are **not wired yet**: they
  wait for the Video Workflow layout work (VID-UX-384) to land on `main`, because they touch the same files.

Acceptance boundary: deterministic tests only (Tk-free contract and projection tests, Tk tests with a fake service and real
PNG frames, the gate). **NOT TESTED on hardware:** no GPU run, no A14B stitched continuation, no live use of the tab.
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
