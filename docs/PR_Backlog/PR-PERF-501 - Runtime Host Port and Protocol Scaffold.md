# PR-PERF-501 - Runtime Host Port and Protocol Scaffold

Status: Specification
Priority: CRITICAL
Effort: LARGE
Phase: Runtime Isolation Part A
Date: 2026-03-30

## 2. Context & Motivation

Current repo truth:

- fresh production execution is queue-only under the canonical runtime defined in
  `docs/ARCHITECTURE_v2.6.md`
- `PipelineRunner.run_njr(...)` remains the only production runner entrypoint
- `AppController` still builds a local `JobService`
- `JobService` still defaults to a local `SingleNodeJobRunner`
- `SingleNodeJobRunner` already runs work on a background `QueueWorker`, but it
  still shares the GUI process
- recent GUI instrumentation now shows sub-millisecond to low-millisecond Tk
  callback costs while multi-second GUI freezes still occur during generation

The user-visible problem is now best explained by same-process runtime pressure,
native blocking, or memory-pressure side effects outside the measured Tk
surfaces. Before StableNew can safely move queue and runner ownership into a
separate runtime host, the repo needs a daemon-shaped host seam that does not
yet change production behavior.

This PR exists now because the later midpoint and daemon PRs should not invent
ad hoc IPC or a second runtime story under deadline pressure. The seam must be
reviewed first as an explicit architectural contract.

Canonical references:

- `docs/ARCHITECTURE_v2.6.md`
- `docs/GOVERNANCE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/LOCAL_RUNTIME_ISOLATION_EXECUTABLE_SEQUENCE_v2.6.md`

## 3. Goals & Non-Goals

Goals:

1. Introduce an explicit runtime host port between GUI controllers and runtime
   execution ownership.
2. Define a versioned, local-only protocol carrying only canonical NJR-derived
   state, queue status, diagnostics payloads, and control commands.
3. Add a local adapter over the current `JobService` so controllers can depend
   on the new host port without changing live execution behavior.
4. Rewire `AppController`, `PipelineController`, and app bootstrap to depend on
   the runtime host port rather than direct production assumptions about local
   `JobService` construction.
5. Prove that the new host port can support both the midpoint child-host cutover
   and the later detached daemon without another contract rewrite.

Non-Goals:

1. Do not launch, connect to, or manage any subprocess host in this PR.
2. Do not change queue ownership, runner ownership, history ownership, or
   backend lifecycle ownership in production.
3. Do not change `PipelineRunner` or `executor` behavior.
4. Do not add a second outer job model, raw backend payload surface, or direct
   GUI execution path.
5. Do not change canonical docs describing runtime topology yet.

## 4. Guardrails

This PR must preserve the following invariants:

1. `NormalizedJobRecord` remains the only executable outer job contract.
2. Fresh production execution remains queue-only.
3. `PipelineRunner.run_njr(...)` remains the only production runner entrypoint.
4. StableNew continues to own queue semantics, runner orchestration, artifacts,
   history, learning, and diagnostics.
5. GUI code must not gain prompt construction, alternate job building, or
   backend-owned workflow contracts.

Boundaries the executor must not cross:

1. Do not modify `src/pipeline/executor.py`.
2. Do not modify `src/pipeline/pipeline_runner.py`.
3. Do not modify NJR schema or stage model contracts.
4. Do not change GUI view behavior beyond minimal constructor or dependency
   wiring required by controller injection.

Contract statement:

- This PR may touch controller and queue service wiring.
- This PR may create a new runtime-host contract package.
- This PR may not change production runtime ownership or queue semantics.

## 5. Allowed Files

### Files to Create

- `src/runtime_host/*.py`
- `tests/runtime_host/test_*.py`
- `tests/controller/test_*runtime_host*.py`
- `docs/CompletedPR/PR-PERF-501-Runtime-Host-Port-and-Protocol-Scaffold.md`

### Files to Modify

