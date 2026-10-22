# PR-VID-SEQ-330 - Physical sequence acceptance procedure

## Status

`PR-VID-SEQ-330-CORE` is verified on fake backends, a temporary SQLite queue and synthetic frames, and runs A, B and C below were
made on the real managed Comfy on 2026-10-22 under the owner's explicit authorisation (section 8 has the result). A physical run
changes shared hardware state and uses the operator's managed runtime (AGENTS.md section 5), so it needs a fresh authorisation each
time. Nothing here registers a workflow or changes governance.

## 1. Authorisation and limits

- A physical run needs the owner's explicit, current authorisation naming the run, the runtime and the budget (roadmap decision D3: a few
  generations). No registered-workflow or governance change is implied or needed: the sequence uses an already approved workflow
  (`wan22_ti2v_5b_i2v_v1` 1.3.0, frames out) and native SVD XT is a separate, optional second run.
- Peak VRAM, host commit and minimum free RAM are recorded for the whole sequence, not per segment, because the Comfy process stays warm.
- Stop at the first sign of GPU device loss (the existing quarantine stops dispatch); do not retry or resume automatically.
- Never adopt, stop or restart an external Comfy or A1111 on the configured endpoints. Preflight refuses to run when one is live.

## 2. Preconditions

1. The branch under test is merged (or the exact SHA is recorded); `python tools/ci/run_pr_gate.py` is green for it.
2. The managed runtime contract (`config/managed_comfy_runtime.json`) is satisfied and nothing else holds the GPU; WebUI is closed.
3. FFmpeg and FFprobe resolve (`resolve_ffmpeg_executable`, `resolve_ffprobe_executable`).
4. A source image already prepared at the workflow's frame size (480x832 portrait for TI2V-5B) and, for run C, an authored second anchor of exactly the same size.
5. The GPU-loss quarantine is clear and enough disk is free for three segments of frames (about 100 MB at 17 frames, more at 49-81).

## 3. Runs

Drive each run through the production chain only: `VideoWorkflowController.submit_sequence_job(...)` -> `JobService.submit_njrs` ->
SQLite queue -> `PipelineRunner.run_njr`. `tools/acceptance/seq330_sequence_acceptance.py` does this: it reuses the isolated-workspace pattern of
`tools/acceptance/vid190_queue_recycling_acceptance.py` (`_Stack`, `_build_stack`, `preflight`) for the scratch queue and observation and
replaces only the job submission. It stops or kills nothing itself (a live external Comfy or A1111 refuses the run).

```bash
python -m tools.acceptance.seq330_sequence_acceptance <source.png> --run A|B|C [--dry] --reports-dir reports/seq330/<run>
```

| Run | Sequence | What it proves |
|---|---|---|
| A | 2 segments, `wan22_ti2v_5b_i2v_v1` 1.3.0, 17 frames each, fixed seeds, `carry_last_frame`, default overlap 1, assembly on, colour matching off | exact-frame carry-forward, one warm Comfy for both segments, one release, in-job assembly |
| B | 3 segments as A; abort the job between segments 2 and 3 with the UI/queue cancel (or interrupt the harness) | the ledger keeps segments 0-1, the cancel releases the owned runtime once; then `resume_sequence(job_id, 2)` runs only segment 2 |
| C | 2 segments, segment 1 `provided` with an authored anchor, overlap 0 | authored anchors are hashed and re-verified; no overlap trim |
| D (optional) | native SVD XT, 2 segments of 14 frames | the pre-postprocess native frame is the anchor; postprocess unchanged |

Do not use colour matching in the first runs; evaluate it afterwards on the recorded frames (it is off by default until quality is evaluated).

## 4. What to capture

For every run: the admitted NJR snapshot and its `plan_digest`; the queue row's lifecycle states from SQLite; `sequence_state.json` and its
SHA-256; every segment's request job id (`<job_id>_segNN`), seed, frame count and workflow version from the backend manifest; process observations
before, during and after (endpoint state, managed-runtime ownership, host RAM, driver VRAM); timings of segment 0 (cold) and segment 1 (warm);
the assembled movie and its manifest; and, for run B, the resumed job's ledger.

## 5. Verification

