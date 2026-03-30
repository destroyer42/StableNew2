# PR-PERF-502 - GUI-Owned Runtime Host Midpoint Cutover

Status: Specification
Priority: CRITICAL
Effort: LARGE
Phase: Runtime Isolation Part A
Date: 2026-03-30

## 2. Context & Motivation

Current repo truth after `PR-PERF-501` is expected to be:

- controllers can depend on a reviewed runtime host port and protocol
- the only production implementation behind that port is still a same-process
  local adapter over `JobService`
- fresh production execution remains queue-only
- `PipelineRunner.run_njr(...)` remains the only production runner entrypoint
- `AppController` and GUI bootstrap still live in the same process as queue,
  runner, history, watchdogs, and managed runtime bootstrap

The user-visible problem remains multi-second GUI freezes during generation even
after Tk callback, log, preview, and diagnostics hot-path optimizations. That
makes same-process runtime pressure the most credible remaining cause. The repo
now needs a real production proving step where execution leaves the GUI process
without yet taking on daemon discovery and reconnect.

This PR exists now because StableNew needs a trustworthy midpoint before final
daemon promotion. The midpoint must be real enough to prove or falsify the core
hypothesis: if queue and runner ownership move off-process, the GUI should stay
materially more responsive during live generation.

Canonical references:

- `docs/ARCHITECTURE_v2.6.md`
- `docs/GOVERNANCE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/LOCAL_RUNTIME_ISOLATION_EXECUTABLE_SEQUENCE_v2.6.md`
- `docs/PR_Backlog/PR-PERF-501 - Runtime Host Port and Protocol Scaffold.md`

## 3. Goals & Non-Goals

Goals:

1. Cut production execution over to a GUI-owned child runtime host that owns
   `JobService`, queue, runner, history, watchdogs, and managed backend
   lifecycle.
2. Make the GUI a client of the runtime host through the port and protocol
   introduced in `PR-PERF-501`.
3. Remove same-process production execution ownership from the GUI stack while
   preserving queue-only semantics and the single runner entrypoint.
4. Surface runtime-host connection state, host pid, startup failures, and
   host-side diagnostics in the Debug Hub.
5. Create a midpoint implementation that can be promoted into a detached daemon
   later without another protocol rewrite.

Non-Goals:

1. Do not introduce a detached daemon or reconnect behavior in this PR.
2. Do not add remote, multi-user, or network-exposed runtime hosting.
3. Do not create or preserve a user-selectable same-process production fallback.
4. Do not change NJR schema, queue semantics, or runner execution semantics.
5. Do not modify `src/pipeline/pipeline_runner.py` or `src/pipeline/executor.py`
   except via already-approved public seams created by earlier PRs.

## 4. Guardrails

This PR must preserve the following invariants:

1. `NormalizedJobRecord` remains the only executable outer job contract.
2. Fresh production execution remains queue-only.
3. `PipelineRunner.run_njr(...)` remains the only production runner entrypoint,
   now executed inside the child host process.
4. StableNew remains the orchestrator; the child host is an internal runtime
   ownership boundary, not a second orchestration system.
5. The GUI may render state and send commands, but must not remain a production
   writer of queue, history, watchdog, or runtime-manager truth after cutover.

Boundaries the executor must not cross:

1. Do not invent a second job model or an alternate direct execution path.
2. Do not expose backend-local workflow JSON or backend payloads through the
   runtime host protocol.
3. Do not leave both old and new production paths active after cutover.
4. Do not move queue policy or builder logic into GUI files.

Contract statement:

- This PR may touch startup, controller wiring, runtime-host modules,
  diagnostics surfaces, config flags, and queue-service integration.
- This PR may change production runtime ownership.
- This PR may not change NJR, queue-only submission semantics, or runner public
  execution semantics.

## 5. Allowed Files

### Files to Create

- `src/runtime_host/*.py`
- `tests/runtime_host/test_*.py`
- `tests/integration/test_runtime_host_*.py`
- `tests/controller/test_*runtime_host*.py`
- `docs/CompletedPR/PR-PERF-502-GUI-Owned-Runtime-Host-Midpoint-Cutover.md`

### Files to Modify

- `src/app_factory.py`
- `src/main.py`
- `src/controller/app_controller.py`
- `src/controller/pipeline_controller.py`
- `src/controller/job_service.py`
- `src/config/app_config.py`
- `src/gui/panels_v2/debug_hub_panel_v2.py`
- `src/gui/views/diagnostics_dashboard_v2.py`
- `src/app/bootstrap.py`
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
- unrelated GUI feature files outside diagnostics surfaces and minimal bootstrap
  or controller fallout
- `docs/GOVERNANCE_v2.6.md` unless human review explicitly requires wording
  alignment after implementation evidence is gathered

## 6. Implementation Plan

### Step 1 - Add the child runtime host bootstrap and entrypoint

What changes:

- implement the production child-host server using the port and protocol from
  `PR-PERF-501`
