# Storyboard: a tree of takes (PR-VID-STORY-380, design)

Date: 2026-11-21. Status: **draft, awaiting Rob's approval**. Execution class: **Architectural** (it extends the frozen
sequence-plan contract with a new execution policy and adds a top-level GUI workspace).
Evidence base: `origin/main` at `0be26d97`.

Decisions in this record are labelled **[Rob]** (said or chosen by Rob in the design conversation of 2026-11-20/21) or
**[call]** (filled in by the designer and accepted by Rob as a whole with "Looks right", or left to the builder where
marked **[builder]**).

**Model recommendation:** Claude Code Opus 5.5 High (Codex: GPT-6 Astra High); a contract change to a frozen execution
plan plus a new workspace is "material architecture" in `docs/AI_MODEL_SELECTION.md`. Expected usage for both PRs: about
25M cache-read, 250k output.

## 1. Intent

Rob wants to grow a scene out of short generated clips and keep control at every junction. Today a clip is about 5 s
(Wan2.2 I2V-A14B: 81 frames at 16 fps). He wants to:

- pick any finished clip and choose the exact **handoff frame** with a slider, not necessarily the last frame (the last
  frames often carry an artifact) **[Rob]**;
- fan out **1-6 alternative continuations** from that frame at once (**parallel**), each with its own positive and
  negative prompt, each **stitched onto the original** so that the handoff frame and the new clip's first frame occupy
  the same frame **[Rob]**;
- look at every result in a storyboard and mark the best one or ones as candidates for more work **[Rob]**;
- or chain 1-6 continuations one after another (**sequential**), each starting from the last frame of the one before,
  and get the whole chain stitched together **[Rob]**;
- later, have AI Assist write the parallel prompt variants and break a written scene into 5-10 s shots **[Rob]** (a
  follow-on project, section 10).

Rob's view is that "Storyboard is still not implemented". The existing Storyboard is a linear shot-list form under
Video Workflow > Advanced > Multi-shot sequence that starts from a still image; nothing lets him look at clips, branch,
compare and continue.

## 2. What exists (evidence, `origin/main` 0be26d97)

- **Multi-segment sequence job** (`src/video/sequence_plan.py`, `sequence_admission.py`,
  `src/pipeline/video_sequence_executor.py`, `sequence_ledger.py`, `sequence_assembly.py`, `sequence_resume.py`): one
  NJR, one queue row, 1-12 segments (`MIN_SEQUENCE_SEGMENTS = 1`), at most 972 generated frames. Segment 0 starts from
  the job's frozen source image (`ANCHOR_SOURCE`); later segments carry the exact last frame as a hashed PNG
  (`ANCHOR_CARRY`, overlap 1 drops the re-rendered anchor) or use an authored image (`ANCHOR_PROVIDED`, overlap 0).
  The ledger records every segment's frames as `FileRecord` (path + SHA-256). Assembly runs inside the job through the
  ASM-332 engine (`MODE_SEQUENCE`, every image one frame, every frame re-hashed, up to `MAX_SEQUENCE_FRAMES = 10_000`).
  Resume is a new NJR that verifies and copies the completed prefix; full replay recomputes every segment.
- The plan is strict and versioned: unknown keys are refused, `validate()` requires
  `policy_version == "stablenew.video_sequence_policy.v1"`, segment 0 must use `ANCHOR_SOURCE` and may not overlap, and
  the plan carries its own canonical `plan_digest` over its content. `plan_origin` and `continuity` are free provenance
  mappings carried unchanged.
