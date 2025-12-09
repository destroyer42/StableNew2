#CANONICAL
# StableNew Coding and Testing Standards (v2.5)

---

# Executive Summary (8–10 lines)

This document defines how code must be written, structured, and tested in StableNew v2.5.  
It aligns with the canonical architecture, governance, and roadmap documents, and gives both humans and AI agents concrete rules for formatting, design patterns, test coverage, and validation workflows.  
The goal is to ensure that every change is small, reviewable, testable, and consistent with the job lifecycle and subsystem boundaries.  
All pipeline, controller, and queue changes MUST be covered by targeted tests; GUI changes SHOULD include behavior tests whenever feasible.  
These standards also define how to design pure functions, dataclasses, and adapters, and how to structure tests around ConfigMergerV2, JobBuilderV2, NormalizedJobRecord, JobService, and GUI panels.  
This file is required reading for contributors and agents generating PRs that modify code.

---

# PR-Relevant Facts (Quick Reference)

- All code changes must follow these standards.  
- Pure logic (mergers, builders, job models) MUST be in testable, GUI-independent modules.  
- Controllers must be thin orchestrators and heavily tested via integration tests.  
- GUI code must not embed pipeline or queue logic; it must call controller methods.  
- Tests MUST be written “failing first” for logic-affecting changes.  
- No PR may reduce test coverage in critical subsystems (pipeline, controller, queue).  
- Coding style emphasizes explicitness, immutability where practical, and small functions.  

---

============================================================
# 0. TLDR / BLUF — Coding & Testing Cheat Sheet
============================================================

### 0.1 Coding TLDR

- **Use dataclasses** for structured data (configs, overrides, job records).  
- **Keep logic pure** where possible (no side effects, no global state).  
- **Respect subsystem boundaries** (GUI vs controller vs pipeline vs queue vs runner).  
- **Minimal imports across boundaries** — prefer adapters and typed interfaces.  
- **No “magic paths”** that bypass ConfigMergerV2, JobBuilderV2, or NormalizedJobRecord.

### 0.2 Testing TLDR

- Pipeline changes → **unit tests + integration tests**.  
- Controller changes → **integration tests** (controller ↔ pipeline ↔ queue).  
- Queue changes → **lifecycle + ordering tests**.  
- GUI changes → **behavior tests** when feasible (panel state, callbacks, preview/queue wiring).  
- All meaningful logic must be tested **failing first**.  

### 0.3 Structure TLDR

- `src/` is for production code.  
- `tests/` mirrors the package layout (e.g., `tests/pipeline`, `tests/controller`, `tests/gui_v2`).  
- Names reflect responsibilities (e.g., `config_merger_v2.py`, `job_builder_v2.py`).  
- Test files follow `test_<module>_v2.py` or similar pattern.

---

============================================================
# 1. Purpose and Scope
============================================================

This document is the **sole canonical reference** for:

- Coding style
- Structural patterns
- Testing strategy
- CI expectations
- How to write, adapt, and test code in StableNew

It applies to:

- All new code (v2.5+)  
- All refactors of existing code  
- All AI-generated PRs  
- All manual PRs touching pipeline, controllers, queue, GUI, or tests  

It does NOT restate architecture or governance rules; it operationalizes them.

---

============================================================
# 2. Core Coding Principles
============================================================

### 2.1 Single Source of Truth

- Config and pipeline behavior must be defined once and reused.
- The job lifecycle (ConfigMergerV2 → JobBuilderV2 → NormalizedJobRecord → Queue → Runner) is the **only** valid path.
- No parallel or duplicate config systems.

### 2.2 Purity & Immutability Where Possible

- Prefer pure functions that return new objects rather than mutating inputs.
- Dataclasses representing configs should be treated as immutable from callers’ perspective, even if fields are technically mutable.

### 2.3 Explicit Over Implicit

- Avoid magic numbers, hidden state, and “doEverything()” APIs.
- Prefer explicit arguments and clearly named dataclasses.

### 2.4 Small, Composable Units

- Functions and methods should be small and focused.
- Split complex logic into helpers.
- Pipeline steps should be testable in isolation.

