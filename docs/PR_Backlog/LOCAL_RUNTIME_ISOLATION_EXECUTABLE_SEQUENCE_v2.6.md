# Local Runtime Isolation Executable Sequence v2.6

Status: Active backlog proposal 2026-03-30  
Date: 2026-03-30  
Branch baseline: `feature/video-secondary-motion-pr-236`  
Applies to: GUI responsiveness under generation load, queue and runner isolation, host lifecycle, diagnostics ownership, runtime topology

## 1. Purpose

StableNew now shows cheap Tk callback timings during generation, but the product
can still hang for multi-second windows. That means the remaining freeze is no
longer best explained by the measured UI callback surfaces. The stronger
working theory was same-process starvation, native blocking, or memory-pressure
side effects while the queue and runner execute, and that theory drove the
runtime-isolation sequence below.

This sequence originally defined the approved migration path from the historical
same-process GUI plus queue plus runner topology to a local runtime host model
that can keep the GUI responsive while jobs run. `PR-PERF-502` has now
completed the midpoint cutover, so this document remains active as the backlog
sequence and soak-validation gate for the follow-through work.

The sequence is intentionally two-stage:

1. a midpoint where production execution moves into a GUI-owned child runtime
   host so the repo can prove real responsiveness gains before taking on GUI
   reconnect semantics
2. a follow-through where the same host protocol is promoted into a detached
   local daemon and the GUI becomes a pure client

The midpoint is not intended to be a separate long-term runtime story. It is a
controlled proving phase for the final daemon model.

## 2. Current Repo Truth

Historical baseline when this sequence was authored:

- fresh execution was queue-only per `docs/ARCHITECTURE_v2.6.md`
- `PipelineRunner.run_njr(...)` remained the only production runner entrypoint
- `AppController` built a local `JobService`
- `JobService` defaulted to a local `SingleNodeJobRunner`
- `SingleNodeJobRunner` started a background `QueueWorker`, but that worker
  still shared the GUI process
- WebUI and Comfy bootstrap were still launched from GUI startup flow

Current production truth after `PR-PERF-502`:

- the GUI launches a bounded-handshake child runtime host before enabling
  runtime-backed actions
- the child runtime host owns `JobService`, queue state, runner execution,
  history, managed-runtime lifecycle, watchdogs, and runtime diagnostics truth
- production controllers operate through the runtime-host client instead of a
  same-process production `JobService` path
- the same-process local adapter remains DI-only and test-only until
  `PR-PERF-503` and `PR-PERF-504` complete the daemon promotion and final
  harmonization steps

Relevant repo seams:

- `src/controller/app_controller.py`
- `src/controller/pipeline_controller.py`
- `src/controller/job_service.py`
- `src/queue/single_node_runner.py`
- `src/app_factory.py`
- `src/main.py`
- `src/utils/process_container_v2.py`

Useful current foundation:

- `JobService.set_event_dispatcher(...)` already exists as a UI-safe event seam
- `JobService.register_external_process(...)` already exists as a cleanup and
  watchdog seam for external pids
- `ProcessContainer` already exists as an OS-level containment seam

## 3. Decision

StableNew should not continue pursuing deeper in-process threading as the main
responsiveness fix. The runner is already off the Tk thread, and the remaining
freeze profile is consistent with same-process contention rather than simple UI
callback cost.

The approved direction is:

1. introduce a daemon-shaped runtime host port and protocol without changing
   behavior
2. cut production over to a GUI-owned child runtime host that owns queue,
   runner, history, watchdogs, and backend lifecycle
3. only after the midpoint proves real responsiveness improvement, promote the
   same host into a detached local daemon
4. remove midpoint-only scaffolding and leave one final production runtime story

## 4. Core Invariants

This sequence must preserve:

- `NormalizedJobRecord` as the only outer executable job contract
- queue-only fresh execution
- `PipelineRunner.run_njr(...)` as the only production runner entrypoint
- StableNew ownership of queue, lifecycle policy, artifacts, history,
  diagnostics, and learning
- no second user-visible production execution path
- no GUI-owned prompt assembly or backend contract invention

The runtime host is an implementation boundary, not a second orchestration
system.

## 5. Sequence Weaknesses and Responses

### Weakness 1: A midpoint can become a permanent second runtime story

Response:

- the midpoint host must use the same client port and protocol that the final
  daemon will use
- the midpoint is production cutover, not a side experiment with a long-lived
  fallback toggle
- the local in-process adapter remains test-only and DI-only after cutover

### Weakness 2: A direct daemon jump is too risky to debug if correctness or responsiveness regresses