- **Workflow eligibility** for sequences is criteria-based (`workflow_segment_errors`): approved (or experimental with
  the job's opt-in) Comfy workflows that need only inputs a sequence supplies, declare no operator controls, have a
  frame-count policy and share one fps and source-preparation policy. Physical sequence runs exist only for TI2V-5B
  1.3.0 (2026-10-22); A14B in a sequence is unrun.
- **Linear Storyboard drafts** (`src/video/storyboard.py`, `storyboard_store.py`): JSON under
  `%LOCALAPPDATA%/StableNew/storyboards/`, atomic writes, revision compare-and-swap, an exclusive `.lock`, 2 MB cap,
  malformed files preserved. This record reuses that persistence pattern, not that schema.
- **Multi-source batch** (`src/video/video_workflow_batch.py`): N independent video jobs frozen and admitted with one
  `JobService.submit_njrs` call, all-or-none.
- **In-app preview** (`src/video/review_preview.py`): FFmpeg-decoded, at most 120 frames and 256 px. Too small to scrub a
  multi-shot cut frame by frame.
- **Comparison window** (`src/gui/views/video_experiment_review_window.py`): side-by-side synchronized playback of the
  arms of a Video Workflow experiment, with ratings saved as Learning evidence.
- **AI Assist** (`docs/Subsystems/AiAssist/AI_ASSIST.md`): offline, CPU-only, nothing installed or qualified, refuses
  while a generation runs. Its suggestion kinds are closed; none covers video prompt variants or scene breakdowns.
- Handoffs: Job History and Recent outputs route clips through `src/gui/controllers/video_workspace_handoff.py`.

## 3. Goals

1. A top-level **Storyboard** tab that shows a tree of takes as shot columns, plays any take's stitched cut, and lets
   the operator choose a handoff frame anywhere in that cut.
2. **Parallel continue:** 1-6 rows (positive, negative, seed) from one handoff frame become 1-6 queued jobs, admitted
   all-or-none. Each finished job yields the new clip and a real stitched-cut file.
3. **Sequential continue:** 1-6 rows from one handoff frame become one queued job whose segments chain by exact last
   frame; it yields one stitched cut for the whole chain and one take per row.
4. Frame-exact joins: the handoff frame appears exactly once in every stitched cut; every frame in a cut is identified
   by SHA-256 and verified before it is encoded.
5. Storyboards are saved by name, survive restart, and recover takes that were queued but not yet recorded.
6. Existing jobs, plans, ledgers, Storyboard drafts and History replay behave exactly as before.

## 4. Non-goals and anti-goals

Non-goals for this package:

- Any AI feature (the **Write with AI…** button is present but disabled with a reason) [Rob, order agreed].
- Raising the 12-segment / 972-frame per-job cap. A scene longer than one job is built by continuing again; the lead-in
  is not generated, so it does not count against the cap.
- Videos made outside StableNew as a root [call]; native SVD roots or takes (no prompt to vary) [call].
- Changing, retiring or migrating the Multi-shot sequence section or its Storyboard drafts [call].
- Deleting takes or files. Drop only hides [call].
- Keep/Drop as Learning evidence; ratings in the comparison view [call].
- RIFE smoothing of takes or stitched cuts [Rob].
- Selective rerender inside an existing chain (the STORYBOARDS.md suffix-regeneration proposal stays separate).
- A physical GPU run inside the PRs (section 12).

Anti-goals (would make this a failure even if it works):

- A take whose stitched cut repeats or skips the handoff frame, or silently uses a changed or substituted frame.
- Any queue watcher that submits a follow-up job when another finishes. That would be a second scheduler.
- GUI code that builds payloads, touches the repository or calls the runner.
- A stored job, plan digest or ledger from before this change that loads, replays or resumes differently.
- Copying every ancestor frame into every take's folder (a deep tree would use gigabytes).

## 5. Constraints

The canonical path is unchanged: `Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr
-> Handler -> Artifacts/History`. Each take batch crosses `JobService.submit_njrs` exactly once. The storyboard file is
authoring state only: it never holds lifecycle or results, and it never becomes an executable plan. It records job ids
and reads status and outputs back from the repository. Ratchets apply (strict mypy for new modules, formatting, no new
blind excepts, no raw or daemon threads, writes through `src/utils/atomic_io.py`, controller line ceilings). The GUI
stays non-blocking: file hashing, frame loading and admission run on registered workers and marshal back through the
existing dispatcher.

## 6. Approaches

1. **Stitch inside each take's job (chosen by Rob).** The sequence plan gains an optional *lead-in*: the parent cut's
   frames up to and including the handoff frame, referenced by a hash-pinned cut manifest. The job generates from the
   handoff frame, drops its own first frame, prepends the lead-in and encodes the stitched cut with the existing in-job
   assembly. Parallel = N one-segment jobs in one submit; sequential = one job with N segments. Gains: every take is a
   real stitched file; sequential reuses the same job; carry-forward, hashing, ledger, resume and assembly are reused.
   Costs: a new plan execution policy (old plans untouched); one stitched MP4 per take (tens of MB for a 60 s cut).
2. **Plain jobs, stitch on export.** Each take is an ordinary single-clip job from the extracted frame; the storyboard
   plays parent and child back to back; a Movie Clips job encodes a cut on export. Rejected: no real stitched file per
   take, Movie Clips has no per-clip trim, back-to-back playback is not frame-exact at the join, and sequential mode
   cannot start from a clip.
3. **Submit sequential takes one at a time as the previous finishes.** Ruled out: the next job's input does not exist
   at submit time, so a component would have to watch the queue and submit follow-ups, a second scheduler forbidden by
   `AGENTS.md` section 2. One job running its segments in order gives the same result.

## 7. Design

### 7.1 Concepts

- **Storyboard:** a named, saved tree. Its **root** is a finished StableNew clip or a still image.
- **Take:** a node below the root, produced by one segment of one queued job. Takes from one parallel batch are
  siblings; takes from one sequential run are a chain.
- **Cut:** the stitched frames from the root to a take, in order. Every node (the root included) has exactly one cut,
  described by a **cut manifest**.
- **Handoff frame:** the frame of a cut that a continuation starts from. It is chosen on the cut's timeline. The take
  that *owns* that frame (the node whose frame range contains it) becomes the parent. Choosing a frame inside an earlier
  shot therefore branches from that earlier take [call].
- **Lead-in:** the first `K` frames of the parent cut (frames `0 … K-1`, the handoff frame being `K-1`), prepended to a
  new take's cut.

### 7.2 The Storyboard tab [Rob: layout B, "shot columns"; details: call, accepted]

```
[Storyboard]  Diner arrest · saved              [New from clip or image…] [Open…] [☐ Show dropped (1)] [Export cut…]
 Shot 1          Shot 2 · from A @ f78        Shot 3 · from A1 @ f80       Shot 4
 [A enters]      [A1 ★ orders]  ★ ✕           [A1a sits]     ★ ✕           [continue A1b ↓]
                 [A3 ★ menu]    ★ ✕           [A1b ★ bite]   ★ ✕   ← selected
                 [A4 rendering…]
                 [Compare these side by side]
 ┌ A1b · cut A → A1 → A1b · 14.6 s ──────────┐ ┌ Continue A1b from its frame 78 ───────────────────────────┐
 │  viewer                                   │ │ (•) Parallel ( ) Sequential      [Write with AI…] (off)   │
 │  [══A══|══A1══|══A1b══●]  ticks = joins    │ │  #  Positive              Negative          Seed          │
 │  ◀ ▶ frame 226/234 · A1b frame 78 of 81   │ │  1  sirens outside, …     blur, extra limbs  random        │
 │                [Continue from this frame] │ │  + Add row (up to 6)                                       │
 └───────────────────────────────────────────┘ │ Engine: Wan2.2 I2V-A14B · 832×480 · 81 f · 16 fps (inherited)│
                                               │                               [Preview] [Queue 3 takes]   │
                                               └────────────────────────────────────────────────────────────┘
```

- A new top-level tab, beside Video Workflow and Movie Clips [call]. The Video Workflow tab is already crowded, and a
  storyboard wall needs width.
- **Entry points** [call]: **New from clip or image…** in the tab, and **Continue in Storyboard** for a finished
  StableNew clip in Recent outputs, Job History (button and context menu) and the Make Video result. Routed through
  `video_workspace_handoff.py`.
- **Columns:** one column per depth. A column header names the parent and handoff frame ("from A @ f78", 1-based).
  Cards show a thumbnail, label, a prompt excerpt, Keep ★ / Drop ✕ toggles and status from the repository (queued,
  running "segment 2 of 4", completed, failed, cancelled). The selected take and its ancestors are highlighted. Columns
  scroll sideways when deep.
- **Viewer:** plays the selected node's cut at its fps. The slider spans the whole cut, with ticks at every join. While
  paused it shows the exact frame. The readout gives the cut position and the owning take's own frame. ◀ ▶ step one
  frame. **Continue from this frame** fills the Continue panel. Frames come from the cut manifest's PNGs, downscaled on a
  worker with a bounded cache, not from the 120-frame FFmpeg preview [call].
- **Continue panel:** a Parallel/Sequential switch, 1-6 rows (positive, negative, seed: blank or `random` draws at
  admission, an integer is used as given). The engine line shows the inherited workflow, version, size, frame count and
  fps, read-only [call: stitching needs identical size and fps]. **Preview** shows the frozen summary (lead-in length,
  segments, seeds intent, total cut length, workflow) and submits nothing. **Queue N takes** (parallel) or **Queue chain
  of N** (sequential) admits.
- **Keep ★ / Drop ✕** are marks in the storyboard file. A dropped take is hidden until **Show dropped**. Any take can be
  continued, kept or not. No file is moved or deleted [call].
- **Compare these side by side** plays the siblings' own new clips (not their whole cuts, so the 120-frame preview limit
  holds) in synchronized playback, with no rating or evidence save. Either a compare-only mode of the existing window or
  a small new view built on its `ComparisonClock` and preview decode [builder].