---

============================================================
# 3. File and Module Structure
============================================================

### 3.1 Production Code Layout

- `src/gui/...` — GUI V2 views, panels, widgets, AppState.  
- `src/controller/...` — AppController, PipelineControllerV2, and similar orchestrators.  
- `src/pipeline/...` — ConfigMergerV2, JobBuilderV2, job models (NormalizedJobRecord), run config structures.  
- `src/queue/` or `src/pipeline/job_service.py` — job queue, job service, lifecycle logic.  
- `src/randomizer/...` — Randomization engine and plan dataclasses.  
- `src/learning/...` — Learning System modules (Phase 2).  
- `src/cluster/...` — Cluster compute modules (Phase 3).

### 3.2 Tests Layout

- Mirror production layout:  
  - `tests/pipeline/test_config_merger_v2.py`  
  - `tests/pipeline/test_job_builder_v2.py`  
  - `tests/controller/test_pipeline_controller_v2.py`  
  - `tests/gui_v2/test_preview_panel_v2.py`  
  - `tests/gui_v2/test_queue_panel_v2.py`  

Each major module should have at least one corresponding test file.

---

============================================================
# 4. Coding Conventions
============================================================

### 4.1 Naming

- Modules: `snake_case`, with `_v2` or `_v2_5` suffix where needed to distinguish from legacy.
- Classes: `PascalCase` (`ConfigMergerV2`, `JobBuilderV2`, `NormalizedJobRecord`).
- Functions: `snake_case`, descriptive (`merge_pipeline_config`, `build_jobs`, `to_ui_summary`).
- Tests: `test_<concise_behavior_name>`.

### 4.2 Dataclasses

- Use `@dataclass` for structured data, with `frozen=True` where practical for flags and config descriptors.
- Provide default factories for lists/dicts.
- Define `to_queue_snapshot()` / `to_ui_summary()` adapters on models instead of performing transformations in controllers.

### 4.3 Imports and Dependencies

- Avoid cross-layer imports that break boundaries (e.g., GUI importing pipeline internals).
- Use type-only imports to minimize circular dependencies.
- Centralize shared types in clearly named modules (e.g., `job_models_v2.py`).

---

============================================================
# 5. Pipeline & Job Model Coding Standards
============================================================

### 5.1 ConfigMergerV2

- Must remain **pure**: no side effects, no I/O.
- Must not import GUI or controllers.
- Must handle override flags and nested stage configs deterministically.
- Tests must cover:
  - override off → base config preserved
  - override on → overrides applied
  - nested stage disable behavior
  - immutability (input configs unchanged)

### 5.2 JobBuilderV2

- Must accept:
  - MergedRunConfig
  - RandomizationPlanV2 (if present)
  - Batch and output settings
- Must emit:
  - A list of NormalizedJobRecord objects
- Must not:
  - Interact with GUI
  - Write to disk
  - Communicate with queue or runner
- Tests must cover:
  - Single-job builds
  - Variant and batch expansion
  - Seed modes
  - Correct variant/batch indices

### 5.3 NormalizedJobRecord

- Central job representation.
- Must define:
  - config snapshot
  - seed
  - variant_index, batch_index
  - output settings
  - metadata for UI and queue
- Must be convertible:
  - To queue format (`to_queue_snapshot`)
  - To UI summary (`to_ui_summary`)
- Tests must verify conversions and data integrity.

### 5.4 Prompt & Config Resolution Tests

- Resolver tests are mandatory: `UnifiedPromptResolver` must be covered for concatenating GUI/pack prompts, applying global negatives, and truncating previews deterministically.
- `UnifiedConfigResolver` must be exercised for stage flag propagation, batch/seed resolution, and final-size overrides so the job summary DTOs can reflect what the runner executes.
- An end-to-end "resolution path" test (bridging builder → summary dto) must exist so preview, queue, and normalized records all share the same `ResolvedPrompt`/`ResolvedPipelineConfig`.
- Use `PipelineController.get_gui_model_defaults` to seed GUI-stage cards and `PipelineController.build_merged_config_for_run` when constructing run payloads so model/profile defaults flow through the controller instead of being read ad-hoc.