- `src/controller/app_controller.py`
- `src/controller/pipeline_controller.py`
- `src/controller/job_service.py`
- `src/app_factory.py`
- `tests/controller/test_app_controller_*.py`
- `tests/controller/test_pipeline_controller_*.py`
- `docs/PR_Backlog/LOCAL_RUNTIME_ISOLATION_EXECUTABLE_SEQUENCE_v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`

### Forbidden Files

- `src/pipeline/pipeline_runner.py`
- `src/pipeline/executor.py`
- `src/pipeline/job_models_v2.py`
- `src/main.py`
- `src/gui/**/*.py` except constructor signature fallout that is explicitly
  required by controller dependency injection
- `docs/ARCHITECTURE_v2.6.md`
- `docs/GOVERNANCE_v2.6.md`
- `docs/DEBUG HUB v2.6.md`

## 6. Implementation Plan

### Step 1 - Create the runtime-host contract package

What changes:

- introduce a dedicated `src/runtime_host/` package for the runtime host port,
  protocol message shapes, version negotiation constants, and local adapter
  interfaces

Why it changes:

- the later child-host and daemon PRs need a reviewed contract before runtime
  ownership moves out of process

Files touched in this step:

- `src/runtime_host/*.py`

Tests:

- add protocol serialization and version tests under `tests/runtime_host/`

### Step 2 - Implement a local adapter over JobService

What changes:

- implement a local adapter that satisfies the new runtime host port by
  delegating to the existing in-process `JobService`
- map queue submission, cancel, diagnostics snapshot retrieval, and event
  subscription through the adapter without changing current behavior

Why it changes:

- controllers need to consume one host-facing contract before a real host
  process can be introduced

Files touched in this step:

- `src/runtime_host/*.py`
- `src/controller/job_service.py`

Tests:

- add local adapter tests covering submission, cancellation, diagnostics, and
  event propagation

### Step 3 - Rewire controller ownership to the host port

What changes:

- change `AppController` and `PipelineController` to depend on the runtime host
  port instead of assuming local production `JobService` construction or direct
  concrete ownership
- keep the same user-visible behavior by wiring the new local adapter in
  bootstrap

Why it changes:

- this removes direct controller dependence on same-process service creation and
  makes later host cutover a bootstrap concern rather than a controller rewrite

Files touched in this step:

- `src/controller/app_controller.py`
- `src/controller/pipeline_controller.py`
- `src/app_factory.py`

Tests:

- update controller tests so they run against the runtime host port or the new
  local adapter instead of direct local service assumptions where appropriate

### Step 4 - Hardening of protocol boundaries

What changes:

- add explicit version identifiers, unsupported-version rejection, and JSON-safe
  payload normalization for protocol messages
- ensure the contract carries canonical snapshots and descriptors only, not
  backend-local payload internals

Why it changes:

- later IPC-based PRs should not discover too late that the contract is not
  stable or serializable enough for real cross-process use

Files touched in this step:

- `src/runtime_host/*.py`
- tests under `tests/runtime_host/`

Tests:

- add rejection and normalization tests for malformed or unsupported messages

### Step 5 - Closeout and bookkeeping

What changes:

- add the final CompletedPR record after implementation
- update active planning references if the final file location changes during
  execution

Why it changes:

- the repo requires one final completed PR record and synchronized active doc
  references

Files touched in this step:

- `docs/CompletedPR/PR-PERF-501-Runtime-Host-Port-and-Protocol-Scaffold.md`
- `docs/DOCS_INDEX_v2.6.md`
- `docs/PR_Backlog/LOCAL_RUNTIME_ISOLATION_EXECUTABLE_SEQUENCE_v2.6.md`

Tests:

- no additional runtime tests; doc bookkeeping only

## 7. Testing Plan

### Unit tests

- protocol serialization and version-negotiation tests under `tests/runtime_host/`
- local adapter tests for submit, cancel, queue snapshot, and diagnostics access
- controller tests proving `AppController` and `PipelineController` can operate
  through the runtime host port without behavior change

Suggested commands:

- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/runtime_host -q`
- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/controller/test_app_controller_*.py tests/controller/test_pipeline_controller_*.py -q`

### Integration tests