- **Export cut…** for the selected take: Reveal the stitched MP4, or Send to Movie Clips through the existing handoff.
  Nothing is re-encoded, because the file already exists [call].
- **Write with AI…** is visible and disabled, with the reason "AI Assist is not set up" (or the readiness record's own
  reason) [call].

### 7.3 Starting a storyboard (root preparation) [call]

- **Root from a clip:** a completed StableNew Comfy video job chosen by job id. If it is a sequence job, its cut
  manifest is derived from its ledger (frames after overlap trim, or the colour-matched copies when it used colour
  matching: exactly the frames it encoded). If it is a single frames-out job, the manifest references its saved PNG
  frames, cross-checked against the backend's per-frame hashes, without copying. If it is encoded only (TI2V-5B
  1.2.0), its frames are decoded once with the bounded, cancellable `decode_clip_to_frames` path into
  `<output root>/storyboards/<storyboard_id>/root/`, and the manifest records basis `decoded`. The root inherits the
  job's frozen workflow identity and settings, except smoothing.
- **Smoothed clips** [Rob, 2026-11-21: "Real 16 fps frames"]: Make Video turns RIFE smoothing on by default when RIFE
  is installed, so many A14B clips play at 32 fps with in-between frames that RIFE invented. A smoothed clip is accepted
  as a root, but the storyboard uses only its **generated frames at the workflow's own fps** (16 for A14B). The backend
  keeps them: for frames-out jobs `frame_paths` and the unsmoothed MP4 stay in the outputs beside the smoothed primary
  (`src/video/comfy_workflow_backend.py` lines 707-737). For an encoded-only job, the decode reads Comfy's own unsmoothed
  file, never the smoothed primary. The slider therefore lands only on real frames, and every take, cut and stitched
  MP4 is at the workflow's fps. The `interpolation` setting is not inherited by takes, so sequences keep refusing RIFE
  as today. When the root was smoothed, the tab shows one line, for an A14B clip: "This clip was smoothed to 32 fps. The storyboard uses
  its 81 generated frames at 16 fps." Smoothing a chosen cut is a follow-on (section 10).
