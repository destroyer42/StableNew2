# PR-QUEUE-GPU-180 — GPU-Loss Dispatch Containment

## Execution Profile + Model/Reasoning Recommendation

Difficult bounded lifecycle/persistence/concurrency package inside existing authorities (Standard class; the stop
conditions — a second queue/scheduler/process owner, a destructive migration, a materially different recovery policy —
did not occur). Codex: GPT-6.1 Sol XHigh. Claude Code: Sonnet 5.5 XHigh, per `docs/AI_MODEL_SELECTION.md`. Preferred
host: Local/Desktop (Windows, SQLite, NVIDIA tooling, retained incident evidence). One primary session.

Worktree `C:/Users/rob/qual/StableNew-queue180`, branch `fix/queue-gpu-180-device-loss-containment`, based on remote
`main`. The base moved from `990d062d` (PR #97) to `8ded6de0` (PR-IMG-BACKEND-QUAL-100 documentation and offline
tooling) during the session; the branch was fast-forwarded, and those two commits touch no file this package changes
other than `STATUS.md` and `docs/CODEX_MAP.md`. The local qualification branch and the owner's photo-optimization files
were not touched. Authorization: local commits only.

## Incident (retained owner evidence, `C:/Users/rob/qual/GPU-20261012-2228/incident.md`)

2026-10-12 about 22:28:01–22:28:02 ET: the RTX 4070 Ti disappeared during a Forge SDXL generation. Forge stayed
HTTP-responsive and answered each later generation POST with HTTP 500 `AcceleratorError: CUDA error: unknown error`;
the existing outage proof (endpoint health + runtime identity) passed, so the queue consumed 14 more jobs in about 27
seconds. NVIDIA's query reported `GPU is lost. Reboot the system to recover this GPU` / `No devices were found`. Root
cause is not established and is not claimed here; this package contains the *consequence*.

## Controller Surface Assessment

No ratcheted controller grew. `job_service.py` is unchanged at its 1233-line ceiling (the diagnostics keys are produced
by `job_service_outage.diagnostics`, which replaced the one existing line). `app_controller.py` gains two thin
delegates (`confirm_gpu_recovery`, `add_gpu_quarantine_listener`) and loses two private helpers that nothing
references (`_should_refresh_queue_async`, `_run_via_pipeline_controller`), a net 7427 -> 7421 with the checked-in
ceiling lowered; `pipeline_controller.py` is untouched. All logic lives in extracted modules:
`src/utils/gpu_device_health.py` (host evidence + fault vocabulary), `src/queue/gpu_loss_assessment.py` (pure decision
table), `src/controller/gpu_loss_coordinator.py` (assessment application, release gate, incident notification,
projection) and the existing `JobQueue` eligibility authority. `src/controller/job_service_outage.py` binds the new
coordinator beside the WebUI one. The Tk layer reaches the release and the notification only through the
`AppController` delegates; the readiness record reads the coordinator's side-effect-free snapshot as the WebUI one does.

## Baseline claim ledger (real client → executor → `run_njr` → worker → SQLite; fake transport, host and manager)

Reproduction: `C:/Users/rob/qual/QUEUE180-evidence/test_baseline_180.py` (log `baseline.log`), measured on unchanged
`990d062d`; the code paths involved are byte-identical at `8ded6de0`.

| Scenario (15 Forge txt2img jobs; Forge answers HTTP 200 and 500 `AcceleratorError` for generation) | Before | After |
|---|---|---|
| Normalized failure path | 15 generation POSTs, 15 FAILED, 0 queued, no hold, 0 restarts | 1 POST, first job FAILED with its original evidence, 14 QUEUED in original order, quarantine active, 1 host query |
| Raised exception path | identical to above | identical to the row above |
| Manual Run Next / Run Now / auto-run after the first loss | each would claim and dispatch the next job | all refused by the same atomic claim; zero dispatches |
| Application restart with the 14 still queued | nothing remembered; the first claim fails again | quarantine restored from SQLite; same identities and order; nothing dispatched |
| Healthy WebUI endpoint / manager READY / recovered GPU | n/a | quarantine unchanged; only operator confirmation plus fresh positive host evidence releases it |

## Design

* **Host evidence** (`src/utils/gpu_device_health.py`). One read-only `nvidia-smi --query-gpu=index,name,
  pci.bus_id,memory.total,memory.used` enumeration, classified purely into `HEALTHY` (every device enumerates with
  readable fields), `DEVICE_LOST` (`GPU is lost`, `No devices were found`, `fallen off the bus`) or `UNAVAILABLE`
  (tool missing, timeout, driver not answering, unreadable fields, unrecognized output, a query still stuck from an
  earlier probe). It is **hard-bounded**: `subprocess.run(timeout=...)` kills the child and then waits for it without
  a bound, so the query runs on a daemon thread that the caller abandons 1 s after the 4 s timeout, and a query that is
  still stuck is never stacked under a second one (`probe_busy`). Projections carry state, a stable reason code and a
  device count only — never raw output, device names or bus identifiers. Production honours
  `STABLENEW_GPU_HOST_PROBE=0` (pytest pins it off).
