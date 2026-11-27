# RUN-LEAN: per-job overhead and silent failures

Status: implemented on a feature branch (2026-11-27); the two timing gates are **not** verified on the live app.

Execution class: Standard. Model recommendation: Claude Code, Sonnet 5.5 or Opus, high effort
(`docs/AI_MODEL_SELECTION.md`). Canonical path unchanged; no second queue or runner.

Controller surface: `app_controller.py` shrank (4775 to 4749 lines; ceiling lowered). `job_service.py` stays at its
ceiling. `job_history_service.py` is unchanged because logging there would grow it past its ceiling.

## Gate

| gate | state |
|---|---|
| Overhead (job duration minus stage total) under 1 s at 1,900 queued | not verified; likely **not met** (see "Fixed part") |
| Cancel to next job start under 5 s | expected for a Cancel in the app; not live-verified; app close and restart is a different path |

Validation plan: focused tests per part, then `tests/queue`, `tests/pipeline`, `tests/controller`, `tests/system`,
the PR gate once on the final tree.

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

## a. Work that grew with the queue

Benchmark on 1,900 real NJRs from the database:

| work | before | after |
|---|---|---|
| queue projection (`AppController._build_queue_projection`), about 2.7 per job | 373 ms (live log 330-390 ms) | about 1 ms; the first projection of a new queue still costs about 400 ms once |

- 92% of the old cost was `thaw_json`: NJR properties convert the whole frozen config on each access although the
  NJR is immutable. `app_controller_services/queue_projection.py` converts each record once.
- A summary's `created_at` is now the time of its first projection (it was the time of each projection). Nothing
  reads it from the queue view.
- Inference, not measured end to end: this CPU work held the GIL while the next job prepared, which explains the
  growth in "pre".
- Left as is: the Tk queue list is still refilled on each change (about 20-130 ms, mostly inside Tk), and one full GC
  pass with 1,900 jobs live takes about 100 ms.

### Fixed part (about 1.1 s with an empty queue)

Removing the queue-dependent work leaves about 1.27 s, above the 1 s gate. In the timestamped log about 1.2 s passes
between `[pipeline] normal job` and `[manifest/txt2img]`, where the backend does its runtime transition, runtime
identity verification and dispatch checks. Which of these costs the time is not measured. They are safety checks and
are unchanged.

The performance record now has `steps[]`: `prepare_run`, `start_gpu_telemetry`, `runtime_transition`,
`runtime_identity`, `before_dispatch`, `assemble_result`, `write_run_metadata` (publication time is already logged as
`publish_ms`). **Next action:** read these after one real batch, then decide what to change.

## b. The wait after a cancel

Two different things were being measured.

**Long gaps (about 75 s to 420 s) were app closes.** Of 22 jobs cancelled while running since 2026-11-06, every case
with a surviving log and a long gap (7) was a window close with a job running: shutdown cancelled the job, the app was
restarted, and dispatch waited for the new WebUI to be ready. Older cases have no log. This change does not shorten a
restart. **Owner decision still open:** closing the app cancels the running job for good; it could instead stay
queued, or the close could wait for it.

**A Cancel in the app did not stop the job.** Three defects, each with a test that failed before the fix:

1. `ReplayEngine` handed the runner its own token (`None`) instead of the job's, so on the queue path the pipeline
   never heard the Cancel.
2. No check between stage preparation and the generation request, so a cancel during preparation still dispatched.
3. The interrupt was sent once; if it landed before WebUI had the request it did nothing. It now repeats every second
   while the cancelled request is open.

Behaviour change: a cancelled job now stops (image and video), and its unfinished output is not saved. Before, it was
marked cancelled but kept generating while the next job waited. A cancel during a model load still waits for the load.

## c. Silent failures

26 broad `except: pass/continue` sites in the pipeline, queue, job service, execution controller and Comfy paths now
log a warning with the job id where one exists. Polling and liveness failures log once per stage. Control flow is
unchanged everywhere. Ratchet: S110 451 to 426, S112 31 to 29, BLE001 1153 to 1150.

- Worth watching in the log: "Global negative terms were NOT applied to the upscale prompt" (the upscale then runs
  without them) and "Progress polling failed" (cancel and stall handling may not act).
- `PipelineRunner._emit_learning_record`, named by the assessment as a way learning records are lost, has **no
  caller** in `src/`. It now logs, but it cannot be losing records today. Removing it is a separate cleanup.
- Left: narrow expected-exception handlers; two in `job_history_service.py` (controller ceiling); WebUI process
  start/stop cleanup.

## d. Idle with work queued

`services/queue_idle_report.py`, sampled by the existing system watchdog every 5 s. After 60 s with jobs queued and
nothing running it logs `QUEUE_IDLE` with the count and reason (update hold, paused, GPU quarantine, WebUI hold,
waiting for the WebUI after start-up, auto-run off, no worker, or worker not claiming), again when the reason changes
and every 10 minutes, and `QUEUE_IDLE_END` afterwards. Observation only. A closed app or sleeping PC cannot log while
it is down.

The three idle gaps in the assessment stay unexplained: those logs have no timestamps. The 416-minute one followed an
app close.