- **Root from a still image:** the operator picks an approved prompt-directed workflow and its settings once (the same
  choices as the Make Video settings line). The first takes have no lead-in.
- Refused with a reason: a non-StableNew video, a native SVD job, a workflow that `workflow_segment_errors` rejects
  (driving video, operator controls, unapproved without opt-in), a job whose frames are missing or fail their hashes,
  a smoothed job whose generated frames or unsmoothed file are gone (only the smoothed MP4 is left).
- Preparation runs on a background worker and publishes nothing durable until it succeeds.

### 7.4 The cut manifest [call; exact field names: builder]

A new artifact, schema `stablenew.storyboard_cut.v1`, written atomically with its SHA-256 recorded by whoever writes it
(root preparation, or the take's job): `fps`, `width`, `height`, `frames` (ordered `{path, sha256}`), `ranges` (ordered
`{owner: "root" | <take_id>, start, end}` covering every frame), `basis` per range (`native`, `decoded`), and the
writing job id when there is one. Paths are referenced, never copied. A 2,000-frame manifest is about 400 KB.

The take's job rewrites its manifest **after every committed segment**, beside the ledger write and before the next
segment dispatches [call, settles builder question 2]. So the finished takes of a chain that failed or was cancelled at
a later row, and a take cancelled during assembly, can be viewed and continued from, because the viewer plays PNGs.
Only the stitched MP4 waits for assembly. A take without an MP4 shows "not encoded" and offers Resume.

