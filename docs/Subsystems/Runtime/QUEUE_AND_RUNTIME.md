# Queue, job lifecycle and managed runtimes

Status: living document, edit in place
Owner area: job execution and runtime safety (`src/queue/`, `src/controller/job_service*.py`, `src/controller/webui_outage_coordinator.py`, `src/controller/gpu_loss_coordinator.py`, `src/api/webui_process_manager.py`, `src/api/webui_runtime_identity.py`, `src/api/webui_identity_attestation.py`, `src/services/runtime_transition_service.py`, `src/services/operator_readiness_service.py`, `src/video/comfy_process_manager.py`)

How to keep this true:
- Change this file in the same PR that changes lifecycle states, claim/hold/quarantine rules, process ownership, the production wiring or a safety rule. Edit the existing row or sentence.
- Do not append per-PR sections, dates or test counts. History lives in `git log` and the per-PR records listed at the end.
- Labels: **[V]** read in the code when this was written; **[A]** taken from `docs/audits/2026-10-16_repo_audit_and_roadmap.md`, not re-checked.

## 1. Scope and the canonical path

This document covers everything between "a validated NJR exists" and "the runner is called": admission, the SQLite lifecycle authority, the runnable queue projection, the single worker thread, cancellation, shutdown, and the runtime layer that keeps a WebUI/Comfy/GPU failure from corrupting that lifecycle (process managers, identity, outage hold, GPU quarantine, transition policy, readiness projection). Compilers and the runner internals are out of scope (see `docs/Subsystems/Image/IMAGE_PIPELINE.md`).

Authority: `AGENTS.md`, `docs/ARCHITECTURE_v2.6.md`. The path, with what each step is today:

| Step | Reality | Where |
|---|---|---|
| Compiler / NJR | Immutable `NormalizedJobRecord` | `src/pipeline/njr_core_v26.py` |
| JobService | `JobService.submit_njrs` is the only fresh-submission boundary; validates every NJR, admits the batch all-or-none | `src/controller/job_service.py`, policy in `src/controller/submission_policy_v26.py` |
| Queue/Repository | SQLite `JobRepository` owns snapshot and lifecycle; `JobQueue` is its runnable projection; history is a projection | `src/queue/job_repository.py`, `src/queue/job_queue.py`, `src/queue/job_history_store.py` |
| Worker | One `SingleNodeJobRunner` thread claims atomically and calls the run callable | `src/queue/single_node_runner.py` |
| Run callable | `JobExecutionController._run_job_callback` -> `ReplayEngine.replay_njr` -> `PipelineController.run_njr` -> `PipelineRunner.run_njr` | `src/controller/job_execution_controller.py`, `src/pipeline/replay_engine.py`, `src/controller/pipeline_controller.py` [V] |
| Handler / runtime | Backend `execute` asks `RuntimeTransitionCoordinator`, then verifies runtime identity, then dispatches | `src/image_backends/webui_family_backend.py`, `src/video/svd_native_backend.py`, `src/video/comfy_workflow_backend.py` |

Run Now is "enqueue with immediate-start policy" (`JobService.run_now`, `SubmissionPolicy.start_when_idle`), never direct execution. Replay and retry create a new NJR and re-enter at JobService. Nothing in the GUI calls a runner.

## 2. Lifecycle and the repository

`JobStatus` has five values (`src/queue/job_model.py`): `queued`, `running`, `completed`, `failed`, `cancelled`. There is no `cancelling`, no `paused`, no `held`. Holds, pause and quarantine are dispatch-eligibility flags, never statuses.

Legal transitions are `_ALLOWED_TRANSITIONS` in `job_repository.py`: queued -> running | cancelled; running -> queued | completed | failed | cancelled; terminal states have none [V]. `running -> queued` exists only for "return to queue" and the outage requeue.

`JobRepository` [V]:
- One `sqlite3` connection (`check_same_thread=False`) behind an `RLock`; file databases use WAL and `synchronous = FULL`; every write is `BEGIN IMMEDIATE`. Path: `workspace_paths.job_repository()` (`src/state/workspace_paths.py`); `:memory:` for tests.
- Tables `repository_metadata` (also the settings store), `jobs`, `legacy_imports`. A `CHECK` constraint restricts `status`; `REPOSITORY_SCHEMA_VERSION = 1` and a mismatch raises. There is no migration framework: any new status or column needs one (importer for old stores: `src/migrations/sqlite_job_importer.py`).
- `record_job_submissions` commits a whole batch in one transaction; a job's identity must match its NJR snapshot (`_canonical_snapshot`). Callbacks fire only after commit.
- `transition_job(job, status, expected_status=...)` reads the durable status inside the write transaction; a different status raises `JobStatusChanged` before any write, an illegal edge raises `InvalidLifecycleTransition`. Only `JobQueue.cancel_if_queued` passes `expected_status` today.
- `recover_interrupted_jobs` (run by `load_runnable_jobs` when `JobQueue` is constructed) turns every persisted RUNNING row into FAILED with `INTERRUPTED_RESTART_ACTION_REQUIRED`, `automatic_replay=False`. A job that was running at a crash is never silently re-run; the operator replays it deliberately. Operator Readiness surfaces the count.
- Settings keys in `repository_metadata`: `queue_paused`, `auto_run_enabled`, `gpu_dispatch_quarantine`.
- Observers (`register_callback`, used by `JobHistoryService`) run synchronously inside `transition_job` and their exceptions are swallowed (`_emit`).

## 3. The queue projection (`JobQueue`)

- Constructed over exactly one repository (a different `history_store` raises; JSON stores are refused). It restores QUEUED rows into a heap of `(-priority, counter, job_id)` and loads `queue_paused` and the GPU quarantine from settings [V].
- Locks: `_admission_lock` serializes durable commit + projection for admissions and full reorders; then `_lock` guards the projection. Order is always `_admission_lock` -> `_lock`; `_quarantine_lock` is taken before `_lock`.
- `claim_next_job` is the only claim: under `_lock` it checks pause, the dispatch fence and holds, pops the next eligible entry, and performs the durable `queued -> running` transition. A held entry keeps its place; a failed write puts the entry back. `get_next_job` pops without a durable transition and is not a claim.
- Terminal results go through `publish_result(..., require_running=True)`: it succeeds only while the job still owns RUNNING, so a cancel that landed first wins and the runner re-reads the durable status.
- Finalized jobs are kept in a bounded deque (100) with their payload cleared.
- Dispatch eligibility (all read and written under `_lock`, so there is no check-then-claim window):

