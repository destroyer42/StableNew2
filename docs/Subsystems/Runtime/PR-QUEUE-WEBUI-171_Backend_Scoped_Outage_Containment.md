# PR-QUEUE-WEBUI-171 - Backend-scoped WebUI outage containment and safe recovery

## Execution Profile + Model/Reasoning Recommendation

Difficult runtime/queue lifecycle package inside existing authorities. Codex: GPT-6.1 Sol XHigh. Claude Code:
Sonnet 5.5 XHigh. Preferred host: Local/Desktop (SQLite lifecycle, Windows process ownership). Stop conditions
(a new scheduler, queue authority or persisted state) did not occur.

## Owner decision (applied)

When the configured WebUI is unavailable, hold **only** WebUI-dependent work; independently executable native SVD and
Comfy video jobs continue through the existing single-node queue. No whole-queue pause is used.

## Controller Surface Assessment

Net reduction: `app_controller.py` 7615 -> 7540 (dead `_run_pipeline_thread`, `_cache_last_run_payload`, the unused
discovery factory and a lifecycle mutation in `_execute_job` removed) and `job_service.py` 1237 -> 1233; ceilings
lowered. New logic lives in extracted modules, not in the ratcheted controllers.

## Claim ledger (measured on unchanged `main` `2692b0b7`, fake transport, real queue/runner/SQLite)

| Baseline | Result before |
|---|---|
| A. 25 image jobs, outage after job 1 (normalized failure) | 24 FAILED, 0 recovery |
| A. same, raised exceptions | 111 `run_callable` invocations and 88 `restart_webui` calls for the outage jobs (4 job replays x 6-attempt restart loops) |
| B. structured connection failure | no recovery path; the worker claimed the next job immediately |
| C. HTTP 500 on one job | the same job generated 5 times with 4 restarts (runner replay) plus the executor's own restart-and-replay |
| D. WebUI, SVD, Comfy, WebUI, SVD | image jobs failed and were consumed; no concept of independence or hold |
| E. manual Run Next | popped the next job with no eligibility; a later transition could not refuse it |
| F. concurrent recovery | two `stop_webui` calls entered concurrently (runner/executor/Launch overlap) |
| `_execute_job` ready gate | marked the in-memory job FAILED, then the worker burned every queued job through the gate |

Existing protections kept: the client's no-replay of ambiguous generation POSTs (`OUTCOME_UNKNOWN`) and its
fail-fast on a definite HTTP response to a generation POST.

## Design

* **Classifier** (`src/queue/backend_dependency.py`, pure): from the frozen NJR - workload kind, enabled stages,
  explicit backend identity. `requires_webui` (A1111/Forge image work, AnimateDiff), `independent_video` (native SVD;
  Comfy video workflow with an explicit `comfy` identity), `unresolved_dependency` (everything else: training, unknown
  backends, records without identity). Unresolved is held with WebUI work. Historical records without an image backend
  identity resolve exactly as at execution (A1111). No model names, GUI state, network or recompilation.
* **Atomic backend-aware claim** (`JobQueue`): `claim_next_job()` / `get_next_job()` skip held entries without popping or
  reordering them (they are re-pushed with their original tuple), select the highest-priority FIFO eligible job, and
  `mark_running()` refuses a held QUEUED job under the same lock. Manual Run Next now uses the same single atomic claim
  instead of select-then-transition. The hold is in memory only: not a lifecycle status, not the persisted pause, never
  the auto-run preference. `return_undispatched_to_queue()` restores a job with its identity and original position.
* **Typed failure evidence** (`src/api/webui_failure_evidence.py`): content-free `webui_failure_evidence/1` built from
  `GenerateErrorCode`, diagnostics and request summary and attached to the normalized `run_njr` failure result, so
  raised and structured failures classify the same way. Categories: pre-dispatch unavailable, readiness failure
  (ready gate), dispatched HTTP error, outcome unknown, timeout, ordinary, not-WebUI. Only a pre-dispatch failure with
  no completed stage evidence is safe to requeue.
* **Coordinator** (`src/controller/webui_outage_coordinator.py`, bound by `job_service_outage`): a suspected outage takes
  one fresh bounded read-only probe (endpoint health, options readable, runtime identity matching the configured
  runtime). Only a failed probe confirms the outage and applies the hold. A manager-owned runtime gets exactly one
  restart cycle per incident (`restart_webui(max_attempts=1)`, which already verifies TRUE-READY); an external runtime is
  never stopped, started, restarted or adopted. Release requires a fresh readiness **and** identity proof; a manager
  READY event is only a trigger. The worker itself runs assessment/recovery between jobs, so nothing competes with an
  active video job and no background owner exists.
* **No replay.** The runner's job-level crash retry (4 re-invocations x restart loop) is removed, as is the executor's
  restart-and-replay of an opaque HTTP 500. A job fails once with its real error, or is restored to QUEUED only on
  positive non-dispatch evidence (bounded to 2 restorations). Backend recovery is never permission to rerun a generation.
* **Serialization.** `restart_webui()` shares the launch lock added in PR-170, so runner, executor and Launch/Retry
  recovery cannot overlap process actions.
* **Restart.** Nothing is persisted. In production a startup gate holds WebUI claims until a fresh proof; verified
  independent video flows without WebUI. Pause, auto-run, the shutdown fence and unresolved historical outcomes take
  precedence.
* **Projection.** `JobService.get_diagnostics_snapshot()["webui_outage"]` and the existing operator-readiness WebUI record:
  status (healthy / unverified / recovering / unavailable / operator action required), endpoint, runtime identity,
  held and independent counts, recovery attempts and last result, first failure category and incident id, and that held
  jobs remain queued, with the existing Launch/Retry controls as the recovery path. Incident log records
  (`WEBUI_OUTAGE | ...`) carry a bounded stdout tail; default projections carry no prompts or paths.

## Acceptance evidence

`tests/queue/test_webui_outage_containment_171.py` (66): classifier table, evidence and assessment, 25-job cascade,
structured/raised/ready-gate shapes, mixed sequence, priority/FIFO resume, Run Next and transition atomicity, idle
without spin, successful/failed owned recovery, one-cycle budget, external runtime untouched, HTTP 500 and
outcome-unknown never replayed, ordinary/SVD/Comfy failures never recover, ambiguous dependency held, concurrent
recovery, manager restart serialization, ready-event proof, shutdown fence, user pause and auto-run, restart restore,
queue manipulation, persistence/lineage, projections. Mutation checks (hold ignored, replay allowed, external
restarted, transition bypass, ordinary treated as outage, release without proof, per-job restart budget) are each
detected. Existing tests that encoded the replay (runner retry module, executor 500 restart, checkpoint resume after a
crash) were replaced or rewritten to the no-replay contract.

## Unchanged

NJR schema, JobService submission, SQLite lifecycle and statuses, `PipelineRunner.run_njr`, replay identities, backend
qualification, A1111/Forge process ownership rules, CLI discovery. No physical generation was run.

## Limitations

1. The executor still performs its own bounded restart for a *pre-dispatch* connection failure and retries the request
   once (safe: nothing was sent). The coordinator counts that attempt and does not restart again for the same failure.
2. Held-job release latency is bounded by the worker's held poll (about 1 s) plus the manager READY trigger.
3. A failed job that already completed earlier stages is never requeued (partial work is not "undispatched"); its
   checkpoints are preserved and a retry is an explicit replay with a new identity.
4. Physical validation on the Windows install requires separate authorization.