### 7.5 Admission: from Continue to jobs

- **One storyboard submission service** in `src/controller/` (beside `movie_clips_submission_service.py`), reached from
  the tab through the existing controller composition with at most a delegating line on `AppController` [call]. It:
  1. resolves the parent's cut manifest and verifies its SHA-256, the handoff frame index, and that the handoff PNG's
     hash matches the manifest entry;
  2. builds the form data from the parent's frozen settings (workflow id and exact version, frame count, fps, target
     size, source preparation, the workflow's default negative where a row leaves it blank);
  3. builds one sequence intent per job: **parallel** = N intents with one segment each; **sequential** = one intent
     with N segments chained by `carry_last_frame`;
  4. freezes each through the existing `freeze_sequence_plan` path with the lead-in and the storyboard provenance
     (storyboard id, one take id per segment, parent take id, handoff index);
  5. crosses `JobService.submit_njrs` **once** with all NJRs (all-or-none) and returns the job ids.
- **Crash-safe recording** [call]: before submission the service writes the pending takes (take ids, rows, parent,
  handoff index, no job id) to the storyboard file; after submission it writes the job ids. If the second write fails or
  the app stops in between, opening the storyboard reconciles pending takes against the repository by the storyboard
  provenance stamped in each NJR, without resubmitting (the pattern Learning uses for admitted experiments). The lookup
  must not add a repository table or schema change without an owner decision [builder: a bounded read over jobs newer
  than the pending take].
- Seeds: blank and `random` are drawn once at admission, as today. Parallel rows draw independently [builder: ensure
  sibling seeds differ].

### 7.6 Execution changes (the contract extension)

- **Plan:** a new execution policy, `stablenew.video_sequence_policy.v2`, used only by storyboard takes. It adds an
  optional `lead_in` block (cut manifest path and SHA-256, frame count `K`, the handoff frame `{path, sha256}`, the
  parent take id) and the per-segment take ids. With a lead-in, segment 0 is conditioned on **the exact handoff PNG**,
  the same way a carried anchor is today. Source preparation (`prepare_declared_workflow_source`: RGB conversion,
  LANCZOS cover resize, re-save) is skipped for it, so no substitute file is ever made, and admission refuses a handoff
  PNG that is not exactly the plan's target size [call, settles builder question 3: today `build_sequence_job` sets
  `source` to the prepared copy, `src/controller/video_sequence_controller.py` lines 88 and 116]. Segment 0 has overlap 1
  (its first generated frame re-renders the handoff frame). A v2 take without a lead-in (first takes from a still root)
  uses source preparation as today and still writes a cut manifest.