- add a focused integration slice proving queue submission, status propagation,
  cancellation, and diagnostics retrieval still work end-to-end when the
  runtime host port is backed by the local adapter

Suggested command:

- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/controller/test_*runtime_host*.py -q`

### Journey or smoke coverage

- smoke the existing queue-first path through the local adapter with one queued
  synthetic job and one cancellation path

### Manual verification

1. Launch the app normally.
2. Queue one existing synthetic or lightweight job path.
3. Confirm queue updates, cancellation, and diagnostics still behave exactly as
   they did before the seam introduction.
4. Confirm no new production host process is launched in this PR.

## 8. Verification Criteria

### Success criteria

1. Controllers depend on a reviewed runtime host port rather than direct local
   production assumptions.
2. The local adapter preserves current queue-first behavior with no visible
   runtime change.
3. The protocol is versioned and carries only canonical NJR-derived state and
   diagnostics payloads.
4. No new user-visible execution mode or runtime host lifecycle appears in this
   PR.

### Failure criteria

1. The PR launches or depends on a subprocess host.
2. The PR introduces a second job model or raw backend payload contract.
3. Controllers still bypass the port and depend on local service internals for
   production behavior.
4. Existing queue and diagnostics behavior regress under the local adapter.

## 9. Risk Assessment

### Low-risk areas

- contract and protocol definition work under a new dedicated package
- local adapter tests that wrap existing `JobService` behavior

### Medium-risk areas with mitigation

- controller rewiring in `AppController` and `PipelineController`
  Mitigation: keep the adapter behaviorally identical to the existing local
  path and validate with focused controller tests.

- protocol overreach that makes later PRs harder instead of easier
  Mitigation: keep the port limited to operations the GUI already needs:
  submission, cancellation, status events, queue snapshot, and diagnostics.

### High-risk areas with mitigation

- accidentally creating a shadow runtime path while adding the seam
  Mitigation: the local adapter is the only production implementation in this
  PR, and no subprocess host code is allowed to execute.

### Rollback plan

- revert the runtime host port integration and restore direct controller wiring
  to local `JobService`

## 10. Tech Debt Analysis

Debt removed:

- direct controller dependence on concrete same-process production `JobService`
  ownership assumptions
- lack of a reviewed runtime-host contract for later process isolation work

Debt intentionally deferred:

- actual child-host production cutover  
  Next PR owner: `PR-PERF-502`
- detached daemon lifecycle, reconnect, and discovery  
  Next PR owner: `PR-PERF-503`
- midpoint-only cleanup and final harmonization  
  Next PR owner: `PR-PERF-504`

## 11. Documentation Updates

This PR should not change Tier 1 runtime truth.

Required documentation work:

1. keep `docs/PR_Backlog/LOCAL_RUNTIME_ISOLATION_EXECUTABLE_SEQUENCE_v2.6.md`
   synchronized if file names or dependency ordering change during execution
2. add `docs/CompletedPR/PR-PERF-501-Runtime-Host-Port-and-Protocol-Scaffold.md`
   during closeout
3. update `docs/DOCS_INDEX_v2.6.md` if active file locations change

Explicit disposition:

- this PR spec remains active in `docs/PR_Backlog/` until implemented
- on completion, create the final `docs/CompletedPR/` record and remove any
  duplicate planning copy if one exists

## 12. Dependencies

### Internal module dependencies

- `src/controller/app_controller.py`
- `src/controller/pipeline_controller.py`
- `src/controller/job_service.py`
- `src/app_factory.py`
- existing queue and diagnostics contracts already exposed by `JobService`

### External tools or runtimes

- Python standard-library serialization and transport primitives only
- no external runtime manager or subprocess dependency in this PR

## 13. Approval & Execution

Planner: GitHub Copilot  
Executor: Codex  
Reviewer: Rob  
Approval Status: Approved

## 14. Next Steps

1. Execute this PR first.
2. After it lands and the runtime host seam is validated, move to
   `PR-PERF-502 - GUI-Owned Runtime Host Midpoint Cutover`.
3. Do not start daemon-lifecycle work until the midpoint proves that real
   process separation materially improves responsiveness.