---

============================================================
# 6. Controller Coding Standards
============================================================

### 6.1 Responsibilities

Controllers must:

- Read from AppState
- Invoke ConfigMergerV2 and JobBuilderV2
- Submit jobs to JobService
- Assemble normalized snapshots (prompt_pack_id, resolved prompt, stage chain, pack metadata) before reaching JobService; AppController wires `require_normalized_records=True` so prompt-pack-only JobService instances reject incomplete submissions.
- Update Preview/Queue panels with normalized jobs
- Enforce run-mode semantics (direct vs queue)
- Never embed pipeline logic directly
- Controller tests should rely on JobService's runner DI (e.g., `stub_runner_factory` returning `StubRunner`) so the canonical run path is exercised without launching real pipelines (`tests/controller/test_core_run_path_v2.py` demonstrates this pattern).

### 6.2 Patterns

- Use small helper methods like `_build_normalized_jobs_from_state`.
- Inject dependencies (job_builder, job_service) for testability.
- Avoid deep nesting; prefer clearly named helper methods.

### 6.3 Testing

- Use integration tests:
  - Given AppState + config + randomization plan
  - Verify correct jobs are built and passed to JobService
- Use mocks/spies for JobService to assert calls, not actual execution.
- Add regression tests that instantiate JobService with `require_normalized_records=True` and confirm submissions without normalized snapshots are rejected so the PromptPack-only invariant remains enforced (`tests/controller/test_job_service_normalized_v2.py` already demonstrates this pattern).

---

============================================================
# 7. GUI Coding and Testing Standards
============================================================

### 7.1 GUI Responsibilities

GUI panels must:

- Create and manage widgets.
- Reflect state from AppState.
- Forward events to controllers via callbacks.
- Render normalized job summaries in preview and queue panels.

They must NOT:

- Perform merging or building logic.
- Call JobService directly.
- Decide on pipeline sequencing.

### 7.2 Dark Mode & Styling

- Use theme tokens defined in theme_v2 (or equivalent).
- Do not hard-code colors or fonts; rely on style configuration.
- Fix known light-mode leftovers as incremental PRs with visual checks.

### 7.3 GUI Testing

- Use GUI tests (skipped if Tk not available) to verify:
  - Panel creation does not error.
  - Callbacks are wired correctly (on_click, on_change).
  - PreviewPanel and QueuePanel update correctly given normalized jobs.
- Prefer small, focused tests over giant UI flows.

### 7.4 Process Leak Investigation (Phase 0)

- `Ctrl+Alt+P` now shows a diagnostic log for the process inspector that enumerates Python processes whose `cwd`, `cmdline`, or StableNew-specific environment markers match the repo. The results are rendered in the UI log panel and the log trace handler so they can be paired with Task Manager/Process Explorer snapshots.
- `[PROC]` log lines are emitted whenever legacy launch pathways spawn new Python processes (e.g., WebUI startup helpers). Each line includes `run_session`, PID, the quoted command line, and the launch working directory so it is easy to correlate with OS-level observations.
- The inspector and logging hooks are purely observability-focused in Phase 0: nothing automatically kills processes or polls in the background. Use them to capture suspicious runs, note the `run_session` IDs, and feed those findings into later phases that will safely terminate stray trees.

### 7.5 Job-Bound Process Cleanup (Phase 1)

- `JobExecutionMetadata.external_pids` is now part of the queue/job model, and `JobService` exposes `register_external_process` plus `cleanup_external_processes` so every job can cleanly terminate its tracked PID tree via `psutil`.
- GUI Stop actions call `JobService.cancel_current()` (and the new `cancel_job` helper when needed) so the queue/runner path owns cancellation and cleanup instead of ad-hoc pipeline tokens or task-manager kills.
- Process cleanup automatically runs once a job reaches a terminal state (completed, failed, cancelled), and the new controller/GUI tests exercise this path so future phases can build additional watchdogs with confidence.
- GUI cancel controls (`Cancel Job`, `Cancel & Return`) now go through `JobService.cancel_current()` before touching the queue, ensuring the same cleanup work runs even when the job is requeued for later retry; the `cancel_current` helper locates the running job via the queue state rather than relying on the runner's private `current_job`.