- **Compatibility:** v1 plans keep their exact `_content()` and therefore their exact `plan_digest`. The `lead_in` key
  must not appear in a v1 plan's content, not even as `null`. A runner that does not know v2 refuses the plan, as today
  for an unknown policy. Golden tests pin the digests of existing v1 fixtures.
- **Admission checks** (refused before an NJR exists): manifest missing, malformed or changed; `K` outside
  `1 … len(frames)`; the handoff entry is not frame `K-1` or its file's hash differs; lead-in frame size not equal to the
  plan's target size; manifest fps not equal to the plan fps; any lead-in frame missing or unhashable [builder: hash
  every lead-in frame at admission, or verify a sample at admission and all of them before assembly; the engine already
  re-hashes everything it encodes].
- **Executor:** segment dispatch is unchanged (segment 0 starts from `source`). In `_assemble_movie`, a v2 plan prepends
  the lead-in frames (verified against the manifest) before the segments' kept frames. Segment 0's overlap trim then
  drops its first frame, so the handoff frame appears once. After assembly it writes the take's cut manifest: the
  lead-in's ranges copied from the parent manifest and truncated at `K`, then one range per segment labelled with its
  take id. It records the manifest path and SHA-256 in the ledger and in `sequence_artifact`.
- **Assembly is always on** for a v2 plan, so every take has a stitched file. Colour matching and RIFE smoothing are off
  for takes in this package (the existing sequence refusal of smoothing stays).
- **Ledger, resume and replay:** the ledger records the lead-in identity. Resume verifies the lead-in again and never
  copies it. Full replay reuses the same lead-in references and refuses if they changed. History's "Create Storyboard
  from Sequence" refuses v2 plans with a precise reason (the linear editor cannot express a lead-in).
- **Outputs:** the job's primary video is the stitched cut, as for sequences today; the segment clips stay listed in
  `sequence_artifact.all_output_paths`.

### 7.7 Reading results back

The tab reads job status, segment progress, outputs and cut-manifest paths from the repository through a read-only
projection keyed by the job ids in the storyboard file (beside `src/video/history_media_projection.py` and
`src/video/sequence_history.py`). A failed or cancelled take offers the existing **Resume Sequence** (chains) and
**Replay Sequence** through the same controller paths History uses. The tab never writes job state.

**Resume and replay identity** [call, settles builder question 1]. Resume and replay copy the frozen plan unchanged
(`src/video/sequence_resume.py`), so their jobs carry the original storyboard and take ids, and Job History can start
them without the tab. Therefore:

- A take holds an ordered list of **attempts** (job ids), not one job id. A **resume** of an attempt (lineage parent is a
  known attempt) is adopted as a new attempt of the same take or takes. The card shows the newest attempt that completed,
  or else the newest attempt.
- A **replay** of a completed attempt produces different pixels (GPU re-runs are not byte-identical), so it is adopted as
  a **new sibling take**: same parent, handoff frame and prompt, a new take id assigned at adoption, labelled "replay of
  A1". The original take is never silently replaced.
- Reconciliation (7.5) adopts any repository job whose NJR names this storyboard, using these rules, whichever surface
  submitted it.

**Export on a middle take of a chain** [call]: there is no MP4 that ends at that take. Export reveals the chain's
stitched file and states the timecode where this take ends.

### 7.8 The storyboard file [call; exact field names: builder]