| Flag | Scope | Persisted | Set/cleared by |
|---|---|---|---|
| `_paused` | whole queue (user's Pause) | yes (`queue_paused`) | `pause`/`resume` |
| `_dispatch_fenced` | whole queue, irreversible | no | `fence_dispatch` (shutdown) |
| `_webui_hold` | WebUI-dependent and unresolved jobs | no | `hold_webui_dispatch`/`release_webui_dispatch` (outage coordinator) |
| `_gpu_quarantine` | every job (no stage is proven GPU-free) | yes (`gpu_dispatch_quarantine`) | `quarantine_gpu_dispatch`/`release_gpu_quarantine` (GPU coordinator) |

- Which jobs a hold covers is decided by `classify_job` in `src/queue/backend_dependency.py`, from the frozen NJR only (never model names, GUI labels, the configured default or the network): explicit/legacy WebUI image backends -> `REQUIRES_WEBUI`; `svd_native` and Comfy `video_workflow` -> `INDEPENDENT_VIDEO`; anything unknown, mixed, training or without a record -> `UNRESOLVED`, which is held together with WebUI work so a missing field can never bypass a hold. A legacy record with no explicit image backend resolves as A1111, exactly as at execution.
- Held jobs stay QUEUED, unchanged, in original order. `dispatch_summary()` is the deterministic projection (`queued`, `held_webui`, `held_gpu_loss`, `eligible`, `independent`, `unresolved`).
- State listeners are notified after the lock is released; `coalesce_state_notifications()` batches them.

## 4. JobService (`src/controller/job_service.py`, 1.2k lines)

- Constructor takes a `JobQueue` (its repository is the only history store), an injected runner or `runner_factory`, and `require_normalized_records`. It registers `_handle_job_status_change` on the queue, binds the continuous-dispatch policy and the outage/GPU coordinators (`job_service_outage.bind_webui_outage_containment`) to the runner. Helper modules: `job_service_auto_run.py` (auto-run flag, pause retirement), `job_service_dispatch.py` (`dispatch_next_now`), `job_service_shutdown.py`, `job_service_outage.py`.
- `submit_njrs`: type check, duplicate-id check, `_validate_normalized_record` (job id, pack identity for PromptPack sources, positive prompt for txt2img, non-empty stage chain), build jobs, `JobQueue.submit_many`, then submitted/updated events, then runner start. Failure before `submit_many` leaves nothing durable; a runner-start error after admission is logged and the ids are still returned.
- Auto-run is `JobService.auto_run_enabled`. On: `_ensure_runner_started` starts (or upgrades a one-shot worker to) the continuous worker. Off: `run_next_now` -> `runner.run_next_once` claims one job atomically and runs it on a one-shot worker; `run_next_once` first asks the outage coordinator for a fresh readiness proof.
- Pause persists in the queue, and retires the worker only when idle (`retire_idle_runner_for_pause`); a running job is never cancelled or joined by Pause.
- `cancel_current(return_to_queue=...)`: without `return_to_queue` it first calls `cancel_job` (durable CANCELLED via `mark_cancelled`, external-process cleanup), then `runner.cancel_current`, which signals the `CancelToken`; the generation stops cooperatively afterwards (see section 11, B10). With `return_to_queue` it asks the runner/queue to restore the job to QUEUED.
- Per-job `ProcessContainer` (`_ensure_container`, factory `build_process_container`) tracks external pids registered via `register_external_process`; on any terminal status or QUEUED it terminates those pids and destroys the container. `JobWatchdog` (`src/utils/watchdog_v2.py`) polls external-process caps and, on violation, calls `cancel_job`. `max_job_runtime_sec` is opt-in (`STABLENEW_WATCHDOG_MAX_JOB_RUNTIME_SEC`, default none) [V].
- Listeners (`_emit`, status callbacks) swallow exceptions; an optional dispatcher marshals them to the GUI thread (`set_event_dispatcher`).

## 5. The worker (`SingleNodeJobRunner`)

- At most one job runs at a time. Threads are non-daemon: `QueueWorker` (continuous) and `QueueWorkerOnce`; all launched threads are tracked in `_workers`. `start()` on a live one-shot worker sets `_continue_after_once` so the same thread hands off to continuous draining with no gap; handoff and retirement decisions are made under `_lifecycle_lock`.
- Loop: honor pause -> check continuous-dispatch policy (auto-run) and shutdown -> clear cancel state -> `maybe_release` hold check -> `claim_next_job` -> create a `CancelToken` (`job._cancel_token`) -> `run_callable(job)` exactly once -> normalize with `normalize_run_result` -> merge stage checkpoints -> on failure observe -> publish once. A failed job is never re-invoked.
- Failure order: `_observe_gpu_loss` first (device loss must be in force before anything else can act or the next claim happens), then the WebUI `assess`. If the decision says `requeue` and the job has no stage checkpoints, `return_undispatched_to_queue` restores it (at most `MAX_UNDISPATCHED_REQUEUES`), otherwise the result is published FAILED, then `_after_failure` runs the one bounded recovery. Both observers are wrapped so containment can never break the worker.
- Cancel is cooperative: the flag is checked before and after the callable; a cancel that wins turns into CANCELLED or back to QUEUED. A `CancellationError` or any exception while the flag is set becomes `mark_cancelled`.
- Idle is event-driven (P3-6) [V]: the worker clears `JobQueue`'s wake event, claims, and if there is nothing waits on that event for at most `IDLE_HEARTBEAT_SECONDS` (1.0 s). Every `_notify_state_listeners` (admission, resume, hold release, return to queue, reorder) and every `stop`/`begin_shutdown`/`_stop_event.set()` (`_WakingEvent`) sets it, so pickup and stop are immediate and an idle worker makes about one claim per second instead of 20. `poll_interval` now only paces the paused loop and non-`JobQueue` stubs. When only held work remains it waits `held_poll_interval` (1.0 s) on the stop event. A 2 s cooldown follows `reprocess_panel` jobs.
- Shutdown: `begin_shutdown` fences the queue (the atomic boundary) then sets `_shutting_down` and the stop event, deliberately lock-free. `stop(timeout)` returns `is_quiescent()`: true only when no launched thread is alive. A join that merely timed out is not quiescence.
- `src/queue/stub_runner.py` is the in-process fake used by tests (no thread, no pipeline).

## 6. Production construction (how it is actually wired)

`src/main.py` -> `build_v2_app` (`src/app_factory.py`) -> `AppController(job_service=None)`. [V]

1. `AppController` builds `PipelineController` (no job service). `PipelineController` builds a `JobExecutionController`, which creates the one `JobRepository` (path `workspace_paths.job_repository()`; `:memory:` when `PYTEST_CURRENT_TEST` is set), the `JobQueue` over it and the `SingleNodeJobRunner` whose callable is `_run_job_callback`. `PipelineController` then builds `JobService(queue, runner, history_store, history_service=..., require_normalized_records=True)`.
2. `AppController` adopts that service (`pipeline_controller.get_job_service()`); `_build_job_service` is the fallback and also sets `require_normalized_records=True`.
3. When the service was not injected, `AppController` calls `webui_outage.enable_startup_gate()`: the queue is WebUI-held with reason `startup_unverified` until a fresh proof (section 8). An injected service (tests) is left untouched.
4. Bootstrap (`src/main.py`, `bootstrap_webui`/`bootstrap_comfy`) builds the managers; autostart launches only when configured and never over a healthy or occupied external endpoint (Comfy returns an unowned manager in that case). WebUI waits with `wait_for_managed_startup`, and `WebUIConnectionController.attach_process_manager` subscribes to readiness epochs. `main_window_v2` builds `OperatorReadinessService` with providers reading `job_service.webui_outage.snapshot` and `job_service.gpu_loss.snapshot`; `main.py` gives the connection controller `set_outage_provider(outage.snapshot)`.
5. GPU quarantine UI: `AppController.confirm_gpu_recovery` (blocking, call off the Tk thread) and `add_gpu_quarantine_listener`.

Shutdown (`AppController.shutdown_app`, sequencing in `src/controller/app_controller_services/shutdown_coordinator.py`): fence queue admission -> cancel active jobs -> stop background work -> stop managed WebUI -> stop the job service within `QUEUE_QUIESCE_TIMEOUT_SECONDS` -> final queue-state save -> `close_repository_when_quiescent`. The shared repository is closed only after every worker has definitively quiesced; otherwise it stays open and queued jobs remain durably QUEUED. The fence is process-lifetime and never persisted: next launch resumes under the normal startup policy.

## 7. Managed WebUI runtime

### 7.1 Process manager (`WebUIProcessManager`)

Sole lifecycle owner of the one WebUI-family process (Forge or A1111 share one endpoint and one manager slot). [V]

- Ownership: `owns_process` is true only for the process this manager launched in its current session (pid matches). `stop_webui` and `restart_webui` take no OS action without ownership. An occupied configured endpoint (`_configured_endpoint_is_occupied`), a live unowned process, or another manager owning a live process refuses the launch (`WebUIStartupError`). Port discovery is gone: `check_health` probes only the configured endpoint.
- `start()`, `ensure_running()` and `restart_webui()` serialize on one `_start_lock`, so bootstrap, Launch, Retry, runner recovery and executor recovery cannot overlap. A launch also refuses unless the GUI is alive (`SingleInstanceLock.is_gui_running`), and a non-daemon orphan-monitor thread (via `ThreadRegistry`) stops the owned process if the GUI exits.
- Startup window: an owned live process that has not yet proven readiness is waited on (bounded by `startup_timeout_seconds`), not killed and relaunched (`_within_startup_window`). `wait_for_managed_startup` polls in slices and reports pid, exit code and stdout/stderr tails if the process dies first, then calls `mark_ready`.
- `mark_ready(source=...)` is the only publisher of a readiness epoch (`ready_epoch`, `WebUIReadyEvent`); listeners receive the current epoch once on subscription. An epoch is a trigger, never proof by itself.
- Stop: terminate, wait the grace period, kill, last-resort process tree, then owned descendants, then container teardown with kill. Launch profiles come from `WebUIProcessConfig.launch_profile_commands`; an undeclared profile is refused without touching the command (`set_launch_profile`).
- Config: `build_default_webui_process_config` -> managed Forge from `config/managed_forge_runtime.json` (profile authority `src/utils/managed_forge_runtime.py`) unless `webui_runtime_identity = a1111_webui` is explicit. An unknown identity or unreadable settings raises; there is no fallback between the two.
- A module global holds the active manager (`get_global_webui_process_manager`, `active_owned_webui_process_manager`); a new manager claims it only if the current one does not own a live process; `clear_global_webui_process_manager(manager)` clears only its own registration.

### 7.2 Per-owner job objects

Each manager builds its own container at construction: `build_process_container(f"webui_process_manager-{uuid}", ...)` (`src/utils/process_container_v2.py`). On Windows that is `WindowsJobObject` (`src/utils/win_jobobject.py`): an anonymous job (`CreateJobObjectW(None, None)`, the name is a label only) with `KILL_ON_JOB_CLOSE`, so it can be reached only through its own handle. Linux uses `src/utils/cgroup_v2.py`; any construction failure silently yields `NullProcessContainer` (debug log) [V]. The pid is attached after `Popen` returns (`_attach_pid_to_container`), so very early grandchildren can escape the job [V]. Tests get a no-op container from the autouse fixture in `tests/conftest.py`; container behavior itself is covered by `tests/utils/test_job_object_isolation.py`.

### 7.3 Endpoint lifecycle and single-flight connection

- The configured endpoint is authoritative: `resolve_effective_webui_base_url` (`src/api/webui_runtime_identity.py`) = explicit `webui_base_url`/`STABLENEW_WEBUI_BASE_URL`, else the identity default (managed Forge `127.0.0.1:7871` from its manifest, A1111 `:7860`). The legacy flat A1111 default is not an explicit Forge choice.
- `WebUIConnectionController` (`src/controller/webui_connection_controller.py`) is the one connection authority for the GUI. `ensure_connected` is single-flight (`_flight` lock): Launch, Retry, auto-reconnect and run preflight join an attempt in flight instead of starting a second; a re-entrant call from the attempt's own thread returns the current state. `get_state` is a read-only projection (process poll, outage snapshot) and never does network work on Tk; `refresh_health` is a fresh read-only probe off Tk that cannot overwrite an explicit Launch/Retry or a newer readiness epoch. An outage snapshot other than `healthy` projects as ERROR, `recovering` as CONNECTING.
- Readiness probing and backoff: `src/api/healthcheck.py` (`probe_webui_endpoint` returns `free`/`occupied`/`healthy`, `wait_for_webui_ready`, `clear_readiness_failure_state`; a hard connection failure starts an exponential cooldown that `mark_ready` and restarts clear).

### 7.4 Runtime identity and attestation

- `classify_runtime_identity` / `probe_endpoint_runtime_identity` classify an endpoint read-only from `/sdapi/v1/cmd-flags`, `/options`, `/sd-modules`, `/sd-vae` (never from process names, ports or folders). `assert_runtime_matches_backend` raises `WebUIRuntimeIdentityMismatch`: Forge work needs a positively identified Forge; A1111 work tolerates an unclassifiable endpoint but not a positive Forge.
- `verify_backend_runtime_identity` (`src/api/webui_identity_attestation.py`) runs before every stage's first generation POST. `ManagedWebUIIdentityAttestor` adds one narrow relaxation: if the exact process StableNew launched was positively classified as Forge in this still-current session (manager, process, pid, endpoint and ready epoch all match), a transient non-positive probe is allowed through (`same_session_attestation`). Contradictory evidence (A1111 list, options without Forge keys) or a changed session drops it; an external endpoint never has one. The slot is in memory only. A bounded initial settle (`INITIAL_IDENTITY_SETTLE_SECONDS` = 8 s) waits for the first positive proof of an owned, declared-Forge session.
- Decision sources: `live_positive`, `same_session_attestation`, `no_valid_attestation`, `contradictory_identity`, `session_changed`, `not_applicable`.

### 7.5 Contained child processes (`src/utils/managed_process.py`)

One containment rule for the children started through `run_bounded` (driving-video inspection, the SVD post-process worker, RIFE) and `ManagedProcess` (managed Comfy): the child is placed in its own anonymous OS container (`build_process_container` -> Windows job object with kill-on-close, Linux cgroup; `ProcessContainer.add_pid` returns whether the OS accepted it), so a dead owner cannot leave it running and one kill reaches its tree. [V]

**Fail closed where containment is required (`containment_required()`, true on Windows, the supported runtime platform).** On Windows the child is created suspended (`CREATE_SUSPENDED`), placed in the job object and only then resumed (`resume_suspended_process`, `NtResumeProcess`), so neither it nor any descendant executes before it is inside the job. If the container cannot be built the child is not started; if the OS refuses or fails the attach, or the child cannot be resumed, it is killed (also on an interrupt during that step). `ContainmentError` is raised in each case (`run_bounded` returns it as `launch_error`, `containment unavailable: ...`; the Comfy manager turns it into `ComfyStartupError`). `ManagedProcess.contained` and `ProcessOutcome.contained` are true only if the OS accepted the child. `NullProcessContainer.reason` says why a container is absent (`disabled`, `unsupported_platform`, `construction_failed`). On other platforms, or with `require_containment=False`, the child runs uncontained with a WARNING (`contained` is `False`): its descendants are then not tracked and a kill reaches only the direct child. Linux cgroup containment needs privileges that CI and most dev hosts lack, so it stays best-effort; it has no suspended-start step, so a descendant forked in the attach window can escape there.

- `run_bounded(command, timeout_seconds=, max_stdout_bytes=, max_stderr_bytes=, cancel=, cwd=, env=, require_containment=)` returns a `ProcessOutcome` (`timed_out`, `cancelled`, `output_truncated`, `launch_error`, raw bytes) and never raises on a launch failure. A timeout, a cancel (a `threading.Event` or a `() -> bool` probe) or a stdout overflow kills the whole tree. Used by driving-video inspection (`run_bounded_process` is a thin wrapper) and by the SVD post-process worker and RIFE (`WORKER_STAGE_TIMEOUT_SECONDS` / `RIFE_TIMEOUT_SECONDS`, 1800 s each; the runner's `CancelToken` is wired so cancelling a job stops the child; a timeout is an `SVDPostprocessError`, a cancel a `CancellationError`).
- `ManagedProcess(command, cwd=, env=, label=, log_path=, require_containment=)` owns a long-lived child: `start()`, idempotent `stop(grace_seconds=)` (terminate, wait, then kill the tree), `stdout_tail()` / `stderr_tail()` (200 lines of at most 2000 characters), `contained`, and a per-instance `owner_token` exported to the child as `STABLENEW_MANAGED_PROCESS_OWNER`. Readers are spawned through `ThreadRegistry` (daemon on purpose: a reader blocks as long as the child holds the pipe, and the child only dies once its owner has exited), decode UTF-8 with `errors="replace"` and never stop draining. A time bound never depends on containment: `run_bounded` returns within the timeout plus the kill wait (at most 5 s) and a 2 s drain, and `stop()` within its grace plus the kill wait and 1 s per pump, even when a descendant that escaped containment still holds the pipes; a stream whose reader is still blocked is never closed (that close would wait for the pipe's EOF), the daemon reader ends when the pipe finally does, and output read before the deadline is kept (`read1`). The managed Comfy manager is its only adopter so far.
- `RotatingTextLog` (size-capped, `.1`..`.N` backups) and `prune_logs` bound log growth. Managed Comfy logs to `logs/comfy/managed_comfy.log`; the WebUI manager's per-launch `webui_{stdout,stderr}_<session>.log` files now live under the repository `logs/webui/` (not the working directory), rotate at 20 MB and only the newest 8 launches are kept (audit E6). Under pytest both locations are redirected to a per-test directory.
- **Not under this rule:** the other `subprocess.run` calls (FFmpeg/FFprobe in `src/pipeline/video.py`, `src/video/video_export.py`, `container_metadata.py`, `motion/secondary_motion_video_reencode.py`, `svd_portable_provenance.py`, GPU health and process inspection, `managed_forge_runtime`) have their own timeouts and are not contained.
- **Not adopted yet:** the WebUI manager keeps its own `Popen`, readers and container (heavily qualified; its identity, orphan-monitor and external-attach rules are not expressible in `ManagedProcess`). Moving it onto the primitive is optional follow-up, not required for B2/B7. Its own `_attach_pid_to_container` remains best-effort: it attaches after `Popen` returns, so a grandchild forked in that window can escape, and a failed attach is only logged (the manager's orphan monitor and identity checks are its other safeguards).

## 8. Outage containment and the startup hold (`WebUIOutageCoordinator`)

A transient, in-memory coordination service (`src/controller/webui_outage_coordinator.py`); the queue still owns claims, the worker still executes, the manager is still the only process owner. [V]

1. Typed evidence (`src/api/webui_failure_evidence.py`: `FailureCategory`, `DispatchCertainty`, `FailureAssessment`) classifies a failed job. Only a suspected outage on a job that runs a WebUI stage takes one fresh, bounded, read-only probe (`default_webui_probe`: endpoint healthy, identity classification with readable options, match against the configured identity). A ready probe means "not an outage".
2. Confirmed outage: `hold_webui_dispatch` (independent video keeps flowing), and `OutageDecision.requeue` only if there is positive evidence nothing was dispatched, no stage checkpoint and no completed work.
3. Recovery: `recover` runs at most `DEFAULT_RECOVERY_BUDGET` (1) cycle per incident, single-flight (`_recovery_lock`), only for a manager-owned runtime, via `manager.restart_webui(wait_ready=True, max_attempts=1)`. An external runtime goes to `operator_action_required` and is never restarted. It is skipped while a GPU quarantine is active. If the executor already spent its restarts for this failure, the budget is not multiplied.
4. Release: `maybe_release` (called each worker iteration, on a manager ready epoch, and forced by `run_next_once`) releases only after a fresh readiness plus identity proof, throttled by `release_interval_s`. A failed proof keeps the hold; queued work is neither failed nor dropped.
5. Startup hold: `enable_startup_gate()` applies the same hold at launch (`startup_unverified`) so restored WebUI jobs wait for a proof instead of failing against a cold endpoint. Wiring in section 6.
6. The coordinator never replays a generation. An unknown outcome of a dispatched POST is terminal/action-required (`SDWebUIClient` classifies; `recover_interrupted_jobs` does the same across restarts).

`snapshot()` is the content-free projection (`status` healthy/unverified/recovering/unavailable/operator_action_required, held counts, incident id, recent incidents). Dead-endpoint cascade handling is covered by `tests/queue/test_dead_forge_cascade_172.py`.

## 9. GPU device-loss quarantine (`GpuLossCoordinator`)

`src/controller/gpu_loss_coordinator.py`, pure assessment in `src/queue/gpu_loss_assessment.py`, host evidence in `src/utils/gpu_device_health.py` (read-only `nvidia-smi` enumeration, off under pytest via `STABLENEW_GPU_HOST_PROBE`). [V]

- A failure signature is only a suspicion that gates one bounded host query; only host evidence of a lost device confirms (`CONFIRMED_DEVICE_LOSS`). Out-of-memory never gates the probe. An unobtainable probe is `EVIDENCE_UNAVAILABLE`, never confirmation. A healthy WebUI is not an input.
- On confirmation `JobQueue.quarantine_gpu_dispatch` takes effect in memory under the claim lock before it is made durable (a failed write marks `persisted: False` but cannot weaken it). First incident wins. All queued work stays queued, unchanged and in order; failed jobs are not retried. `_GPU_FREE_STAGES` is deliberately empty, so image, video and training are all held.
- Release (`GpuLossCoordinator.release`) requires explicit operator confirmation AND fresh positive host evidence, and a matching incident id; refusal codes are stable strings (`operator_confirmation_required`, `no_positive_recovery_evidence`, `incident_mismatch`, `release_not_durable`). The durable record is cleared first, then memory. It never restarts a runtime, resets a driver, reboots, kills a process or issues a generation probe.
- Surfaces: `OperatorReadinessService` lists the `gpu_device` record first while quarantined; the WebUI outage message changes wording when GPU jobs are held.

### 9.1 Survivor telemetry (observation only)

`src/utils/gpu_survivor_telemetry.py` (`GpuSurvivorTelemetry`) leaves a flushed, fsynced record of GPU state because a device loss can end the process before any normal diagnostic runs. It has no queue, repository, process-lifecycle or execution authority; every failure is swallowed.

- **Per job:** `PipelineRunner._start_gpu_survivor_telemetry` starts a recorder for every GPU-capable job (`JOB_SAMPLE_INTERVAL_S` = 0.5 s) under `<cwd>/reports/diagnostics/gpu_survivor/survivor.jsonl`, with `job_started`, `stage_started`, `generation_dispatched` and `job_finished` events.
- **Per app session:** `main()` calls `start_gpu_session_telemetry()` just before the Tk loop and `stop_gpu_session_telemetry()` in its `finally` (and `graceful_exit` calls it first, because that path ends in `os._exit`). It samples every 5 s into `gpu_survivor/session/` (4 MB x 7 files), so a loss during startup, model load or idle still has a lead-up. `STABLENEW_GPU_SESSION_TELEMETRY=0` turns it off; the autouse test fixture sets that.
- **What a sample holds:** `nvidia-smi` utilization, memory, temperature, power, clocks, pstate, PCIe link now and max, throttle-reason bitmask, fan speed (`query_gpu_survivor_snapshot` in `src/utils/process_inspector_v2.py`; an unsupported additive field falls back to the base set). When the query returns nothing the record keeps `gpu: null` and adds `gpu_query` with a `status` (`gpu_lost`, `timeout`, `no_nvidia_smi`, `no_devices`, `nonzero_exit`, `error`) and the driver text.
- **Reading it:** every record carries `scope` (`job` or `session`). Point `tools/diagnostics/correlate_gpu_incidents.py --telemetry-dir` at the directory (it reads subdirectories, so `session/` is included); only job-scoped records or an active SQLite job classify an incident as proven active GPU work, while a session sample alone yields `stablenew_open_no_proven_active_generation`. Add `--windows-pnp` (or `--pnp-events-xml <exported events>`) to read Kernel-PnP / Device Management event 1000 ("could not be query removed ... vetoed") for the GPU's device instance, read-only. Each incident then carries a `windows_pnp` section with the signed `delta_seconds` (event minus incident; negative is before), the veto type number and label, and the vetoing component. It is a timing marker only: it never changes `classification` and does not establish hardware failure, that the device disappeared, or the responsible component. A missing, inaccessible or non-Windows event log is reported as `unavailable_*`, never as "no marker".
- **Thread rule:** the loop is a non-daemon `ThreadRegistry` thread and exits when the registry requests shutdown, so `shutdown_all` never waits on it.

### 9.2 Resuming after a device loss, and what the queue shows meanwhile

The quarantine is durable (`repository_metadata.gpu_dispatch_quarantine`) and survives a reboot: a rebooted, healthy GPU does **not** release it. While it is set the worker claims nothing, so pausing/unpausing, toggling auto-run and Send Job have no visible effect and the queue count does not move. Resume only through the GUI: header **Readiness** button -> the `gpu_device` row -> **Confirm GPU recovered...**. That runs `AppController.confirm_gpu_recovery` -> `GpuLossCoordinator.release(operator_confirmed=True)`, which re-checks the GPU read-only and then releases held jobs in order. The Readiness window also opens by itself at startup while a quarantine is active. [V] The queue panel names the hold: `dispatch_hold_status.format_dispatch_hold` turns `JobQueue.dispatch_summary()` into one sentence, carried by `QueueProjection.dispatch_hold` into `AppStateV2.queue_dispatch_hold`, shown in the status label (severity `held`) and repeated when Send Job is refused. `AppController.confirm_gpu_recovery` republishes the queue projection so the message clears on release. A WebUI outage hold is described the same way. Pausing and auto-run still do not override a hold.

### 9.3 Startup cost of the job history

`JobRepository.list_jobs` / `list_recent_jobs` choose the newest ids first (`idx_jobs_created_at`, created idempotently by `_ensure_created_at_index`; `DROP INDEX idx_jobs_created_at` undoes it) and fetch full rows only for those. The history panel and the duration-stats (queue ETA) refresh both run off the UI thread (`RuntimeProjectionCoordinator.publish_duration_stats_refresh`). Before this, two `SELECT * ... ORDER BY created_at` passes sorted the whole multi-gigabyte table on the UI thread at every launch (about 14 s warm on a 2.1 GB repository). Resource GETs to the WebUI also share a short "connection refused" circuit in `SDWebUIClient` (`CONNECTION_REFUSED_CIRCUIT_SEC`, GET only, cleared on success and by `clear_runtime_failure_state` when the backend is proven READY), because a refused loopback connection costs about 2 s per attempt on Windows and the GUI makes many such calls while the managed WebUI is still starting.

## 10. Runtime transition policy and managed Comfy

**Transition** (`RuntimeTransitionCoordinator.prepare_for`, `src/services/runtime_transition_service.py`) runs once, synchronously, inside a single admitted job's backend `execute()` (image: `WebUIFamilyImageBackend`; also the SVD and Comfy backends). It releases StableNew-owned conflicting residency through each runtime's own owner, never touches the queue or SQLite, and never restarts anything. [V]

| Target | Released first |
|---|---|
| `forge_webui` / `a1111_webui` | the owned other WebUI identity in the shared slot, owned Comfy, SVD cache |
| `comfy` | owned WebUI-family runtime, SVD cache |
| `svd_native` | owned WebUI-family runtime, owned Comfy |

Result `READY`, `ACTION_REQUIRED` (an external/ambiguous conflicting runtime; no OS action, no waiting) or `RELEASE_FAILED`. It never raises on those; the backend raises `RuntimeTransitionError` before dispatch.

**Managed Comfy** (`src/video/comfy_process_manager.py`, identity pinned in `config/managed_comfy_runtime.json`): same ownership rule (launch refuses over a healthy or occupied external endpoint; stop/restart only for its own process). It launches through the shared `ManagedProcess` primitive (section 7.5): the child joins its own anonymous job object (kill-on-close) as soon as it spawns, `stop()` reaps the whole tree, output is drained by registry-spawned readers that decode UTF-8 with `errors="replace"` into bounded tails and a rotating `logs/comfy/managed_comfy.log`, and the tails survive `stop()` for diagnostics. Constructing any `ComfyProcessManager` still overwrites the module-global registration [V]. The Comfy backend (`comfy_workflow_backend.py`) releases the owned runtime after each job, reports liveness while waiting on history, and waits up to `history_timeout`; the wait is cancel-aware and a cancelled job interrupts or dequeues only its own prompt (`docs/Subsystems/Video/VIDEO_PIPELINE.md`, section 4; typed errors in `src/api/http_transport.py`).

## 11. Audit status (B2, B3, B7, B10, verified against the code)

| Finding | Status | Evidence and what remains |
|---|---|---|
| **B2** shared named job object | **Fixed** [V] | Anonymous job object (`CreateJobObjectW(None, None)`), unique per-manager label, autouse `NullProcessContainer` fixture in `tests/conftest.py`, regression `tests/utils/test_job_object_isolation.py`. The general primitive exists (`src/utils/managed_process.py`, section 7.5) and fails closed on Windows: the child is created suspended, joined to its job and resumed, and a failed attach or build refuses to run it (`tests/utils/test_process_containment_failsafe.py`). **Still open:** the WebUI manager keeps its own best-effort attach after `Popen` (section 7.2), and Linux cgroup containment is best-effort. |
| **B3** startup gate and NJR strictness not wired | **Fixed** [V] | `PipelineController` constructs the service with `require_normalized_records=True`; `AppController` enables the startup gate on the adopted service when it was not injected; `tests/controller/test_production_wiring_startup_gate.py` proves one service, the `startup_unverified` hold, strict NJRs, release on a fresh proof and persistence of the hold on a failed proof (via `AppController(None)`, the construction `build_v2_app` takes, since Tk is not needed). **Still open (P3-2):** there is still no single composition root: `JobRepository(` is built in `JobExecutionController` and in `AppController._build_job_service`; a `PYTEST_CURRENT_TEST` branch chooses the repository path; pause/auto-run intent lives in `JobQueue` (persisted), `JobService.auto_run_enabled`/`_queue_status`, `JobExecutionController` and `AppState.auto_run_queue`. `require_normalized_records` still defaults to `False` for a directly constructed `JobService`. |
| **B7** Comfy crash containment, cancellation, readers | **Fixed** [V] | P3-3: the managed Comfy child is job-contained (a hard-killed owner cannot orphan it: `tests/utils/test_managed_process.py::test_managed_process_child_dies_when_its_owner_dies`), `stop()` reaps the tree, readers cannot die on a bad byte. P3-4: `_wait_for_history_entry` honours `cancel_token` (`tests/video/test_comfy_cancel_p3_4.py`), `ComfyApiClient.interrupt` / `delete_from_queue` exist, and `queue_prompt` raises a typed `DispatchOutcomeUnknown` and is never retried. **Residual:** a Comfy orphaned by a build that predates containment is still seen as an external runtime (launch and stop both refuse). |
| **B10** queue lock, observers, cancellation | **Mostly fixed** [V] (P3-6) | **Fixed:** (1) `JobRepository.defer_emissions()` holds observer notifications until the outermost `with` exits; `JobQueue._update_status` and `claim_next_job` run their locked section inside it, so no observer ever runs under the queue `_lock` (`tests/queue/test_queue_discipline_p3_6.py` proves an observer that reads the queue no longer deadlocks). (2) The claim (QUEUED to RUNNING), `cancel_running_job(return_to_queue=True)`, `return_undispatched_to_queue` and `require_running` updates pass `expected_status`; a return of a job that already moved on returns `None` instead of overwriting it, a claim that loses to a durable cancel raises `JobStatusChanged` and restores the heap. (4) Idle is event-driven (section 5). **Open:** (3) `JobService.cancel_current` marks CANCELLED durably before the generation actually stops; a `cancelling` status is an owner decision (audit decision 12). (5) The runner's 600 s constant (`QUEUE_JOB_SOFT_TIMEOUT_SECONDS`) only logs after the callable returns; the opt-in watchdog runtime cap covers external pids only. Other `transition_job` callers that pass no `expected_status` (completion, failure, cancel of a running job) rely on the durable UPDATE's own source-status guard. |

Related (B9, fixed in P3-5) [V]: `_json_loads` still returns the default for a corrupt stored column (one bad row must not take the history down) but now logs at ERROR and records the job id and column (`recent_integrity_errors()` in `src/queue/job_repository.py`, bounded to 200); `JobQueue._notify_status`, `JobRepository._emit` and `JobService._emit` still isolate a raising listener but log it at WARNING with its traceback. A corrupt `njr_snapshot` still raises `JobRepositoryError`.

## 12. Invariants that must not be broken

1. SQLite `JobRepository` is the only lifecycle authority. `JobQueue` is a projection. No second queue, runner, history store or compiler. The GUI never calls a runner or a backend.
2. Fresh work enters only through `JobService.submit_njrs`; a batch is all-or-none; the NJR is immutable.
3. A claim and its durable `queued -> running` transition are atomic with respect to pause, the shutdown fence, the WebUI hold and the GPU quarantine. Never add a claim path outside `claim_next_job`/`mark_running`.
4. A job that was RUNNING when the process died is terminal and action-required; nothing replays it automatically. An ambiguous dispatched generation POST is never re-sent.
5. Holds and quarantine are eligibility flags, not statuses. They never fail, drop, reorder or edit queued jobs. The GPU quarantine survives restart and is released only by operator confirmation plus fresh host evidence.
6. Only a process a manager launched is ever stopped, restarted or killed. External A1111/Forge/Comfy processes are never adopted, restarted or killed; an occupied endpoint refuses launch. No port discovery.
7. Forge work needs a positively identified Forge (live, or same-session attestation of the owned process) before every stage's first dispatch; mismatch is refused with no backend fallback.
8. Readiness epochs and manager READY events are triggers. Releasing a hold needs a fresh readiness plus identity proof.
9. Shutdown order is fence -> cancel -> teardown -> quiescence -> repository close. Never close the repository under a live worker.
10. Each process manager owns its own anonymous container; never name or share a job object.
11. Persisted state goes through the repository or `src/utils/atomic_io.py`.
12. The physical-GPU hold was lifted on 2026-10-18 (section 13); the device-loss quarantine is unchanged. Protected actions need owner approval (`AGENTS.md` section 5).

## 13. GPU constraints (the standing hold was lifted on 2026-10-18)

The owner lifted the physical-GPU hold: device loss is intermittent and has no accepted root cause (`STATUS.md` Holds), and jobs are running. For this subsystem:

- Physical work (real generation, qualification, starting or stopping a managed runtime) is allowed when a package's acceptance needs it. Production `WebUIOutageCoordinator.recover` performs a real owned restart on a confirmed outage, and `RuntimeTransitionCoordinator` stops real owned runtimes; never trigger either against a live manager from a test, gate or CI.
- Tests must be hermetic: no WebUI, model, GPU, `nvidia-smi` or display. The autouse fixtures pin `STABLENEW_GPU_HOST_PROBE=0`, `STABLENEW_GPU_SESSION_TELEMETRY=0`, `STABLENEW_WEBUI_AUTOSTART=0`, `STABLENEW_COMFY_AUTOSTART=0`, `STABLENEW_NO_WEBUI=1`, and replace the WebUI container with a no-op. Inject probes, manager getters, clocks and runners instead of touching the real ones.
- Do not weaken containment to "make progress": no auto-release of the quarantine, no hold release without proof, no recovery while quarantined, no replay of failed work.
- Restart-while-queued physical verification (held then released against a running Forge) is an open owner decision, not something to run opportunistically.

## 14. How to test

Configuration is `pyproject.toml` only. Run `python tools/ci/run_pr_gate.py` for the required gate; run focused tests first.

| Area | Tests | Hermetic seam |
|---|---|---|
| Repository, queue, claims, fence, atomic admission | `tests/queue/` (`test_job_repository_sqlite.py`, `test_job_queue_basic.py`, `test_batch_admission_atomicity.py`, `test_dispatch_fence_unit_140.py`) | `JobRepository(":memory:")`, `src/queue/stub_runner.py`, `tests/helpers/njr_queue_harness.py` |
| Worker and shutdown | `tests/queue/test_single_node_runner.py`, `test_queue_shutdown_lifecycle.py`, `test_shutdown_admission_fence_140.py`; `tests/controller/test_shutdown_*_140.py`, `test_app_controller_shutdown_v2.py` | stub run callables, thread joins |
| Outage hold, dead-endpoint cascade | `tests/queue/test_webui_outage_containment_171.py`, `test_dead_forge_cascade_172.py` | injected `probe`, `manager_getter`, `clock` on `WebUIOutageCoordinator` |
| GPU quarantine | `tests/queue/test_gpu_loss_assessment_180.py`, `test_gpu_quarantine_queue_180.py`, `test_gpu_loss_containment_180.py`, `tests/services/test_operator_readiness_gpu_180.py` | injected host probe |
| JobService, production wiring | `tests/controller/test_job_service_*.py`, `test_production_wiring_startup_gate.py`, `test_auto_run_worker_lifecycle_v2.py` | injected runner/service; `AppController(None, threaded=False)` for wiring |
| Process manager, endpoint lifecycle, connection | `tests/api/test_webui_process_manager*.py`, `test_webui_runtime_identity.py`, `test_healthcheck_v2.py`; `tests/controller/test_webui_endpoint_lifecycle_170.py`, `test_webui_connection_controller*.py` | fake process objects; `tests/helpers/fake_webui_transport.py` |
| Identity attestation | `tests/api/test_managed_forge_identity_attestation.py`, `test_managed_forge_initial_identity_settle.py` | injected clock/sleeper |
| Transition policy, readiness | `tests/services/test_runtime_transition_service.py`, `test_runtime_transition_forge.py`, `test_operator_readiness_service.py` | injected managers/providers |
| Job object isolation | `tests/utils/test_job_object_isolation.py` | real Windows job objects, no WebUI |

A new refusal or hold test should assert both the outcome and that no claim, dispatch POST or process action happened. Operator-only code in `tools/qualification/` and `tools/acceptance/` is never part of CI.

## 15. Known debt and traps

- God objects [A/V]: `src/controller/app_controller.py` (about 7.3k lines) and `src/controller/pipeline_controller.py` own wiring that belongs in one composition root (P3-2); `JobService` is 1.2k lines. Controller line ceilings are ratcheted: extract into `src/controller/app_controller_services/` or `src/controller/pipeline_controller_services/` instead of growing them.
- Two paths build a service: `PipelineController` (used) and `AppController._build_job_service` (fallback). Keep their flags identical until P3-2 removes one.
- Locking: never call something that can re-enter `JobQueue._lock` from a repository observer or from inside `_update_status`/`claim_next_job`; notify after release.
- Adding a lifecycle state (for example `cancelling`, audit P3-6) is a schema change: the `CHECK` constraint and `REPOSITORY_SCHEMA_VERSION` have no migration path today, and `JobStatus`, `_ALLOWED_TRANSITIONS`, history views, the batch projection and the recovery code all enumerate statuses.
- Cancellation is cooperative through `CancelToken`; the backends and stages must poll it. A cancelled job's durable status can precede the end of the generation.
- Hold bookkeeping: the WebUI hold and fence are in memory by design; the GPU quarantine is not. Do not persist the former or make the latter expire.
- `JobService.run_now`/`run_next_now` swallow errors in places and legacy `submit_job_with_run_mode` still exists for non-NJR jobs; new work should use `submit_njrs`.
- Empty `except`/listener swallowing is widespread (ratcheted in `tools/ci`); when debugging a missing event, check the swallow sites listed in section 11 first.
- The orphan monitor and `SingleInstanceLock.is_gui_running` gate WebUI launches: a headless tool or test that builds a real manager will be refused, by design.
- `ComfyProcessManager.__init__` registers itself globally even if it never launches; the transition coordinator and outage coordinator read that global.

- Repository size [V]: every job row carries its full NJR snapshot (average about 51 KB, Learning model-comparison jobs about 1.2-1.5 MB, see `docs/Subsystems/Learning/LEARNING.md`) and its `result_json`; nothing prunes rows whose images and manifests were deleted. A list query that selects every column over the whole table is therefore slow; always select ids first.

## 16. How to change or extend today

- New dispatch gate (another hold): add an eligibility flag to `JobQueue` evaluated inside `_is_held_locked`, expose it through `dispatch_summary`, give it one coordinator, and decide persistence explicitly. Add the classification input to `backend_dependency.py` from frozen NJR data only.
- New runtime dependency or backend: extend `classify_frozen_identity`, `KNOWN_TRANSITION_TARGETS` and `_CONFLICTING_MANAGED_RUNTIMES`, and call `prepare_for` from the backend's `execute()`; ownership questions go to the runtime's own manager, never to the coordinator.
- New process-owning runtime: give it its own manager with ownership by launch session, an anonymous container assigned before work starts, bounded UTF-8 output readers, and no adoption of external processes (the planned `ManagedProcess` primitive, audit P3-3, is the intended home).
- New failure class for containment: add a typed category in `src/api/webui_failure_evidence.py` or `src/queue/gpu_loss_assessment.py`; a message keyword may raise suspicion but never confirms anything.
- Operator-visible state: project it from the coordinator `snapshot()` into `OperatorReadinessService`; do not read private state from the GUI.
- Update this file, `STATUS.md` (supported capabilities) and, for physical evidence, a record in `docs/Subsystems/Runtime/`.

## 17. Evidence records

Per-PR records stay in `docs/Subsystems/Runtime/` as historical evidence. They may describe superseded behavior; the code and this file win.

| Record | Why it matters |
|---|---|
| `docs/Subsystems/Runtime/PR-RUNTIME-SHUTDOWN-140_Shutdown_Admission_and_Repository_Quiescence.md` | The dispatch fence and quiescence-before-close contract |
| `docs/Subsystems/Runtime/PR-RUNTIME-WEBUI-LIFECYCLE-130_WebUI_Lifecycle_Convergence.md` | One managed WebUI lifecycle and recovery truth |
| `docs/Subsystems/Runtime/PR-RUNTIME-WEBUI-WATCHDOG-120_WebUI_Startup_and_UI_Watchdog_Lifecycle.md` | Startup and watchdog behavior history |
| `docs/Subsystems/Runtime/PR-RUNTIME-WEBUI-170_Managed_WebUI_Endpoint_and_Lifecycle_Consistency.md` | Authoritative endpoint, launch serialization, single-flight connection |
| `docs/Subsystems/Runtime/PR-QUEUE-WEBUI-171_Backend_Scoped_Outage_Containment.md` | Backend-scoped hold, bounded owned recovery, release on fresh proof |
| `docs/Subsystems/Runtime/PR-QUEUE-WEBUI-172_Dead_Forge_Endpoint_Cascade_Repair.md` | Dead-endpoint cascade without replay |
| `docs/Subsystems/Runtime/PR-QUEUE-GPU-180_GPU_Loss_Dispatch_Containment.md` | GPU quarantine design, evidence classes, release rules |
| `docs/Subsystems/Runtime/PR-RUNTIME-FORGE-IDENTITY-150_Managed_Forge_Identity_Attestation.md` | Same-session attestation and the initial settle |
| `docs/Subsystems/Runtime/PR-RUNTIME-100_Owned_Runtime_Transition_Policy.md` | Target-driven release policy |
| `docs/Subsystems/Runtime/PR-RUNTIME-READINESS-140_Operator_Readiness_Recovery_Projection.md` | Readiness and recovery projection |
| `docs/Subsystems/Runtime/PR-RUNTIME-110_Comfy_Video_Runner_Liveness.md` | Comfy wait liveness reporting |
| `docs/Subsystems/Runtime/DIAG-GPU-100_Hard_Crash_Correlation_and_Survivor_Telemetry.md` | The device-loss incident record behind the HOLD |
| `docs/Subsystems/Runtime/DIAG-GPU-110_Windows_Dump_Attribution.md` | Dump attribution for the same incident |
| `docs/audits/2026-10-16_repo_audit_and_roadmap.md` | Audit B2, B3, B7, B9, B10 and the P3 plan referenced above |