---

### 7.6 Phase 2 Memory Hygiene: Child Script I/O

- `scripts/a1111_batch_run.py` introduces a lightweight `BatchRunClient` that always uses `with open(...)` and `with Image.open(...)` blocks, explicitly closes the backing `BytesIO` buffer, and runs `gc.collect()` on a configurable cadence so no large objects linger between iterations.
- `scripts/a1111_upscale_folder.py` reuses that client to execute a folder of image assets while honoring `max_images` and keeping the workload deterministic; every call is routed through the client so the same I/O discipline applies to legacy helper scripts before they send payloads to the WebUI API.
- The new script-level tests (`tests/scripts/test_batch_run_memory_hygiene.py`, `tests/scripts/test_upscale_memory_hygiene.py`) mock the session/post behavior, assert that buffers are closed and garbage-collected, and confirm the helper only touches the requested image subset so downstream runs stay bounded.

### 7.7 Phase 3 Watchdog & Resource Caps

- `WatchdogConfig` (see `src/config/app_config.py`) exposes configurable caps via `STABLENEW_WATCHDOG_*` env vars and defaults: periodic sampling (`interval_sec`), `max_process_memory_mb`, `max_job_runtime_sec`, and `max_process_idle_sec`.
- `JobService` now instantiates `JobWatchdog` threads (`src/utils/watchdog_v2.py`) once a job enters `RUNNING`; each watchdog inspects the job’s `execution_metadata.external_pids`, measures RSS/idle/runtime, and fires `[WATCHDOG]` log lines plus `cancel_job(...)` when a threshold is exceeded (any cleanup still flows through Phase 1’s process metadata hooks).
- The watchdog log prefix is visible in the GUI log panel so developers can pair `job=<id> reason=MEMORY|IDLE|TIMEOUT` entries with OS-level observations; the watchdog thread always stops when a job reaches a terminal state to avoid leaked helpers.
- Tests `tests/utils/test_watchdog_v2.py` and `tests/controller/test_job_service_watchdog.py` validate both the standalone watchdog logic and the JobService wiring that cancels jobs on violation while still cleaning up tracked processes.

### 7.8 Phase 4 OS-Level Containment

- StableNew now builds an OS-level `ProcessContainer` (job object on Windows, cgroup v2 on Linux) for every job that registers external PIDs; see `src/utils/process_container_v2.py`, `src/utils/win_jobobject.py`, and `src/utils/cgroup_v2.py`.
- Caps such as `STABLENEW_PROCESS_CONTAINER_MEMORY_MB`, `STABLENEW_PROCESS_CONTAINER_CPU_PERCENT`, and `STABLENEW_PROCESS_CONTAINER_MAX_PROCESSES` complement Phase 3’s watchdogs by configuring container-level memory/cpu/pids limits via `ProcessContainerConfig` (see `src/config/app_config.py`).
- `JobService` adds each registered PID to the container, runs Python-level cleanup first, and always calls `container.kill_all()` + `container.teardown()` when a job reaches a terminal state so an OS-level kill is guaranteed even if psutil fails; `[CONTAINER]` log lines (`PROCESS_CONTAINER_LOG_PREFIX`) make container events easy to correlate with OS-level observations.
- If the OS or environment cannot build the native container (e.g., missing privileges), the loader falls back to a `NullProcessContainer` but still logs the failure so diagnostics point back to the missing OS boundary.

### 7.9 Phase 5 Diagnostics Dashboard & Crash Reporting