* **Fault vocabulary.** Failure text (response body, exception message) maps to `device_fault`, `out_of_memory` or
  `numeric_fault`. `build_failure_evidence` now records only that code as `accelerator_fault`. A signature is a
  *suspicion*: it decides whether the host is asked, and never confirms anything alone.
* **Assessment** (`src/queue/gpu_loss_assessment.py`, pure). Evidence classes: `confirmed_device_loss`,
  `suspected_device_loss`, `cuda_out_of_memory`, `model_failure`, `transport_failure`, `evidence_unavailable`,
  `not_gpu_failure`. The host is queried only for a GPU-dependent job that shows a device fault or the existing typed
  outage suspicion (transport, 5xx, readiness, outcome unknown). Allocation and numeric failures never query it (the
  driver demonstrably answered). Only `DEVICE_LOST` host evidence confirms; an unavailable probe is never confirmation.
* **Quarantine in the existing claim authority** (`JobQueue`). `quarantine_gpu_dispatch` / `release_gpu_quarantine`
  extend the same lock-protected eligibility predicate used by `claim_next_job`, `get_next_job` and `mark_running`
  (the only QUEUED → RUNNING sites), so auto-run, manual Run Next and Run Now are refused atomically. It is effective
  in memory before its durable write, so a failed write cannot weaken it. It is not a lifecycle status, not the
  persisted `queue_paused`, not the auto-run preference and does not touch the WebUI hold. Held jobs keep identity,
  status and priority/FIFO order.
* **Dependency reuse.** `DependencyAssessment.held_by_gpu_loss` is derived from the frozen NJR classifier. Independence
  from the WebUI (native SVD, Comfy video) is *not* independence from the GPU, so they are held with Forge/A1111 image,
  AnimateDiff, training and unresolved work. `_GPU_FREE_STAGES` is deliberately empty: no admissible stage type is
  GPU-free today; a proven entry is the only thing that lets work continue.
* **Persistence.** One repository setting, `gpu_dispatch_quarantine`, restored when `JobQueue` is constructed — no new
  table, status or lifecycle owner. The record is content-free: schema, incident id, evidence class, UTC time, trigger
  (job id, dependency reason, stage, failure category, fault code, dispatch certainty), host evidence summary and the
  release requirements.
* **Trigger point.** The worker consults `GpuLossCoordinator.assess_failure` first inside the existing
  `_observe_failure` seam, for raised and normalized failures alike and before the WebUI assessment, publication and the
  next claim. Failures observed while already quarantined do not probe again.
* **WebUI interlock.** `WebUIOutageCoordinator.recover` performs no owned restart while a quarantine is active
  (`last_recovery_result = gpu_device_loss_quarantine`): restarting the WebUI cannot repair a lost device.
* **Release** (`GpuLossCoordinator.release`). Requires `operator_confirmed=True`, a matching incident id when one is
  supplied, and a fresh `HEALTHY` host enumeration; then performs the durable release. A reboot, a healthy WebUI, a
  manager READY epoch or a recovered GPU on their own release nothing, and a refusal records a content-free reason.
  It restarts nothing, resets nothing, kills nothing and issues no generation probe. A quarantine whose own write
  failed (`persisted: false`) has no durable record to clear, so a still-failing store cannot trap the operator in it;
  a durable record that cannot be cleared is never half-released. A lost double-click race is reported as
  `not_quarantined`, not as a save failure.
* **Projection.** `JobService.get_diagnostics_snapshot()["gpu_device_loss"]` and a first-listed Operator Readiness
  `GPU device` record (incident, evidence class, host reason, first failed job and stage, held-job count, requirements,
  recovery steps). `collect()` never probes (it runs on Tk). `GpuLossCoordinator.add_incident_listener` announces each
  new (or, optionally, a restored) incident once; the main window opens Operator Readiness from it through
  `AppController.add_gpu_quarantine_listener`. The record carries **Confirm GPU recovered...**, which asks for
  confirmation and runs `AppController.confirm_gpu_recovery` off the Tk thread. Held jobs are labelled by their actual
  hold: the Batches view says "held (GPU quarantine)" / "held - GPU" (`JobQueue.is_job_held_by_gpu_loss`), reserves
  "held (WebUI)" for the WebUI hold (`is_job_held_by_webui`), and the WebUI projection no longer says independent video
  jobs continue while a quarantine holds them.

