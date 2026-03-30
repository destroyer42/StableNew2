# PR-PERF-503 - Detached Local Runtime Daemon Promotion

Status: Specification
Priority: HIGH
Effort: LARGE
Phase: Runtime Isolation Part B
Date: 2026-03-30

## 2. Context & Motivation

Current repo truth after `PR-PERF-502` is expected to be:

- production execution already runs through the runtime host port and protocol
  introduced in `PR-PERF-501`
- the GUI is a runtime client, but production runtime ownership still lives in a
  GUI-owned child host process
- `JobService`, queue, runner, history, watchdogs, and managed backend
  lifecycle are child-host-owned rather than GUI-thread-owned
- WebUI and Comfy lifecycle ownership have already moved out of GUI startup and
  into the host
- fresh production execution remains queue-only and
  `PipelineRunner.run_njr(...)` remains the only production runner entrypoint

If `PR-PERF-502` succeeds, StableNew will have proven the responsiveness value
of process separation, but it will still have an incomplete production runtime
story. The GUI would remain the owner of host lifetime, so GUI restart,
reconnect, and long-lived runtime continuity would still be constrained by the
midpoint topology.

This PR exists now because the midpoint is intentionally transitional. Once the
repo proves that off-process runtime ownership materially improves GUI
responsiveness, the production topology should converge on one detached local
daemon model rather than preserving GUI-owned lifetime semantics.

Canonical references:

- `docs/ARCHITECTURE_v2.6.md`
- `docs/GOVERNANCE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/LOCAL_RUNTIME_ISOLATION_EXECUTABLE_SEQUENCE_v2.6.md`
- `docs/PR_Backlog/PR-PERF-501 - Runtime Host Port and Protocol Scaffold.md`
- `docs/PR_Backlog/PR-PERF-502 - GUI-Owned Runtime Host Midpoint Cutover.md`

## 3. Goals & Non-Goals

Goals:

1. Promote the proven runtime host into a detached local daemon without
   rewriting the port, protocol, queue semantics, or runner semantics.
2. Allow the GUI to discover and connect to an existing daemon or launch one if
   none is present.
3. Preserve queue, running-job, history, and diagnostics state across GUI
   restart and reconnect.
4. Make runtime-manager emergency cleanup, backend lifecycle, and daemon
   lifetime fully daemon-owned rather than GUI-owned.
5. Establish the detached daemon as the intended production runtime topology so
   that the final cleanup PR can remove midpoint-only scaffolding.

Non-Goals:

1. Do not redesign or replace the runtime host protocol created in
   `PR-PERF-501`.
2. Do not add remote, multi-user, or network-exposed runtime hosting.
3. Do not change NJR schema, queue-only submission semantics, or runner
   execution semantics.
4. Do not remove every midpoint-only codepath in this PR; final removal belongs
   to `PR-PERF-504`.
5. Do not introduce multi-daemon coordination, cross-machine orchestration, or
   a second production queue owner.

## 4. Guardrails

This PR must preserve the following invariants:

1. `NormalizedJobRecord` remains the only executable outer job contract.
2. Fresh production execution remains queue-only.
3. `PipelineRunner.run_njr(...)` remains the only production runner entrypoint,
   now owned by the detached daemon.
4. StableNew continues to own queue policy, artifacts, history, diagnostics,
   and learning; the daemon is an internal runtime boundary, not a second
   orchestration system.
5. The GUI may discover, connect, render state, and send commands, but it must
   not resume production ownership of queue, history, watchdog, or runtime
   lifecycle truth.

Boundaries the executor must not cross:

1. Do not invent a second job model or direct GUI execution path.
2. Do not expose backend-local workflow JSON or backend payloads through the
   runtime host protocol.
3. Do not allow duplicate daemon ownership or split queue ownership between GUI
   instances and the daemon.
4. Do not move builder logic, queue policy, or backend contract invention into
   GUI files.

Contract statement:

- This PR may touch runtime-host modules, startup and discovery wiring,
  controller reconnect wiring, single-instance coordination, diagnostics
  surfaces, and runtime lifecycle ownership.
- This PR may change production runtime lifetime from GUI-owned child host to a
  detached local daemon.
- This PR may not change NJR, queue-only semantics, or runner public execution
  semantics.

## 5. Allowed Files

### Files to Create