- The new `DiagnosticsDashboardV2` panel (located under the Pipeline tab’s history card) consumes `JobService.get_diagnostics_snapshot()` and `system_info_v2` to show live job metadata, watchdog/cleanup events, OS container status, and StableNew-like process summaries without allowing any mutations.
- Manual crash/dump bundles are built via `src/utils/diagnostics_bundle_v2.build_crash_bundle()` and are wired to the LogTracePanel’s “Crash Bundle” button plus the `AppController.generate_diagnostics_bundle_manual()` helper so users can capture a consistent record on demand.
- The same bundling helper also fires when unexpected exceptions propagate through `sys.excepthook`, Tk’s `report_callback_exception`, worker-thread hooks, or `JobService.EVENT_WATCHDOG_VIOLATION`, so every failure includes logs, job metadata, process enumerations, and anonymized system info in `reports/diagnostics/`.

### Phase S1 Unified Debug Hub (V2.5)

- `DebugHubPanelV2` brings Pipeline, Prompts, API, Processes, Crash Reports, and System tabs into one window and is accessible from the header "Debug" button wired through `AppController.open_debug_hub()`/`MainWindowV2` (no executor or pipeline core changes are required).
- The Pipeline tab reuses `DiagnosticsDashboardV2`, the Prompts tab surfaces `NormalizedJobRecord` prompt metadata, the API tab hosts `LogTracePanelV2`, the Processes tab lists `iter_stablenew_like_processes()`, and the Crash tab surfaces zipped bundles stored under `reports/diagnostics/`.
- Both the Debug Hub (Pipeline tab) and the Job History panel expose an “Explain This Job” action that launches `JobExplanationPanelV2`, which reads `runs/<job_id>/run_metadata.json` plus stage manifests (`txt2img_01.json`, `img2img_01.json`, `upscale_01.json`) to summarize the origin, prompts/negatives, and global-negative merge for the selected job without manual file browsing.
- The Processes tab now surfaces the background auto-scanner status and toggle, leveraging `ProcessAutoScannerService` to scan every ~30s, protect tracked job PIDs, and log/terminate strays when they exceed idle/memory thresholds; `tests/utils/test_process_auto_scanner_service.py` cover the detection logic.
- Because the hub reuses existing controller hooks, process inspectors, and diagnostics bundles, it stays read-only and non-blocking; `tests/gui_v2/test_debug_hub_panel_v2.py` exercises the new tab layout so regressions can be caught early.

### 7.10 Phase 6 Unified Error Model & Exception Taxonomy

- `src/utils/error_envelope_v2.py` and `src/utils/exceptions_v2.py` now provide a shared `UnifiedErrorEnvelope`, `wrap_exception`, and taxonomy (`PipelineError`, `WebUIError`, `WatchdogViolationError`, `ResourceLimitError`, etc.) so every failure carries `error_type`, `subsystem`, `severity`, `stage`, `remediation`, and contextual metadata.
- The pipeline runner, executor, JobService, watchdog, and PipelineController wrap and re-log exceptions through `wrap_exception`/`log_with_ctx`, store `Job.error_envelope`, and expose the serialized envelope via diagnostics snapshots so downstream tooling has consistent, machine-readable failure records.
- LogTracePanelV2 highlights structured error lines, and AppController now surfaces `ErrorModalV2` plus crash-bundle context whenever runs fail, giving users remediation tips, stack traces, the current envelope snapshot, and a direct way to open `reports/diagnostics/`.
- Diagnostics bundles sanitize local paths, include `[DIAG]` log notifications, and surface the last bundle's filename in the dashboard so support engineers can pair GUI logs with zipped evidence without exposing user-sensitive paths.

### 7.10 Job Lifecycle Logging

- `JobLifecycleLogger` writes structured `JobLifecycleLogEvent` entries into `AppStateV2.log_events` whenever the GUI adds a draft job, enqueues a preview, or JobService updates a job's running/completed status. The buffer is capped via `log_events_max` so the console stays responsive.
- `DebugLogPanelV2`, embedded in the Pipeline tab, subscribes to `log_events` and renders the most recent entries as `HH:MM:SS | source | event | job=...`. This gives operators an in-app narrative of Add-to-Job, Add-to-Queue, runner picks, and completions without tailing external logs.

### 7.11 Job Snapshotting & Replay (Phase 9)