```bash
python -m tools.acceptance.seq330_sequence_verification <run>/sequence_state.json --report reports/seq330/<label>_verdict.json
```

The verifier re-reads the artifacts and fails the run unless the ledger is a completed contiguous prefix of its plan, every file still has its
recorded hash, every final frame is a PNG, every carried anchor equals the previous final frame, each frames-out segment produced exactly its admitted
count, the assembled movie has its recorded hash and decodes to the recorded frame count and rate, and one runtime-release record exists. A resumed
child must additionally show `origin: reused` for exactly the parent's prefix and, once the parent run folder is deleted, still verify.

Judge by hand (not automatable): that the second segment visibly continues the first (no jump at the join), that the overlap trim removed a repeated
frame and not a content frame, and that segment 1's start matches segment 0's last frame. Record any identity or tone drift; do not claim colour matching
or the carry-forward fixes it.

## 6. Pass criteria

- Run A: completed; two distinct segment job ids and seeds in the manifests; Comfy started once (its process id unchanged between the segments); the runtime
  release recorded once, after segment 1; assembled frame count `17 + 16`; verifier `passed`.
- Run B: the cancelled job leaves a valid ledger of two segments; the queue row says cancelled (SQLite), not the ledger; the resumed job is a new job id with
  `source.parent_job_id`, generates only segment 2, and the verifier `passed`; the parent ledger is byte-identical before and after the resume.
- Run C: the authored anchor's hash in the ledger equals the file; the verifier `passed`.
- Any run: no process was stopped that StableNew did not own; no generation request was replayed; peak VRAM and host commit stay within the single-clip envelope
  already recorded for the workflow (they should, since segments are sequential).

## 7. Stop and report

Stop and report, without retrying, on: GPU device loss, a verifier failure, an unexpected release of an external runtime, a frame-count mismatch, or a
resume that is refused for a reason other than the one the run injected. A failed physical run changes nothing in the catalog or governance; the evidence
goes in `reports/seq330/` and the next decision is the owner's.

## 8. Result of the 2026-10-22 run (RTX 4070 Ti 12 GB, managed ComfyUI, `wan22_ti2v_5b_i2v_v1` 1.3.0, 17 frames per segment)

Runs A, B and C passed and every verdict from `seq330_sequence_verification` was `passed` (evidence kept locally under `reports/seq330/`, not committed).
D (native SVD) was not run.

| Run | Outcome |
|---|---|
| A | Completed in about 95 s with **one** Comfy process for both segments; the runtime was released once after segment 1; 33 assembled frames (17 + 16). Segment 1's input anchor is segment 0's exact final frame; that anchor differs from the dropped overlap frame by 0.6/255 mean absolute difference, against about 4.7 between consecutive content frames. Peak VRAM 11.2 GiB (the single-clip envelope), minimum free host RAM 1.9 GB. |
| B | The operator cancel (`JobService.cancel_current`) arrived while segment 1 was running: the job ended `cancelled`, the ledger kept segment 0 and the runtime was released once. `resume_sequence` queued a new job that reused segment 0 (`origin: reused`), generated only the remaining two segments on a new Comfy process, and assembled; the parent ledger was byte-identical afterwards. |
| C | An authored 480x832 anchor for segment 1 with overlap 0 completed; the ledger recorded its basis `provided` and hash; 34 assembled frames. |

What the real runs found (each is fixed on the branch and covered by a regression test):

1. A held (warm) Comfy holds the model in host RAM, so the cold-load floor of 16 GB free RAM refused every later segment ("only 7.3 GB of system RAM is
   available"). The backend now skips that floor only for a later segment served by the very owned process that ran the previous one (a single clip, an unowned
   runtime or a restarted process still gets it); the GPU-memory floor still applies.
2. A relative run folder produced a relative carried-anchor path, which ComfyUI rejected ("Invalid image file"). The executor and ledger now use absolute paths.
3. A cancel can arrive after the last segment but before assembly, leaving only the assembly to do; `resume_sequence` accepts `from_segment` equal to the
   segment count and re-assembles without regenerating anything.

Not judged here: visual quality of the join over a longer chain, identity or tone drift, colour matching (off), native SVD and a failure injected by a real GPU
fault.