- create a host bootstrap path that initializes the GUI kernel, `JobService`,
  queue, runner, history store, watchdogs, and managed runtime ownership inside
  the child process

Why it changes:

- the midpoint must prove real process separation, not just a new abstraction

Files touched in this step:

- `src/runtime_host/*.py`
- `src/app/bootstrap.py`

Tests:

- add host bootstrap and protocol handshake tests under `tests/runtime_host/`

### Step 2 - Add the GUI-side runtime client and startup launcher

What changes:

- add a GUI-side runtime client that connects to a GUI-owned child host
- update startup so production app creation launches the child host and waits
  for a bounded handshake before enabling runtime-backed actions
- surface clear startup failure messages if the child host cannot initialize

Why it changes:

- the GUI must stop owning the runtime directly while still presenting a stable
  local app experience

Files touched in this step:

- `src/app_factory.py`
- `src/main.py`
- `src/runtime_host/*.py`
- `src/config/app_config.py`

Tests:

- add client-launcher tests and failed-handshake tests

### Step 3 - Rewire controllers to the production runtime client

What changes:

- change `AppController` and `PipelineController` production wiring to use the
  runtime client rather than a local adapter
- keep the local adapter available only for tests and DI scenarios
- ensure controller event delivery still marshals onto the GUI thread

Why it changes:

- after this PR, the GUI should consume host state rather than own queue and
  runner behavior locally

Files touched in this step:

- `src/controller/app_controller.py`
- `src/controller/pipeline_controller.py`
- `src/app_factory.py`

Tests:

- update controller tests to exercise runtime-client-backed behavior where
  appropriate

### Step 4 - Move managed backend lifecycle into the child host

What changes:

- relocate WebUI and Comfy runtime bootstrap, monitoring, and cleanup ownership
  from GUI startup into the host process
- ensure host-owned pids continue to register through `JobService` cleanup and
  watchdog seams

Why it changes:

- the midpoint will not be a meaningful process-isolation test if managed
  runtime ownership remains in the GUI process

Files touched in this step:

- `src/main.py`
- `src/runtime_host/*.py`
- `src/controller/job_service.py`
- `src/config/app_config.py`

Tests:

- add cleanup, watchdog, and host-pid propagation tests

### Step 5 - Extend diagnostics and Debug Hub host visibility

What changes:

- add runtime-host connection state, host pid, protocol version, startup error,
  and host-owned diagnostics visibility to the Debug Hub surfaces
- ensure diagnostics snapshots clearly distinguish GUI-client state from host
  runtime state

Why it changes:

- midpoint soak validation depends on being able to see host state explicitly

Files touched in this step:

- `src/gui/panels_v2/debug_hub_panel_v2.py`
- `src/gui/views/diagnostics_dashboard_v2.py`
- `src/controller/app_controller.py`
- `src/runtime_host/*.py`

Tests:

- add GUI diagnostics tests covering host-state rendering and failure surfaces

### Step 6 - Hardening before midpoint adoption

What changes:

- add explicit shutdown RPC and parent-driven host teardown
- add parent-death and stale-child cleanup handling
- ensure host crash or disconnection is surfaced clearly in the GUI instead of
  silently freezing controls

Why it changes:

- the midpoint should be safe enough to soak before daemon promotion begins

Files touched in this step:

- `src/runtime_host/*.py`
- `src/main.py`
- `src/app_factory.py`
- diagnostics-related controller code as needed

Tests:

- add host-crash, disconnect, and shutdown integration tests

### Step 7 - Closeout and bookkeeping

What changes:

- update canonical docs that now reflect changed runtime ownership truth
- add the final CompletedPR record after implementation

Why it changes:

- this PR changes runtime behavior enough that canonical docs and closeout
  bookkeeping must move in the same PR

Files touched in this step:

- `docs/ARCHITECTURE_v2.6.md`
- `docs/DEBUG HUB v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`
- `docs/CompletedPR/PR-PERF-502-GUI-Owned-Runtime-Host-Midpoint-Cutover.md`

Tests:

- no additional code tests; documentation validation must cite the implemented
  behavior and the passing integration slices from earlier steps

## 7. Testing Plan

### Unit tests

- runtime host server bootstrap and message handling tests under
  `tests/runtime_host/`
- runtime client request and event relay tests under `tests/runtime_host/`
- controller tests proving `AppController` and `PipelineController` operate
  correctly through the runtime client

Suggested commands:

- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/runtime_host -q`
- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/controller/test_app_controller_*.py tests/controller/test_pipeline_controller_*.py -q`

### Integration tests

- child host startup and shutdown
- submit a synthetic job through the GUI-side runtime client and validate queue
  updates and canonical result propagation
- cancel a running synthetic job and confirm host-owned cleanup
- host crash or disconnect reporting to the GUI
- diagnostics snapshot retrieval showing host-specific fields

Suggested command:

- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/integration/test_runtime_host_*.py -q`

### Journey or smoke coverage

- GUI startup smoke with child-host launch
- one queue-submit and cancel smoke through the runtime client
- one diagnostics smoke with Debug Hub open during a synthetic run

### Manual verification

1. Launch the app and confirm a child runtime host starts successfully.
2. Run one real generation while repeatedly dragging, resizing, and tab-switching
   in the GUI.
3. Open the Debug Hub during generation and confirm host connection fields,
   host pid, and runtime diagnostics remain live.
4. Cancel a running job and confirm cleanup completes without leaving a stale
   child host.
5. Close the app while the host is active and confirm deterministic host
   shutdown.

## 8. Verification Criteria

### Success criteria

1. Production execution no longer runs in the GUI process.
2. The GUI remains materially more responsive during live generation than under
   the same-process baseline.
3. Queue, history, watchdog, and runtime-manager ownership are child-host-owned
   after cutover.
4. Debug Hub surfaces host connection state and host diagnostics clearly.
5. The local adapter from `PR-PERF-501` is no longer a production path.

### Failure criteria

1. Production users can still reach a same-process execution path after cutover.
2. GUI and host both write queue, history, or watchdog truth.
3. Managed runtime bootstrap remains GUI-owned in production.
4. Host disconnection or startup failure silently degrades into hung controls or
   ambiguous state.

## 9. Risk Assessment

### Low-risk areas

- reuse of the already-reviewed port and protocol from `PR-PERF-501`
- diagnostics surfacing of host pid and connection state once the client exists

### Medium-risk areas with mitigation

- startup and shutdown sequencing between GUI and child host  
  Mitigation: explicit handshake, bounded startup timeout, deterministic
  shutdown RPC, and stale-child cleanup tests.

- controller assumptions about same-process state ownership  
  Mitigation: migrate controllers to consume host snapshots only and extend
  controller tests under the runtime client.

### High-risk areas with mitigation

- state divergence between GUI and child host  
  Mitigation: make the host the only production writer of queue, history,
  watchdog, and runtime state, and keep the GUI as a render-and-command client.

- orphan host or broken cleanup scenarios  
  Mitigation: explicit parent-death handling, teardown RPC, and host-lifecycle
  integration tests.

### Rollback plan

- revert this PR and return production wiring to the local adapter created in
  `PR-PERF-501`

## 10. Tech Debt Analysis

Debt removed:

- same-process production execution ownership in the GUI stack
- GUI-owned managed runtime bootstrap in production
- lack of explicit host-state diagnostics during generation

Debt intentionally deferred:

- detached daemon lifecycle, discovery, and reconnect  
  Next PR owner: `PR-PERF-503`
- midpoint-only lifecycle scaffolding cleanup after daemon promotion  
  Next PR owner: `PR-PERF-504`

## 11. Documentation Updates

This PR changes runtime ownership truth and therefore requires same-PR doc
updates.

Required documentation work:

1. update `docs/ARCHITECTURE_v2.6.md` if implementation evidence confirms that
   the current production topology must now be described as GUI client plus
   local child runtime host while preserving queue-only and single-runner
   invariants
2. update `docs/DEBUG HUB v2.6.md` to document host connection and host
   diagnostics surfaces
3. update `docs/StableNew Roadmap v2.6.md` to record midpoint adoption status
   and link back to the active sequence
4. update `docs/DOCS_INDEX_v2.6.md` if active doc locations or status change
5. add `docs/CompletedPR/PR-PERF-502-GUI-Owned-Runtime-Host-Midpoint-Cutover.md`
   during closeout

Explicit disposition:

- this PR spec remains active in `docs/PR_Backlog/` until implemented
- the multi-PR runtime isolation sequence remains active in
  `docs/PR_Backlog/LOCAL_RUNTIME_ISOLATION_EXECUTABLE_SEQUENCE_v2.6.md`
- after implementation, add the CompletedPR closeout and keep the sequence
  active until `PR-PERF-504` completes

## 12. Dependencies

### Internal module dependencies

- `PR-PERF-501 - Runtime Host Port and Protocol Scaffold`
- `src/app_factory.py`
- `src/main.py`
- `src/controller/app_controller.py`
- `src/controller/pipeline_controller.py`
- `src/controller/job_service.py`
- `src/runtime_host/*.py`
- existing process-container and watchdog seams already present in `JobService`

### External tools or runtimes

- local-only IPC transport and child process management
- existing WebUI and Comfy runtimes, now moved behind host ownership

## 13. Approval & Execution

Planner: GitHub Copilot  
Executor: Codex  
Reviewer: Rob  
Approval Status: Pending

## 14. Next Steps

1. Implement this midpoint only after `PR-PERF-501` lands cleanly.
2. Soak the midpoint with real generation runs and confirm it materially
   improves GUI responsiveness.
3. If the midpoint succeeds without unacceptable queue, diagnostics, or runtime
   regressions, proceed to `PR-PERF-503 - Detached Local Runtime Daemon
   Promotion`.