## Acceptance evidence

`tests/queue/test_gpu_loss_containment_180.py` (26, canonical path), `test_gpu_quarantine_queue_180.py` (15, queue),
`test_gpu_loss_assessment_180.py` (23, decision table), `tests/utils/test_gpu_device_health_180.py` (38, incident output
shapes, vocabulary, hard bound), `tests/services/test_operator_readiness_gpu_180.py` (4),
`tests/gui_v2/test_gpu_quarantine_readiness_180.py` (6) and `tests/gui_v2/test_batch_gpu_hold_labels_180.py` (4): 116
new tests. 20 mutation checks (runner never consults the observer, eligibility ignores the quarantine, healthy host
confirms, unavailable probe confirms, release without confirmation or positive evidence, no persistence, WebUI release
lifts it, owned recovery ignores it, out-of-memory asks the host, GPU-free allowance dropped, restore ignored, unbounded
probe, stacked probes, GPU hold labelled WebUI, never-persisted release blocked, release failure mislabelled, idle
summary always built, delegate without confirmation, incident re-announced) are each detected. The worker-settling
helper in the end-to-end tests is state-based (no RUNNING job, idle worker, nothing eligible, after two idle
iterations), not a wall-clock window.

Affected suites (`tests/queue`, `tests/controller`, `tests/services`, `tests/utils`, `tests/api`) pass unchanged,
including PR-QUEUE-WEBUI-171 (65) and -172 (31), cancellation, shutdown fencing and the ambiguous-POST protections.

The queue serializes apply/release (durable write and in-memory flag together) under one extra lock. A concurrent
apply/release interleaving that would desynchronize them was **not** reproduced in 12 stress trials with the lock
removed; the lock and `test_concurrent_apply_and_release_keep_durable_and_memory_state_identical` are a defensive
invariant, not a demonstrated bug fix.

## Gate evidence (exact commit `b5051dbe`, local; hosted CI not run — nothing was published)

`python tools/ci/run_pr_gate.py` (Python 3.14.8, Ruff 0.14.9): repository completeness OK (574 files), controller
surface ratchet OK (`job_service.py` unchanged at its 1233 ceiling), Ruff clean, mypy smoke clean (10 files), isolated
collection 9,381 tests (repository unchanged), required smoke 386 passed (repository unchanged); `git diff --check`
clean. Security review (processes/persistence/untrusted input): no required fixes; one low defense-in-depth note —
`shutil.which("nvidia-smi")` searches the working directory first on Windows, a pattern already used by
`process_inspector_v2.collect_gpu_survivor_snapshot`, which this probe shares and whose output the release gate now
trusts. Evidence files: `C:/Users/rob/qual/QUEUE180-evidence/` (`baseline.log`, `test_baseline_180.py`, `pr-gate.log`).

## Unresolved failure classes (honest limits)

1. **Suspected loss does not quarantine.** A device-fault signature while the GPU still enumerates (for example a
   poisoned CUDA context inside a live Forge), or while the probe is unavailable (`nvidia-smi` missing or timing out),
   is projected and logged but cannot confirm. The cascade continues as before for that class. A consecutive-fault
   breaker or an owned-Forge restart for a sticky context is a different recovery policy and needs an owner decision.
2. **GPU lost while idle with Forge dead.** The first claimed job can reach the executor's existing single bounded
   pre-dispatch restart before the queue-level assessment runs; the quarantine applies when that job fails.
3. **Positive recovery means enumeration, not CUDA usability, and a repeat fault does not re-quarantine.** A generation
   probe is explicitly out of scope, so the first post-release job is the real test. If it fails with the same device
   fault while the GPU enumerates, that is only a *suspected* loss (class 1): only `DEVICE_LOST` host evidence confirms,
   so nothing is held again. A runtime whose CUDA context stayed poisoned (it was not restarted, or is external) can
   therefore consume the queue after a release. A short post-release probation in which a repeat device-fault
   signature re-quarantines is a recovery-policy change that needs an owner decision; it is not implemented.
4. **NVIDIA/`nvidia-smi` only.** Without it nothing can be confirmed (class 1). Multi-GPU: any lost device confirms;
   release requires every queried device to enumerate.
5. **Undispatched failure at the instant of loss** is published FAILED as before (this package does not widen the
   requeue rule); the 14 earlier FAILED records are never altered or retried.
6. **Native SVD** failures carry text only (no typed envelope); they use the same vocabulary and host gate.
7. No physical validation was performed: no GPU workload, NVIDIA reset, reboot, runtime change or model download.