- Each `Job` now carries a precise JSON snapshot built by `src/utils/snapshot_builder_v2.py` that serializes the normalized job, effective prompts, run config, stage metadata, model selection, seeds, and randomizer summary; this snapshot is attached before the job is queued so it survives the entire lifecycle.
- `JobHistoryService` persists the snapshot (`JobHistoryEntry.snapshot`) via the history store so every completed or failed job keeps a deterministically replayable record alongside the existing payload summary, timestamps, and result fields.
- The history panel renders a new `Replay Job` button that fires `AppController.on_replay_history_job_v2`, which delegates to `PipelineController.replay_job_from_history(entry.job_id)`; the controller rebuilds the normalized job from the snapshot, updates the preview list, and re-queues the job through `_to_queue_job()` → `JobService.submit_job_with_run_mode()` so the core run path is exercised again.
- Snapshot/replay coverage lives in `tests/utils/test_snapshot_builder_v2.py`, `tests/controller/test_pipeline_replay_job_v2.py`, and `tests/gui_v2/test_job_history_panel_v2.py`, and architecture/docs now describe the replay flow so QA and investigation tooling can rely on deterministic reproduction of any historical run.

### 7.12 Snapshot-Based Regression Suite (Phase 10)

- The regression harness in `tests/regression/test_snapshot_regression_v2.py` loads curated snapshots from `tests/data/snapshots/` and replays them via `PipelineController.reconstruct_jobs_from_snapshot` + `_submit_normalized_jobs()` to ensure the canonical AppController → PipelineController → JobService path stays functional for known-good job patterns.
- Each snapshot JSON was produced with `build_job_snapshot(...)` and stores the run config, normalized job, effective prompts, stage metadata, seeds, and randomizer expansion info; the README in the snapshot folder documents how to add new fixtures.
- Run the suite with `pytest -m snapshot_regression` to verify that the pipeline still reconstructs/takes the job path without hitting SDWebUI. The tests assert the expected stage sequence, variant counts, and that the job is enqueued through the stubbed JobService once the snapshot is replayed.

### 7.12 Phase 8 Unified Logging & Telemetry Harmonization

- `src/utils/logger.py` now attaches JSON payload metadata to every `log_with_ctx` call, exposes `JsonlFileHandler`/`JsonlFileLogConfig`, and lets consumers enable `attach_jsonl_log_handler` so `logs/stablenew.log.jsonl` holds per-line JSON suitable for crash bundles or offline analysis.
- `AppController` wires `attach_jsonl_log_handler` through `get_jsonl_log_config`, making the same JSONL stream available to diagnostics bundles without touching pipeline or controller logic.
- `LogTracePanelV2` gained subsystem/job filters, payload-aware summaries, and the ability to highlight `job_id`, `subsystem`, and `stage` so GUI logs become easier to scan and diagnose across V7/V8 telemetry layers.
- Crash bundles and diagnosis zips now copy the active JSONL file (plus rotations) straight into `logs/` inside the archive, letting support engineers correlate GUI output with log lines without needing bespoke parsing scripts.
### 7.11 Phase 7 Retry Semantics & Recovery

- `src/utils/retry_policy_v2.py` introduces stage-aware policies (txt2img, img2img, upscale) so the WebUI client knows how many retry attempts to make, which backoff strategy to use, and how much jitter to add before each retry.
- `SDWebUIClient._perform_request` now accepts an optional `stage`/`policy`, logs every failed attempt with a `LogContext`, and fires a configurable `retry_callback` so downstream services can persist retry metadata.
- `JobService.record_retry_attempt` stores each attempt inside `JobExecutionMetadata.retry_attempts`, and the runner path (`SingleNodeJobRunner._ensure_job_envelope`) attaches those events to the resulting `UnifiedErrorEnvelope.retry_info` so dashboards, crash bundles, and GUI error modals reveal retry history.
- Tests `tests/api/test_webui_retry_policy_v2.py` and `tests/controller/test_job_retry_metadata_v2.py` guarantee the policy application and metadata plumbing work without touching the pipeline core, keeping the new behavior isolated.

============================================================
# 8. Queue & Runner Testing Standards
============================================================

