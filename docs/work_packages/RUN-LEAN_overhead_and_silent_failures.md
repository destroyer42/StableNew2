# RUN-LEAN: per-job overhead and silent failures

Status: investigation in progress (2026-11-26). No source or test change yet.

Execution class: Standard. Model recommendation: Claude Code, Sonnet 5.5 or Opus, high effort
(`docs/AI_MODEL_SELECTION.md`). Canonical path unchanged; no second queue or runner.

## Scope

- a. Remove per-job work that grows with queue length; add per-step timing to the job performance record.
- b. Remove the wait after a cancel.
- c. Log silent swallows on the execution path with the job id; lower the S110 baseline.
- d. Log a timestamped record when jobs are queued and nothing has run for over 60 s, with the reason.

Characterization tests come before any behaviour change; separate commits.

## Gate

- Overhead (job duration minus stage total) under 1 s at 1,900 queued.
- Cancel to next job start under 5 s.

## Baseline (live job database read `mode=ro`, live logs, 2026-11-26; 2,284 single-stage txt2img jobs)

Median seconds. "post" is response to `completed_at`, minus stage finalization. "pre" is overhead minus post.

| queued | overhead | pre | of which memory cleanup | post |
|---|---|---|---|---|
| 0-50 | 1.27 | 1.12 | 0.16 | 0.15 |
| 50-200 | 1.69 | 1.52 | 0.24 | 0.16 |
| 500-900 | 2.13 | 1.94 | 0.29 | 0.18 |
| 900-1300 | 2.36 | 2.18 | 0.32 | 0.16 |
| 1300-1700 | 2.57 | 2.40 | 0.35 | 0.17 |
| 1700+ | 3.13 | 2.96 | 0.38 | 0.17 |

Correction to the assessment: the growth is **before** the stage, not after it. Post-stage time is flat, result
publication takes about 11 ms, and claim-to-runner-start about 2 ms.

## Findings for (a)

Benchmark on 1,900 real NJRs from the database (median):

| work | cost | where it runs |
|---|---|---|
| `UnifiedJobSummary.from_normalized_record` for every active job (`AppController._build_queue_projection`) | 373 ms (live log: 330-390 ms) | background thread, about 2.7 times per job |
| queue `Listbox` delete and re-insert of every row (`QueuePanelV2.update_jobs`) | 132 ms | Tk thread, on every start and finish |
| one full GC pass with the queue live | 106 ms | whichever thread allocates |
| `_format_queue_job_summary`, display strings, signatures, matrix and LoRA previews | under 20 ms each | various |

- 92% of the projection is `thaw_json` (`src/pipeline/njr_core_v26.py`): NJR properties convert the whole frozen
  config on each access, although the NJR is immutable.
- Inference, not yet measured end to end: this CPU work holds the GIL while the next job does its setup, which
  explains the growth in "pre".

Planned fix: cache the summary per immutable NJR in the projection (only `status` varies; check readers of
`created_at`, which is currently the projection time), then update only changed listbox rows.

## Open: the fixed part (about 1.1 s with an empty queue)

Removing the queue-dependent work alone leaves about 1.27 s, so it does not meet the gate. In the timestamped log,
about 1.2 s passes between `[pipeline] normal job` and `[manifest/txt2img]`. The path there is
`ImageBackend.execute`: runtime transition, runtime identity verification (`verify_backend_runtime_identity`), then
`_before_dispatch` (dependency gate, module baseline). Which step costs the time is not measured. These are safety
checks: measure before changing any, and ask the owner before weakening one.

Memory cleanup (about 0.16 s) and run-directory resolution (about 0.2 s) are the other fixed costs.

## Noted for (b), (c), (d); not investigated

- (b) Not started.
- (c) Assessment sites: `executor.py` stall interrupt, `single_node_runner.py` `_notify`, `pipeline_runner.py`
  learning record writer and callback, `job_queue.py` state listeners, `pipeline_runner.py` `_cleanup_at_job_start`,
  `job_service.py` `run_now`.
- (d) Not started.
