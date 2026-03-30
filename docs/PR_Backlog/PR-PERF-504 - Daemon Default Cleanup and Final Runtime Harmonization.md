# PR-PERF-504 - Daemon Default Cleanup and Final Runtime Harmonization

Status: Specification
Priority: HIGH
Effort: MEDIUM
Phase: Runtime Isolation Part C
Date: 2026-03-30

## 2. Context & Motivation

Current repo truth after `PR-PERF-503` is expected to be:

- production runtime lifetime is already daemon-owned
- the GUI is a client of the detached local runtime daemon
- reconnect and daemon-backed state restoration already work well enough for
  production use
- the runtime host protocol and queue semantics from `PR-PERF-501` remain the
  active contract
- `PipelineRunner.run_njr(...)` remains the only production runner entrypoint

At that point, the remaining work is not another topology change. The remaining
work is cleanup and harmonization: remove midpoint-only child-host scaffolding,
eliminate any lingering transitional production branches, and make code and
docs describe one final runtime story only.

This PR exists now because the sequence should not end with both the midpoint
and daemon models still visible as active current truth. If the daemon is the
accepted production topology, the repo should retire midpoint-only logic and
close out the runtime-isolation sequence cleanly.

Canonical references:

- `docs/ARCHITECTURE_v2.6.md`
- `docs/GOVERNANCE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/LOCAL_RUNTIME_ISOLATION_EXECUTABLE_SEQUENCE_v2.6.md`
- `docs/PR_Backlog/PR-PERF-501 - Runtime Host Port and Protocol Scaffold.md`
- `docs/PR_Backlog/PR-PERF-502 - GUI-Owned Runtime Host Midpoint Cutover.md`
- `docs/PR_Backlog/PR-PERF-503 - Detached Local Runtime Daemon Promotion.md`

## 3. Goals & Non-Goals

Goals:

1. Remove midpoint-only GUI-owned child-host production scaffolding from code.
2. Leave one final production runtime story: GUI client plus detached local
   runtime daemon.
3. Restrict the local runtime adapter and any same-process helpers to DI-only
   and test-only usage.
4. Harmonize canonical docs, roadmap references, and sequence bookkeeping so
   they describe only the final daemon model.
5. Close out the runtime-isolation sequence with clean CompletedPR and
   CompletedPlans records once implementation is complete.

Non-Goals:

1. Do not redesign the detached daemon model established in `PR-PERF-503`.
2. Do not rewrite the runtime host protocol or change queue semantics.
3. Do not add new runtime features such as remote hosting, multi-user support,
   or distributed scheduling.
4. Do not remove legitimate DI or test seams that are still required by unit
   and integration coverage.
5. Do not reopen midpoint-proof questions that were already settled by
   `PR-PERF-502` soak validation and `PR-PERF-503` daemon promotion.

## 4. Guardrails

This PR must preserve the following invariants:

1. `NormalizedJobRecord` remains the only executable outer job contract.
2. Fresh production execution remains queue-only.
3. `PipelineRunner.run_njr(...)` remains the only production runner entrypoint,
   owned by the detached daemon.
4. StableNew continues to own queue policy, artifacts, history, diagnostics,
   and learning through one final daemon-backed production topology.
5. The GUI must not regain production ownership of queue, history, watchdog,
   backend lifecycle, or runtime lifetime.

Boundaries the executor must not cross:

1. Do not invent a same-process production fallback while removing midpoint
   scaffolding.
2. Do not change backend contracts, builder logic, or job schemas.
3. Do not remove DI or test seams unless replacement coverage is in place.
4. Do not leave contradictory docs active after final harmonization.

Contract statement:

- This PR may remove transitional bootstrap and lifecycle code, tighten daemon
  defaults, restrict local adapters to DI or test usage, and update canonical
  docs and bookkeeping.
- This PR may not change NJR, queue-only semantics, or runner public execution
  semantics.

## 5. Allowed Files

### Files to Create

- `docs/CompletedPR/PR-PERF-504-Daemon-Default-Cleanup-and-Final-Runtime-Harmonization.md`
- `docs/CompletedPlans/LOCAL_RUNTIME_ISOLATION_EXECUTABLE_SEQUENCE_v2.6.md`

### Files to Modify

- `src/app_factory.py`
- `src/main.py`
- `src/controller/app_controller.py`
- `src/controller/pipeline_controller.py`
- `src/controller/job_service.py`
- `src/runtime_host/*.py`
- `src/utils/single_instance.py`
- `src/config/app_config.py`
- `src/gui/panels_v2/debug_hub_panel_v2.py`
- `src/gui/views/diagnostics_dashboard_v2.py`
- `tests/runtime_host/test_*.py`
- `tests/integration/test_runtime_daemon_*.py`
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
- unrelated feature files outside runtime-lifecycle cleanup, diagnostics, and
  documentation harmonization fallout