Schema `stablenew.storyboard-tree.v1`, one JSON per storyboard under `%LOCALAPPDATA%/StableNew/storyboard_trees/`,
reusing `storyboard_store.py`'s rules: atomic write, revision compare-and-swap (a stale save is refused; reopen or Save
As), exclusive `.lock`, 2 MB cap, malformed or future-schema files never rewritten. Contents: id, title, revision,
timestamps; root `{kind: clip | image, job_id?, image path + sha256?, cut_manifest {path, sha256}, workflow identity}`;
takes `[{take_id, parent_id, handoff_index, mode: parallel | sequential, batch_id, chain_position, prompt,
negative_prompt, seed_intent, attempts: [job_id], segment_index, replay_of?, mark: none | kept | dropped, created_at}]`. No status, output path
or executable plan is stored. Actions: New, Open, Rename, Save As. No delete in this package.

### 7.9 Refusals and failure states (all shown inline, nothing queued)

| Situation | Behaviour |
|---|---|
| The root clip was smoothed with RIFE | Accepted; the generated frames are used at the workflow's fps and a one-line note says so (7.3) |
| A smoothed root whose generated frames or unsmoothed file are gone | Refused: "Only the smoothed video is left; its in-between frames were invented, so it cannot be continued exactly" |
| A parent's frames moved, deleted or changed (for example a Review Discard moved them to `output/_archive`) | The take shows "frames missing or changed" with the first bad path; Continue from it is refused; its existing stitched MP4 still plays |
| The inherited workflow is no longer approved | Continue refused with the catalog reason; experimental only with the job's own opt-in, never restored from the file |
| More than 6 rows, or a sequential run over the per-job cap | Refused by row count or by admission's own message |
| An empty positive prompt in a row | Refused naming the row, as admission does for shots |
| Admission fails for any job of a parallel batch | Nothing is queued (all-or-none); pending takes are removed from the file |
| App stops between submission and recording | Reconciled on open (7.5) |
| A take's job fails or is cancelled | The card shows the state; Resume (chains) or Replay offered |
| AI Assist not ready | **Write with AI…** disabled with the readiness reason |

## 8. Owner decisions recorded

- Tree of takes, not a linear timeline [Rob].
- Layout B, shot columns [Rob].
- The eight behaviour proposals in 7.2-7.3 (own tab, saved by name, slider over the whole cut with branching, marks only,
  inherited engine and random seeds, one job per take producing a stitched cut, old section unchanged, AI button
  disabled) [Rob: "Looks right"].
- Approach 1, stitch inside each job, including the v2 execution policy for the sequence plan [Rob]. Approving this
  record is the architecture approval required by `AGENTS.md` section 2.
- Order of the projects: this package first; AI variants and AI scene breakdown later [Rob, not objected].
- Smoothed clips enter as their real generated frames at the workflow's fps; takes and cuts are not smoothed in this
  package, and smoothing a chosen cut is a follow-on [Rob, 2026-11-21: "Real 16 fps frames"].

## 9. Left to the builder

Exact field names and module names; the comparison view's construction; the reconciliation lookup (within the
no-schema-change limit); the lead-in hashing schedule; thumbnail and frame-cache sizes; Tk widget structure for the
columns (canvas or frames) and lazy thumbnail loading; tree size limit inside the 2 MB cap; 0-based storage with 1-based
display; whether the two PRs below merge into one when the diff stays small.

## 10. Follow-on projects (not in this package)

1. **AI parallel variants:** a new AI Assist suggestion kind returning 1-6 `{positive, negative}` pairs for one intent,
   framed with the target workflow's prompting practice; filled into the rows by an explicit operator action.
2. **AI scene breakdown:** a suggestion kind that splits a scene into timed shots (5-10 s) with per-shot prompts, filling
   a sequential run or several runs. A two-minute scene is about 24 shots, over one job's 12-segment cap, so this needs
   either chained continue runs or an owner decision on the cap. Character identity drift over that many handoffs is
   unaddressed today (colour matching only).
