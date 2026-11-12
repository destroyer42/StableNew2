# P3-2A — One construction site and a verified record for the runtime stack

Status: **AUTHORIZED for local implementation by the owner on 2026-11-12 (stage A only).** Not started.
Produced by the P3-2 decision report
([assessment](../assessments/2026-11-12_p3_2_runtime_composition_root_decision.md), measured at
`67e0e559d1998321d567e78f9b4e16cf4e6d9807`). This file is the copy-paste prompt for a fresh implementation session and
follows `docs/CODEX_WORK_PACKAGE_TEMPLATE.md`. Do not repeat the architecture discovery that remains valid; do verify the
start state. Where this file and section 10 of the assessment differ, this file wins (it carries the owner's amendments).

## Owner decision (2026-11-12)

Approved:

- **OD-1:** staged P3-2A as a behavior-preserving intermediate milestone. Full P3-2 composition-root ownership stays open
  after stage A.
- **OD-3:** remove `AppController._build_job_service` and `_single_node_runner_factory` after the required reachability
  evidence, replacing the dormant fallback with fail-closed behavior. Retain `_execute_job`,
  `PipelineController._run_job` and their tests pending a separate retirement decision.
- **OD-4:** preserve hermetic test isolation with one consolidated repository-location rule. Environment-based pytest
  detection is accepted as temporary compatibility debt, not the permanent target.
- **OD-8:** documentation updates reflecting the actual accepted architecture; exact wording is an implementation and
  detail-review responsibility.

Deferred (out of scope here): OD-2 full bootstrap-level composition and injection; OD-5 pause and auto-run ownership;
OD-6 an authoritative production-mode flag (**do not introduce an independently stored flag in stage A**); OD-7
retirement of the dormant launcher and direct-admission replay paths; OD-9 worktree sequencing (a scheduling constraint).

Required contract corrections (binding):

1. Investigate and preserve the compatibility behavior of `_job_repository_path` and `_job_history_path`. Under pytest
   the controller's stored temporary path differs from the actual in-memory repository. Do not silently replace those
   values with `None` or break operator tooling (`tools/operator_journey/golden/session.py:119`,
   `tools/operator_journey/journeys/learning_lora_strength.py:464`,
   `tests/controller/test_app_controller_lora_runtime.py:103`).
2. Check the proposed `src/app/runtime_stack.py` location against import-direction and layering rules. A different
   dependency-safe location is acceptable if required. Known fact to check first:
   `src/queue/single_node_runner.py:16` imports `src.controller.runtime_state`, so importing `src.queue` already loads
   the `src.controller` package (`src/controller/__init__.py` is empty at the measured SHA).
3. Keep `RuntimeStack` read-only and identity-verifying. It must not become another lifecycle, process, cancellation or
   state authority.
4. Treat any pre-existing startup AppState projection mismatch as a characterized finding. Preserve existing behavior;
   do not introduce an unrelated repair.
5. Distinguish actual production construction sites from permitted test and offline constructors in the source-level
   guard.
6. Preserve existing construction order, repository recovery timing, callback registration, startup readiness gating,
   deferred autostart, runner replacement, shutdown sequencing and external process ownership.
7. Reuse the existing accepted evidence where valid. Complete the full-census reachability trace before deleting dormant
   methods. Run focused deterministic validation, the prescribed late gate, and verify required hosted CI (hosted CI
   needs publication, which is not authorized here: report it as pending).
8. If a new dependency cycle, second mutable authority, unexpected repository-path change or additional lifecycle
   decision becomes necessary, stop and report rather than expand scope.

Execution authorization: a fresh top-level session and a short-lived feature branch/worktree from verified current
`origin/main`. Preserve all existing user changes. Implement, test, update necessary documentation and commit locally.
**Do not push, publish a PR, merge, modify `main`, restart any runtime, or conduct physical GPU/Forge/SVD/Comfy testing
without separate authorization.** Stop at completion of P3-2A; do not begin P3-2B or any other architecture package.

## Objective

- Outcome: in `src`, the application's `JobRepository`, `JobQueue`, `SingleNodeJobRunner` and `JobService` are each
  constructed at one production call site in one factory module; the assembled stack is a frozen, identity-verified
  `RuntimeStack`; `AppController` has no second wiring. Operator behavior and the canonical path
  `Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`
  are unchanged.
- In scope:
  1. New factory module (proposed `src/app/runtime_stack.py`, subject to correction 2):
     `resolve_job_repository_location`, `build_queue_stack`, `assemble_runtime_stack`, `RuntimeStack`,
     `RuntimeCompositionError`. `RuntimeStack` is frozen and stores identities only: repository, queue, job_service,
     history_service, job_execution_controller. `runner`, `webui_outage` and `gpu_loss` are read properties that
     delegate to `job_service`. It stores **no production flag** (OD-6) and has no behavior beyond `verify()`.
  2. `JobExecutionController.__init__` delegates repository, queue and runner construction to `build_queue_stack`
     with today's arguments (`poll_interval`, `on_status_change=self._on_status`, run callable
     `self._run_job_callback`) and today's order. Signature and single-authority guards unchanged.
  3. `PipelineController.__init__` obtains its service through `assemble_runtime_stack` (which constructs
     `JobService(queue, runner, repository, history_service=..., require_normalized_records=True)` only when none was
     injected); add `get_runtime_stack()`.
  4. `AppController`: delete `_build_job_service` and `_single_node_runner_factory`; the branch that called the builder
     raises `RuntimeCompositionError`. Remove the two dead overrides in `tests/controller/test_core_run_path_v2.py`
     (`RecordingAppController._single_node_runner_factory`, `_build_job_service`) without changing an assertion.
  5. `_job_repository_path` / `_job_history_path` (correction 1): first write a characterization test of today's
     values in production mode (workspace path) and under pytest (a unique temp path per controller, never `None`).
     Preferred change: none. Permitted change: take the adopted repository's `path` when it is not `None`, keeping the
     existing value otherwise. Any other outcome is a stop condition.
  6. Documentation listed under Documentation impact.