### 8.1 Queue Tests

- Must verify:
  - Jobs are enqueued in correct order.
  - Reordering works as expected.
  - Removal (single job, clear queue) works correctly.
  - States (pending, running, completed, failed, cancelled) transition correctly.
  - History recording tests verify JobService → JobHistoryService flows capture completed and failed jobs.
  - JobService emits `EVENT_JOB_STARTED`, `EVENT_JOB_FINISHED`, and `EVENT_JOB_FAILED` callbacks whenever those queue state transitions occur so that GUI/history listeners can sample lifecycle changes.

### 8.2 Runner Tests

- Should validate:
  - Stage ordering: txt2img → img2img → refiner → hires → upscale → adetailer.
  - Stage skipping: disabled stages are skipped.
  - Proper passing of intermediate images/metadata.

### 8.3 Integration Tests

- Controller + JobService + Runner integration tests should confirm:
  - Correct pipeline payloads.
  - Correct job metadata preserved.

---

============================================================
# 9. Randomizer & Learning Testing Standards
============================================================

### 9.1 Randomizer

- Engine must be:
  - Deterministic with fixed seed.
  - Independent of GUI and JobService.
- Tests must cover:
  - Variant combinations.
  - Seed mode behavior.
  - Max variants truncation.
  - Isolation from legacy randomizer.

### 9.2 Learning System (Phase 2)

- Must record:
  - Config snapshot
  - Seed
  - Prompt
  - Runtime metrics
  - Quality metrics (manual/auto)
- Tests:
  - Learning record schema stability.
  - No pipeline behavior changes caused by learning hooks.
  - End-to-end tests verifying learning data written correctly.

---

============================================================
# 10. Test Strategy: Failing First and CI
============================================================

### 10.1 Failing First

- Before making changes, write failing tests that capture the desired behavior.
- Then:
  - Implement code
  - Run tests
  - Validate all pass
- This enforces behavior-driven development and reduces regressions.

### 10.2 CI Expectations

- PRs must run pytest on modified test suites.
- No PR may merge with failing tests (except explicitly documented flaky tests, and even then sparingly).
- Coverage goals:
  - Pipeline and controller code: very high coverage.
  - GUI: targeted coverage for behavior-critical paths.

---

============================================================
# 11. Examples & Patterns
============================================================

### 11.1 Good Pattern: Pipeline Function

```python
def merge_and_build_jobs(
    base_config: RunConfigV2,
    overrides: StageOverridesBundle,
    randomization_plan: RandomizationPlanV2,
    batch_settings: BatchSettings,
    output_settings: OutputSettings,
    *,
    merger: ConfigMergerV2,
    builder: JobBuilderV2,
) -> list[NormalizedJobRecord]:
    merged = merger.merge_pipeline(base_config, overrides)
    jobs = builder.build_jobs(
        merged_config=merged,
        randomization_plan=randomization_plan,
        batch_settings=batch_settings,
        output_settings=output_settings,
    )
    return jobs
11.2 Good Pattern: Controller Integration Test
python
Copy code
def test_controller_builds_jobs_and_submits_to_queue(job_builder, job_service, app_state):
    controller = PipelineControllerV2(
        app_state=app_state,
        job_builder=job_builder,
        job_service=job_service,
        # other deps...
    )

    # configure app_state...

    controller.start_pipeline_v2()

    job_builder.build_jobs.assert_called_once()
    job_service.submit_jobs.assert_called_once()
============================================================

12. Deprecated Patterns (Archived)
============================================================
#ARCHIVED
(This section is informational only; do NOT use these patterns.)

Deprecated:

Logic inside GUI event handlers that modifies pipeline behavior directly.

Controllers performing manual merging instead of using ConfigMergerV2.

Direct runner invocations bypassing JobService.

Use of V1 MainWindow pipeline code.

Untested changes to critical subsystems.

Single, massive test files that combine many subsystems.

Replaced by:

Clean layering.

Merger + Builder + Normalized job model.

JobService-managed execution.

Modular, focused test files.

End of StableNew_Coding_and_Testing_v2.5.md