- `src/runtime_host/*.py`
- `tests/runtime_host/test_*.py`
- `tests/integration/test_runtime_daemon_*.py`
- `tests/controller/test_*runtime_host*.py`
- `docs/CompletedPR/PR-PERF-503-Detached-Local-Runtime-Daemon-Promotion.md`

### Files to Modify

- `src/main.py`
- `src/app_factory.py`
- `src/app/bootstrap.py`
- `src/controller/app_controller.py`
- `src/controller/pipeline_controller.py`
- `src/controller/job_service.py`
- `src/utils/single_instance.py`
- `src/config/app_config.py`
- `src/gui/panels_v2/debug_hub_panel_v2.py`
- `src/gui/views/diagnostics_dashboard_v2.py`
- `tests/controller/test_app_controller_*.py`
- `tests/controller/test_pipeline_controller_*.py`
- `tests/gui_v2/test_debug_hub_panel_v2.py`
- `tests/gui_v2/test_diagnostics_dashboard_v2.py`
- `docs/ARCHITECTURE_v2.6.md`
- `docs/DEBUG HUB v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`
- `docs/PR_Backlog/LOCAL_RUNTIME_ISOLATION_EXECUTABLE_SEQUENCE_v2.6.md`

### Forbidden Files

- `src/pipeline/pipeline_runner.py`
- `src/pipeline/executor.py`
- `src/pipeline/job_models_v2.py`
- unrelated GUI feature files outside diagnostics surfaces and minimal runtime
  connection fallout
- `docs/GOVERNANCE_v2.6.md` unless human review explicitly requires wording
  alignment after implementation evidence is gathered

## 6. Implementation Plan

### Step 1 - Add detached daemon discovery and lifecycle management

What changes:

- implement daemon discovery, attachment, launch-if-absent, and single-daemon
  ownership rules using the runtime host package and local single-instance
  coordination
- define the daemon bootstrap path separately from the midpoint child-host
  launcher while reusing the existing port and protocol

Why it changes:

- detached runtime ownership requires explicit discovery and lifecycle control
  rather than parent-bound child process startup

Files touched in this step:

- `src/runtime_host/*.py`
- `src/utils/single_instance.py`
- `src/config/app_config.py`

Tests:

- add daemon discovery, duplicate-daemon rejection, and launch-if-absent tests
  under `tests/runtime_host/`

### Step 2 - Promote startup and bootstrap to the daemon model

What changes:

- update app startup so the GUI attaches to an existing daemon or launches one
  if absent, then performs a bounded handshake before enabling runtime-backed
  actions
- remove production dependence on GUI-owned host lifetime while preserving
  local-only operation

Why it changes:

- detached daemon promotion is only real if the GUI no longer owns runtime
  lifetime from process birth to teardown

Files touched in this step:

- `src/main.py`
- `src/app_factory.py`
- `src/app/bootstrap.py`
- `src/runtime_host/*.py`

Tests:

- add attach-to-existing-daemon and failed-daemon-startup tests

### Step 3 - Rewire controllers around reconnectable daemon state

What changes:

- update `AppController` and `PipelineController` to tolerate disconnect,
  reconnect, and daemon-backed state restoration without reintroducing local
  production ownership
- ensure the GUI can rehydrate queue, running-job, history, and diagnostics
  state from daemon snapshots after restart

Why it changes:

- daemon promotion is not sufficient unless the GUI can safely reconnect to the
  already-running runtime without duplicating ownership

Files touched in this step:

- `src/controller/app_controller.py`
- `src/controller/pipeline_controller.py`
- `src/app_factory.py`
- `src/runtime_host/*.py`

Tests:

- add controller reconnect and state-rehydration tests

### Step 4 - Make cleanup and backend lifetime daemon-owned

What changes:

- move emergency cleanup ownership, backend pid tracking, and runtime-manager
  lifetime semantics fully under daemon ownership
- ensure GUI exit does not silently destroy a healthy daemon, while explicit
  daemon stop and stale-daemon cleanup remain deterministic

Why it changes:

- without daemon-owned cleanup and backend lifetime, the repo would still carry
  midpoint assumptions hidden behind a new launcher

Files touched in this step:

- `src/runtime_host/*.py`
- `src/controller/job_service.py`
- `src/main.py`
- `src/config/app_config.py`

Tests:

- add daemon-owned cleanup, backend-pid registration, and stale-daemon cleanup
  tests