- Explicit exclusions: `AppController._execute_job`, its nine tests and `PipelineController._run_job`; the
  startup-gate expression at `app_controller.py:558-560`; `arm_runtime_handoff` and everything in `src/main.py`; pause
  and auto-run ownership; `JobService`, `JobQueue`, `JobRepository`, `SingleNodeJobRunner`, `ReplayEngine` and
  coordinator behavior or signatures; the `JobQueue()` and `JobService` default constructions; every process manager
  and `run_app`; widget-level composition; `JobExecutionController.replay`; the other `PYTEST_CURRENT_TEST` branches;
  the `queue._history_store` write at `app_controller.py:640-651`; any repair of an AppState projection mismatch.

## Execution class and model recommendation

- Execution class: Architectural (implementation of an approved decision).
- Execution location: Local, dedicated worktree (the owner's application runs from the main checkout; use the main
  checkout's `.venv` interpreter).
- Model recommendation: Claude Code Sonnet 5.5 XHigh; Codex GPT-6.1 Sol XHigh. Preferred host: Local/Desktop.
- Expected usage: about 12M cache-read, 50k output.
- Separable hard part worth delegating: none.

## Exact start state and authorities

- Record the task-start timestamp with timezone and all session IDs before discovery.
- Branch from verified current `origin/main`. The assessment was measured at
  `67e0e559d1998321d567e78f9b4e16cf4e6d9807`. If
  `git diff --stat 67e0e559 origin/main -- src/controller/app_controller.py src/controller/pipeline_controller.py src/controller/job_execution_controller.py src/controller/job_service.py src/app src/main.py src/app_factory.py`
  is not empty, re-derive the line numbers.
- Sequencing (OD-9): ARCH-952 and ARCH-953 edit `app_controller.py`. Check `git worktree list` and open PRs; if one is
  in flight on the same lines, report before editing.
- Preserve unrelated user changes (for example `presets/settings.json` in the main checkout).
- Authorities: `AGENTS.md`, `STATUS.md`, `docs/Subsystems/Runtime/QUEUE_AND_RUNTIME.md` sections 6, 11, 12 and 15,
  `docs/Subsystems/GUI/GUI_Ownership_Map_v2.6.md` (GUI-SEAM-730), `docs/ARCHITECTURE_v2.6.md` sections 5 and 11, and
  the assessment (sections 2, 5, 7, 11).

## Surface assessment

- Files allowed to change: the factory module (new), `src/controller/job_execution_controller.py`,
  `src/controller/pipeline_controller.py`, `src/controller/app_controller.py`,
  `tests/app/test_runtime_stack_wiring_p3_2.py` (new), `tests/app/test_runtime_stack_negative_p3_2.py` (new),
  `tests/controller/test_core_run_path_v2.py` (dead overrides only), the ratchet baselines through `--update`, the
  documents below, `docs/CODE_MAP.md` (regenerated), this file's completion report.
- Controller Surface Assessment: `app_controller.py` (ceiling 6,192, at ceiling) loses about 30 lines;
  `pipeline_controller.py` (ceiling 1,608, at ceiling) must end lower than it starts, which is why construction moves
  into the factory rather than being wrapped in the controller; `job_service.py` (1,227) and `job_history_service.py`
  (647) are untouched; `job_execution_controller.py` (455) stays under the 600-line new-controller limit. No ceiling
  rises. `controller_gui_imports` (6) is unaffected.
- Architecture authority changed: Yes, one paragraph in `docs/ARCHITECTURE_v2.6.md` section 11 (approved under OD-8).

## Acceptance and evidence reuse

1. Tests first, against unmodified `main`: golden tests G1-G9 and negative tests N1-N7 from assessment section 11 are
   written and run before any source edit, with these amendments:
   - N1 (correction 5) keeps two separate allowlists: **production construction sites** (the factory module for
     `JobRepository`, `JobQueue`, `SingleNodeJobRunner`, `JobService`; `job_service_outage.py` for the coordinators;
     `default_runtime_ports.py` for `PipelineRunner`; `webui_outage_coordinator.py` for `RuntimeHandoffGate`;
     `comfy_workflow_backend.py` for `ComfyProcessManager`; `src/main.py` and `webui_connection_controller.py` for
     `WebUIProcessManager`) and **permitted non-production constructors**, each with its reason (`job_queue.py` default
     `JobRepository()` and `job_service.py` default runner: test convenience; `migrations/sqlite_job_importer.py`:
     offline importer; `main_window_v2.py::run_app`: dormant launcher, OD-7). A site in neither list fails.
   - G8 (correction 4) records today's AppState identity and auto-run/pause projection after `build_v2_app`. If it
     shows a mismatch, pin the observed behavior, report it as a finding, and change nothing.
   - Add G10: `_job_repository_path` / `_job_history_path` characterization (in-scope item 5).
   - Add G11 (correction 6): `replace_queue_runner` leaves controller and service on the same new runner, the same
     coordinator objects observing it, and `RuntimeStack.runner` returning it.
   - No test may assert a stored production flag (OD-6).
   Each golden test must pass on `main` as written, except N1 (target allowlist) and N4 (fallback fails closed), which
   are expected to fail on `main` and pass after. Any other golden test failing on `main` is a finding: stop and report.
2. Full-census reachability trace before deleting: wrap `AppController._build_job_service` and
   `_single_node_runner_factory` with a recorder (pytest plugin, not committed) and run the census. Zero calls is
   required. One or more calls: stop, list the tests, do not delete.
3. After the change: the same golden tests pass unmodified; construction counts on the production path are exactly one
   each for repository, queue, runner, service, history service, outage coordinator and GPU coordinator, and zero for
   both process managers.
4. `python tools/ci/run_pr_gate.py --full` once, plus `python -m pytest tests/tools -q`. Hosted `required`,
   `full-suite` and `windows` are reported as pending: publication is not authorized.
5. The operator's real repository file is identical in size and mtime before and after the local runs.

- Evidence reused, not re-run: the 2026-11-12 static map and 879-test trace at `67e0e559` (valid while the start-state
  diff is empty); `tests/controller/test_production_wiring_startup_gate.py`, `tests/controller/test_shutdown_*_140.py`
  and `tests/gui_v2/test_single_composition_730.py` as the existing startup-gate, shutdown and Tk-host proofs; hosted
  CI of `67e0e559`.
- Completion evidence: deterministic tests only. Qualification claim: N/A. Not demonstrated: any physical launch;
  restart-while-queued against a running Forge (`STATUS.md` open decision 5).
- Review/Repair budget: one batched repair and reverification cycle.

## Token-Efficient Validation Plan

1. Verify layering (correction 2) with a two-line import probe before writing the module.
2. Write the golden and negative tests; run only those two files on `main`.
3. Run the census trace once.
4. Make the change; run the two files, then `tests/controller tests/app tests/queue`.
5. Ratchet tools with `--update`; `ruff check` on changed files; the gate once; `tests/tools` once.
6. `git diff --stat`, `git diff --check`; commit locally; stop.

## Stop conditions

- Any call to the fallback in the census trace, or a golden test that fails on unmodified `main` (other than N1, N4).
- A new dependency cycle, a second mutable authority, an unexpected repository-path change, or an additional lifecycle
  decision (correction 8).
- The change needs a different construction order, a late-bound run callable, a change to when interrupted jobs are
  recovered or when the startup gate is enabled, or any edit to `JobService`, `JobQueue`, `JobRepository`, the runner,
  the coordinators or `src/main.py`.
- Either controller ceiling would rise.
- Pause or auto-run ownership, a process manager, or a persisted format would have to change.
- Any test run touches the operator's real repository file.
- Another authorized package has changed the same lines.
- A second failure class remains after the one repair cycle.
- Push, PR, merge, runtime restart or physical testing would be needed to finish.

## Documentation impact

- `docs/Subsystems/Runtime/QUEUE_AND_RUNTIME.md`: section 6 (steps 1-2), section 11 B3 row ("Still open (P3-2)"),
  section 15 (remove "Two paths build a service"; correct the line count).
- `STATUS.md`: decision 11 and the Phase 3 sentence, edited in place (stage A done; full composition root still open).
- `docs/Subsystems/GUI/GUI_Ownership_Map_v2.6.md` lines 116-119.
- `docs/ARCHITECTURE_v2.6.md` section 11: one paragraph naming the runtime-stack construction site and the read-only
  record, and recording the pytest environment rule as temporary compatibility debt (OD-4).
- `docs/CODE_MAP.md`: regenerate. `docs/CODEX_MAP.md`: add the factory module to the "GUI to queue submission" row only
  if the 60-line cap allows.

## Completion report

Per `AGENTS.md` section 8: exact SHA and diff, behavior and identity evidence, outstanding risks, documentation impact,
and the measured `Model / usage` line from `tools/usage_report.py`.