Response:

- the sequence inserts a child-host proving phase before daemon promotion
- reconnect, discovery, and daemon ownership are deferred until after the repo
  verifies that process separation materially changes freeze behavior

### Weakness 3: If backend lifecycle stays GUI-owned during the midpoint, the test is incomplete

Response:

- the midpoint PR explicitly moves WebUI and Comfy lifecycle ownership into the
  child runtime host
- the GUI becomes a client for runtime state rather than the owner of backend
  bootstrap and cleanup

### Weakness 4: Splitting runtime ownership across GUI and host could create state divergence

Response:

- after midpoint cutover, the host is the only writer for queue, running-job,
  watchdog, history, and runtime diagnostics truth
- the GUI only renders host snapshots and sends commands

### Weakness 5: Child-host-only code can become migration debt later

Response:

- the sequence explicitly reserves a cleanup PR after daemon promotion
- any midpoint-only lifecycle code must be identified as removal debt owned by
  the final harmonization PR

## 6. Recommended Order and Approval Gates

### Current completion state

- `PR-PERF-501` completed on 2026-03-30.
- `PR-PERF-502` completed on 2026-03-30 and moved production execution to the
  GUI-owned child runtime host with host-owned queue, runner, managed-runtime,
  and diagnostics truth.

### Recommended next PR to approve after midpoint soak signoff

`PR-PERF-503 - Detached Local Runtime Daemon Promotion`

Reason:

- the midpoint cutover is now complete in production code and docs
- daemon promotion is the next remaining runtime-isolation change
- approval is still blocked until midpoint soak signoff confirms materially
  improved GUI responsiveness without major queue, watchdog, or diagnostics
  regressions

### Estimated execution order

1. `PR-PERF-501`  
  Dependency: none  
  Status: Completed 2026-03-30
  Delivered role: seam creation only

2. `PR-PERF-502`  
   Dependency: `PR-PERF-501`  
  Status: Completed 2026-03-30
  Delivered role: midpoint production cutover to GUI-owned child host

3. `PR-PERF-503`  
   Dependency: `PR-PERF-502` plus successful midpoint soak verification  
   Expected role: daemon promotion and reconnect

4. `PR-PERF-504`  
   Dependency: `PR-PERF-503`  
   Expected role: remove midpoint-only scaffolding and harmonize final docs

### Approval cadence

1. `PR-PERF-501` completed on 2026-03-30.
2. `PR-PERF-502` completed on 2026-03-30; midpoint soak verification is now
  the blocking gate.
3. Do not approve `PR-PERF-503` until the midpoint proves one real outcome:
   materially improved GUI responsiveness under active generation without major
   queue, watchdog, or diagnostics regressions.
4. Approve `PR-PERF-504` only after daemon behavior is proven stable enough to
   retire midpoint lifecycle code.

## 7. Dependency Graph

`PR-PERF-501 -> PR-PERF-502 -> PR-PERF-503 -> PR-PERF-504`

Additional execution gates:

- `PR-PERF-502` requires protocol and local-adapter readiness from
  `PR-PERF-501`
- `PR-PERF-503` requires explicit midpoint soak signoff from `PR-PERF-502`
- `PR-PERF-504` requires daemon promotion to be the accepted production truth

## 8. PR Sequence

### `PR-PERF-501 - Runtime Host Port and Protocol Scaffold`

Status: Completed 2026-03-30  
Priority: CRITICAL  
Effort: LARGE  
Depends on: none

Completion record:

- `docs/CompletedPR/PR-PERF-501-Runtime-Host-Port-and-Protocol-Scaffold.md`

Purpose:

- introduce a daemon-shaped runtime host port and protocol while keeping current
  behavior unchanged

Primary outcomes:

- explicit runtime host port between GUI and execution runtime
- versioned local protocol carrying canonical NJR snapshots, status events,
  diagnostics, and control commands only
- local adapter over the current `JobService`
- AppController and PipelineController depend on the new port instead of direct
  production assumptions about local `JobService`

Key file targets:

- `src/controller/app_controller.py`
- `src/controller/pipeline_controller.py`
- `src/controller/job_service.py`
- `src/app_factory.py`
- new runtime-host package under `src/`
- new protocol and controller tests under `tests/`

Execution gate:

- after this PR, the repo has one reusable runtime boundary but unchanged
  production behavior

Why this PR is first:

- it de-risks every later PR without changing live execution semantics
- it is the cleanest point to review architectural boundaries before process
  separation begins

### `PR-PERF-502 - GUI-Owned Runtime Host Midpoint Cutover`