### Step 5 - Extend diagnostics and Debug Hub daemon visibility

What changes:

- surface daemon pid, connection mode, launch-versus-attach state, reconnect
  status, and daemon startup or disconnect errors in diagnostics and Debug Hub
- ensure diagnostics clearly distinguish GUI client state from daemon-owned
  runtime state

Why it changes:

- reconnect and daemon-lifetime debugging require explicit visibility rather
  than inferred behavior

Files touched in this step:

- `src/gui/panels_v2/debug_hub_panel_v2.py`
- `src/gui/views/diagnostics_dashboard_v2.py`
- `src/controller/app_controller.py`
- `src/runtime_host/*.py`

Tests:

- add GUI diagnostics tests for daemon connection, reconnect, and launch errors

### Step 6 - Hardening for stale daemon, upgrade mismatch, and multi-window use

What changes:

- add stale-daemon detection, unsupported-protocol handling, and clear recovery
  behavior when GUI and daemon versions do not align
- ensure multiple GUI launches attach safely without creating duplicate runtime
  owners

Why it changes:

- detached lifecycle introduces a new class of correctness risks that must be
  resolved before the midpoint can be considered retired

Files touched in this step:

- `src/runtime_host/*.py`
- `src/utils/single_instance.py`
- `src/main.py`
- diagnostics and controller code as needed for surfaced error states

Tests:

- add protocol-mismatch, stale-daemon, and second-GUI attach integration tests

### Step 7 - Closeout and bookkeeping

What changes:

- update canonical docs that now describe daemon-owned runtime lifetime as the
  active production truth
- add the final CompletedPR record after implementation

Why it changes:

- this PR changes runtime-topology truth and must move docs with the code

Files touched in this step:

- `docs/ARCHITECTURE_v2.6.md`
- `docs/DEBUG HUB v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`
- `docs/CompletedPR/PR-PERF-503-Detached-Local-Runtime-Daemon-Promotion.md`

Tests:

- no additional code tests; documentation validation must cite implemented
  daemon behavior and the passing reconnect or lifecycle slices from earlier
  steps

## 7. Testing Plan

### Unit tests

- daemon discovery, launch, and attach tests under `tests/runtime_host/`
- reconnect and state-rehydration tests for controller behavior under daemon
  ownership
- protocol mismatch and stale-daemon detection tests under `tests/runtime_host/`

Suggested commands:

- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/runtime_host -q`
- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/controller/test_app_controller_*.py tests/controller/test_pipeline_controller_*.py -q`

### Integration tests

- start the GUI with no daemon present and verify daemon launch plus handshake
- start a second GUI instance and verify safe attach without duplicate queue
  ownership
- start a synthetic job, close the GUI, relaunch the GUI, and confirm queue,
  running-job, and diagnostics state rehydrate from the daemon
- verify explicit daemon stop and stale-daemon recovery paths
- verify protocol-version mismatch is surfaced clearly and blocks unsafe attach

Suggested command:

- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/integration/test_runtime_daemon_*.py -q`

### Journey or smoke coverage

- GUI startup smoke with daemon attach or launch
- one queue-submit and cancel smoke after reconnect
- one diagnostics smoke with Debug Hub open while connected to an existing
  daemon

### Manual verification

1. Launch the app with no daemon running and confirm a detached daemon starts.
2. Submit a job, then close and relaunch the GUI while the daemon remains
   active.
3. Confirm queue, running-job, and diagnostics state reappear after reconnect.
4. Launch a second GUI instance and confirm it attaches safely without creating
   duplicate runtime ownership.
5. Stop the daemon explicitly and confirm the GUI reports the disconnect or
   recovery state clearly.

## 8. Verification Criteria

### Success criteria

1. Production runtime lifetime is daemon-owned rather than GUI-owned.
2. The GUI can reconnect to an existing daemon and recover queue, running-job,
   history, and diagnostics state without duplicating ownership.
3. The same runtime host protocol from `PR-PERF-501` remains the active
   contract.
4. Debug Hub and diagnostics clearly expose daemon connection and error state.
5. StableNew no longer requires GUI-owned host lifetime to keep generation
   running.

### Failure criteria

1. GUI restart can create duplicate queue ownership or lose authoritative
   runtime state unexpectedly.
2. Daemon promotion requires a protocol rewrite or a second incompatible
   runtime contract.
3. Production still depends on GUI-owned lifetime semantics to keep runtime
   state valid.
4. Disconnect, protocol mismatch, or stale-daemon states degrade into silent or
   ambiguous behavior.

## 9. Risk Assessment

### Low-risk areas

- reuse of the already-reviewed runtime host protocol and client contract
- diagnostics surfacing of daemon pid and attach state once daemon metadata is
  available

### Medium-risk areas with mitigation

- daemon discovery and startup sequencing  
  Mitigation: bounded handshake, attach-or-launch tests, and explicit stale
  daemon cleanup rules.

- controller assumptions about continuous local ownership  
  Mitigation: reconnect and rehydration tests that force controllers to consume
  daemon snapshots instead of local state.

### High-risk areas with mitigation

- duplicate daemon or duplicate queue ownership  
  Mitigation: single-instance coordination, daemon ownership locks, and
  multi-window attach tests.

- version mismatch between GUI and daemon  
  Mitigation: explicit protocol-version negotiation, clear rejection paths, and
  surfaced recovery messaging.

- cleanup regressions when the GUI exits but the daemon remains alive  
  Mitigation: daemon-owned cleanup rules, explicit stop paths, and integration
  tests covering GUI exit plus reconnect.

### Rollback plan

- revert this PR and return production runtime lifetime to the GUI-owned child
  host topology delivered by `PR-PERF-502`

## 10. Tech Debt Analysis

Debt removed:

- GUI-owned runtime lifetime as the active production topology
- inability to reconnect safely after GUI restart
- parent-bound host lifetime assumptions that keep the midpoint active

Debt intentionally deferred:

- removal of midpoint-only child-host scaffolding and final runtime-harmonizing
  cleanup  
  Next PR owner: `PR-PERF-504`
- final completed-plan bookkeeping once the entire runtime isolation sequence is
  fully implemented  
  Next PR owner: `PR-PERF-504`

## 11. Documentation Updates

This PR changes runtime-topology truth and therefore requires same-PR doc
updates.

Required documentation work:

1. update `docs/ARCHITECTURE_v2.6.md` to describe detached daemon runtime
   lifetime if implementation evidence confirms that daemon ownership is now the
   active production topology
2. update `docs/DEBUG HUB v2.6.md` to document daemon connection, reconnect,
   and daemon-owned diagnostics surfaces
3. update `docs/StableNew Roadmap v2.6.md` to record daemon promotion status and
   link back to the active sequence
4. update `docs/DOCS_INDEX_v2.6.md` if active doc locations or status change
5. add `docs/CompletedPR/PR-PERF-503-Detached-Local-Runtime-Daemon-Promotion.md`
   during closeout

Explicit disposition:

- this PR spec remains active in `docs/PR_Backlog/` until implemented
- the multi-PR runtime isolation sequence remains active in
  `docs/PR_Backlog/LOCAL_RUNTIME_ISOLATION_EXECUTABLE_SEQUENCE_v2.6.md`
- after implementation, add the CompletedPR closeout and keep the sequence
  active until `PR-PERF-504` completes final cleanup

## 12. Dependencies

### Internal module dependencies

- `PR-PERF-501 - Runtime Host Port and Protocol Scaffold`
- `PR-PERF-502 - GUI-Owned Runtime Host Midpoint Cutover`
- midpoint soak validation confirming materially improved GUI responsiveness
- `src/main.py`
- `src/app_factory.py`
- `src/controller/app_controller.py`
- `src/controller/pipeline_controller.py`
- `src/controller/job_service.py`
- `src/utils/single_instance.py`
- `src/runtime_host/*.py`

### External tools or runtimes

- local-only IPC transport and detached process management
- existing WebUI and Comfy runtimes, now remaining behind daemon ownership

## 13. Approval & Execution

Planner: GitHub Copilot  
Executor: Codex  
Reviewer: Rob  
Approval Status: Pending

## 14. Next Steps

1. Implement this PR only after `PR-PERF-502` lands and midpoint soak
   verification confirms materially improved GUI responsiveness.
2. After daemon promotion is stable, proceed to
   `PR-PERF-504 - Daemon Default Cleanup and Final Runtime Harmonization`.
3. Do not retire the runtime isolation sequence until midpoint-only scaffolding
   and final doc harmonization are complete.