3. Retire or rename the Multi-shot sequence section and its "Storyboard" drafts once this tab covers the same ground
   (the shared word "Storyboard" is a known wording overlap until then).
4. Videos from outside StableNew as a root; native SVD takes.
5. **Smooth a chosen cut:** an explicit action that RIFE-smooths a finished take's stitched MP4 as its own queued job
   through the canonical path, leaving the 16 fps cut and its frames as they are [Rob].

## 11. Controller Surface Assessment

New coordination goes in a new submission service module, not in `AppController` or `VideoSequenceControllerMixin`.
`src/controller/app_controller.py` is exactly at its 5,010-line ceiling in `tools/ci/controller_surface_baseline.json`,
so the package adds **zero net lines** to it: the tab reaches the service through the existing composition (the runtime
stack or controller services), or any line added is offset by one removed in the same PR [builder]. No ceiling is
raised. The tab frame stays presentation only; state lives in a Tk-free view contract under
`src/gui/view_contracts/`.

## 12. Delivery, validation and acceptance boundary

**PR A (execution):** v2 plan policy and lead-in, cut manifest writer and reader, root preparation, the storyboard file
store, the submission service with all-or-none parallel admission and crash-safe recording, the History refusal for v2.
**PR B (workspace):** the Storyboard tab, viewer and slider, Continue panel, marks, compare, export, handoff entries,
and reading results back.

Token-efficient validation plan: focused new tests first, then `python tools/ci/run_pr_gate.py` in an isolated worktree
(not the live checkout), then `tests/tools` when new `src` modules are added (the gate misses the tools census).

- Plan: v1 digest goldens unchanged; v2 validation refusals; v1 runner refusing v2.
- Executor with a fake backend: lead-in prepended, handoff frame exactly once, cut-manifest ranges, refusal on a
  changed lead-in frame at admission and before assembly, resume and replay with a lead-in.
- Root preparation: frames-out reference without copying, decoded basis, sequence-job root, each refusal.
- Submission service: all-or-none batch, pending/recorded writes, reconciliation after a simulated stop, seeds.
- Store: compare-and-swap, lock, malformed and future-schema preservation, size cap.
- Tab: Tk-free view-contract tests for selection, ownership of a frame by range, branching from an earlier shot, row
  limits, disabled states; a small number of hidden-desktop Tk tests for wiring.

Acceptance: deterministic tests, the PR gate and CI, and updated living docs. **Not claimed:** any physical GPU run. A14B
in a sequence and A14B stitched continuations have not run on hardware. Rob's first live use (one clip, three parallel
takes, one take continued with a two-row sequential run) is the demonstration, after merge. Nothing here is a
qualification claim.

Docs to update in the PRs: `docs/Subsystems/Video/VIDEO_PIPELINE.md` section 7.1 (v2 policy, lead-in, cut manifest), a
Storyboard tab section in `docs/Subsystems/Video/STORYBOARDS.md`, the `docs/CODEX_MAP.md` row, a regenerated
`docs/CODE_MAP.md`, and the `STATUS.md` video line.

## 13. Risks and unknowns

- **Identity drift** over many handoffs is real and unaddressed. The storyboard makes bad junctions easy to discard;
  it does not prevent drift.
- **A14B in a sequence is physically unrun**; its 1200 s Comfy wait and `--disable-pinned-memory` requirement apply per
  job as today.
- **Disk:** each take writes a stitched MP4 (tens of MB for a minute) on top of its own clip and frames. Lead-ins are
  referenced, not copied.
- **Dependency on parent files:** descendants depend on ancestors' frame files. Moving or archiving them blocks
  continuing (shown, never silent) but does not break already-encoded cuts.
- **Assembly time** grows with cut length, because every take re-encodes its whole cut (CPU, bounded by the engine's
  timeout scaling).
- **Tk performance** with many thumbnail cards; lazy loading is required.