Status: Completed 2026-03-30  
Priority: CRITICAL  
Effort: LARGE  
Depends on: `PR-PERF-501`

Completion record:

- `docs/CompletedPR/PR-PERF-502-GUI-Owned-Runtime-Host-Midpoint-Cutover.md`

Standalone execution spec:

- `docs/PR_Backlog/PR-PERF-502 - GUI-Owned Runtime Host Midpoint Cutover.md`

Purpose:

- move production execution into a GUI-owned child runtime host while keeping
  the GUI as a client

Primary outcomes:

- JobService, queue, runner, history, watchdogs, and runtime-manager ownership
  move into the child host process
- production GUI submits commands and renders host snapshots through the runtime
  client
- WebUI and Comfy lifecycle ownership move out of GUI startup and into the host
- Debug Hub surfaces host connection state and host diagnostics

Key file targets:

- `src/app_factory.py`
- `src/main.py`
- `src/controller/app_controller.py`
- `src/controller/pipeline_controller.py`
- `src/controller/job_service.py`
- `src/gui/panels_v2/debug_hub_panel_v2.py`
- `src/gui/views/diagnostics_dashboard_v2.py`
- new runtime host launcher and host entrypoint modules
- integration and smoke tests under `tests/`

Execution gate:

- a real generation run must show materially improved GUI responsiveness before
  daemon promotion proceeds

Specific midpoint validation questions:

- does process separation materially change the multi-second freeze profile?
- do queue, cancel, history, diagnostics, and watchdog flows still behave
  correctly when the GUI is only a client?

### `PR-PERF-503 - Detached Local Runtime Daemon Promotion`

Status: Proposed  
Priority: HIGH  
Effort: LARGE  
Depends on: `PR-PERF-502` plus successful midpoint soak verification

Standalone execution spec:

- `docs/PR_Backlog/PR-PERF-503 - Detached Local Runtime Daemon Promotion.md`

Purpose:

- promote the already-proven runtime host into a detached local daemon without
  changing protocol or queue semantics

Primary outcomes:

- detached daemon owns runtime lifetime
- GUI connects to an existing daemon or launches one if absent
- GUI restart and reconnect restore queue, running-job, and diagnostics state
- runtime-manager emergency cleanup and lifecycle become daemon-owned

Key file targets:

- `src/main.py`
- `src/app_factory.py`
- `src/controller/app_controller.py`
- `src/controller/pipeline_controller.py`
- `src/utils/single_instance.py`
- daemon discovery and host lifecycle modules under `src/`
- reconnect and daemon lifecycle tests under `tests/`
- canonical docs if final runtime-topology wording changes

Execution gate:

- daemon reconnect is stable enough that the GUI no longer needs to own runtime
  lifetime

### `PR-PERF-504 - Daemon Default Cleanup and Final Runtime Harmonization`

Status: Proposed  
Priority: HIGH  
Effort: MEDIUM  
Depends on: `PR-PERF-503`

Standalone execution spec:

- `docs/PR_Backlog/PR-PERF-504 - Daemon Default Cleanup and Final Runtime Harmonization.md`

Purpose:

- remove midpoint-only lifecycle code and leave one final production runtime
  story in code and docs

Primary outcomes:

- child-host-only production scaffolding is removed
- local adapter remains DI-only and test-only
- docs, roadmap references, and completed-plan bookkeeping reflect only the
  final daemon model

Key file targets:

- `src/app_factory.py`
- `src/main.py`
- `src/controller/app_controller.py`
- `src/controller/pipeline_controller.py`
- canonical docs and docs index
- final CompletedPR and CompletedPlans bookkeeping files

Execution gate:

- no production path still routes execution through a GUI-owned local runtime

## 9. Recommended First Approval

Approve `PR-PERF-501` first.

Why this is the correct first approval:

- it is the smallest architectural slice that still moves the plan forward
- it is required by both the midpoint and the daemon follow-through
- it can be reviewed for architectural correctness before any risky process
  cutover lands
- if the team cannot agree on the port and protocol, it is better to discover
  that before changing startup, queue ownership, or backend lifecycle

## 10. Completion Rule for This Sequence

This sequence is only complete when all of the following are true:

- production execution no longer runs in the GUI process
- the GUI is a client of a local runtime daemon
- reconnect works without creating duplicate queue ownership
- the midpoint child-host phase is no longer treated as active current truth
- canonical docs and indexes describe one final runtime story

Until then, this sequence remains active backlog and should not be split into
ad hoc performance fixes that bypass the defined runtime-host migration path.