- `docs/GOVERNANCE_v2.6.md` unless human review explicitly requires wording
  alignment after implementation evidence is gathered

## 6. Implementation Plan

### Step 1 - Remove midpoint-only production launch and lifecycle branches

What changes:

- remove GUI-owned child-host production bootstrap branches, midpoint-only
  launch helpers, and other transitional lifecycle code that should no longer
  exist once the daemon is the accepted production runtime
- keep only the detached-daemon production startup path

Why it changes:

- final harmonization should leave one runtime story, not a daemon plus
  midpoint dual topology

Files touched in this step:

- `src/app_factory.py`
- `src/main.py`
- `src/runtime_host/*.py`
- `src/config/app_config.py`

Tests:

- update bootstrap tests to assert daemon-only production startup behavior

### Step 2 - Restrict local adapter and same-process helpers to DI-only and test-only use

What changes:

- ensure the local runtime adapter and any same-process helper seams can only be
  used by explicit DI or test setup, not by production bootstrap
- add clear guardrails or failure paths if production wiring attempts to route
  back through midpoint-era local ownership

Why it changes:

- final cleanup is incomplete if same-process or midpoint-era ownership remains
  silently reachable in production

Files touched in this step:

- `src/controller/job_service.py`
- `src/runtime_host/*.py`
- `src/app_factory.py`
- `src/controller/app_controller.py`
- `src/controller/pipeline_controller.py`

Tests:

- add tests proving production wiring cannot accidentally select the local
  adapter while DI and test scenarios still work

### Step 3 - Harmonize diagnostics and controller wording to the final daemon model

What changes:

- remove midpoint-specific labels, connection states, and debug wording that no
  longer reflect active production topology
- ensure diagnostics and Debug Hub surfaces describe one final daemon-backed
  runtime model

Why it changes:

- users and developers should not have to infer which runtime story is current
  from transitional labels or debug fields

Files touched in this step:

- `src/controller/app_controller.py`
- `src/gui/panels_v2/debug_hub_panel_v2.py`
- `src/gui/views/diagnostics_dashboard_v2.py`
- `src/runtime_host/*.py`

Tests:

- update diagnostics GUI tests to assert final daemon wording and state fields

### Step 4 - Retire active sequence and finalize docs bookkeeping

What changes:

- update canonical docs and roadmap wording so they describe only the final
  daemon-backed production topology
- move the runtime-isolation sequence out of active backlog and into
  `docs/CompletedPlans/`
- add the final CompletedPR record and retire the active backlog copy of this
  PR spec after implementation closeout

Why it changes:

- the sequence is not complete until code and docs agree on one final runtime
  story and the planning artifacts are no longer marked active

Files touched in this step:

- `docs/ARCHITECTURE_v2.6.md`
- `docs/DEBUG HUB v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`
- `docs/PR_Backlog/LOCAL_RUNTIME_ISOLATION_EXECUTABLE_SEQUENCE_v2.6.md`
- `docs/CompletedPlans/LOCAL_RUNTIME_ISOLATION_EXECUTABLE_SEQUENCE_v2.6.md`
- `docs/CompletedPR/PR-PERF-504-Daemon-Default-Cleanup-and-Final-Runtime-Harmonization.md`

Tests:

- no additional runtime tests; documentation validation must cite implemented
  daemon-only production behavior and the passing cleanup slices from earlier
  steps

## 7. Testing Plan

### Unit tests

- daemon-only bootstrap selection tests
- local-adapter guard tests proving production bootstrap cannot select
  same-process ownership
- controller and diagnostics tests proving midpoint wording and state branches
  are no longer active

Suggested commands:

- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/runtime_host -q`
- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/controller/test_app_controller_*.py tests/controller/test_pipeline_controller_*.py -q`

### Integration tests

- daemon launch or attach still works after midpoint code removal
- GUI restart and reconnect still restore queue, running-job, and diagnostics
  state without any midpoint fallback path
- production startup fails clearly if daemon ownership cannot be established
  rather than silently routing back to local runtime ownership

Suggested command:

- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/integration/test_runtime_daemon_*.py -q`

### Journey or smoke coverage

- GUI startup smoke with detached daemon
- one queue-submit and cancel smoke through the final daemon path
- one reconnect smoke after GUI restart with Debug Hub open

### Manual verification

1. Launch the app and confirm production startup uses the detached daemon path
   only.
2. Verify no GUI-owned child runtime host is created during normal production
   startup.
3. Submit a job, restart the GUI, and confirm reconnect still restores runtime
   state.
4. Open the Debug Hub and confirm wording and connection state reflect only the
   final daemon model.
5. Review docs and confirm the active backlog no longer presents the midpoint as
   current truth once implementation closeout is finished.

## 8. Verification Criteria

### Success criteria

1. No production path still routes execution through a GUI-owned local runtime.
2. Midpoint-only child-host scaffolding is removed from active production code.
3. Local runtime adapters remain available only for DI or test scenarios.
4. Canonical docs, roadmap references, and diagnostics wording describe one
   final daemon-backed runtime story.
5. The runtime-isolation sequence is closed out cleanly into CompletedPR and
   CompletedPlans records when implementation finishes.

### Failure criteria

1. Production bootstrap can still silently fall back to midpoint or same-process
   runtime ownership.
2. Docs or diagnostics continue to present the midpoint as active current truth.
3. Cleanup removes needed DI or test seams without replacement coverage.
4. Final bookkeeping leaves contradictory active and completed runtime-isolation
   docs in place.

## 9. Risk Assessment

### Low-risk areas

- documentation harmonization once the final daemon topology is already proven
- removal of clearly dead midpoint-only labels and state branches

### Medium-risk areas with mitigation

- removing transitional startup paths that still hide untested dependencies  
  Mitigation: daemon-only bootstrap tests and reconnect smoke coverage before
  removing midpoint branches.

- tightening local adapter usage without breaking DI or tests  
  Mitigation: explicit guard tests that distinguish production bootstrap from
  test or DI wiring.

### High-risk areas with mitigation

- accidental regression if a surviving production codepath still depends on
  midpoint scaffolding  
  Mitigation: integration tests that force daemon launch or attach and verify no
  local fallback is reachable.

- documentation and code drifting out of sync during final closeout  
  Mitigation: require doc wording to cite implemented daemon-only behavior and
  completed test evidence in the same PR.

### Rollback plan

- revert this PR and return to the daemon-enabled but not fully harmonized state
  delivered by `PR-PERF-503`

## 10. Tech Debt Analysis

Debt removed:

- midpoint-only child-host production scaffolding
- transitional runtime-topology wording that keeps two runtime stories alive
- silent production reachability of local runtime ownership paths

Debt intentionally deferred:

- none inside the runtime-isolation sequence if this PR lands cleanly; any
  later daemon optimization or UX polish requires a new PR spec outside this
  sequence

## 11. Documentation Updates

This PR finalizes runtime-topology truth and therefore requires same-PR doc
updates and closeout bookkeeping.

Required documentation work:

1. update `docs/ARCHITECTURE_v2.6.md` to describe only the final detached local
   daemon runtime topology if implementation evidence confirms that midpoint
   production code is retired
2. update `docs/DEBUG HUB v2.6.md` to reflect daemon-only diagnostics and final
   connection-state wording
3. update `docs/StableNew Roadmap v2.6.md` to mark runtime-isolation execution
   complete and point to the final completed records
4. update `docs/DOCS_INDEX_v2.6.md` to retire active runtime-isolation backlog
   references that are no longer current after closeout
5. add `docs/CompletedPR/PR-PERF-504-Daemon-Default-Cleanup-and-Final-Runtime-Harmonization.md`
   during closeout
6. move `docs/PR_Backlog/LOCAL_RUNTIME_ISOLATION_EXECUTABLE_SEQUENCE_v2.6.md`
   to `docs/CompletedPlans/LOCAL_RUNTIME_ISOLATION_EXECUTABLE_SEQUENCE_v2.6.md`
   once the sequence is fully implemented

Explicit disposition:

- this PR spec remains active in `docs/PR_Backlog/` until implemented
- after implementation, add the CompletedPR closeout and retire the active
  backlog copy of this spec
- after implementation, move the runtime-isolation sequence to
  `docs/CompletedPlans/` because this PR completes the sequence
- any stale duplicate runtime-isolation backlog specs that remain active after
  their corresponding CompletedPR records exist must be retired in the same
  closeout pass

## 12. Dependencies

### Internal module dependencies

- `PR-PERF-501 - Runtime Host Port and Protocol Scaffold`
- `PR-PERF-502 - GUI-Owned Runtime Host Midpoint Cutover`
- `PR-PERF-503 - Detached Local Runtime Daemon Promotion`
- daemon promotion stability and reconnect behavior already accepted as current
  production truth
- `src/app_factory.py`
- `src/main.py`
- `src/controller/app_controller.py`
- `src/controller/pipeline_controller.py`
- `src/controller/job_service.py`
- `src/runtime_host/*.py`

### External tools or runtimes

- local-only IPC transport and detached daemon process management already in
  place from `PR-PERF-503`
- existing WebUI and Comfy runtimes behind daemon ownership

## 13. Approval & Execution

Planner: GitHub Copilot  
Executor: Codex  
Reviewer: Rob  
Approval Status: Pending

## 14. Next Steps

1. Implement this PR only after `PR-PERF-503` lands cleanly and daemon behavior
   is accepted as the active production topology.
2. Close out the runtime-isolation sequence in the same implementation wave so
   there is no lingering active midpoint or daemon-transition backlog state.
3. Any future daemon optimization or UX work should start as a new PR series,
   not by reopening this completed harmonization pass.
