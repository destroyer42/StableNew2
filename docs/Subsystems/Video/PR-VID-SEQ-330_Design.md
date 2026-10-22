# PR-VID-SEQ-330 - Repair and wire the sequence layer (design note for owner review)

## Status

**PROPOSED - NOT IMPLEMENTED - NEEDS OWNER APPROVAL BEFORE ANY CODE.** Classification: **Architectural** (it changes how
one video job executes and what replay re-verifies). Authority: roadmap `docs/audits/2026-10-20_video_experience_roadmap.md`
section 4 (Phase D) and owner decision **D7** (2026-10-20: segment chaining may use a frame extracted from the previous
segment of the same job, recorded with its SHA-256 and re-verified on replay). This note does not change D7; it proposes how
to deliver it and asks seven questions (section 8).

## 1. What exists and why it cannot be used (verified in the checkout)

`PipelineRunner._execute_sequence` (`src/pipeline/pipeline_runner.py:574`) runs when a `video_workflow` stage config carries
`sequence_metadata.total_segments > 1`. Nothing in `src` writes that block, so the path is unreachable in production. If it
were reached it would fail in five places:

| # | Defect | Where | Effect |
|---|---|---|---|
| 1 | The carry-forward is the previous segment's **primary output path**, an `.mp4` | `prior_output_path = primary_output`, then `planner.apply_carry_forward` | The next segment's `LoadImage` is handed a video. The "last frame" is never extracted. |
| 2 | Only `prompt` and `negative_prompt` reach a segment | `_execute_video_stage(prompt=..., negative_prompt=...)`; the planner's `segment_length_frames`, `overlap_frames`, `workflow_id` and `extra` are computed and dropped | Per-segment length, seed and workflow are ignored. Every segment is the job's frozen frame count and seed. |
| 3 | Comfy is stopped after **every** segment | `release_owned_runtime_after_job` is applied inside `ComfyWorkflowVideoBackend.execute` | Each segment cold-starts Comfy and reloads 18 GB of weights. |
| 4 | Only `video_workflow` enters the sequence branch | `VideoStageHandler.run` checks `stage.stage_name == "video_workflow"` | Native SVD cannot be chained. |
| 5 | A failed segment loses the sequence | the loop has no durable state between segments | Segment n failing (including a GPU device loss) discards 0..n-1 and a retry starts over. |

Also true today: `SegmentProvenanceRecord.manifest_path` is always `None`, `frame_paths` is never filled, and the
sequence manifest is written only after the last segment. Assembly of the segments is `stitch_video_segments`, a `-c copy`
concat (the Movie Clips engine, PR-VID-ASM-332, is the intended replacement and is already merged).

## 2. Scope of SEQ-330 (and what it leaves to SEQ-331)

In scope: the **runner-side machinery** that makes a multi-segment job correct, durable and resumable, reachable through one
typed, validated intent block. Out of scope: the Storyboard form, keyframe pickers and the "Make video" flow (SEQ-331), the
first-last-frame graph (FLF-322) and the Wan A14B graph (WAN-321). SEQ-330 is testable end to end with the fake Comfy and
fake SVD backends and, once WAN-324 registers, with TI2V-5B frames-out.

## 3. Design

### 3.1 One job, N segment stages (not N jobs)

A sequence stays **one NJR, one queue row, one `run_njr` call**; segments execute inside it. This preserves invariant 1 of
`AGENTS.md` (no second queue, runner or lifecycle authority), keeps the Comfy process warm across segments, and keeps
History/replay a single record. The cost is that cancel and retry granularity is the segment (section 3.6), which the
checkpoint ledger absorbs.

*Rejected:* one NJR per segment, chained by lineage. It makes retry natural but breaks warm-runtime reuse, makes the queue show
N jobs for one movie, and needs a new "this job depends on that one" notion the queue does not have.

### 3.2 A typed intent block, frozen at admission

`sequence_metadata` stops being a free dict. A frozen dataclass `SequencePlan` (in `src/video/sequence_models.py`) is built
by the NJR builder and written into the stage config as plain data, validated at admission, never at run time:

- `segments`: ordered list of `SegmentSpec { frame_count, seed, prompt, negative_prompt, workflow_id, workflow_version,
  anchor: {"policy": "carry_last_frame" | "provided", "image_path", "image_sha256"} , end_anchor (reserved for FLF-322) }`
- `assembly`: the existing assembly request fields (resolved by the ASM-332 engine, not the legacy service)
- `color_match`: `{enabled, reference: "segment0_first_frame"}`
- `max_segments` cap (proposed 12) and a total-frame cap (proposed 12 x 81), refused with a readable message, never clamped.

Seeds are **concrete per segment at admission** (`parse_seed_input`, never generated at run time), so the job replays exactly.
Frame counts are validated against each segment's workflow `frame_count_policy` (4n+1 for Wan). A `provided` anchor is
hashed at admission; replay re-hashes and refuses on mismatch (the same rule the single-clip path already applies to
sources).

### 3.3 The exact last frame is a verified artifact (D7)

After each segment the runner takes the segment's **last frame as a PNG** and records its SHA-256 in the segment ledger:

- frames-out Comfy workflows (WAN-324): the last PNG Comfy saved, already hashed in `frames_out`;
- native SVD: the last **native** frame (before RIFE and loop export), which the SVD runner does not save today; 330A adds one
  lossless PNG write of it (`SVDResult.frame_paths` are the exported, post-RIFE frames and are not the right anchor);
- any other clip: FFmpeg decodes exactly the last frame of the encoded file (fallback, recorded as `basis: "decoded"`,
  because it is not the pre-encode frame).

The next segment's `LoadImage` receives that PNG (a StableNew-owned file in the run directory, content-addressed by its
hash). Defect 1 is fixed by construction: a video path can no longer be an anchor, and the planner refuses it.

Replay: a replay re-runs the whole sequence from the frozen plan, so it re-derives each carried frame; it **verifies** that the
re-derived frame equals the recorded hash where the backend is deterministic and **records a divergence** (not a failure)
where it is not (a GPU re-run is not bit-exact). This matches how the single-clip path treats re-runs today. Resume
(section 3.6) never re-derives: it re-verifies stored hashes only.

### 3.4 Per-segment overrides through one typed seam

`_execute_video_stage` gains one keyword, `stage_config_overrides: Mapping[str, Any] | None`. The runner builds the segment's
stage config as a deep copy of the frozen one with only the segment's own typed fields applied
(`frame_count`, `seed`, `workflow_id`, `workflow_version`, `prompt`, `negative_prompt`, `source_preparation` for its anchor).
The NJR itself is never mutated. Every override key is allow-listed; an unknown key is a planning error. This fixes defect 2
and is the seam FLF-322 (end anchor) and SEQ-331 reuse.

### 3.5 Keep the owned runtime warm, release on every exit path

`ComfyWorkflowVideoBackend.execute` releases the owned runtime inside the call when the spec declares
`release_owned_runtime_after_job`. Add a request flag `hold_runtime_for_sequence: bool` (default false): when true the backend
skips the post-job release and returns; the **runner** performs exactly one release in a `finally` after the last segment,
after a failure, after a cancel and on `BaseException`, through the existing `ComfyProcessManager.stop()` (owned processes
only, same rule as today). The single-clip path is byte-for-byte unchanged. Defect 3 is fixed without adding a lifecycle
authority: ownership stays with the backend's process manager.

### 3.6 Checkpointing, and "retry from segment n" on the canonical path

A durable **sequence ledger** `sequence_state.json` is written atomically (`src/utils/atomic_io`) in the run directory after
every completed segment: plan hash, per segment `{index, status, output paths with SHA-256, last_frame_path, last_frame_sha256,
frame_count, seed}`. It is written before the next segment dispatches, so a loss during segment n leaves 0..n-1 intact.

A failed or device-lost sequence is **resumed by creating a new NJR with parent lineage** (the existing replay mechanism, with
`source.parent_job_id` set) whose stage config carries `sequence_resume = {parent_job_id, from_segment, ledger_sha256}`:

1. `JobService.submit_njrs` admits it like any replay; nothing bypasses the queue.
2. The runner reads the parent's ledger, **re-verifies** every referenced file by SHA-256, copies the small artifacts it needs
   (each completed segment's encoded clip and the carried last frame, not the PNG frame sets) into the new run directory so the
   child never depends on a parent directory that may be pruned, and executes only segments `from_segment` onward.
3. A hash mismatch, a missing file or a different plan hash refuses the resume with a readable reason; it never "repairs".

The GPU-loss quarantine (`PR-QUEUE-GPU-180`) already stops dispatch after a device loss; resume is an explicit operator action
(a "Resume from segment n" button on the History row is SEQ-331 UI; SEQ-330 ships the controller call and tests).

### 3.7 Colour continuity and overlap

- **Colour match** (default on for `carry_last_frame`, off for `provided` anchors, which are authored images): each segment's
  frames are histogram-matched per channel to the **first frame of segment 0** before encoding, so a long chain does not drift in
  tone. Pure NumPy/Pillow, no new dependency, deterministic, recorded in the ledger (`color_match: {reference_sha256, method}`).
- **Overlap**: `overlap_frames` is honoured as "drop the first k frames of segment i>0" (they re-render the anchor frame).
  Default 1 for `carry_last_frame` (the anchor frame itself is the segment's first frame), 0 for `provided`.

### 3.8 Native SVD in sequences

`VideoStageHandler` enters the sequence branch for `svd_native` as well as `video_workflow`, through the same
`_execute_video_stage` seam. SVD's per-segment `frames` and `seed` come from the same typed overrides. SVD's RIFE and loop
export apply per segment before the last frame is taken (the carried frame is the **pre-RIFE** last native frame, so the next
segment is conditioned on a native frame, not an interpolated one).

### 3.9 Assembly

The assembled movie uses the ASM-332 engine (`xfade`, normalisation, queued CPU workload semantics) rather than the legacy
`AssemblyService`/`-c copy` stitch, with transitions off by default for `carry_last_frame` chains (the join is already
continuous) and available for `provided` chains. The legacy `stitch_video_segments` copy path is deleted once nothing calls
it (a named removal condition per `AGENTS.md`).

## 4. Files touched (estimate)

| File | Change |
|---|---|
| `src/video/sequence_models.py`, `sequence_planner.py`, `sequence_manifest.py` | `SequencePlan`/`SegmentSpec`, ledger records, hash fields, planner refuses a video anchor |
| `src/video/sequence_ledger.py` (new) | atomic ledger read/write/verify, resume loader |
| `src/video/sequence_frames.py` (new) | last-frame extraction (frames-out, SVD, decoded) and colour match |
| `src/pipeline/video_sequence_executor.py` (new) | the segment loop moved out of `PipelineRunner` (it must not grow), warm-runtime `finally`, resume |
| `src/pipeline/pipeline_runner.py` | `_execute_video_stage(stage_config_overrides=...)`; `_execute_sequence` becomes a thin call |
| `src/pipeline/run_stage_handlers.py` | sequence branch for `svd_native` |
| `src/video/comfy_workflow_backend.py`, `video_backend_types.py` | `hold_runtime_for_sequence` request flag |
| `src/video/video_workflow_njr_builder.py` | build and validate `SequencePlan` from a typed form block (also used by SEQ-331) |
| `src/controller/video_workflow_controller.py` | `resume_sequence(job_id, from_segment)` (one call, delegates to replay) |
| docs | `VIDEO_PIPELINE.md` sections 8-9, `CODEX_MAP.md`, roadmap 6.2 |

Controller-surface ratchet: the controller gains one small method and must not exceed its ceiling; `PipelineRunner` must not
grow (the executor module absorbs the loop). Both are checked by the existing ratchets.

## 5. Acceptance (each is a test)

1. A plan with a video-file anchor, an unknown override key, an illegal frame count, more than the segment cap or an unhashed
   `provided` anchor is refused before anything is queued.
2. Runner tests with a fake backend prove: a **PNG** (never an `.mp4`) reaches `LoadImage` for segment i>0; per-segment frame
   count, seed and workflow are the values the backend receives; the recorded last-frame SHA-256 equals the file's hash.
3. A fake owned-runtime manager proves Comfy is started once and released **once**, after the last segment, and also after a
   failure, a cancel and a `BaseException`; the single-clip path still releases inside `execute`.
4. A segment that raises leaves a ledger with segments 0..n-1 verified; a resume NJR (parent lineage) runs only n.., refuses a
   tampered file, a missing file and a different plan hash.
5. Colour match is deterministic on synthetic frames and is recorded; it is off for `provided` anchors.
6. `svd_native` takes the same path with a fake SVD runner.
7. Replay of a stored single-clip NJR is unchanged (existing replay tests green); `git diff` shows no change to the controller
   or runner ceilings.
8. One physical acceptance (D3 budget, a few generations): two chained TI2V-5B frames-out segments on the real runtime,
   recording peak VRAM, host commit and min free RAM, with Comfy started once. Skipped until WAN-324 is registered.

## 6. Delivery in four reviewable PRs

| PR | Contents | Needs the GPU |
|---|---|---|
| **330A** | `SequencePlan`, planner refusals, ledger, last-frame extraction (frames-out, SVD, decoded), typed overrides seam, executor module, tests 1, 2, 7 | no |
| **330B** | warm runtime (`hold_runtime_for_sequence`), single guaranteed release, tests 3 | no |
| **330C** | colour match, overlap trim, `svd_native` in the branch, ASM-332 assembly, tests 5, 6 | no |
| **330D** | resume from a ledger (controller call, replay lineage, copy-and-verify), tests 4, physical acceptance 8 | one short run |

## 7. Risks and counter-hypotheses

- **Last-frame chaining drifts.** Identity and tone degrade over segments; this is a property of the technique, not of the
  plumbing. Mitigations: colour match (3.7), authored `provided` anchors (SEQ-331 / FLF-322), and a visible "drift" note in the
  History row. The eval kit (EVAL-320) should score a 3-segment chain before SEQ-331 builds on it.
- **Re-runs are not bit-exact on a GPU.** Hence "verify where deterministic, record divergence otherwise" in 3.3; resume never
  depends on it.
- **Host RAM headroom.** A warm Comfy keeps its weights resident between segments, but segments are sequential, so peak memory
  equals one clip's (the physical acceptance records it). Releasing between segments is the safe fallback and is one flag.
- **GPU device loss mid-sequence.** The ledger is the whole point; resume is explicit and re-verifies. The GPU-loss quarantine
  is unchanged. (This is also the first real consumer of the DIAG-GPU recorder's incident output.)
- **Scope creep into SEQ-331.** The typed `SequencePlan` is the only interface SEQ-331 needs; no UI lands here.

## 8. Decisions requested

1. **One job with N segment stages (recommended) versus one job per segment.** Section 3.1.
2. **Resume = a new NJR with parent lineage that re-verifies and copies prior artifacts (recommended)**, not in-place mutation of
   the failed job and not reuse of the parent directory. Section 3.6.
3. **Replay of a sequence re-derives frames and records divergence** rather than failing on a non-bit-exact GPU re-run.
   Section 3.3.
4. **Caps:** 12 segments and 12 x 81 total frames at admission (refuse, never clamp). Change if you want longer.
5. **Colour match on by default for `carry_last_frame` chains**, off for authored anchors. Section 3.7.
6. **Delete the legacy `stitch_video_segments` copy path** once the ASM-332 engine assembles sequences. Section 3.9.
7. **Delivery order 330A -> D** as four PRs (or one, if you prefer fewer reviews).

## 9. Docs impact when this lands

`VIDEO_PIPELINE.md` (sections 3, 8, 9: sequence layer no longer dormant, ledger, resume), `CODEX_MAP.md` (new modules), roadmap
section 6.2, `STATUS.md` (one line), and a test-gate row for the new sequence suites.
