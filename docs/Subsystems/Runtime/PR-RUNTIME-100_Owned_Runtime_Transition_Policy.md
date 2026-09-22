# PR-RUNTIME-100 — Owned GPU Runtime Transition Policy

Status: **COMPLETE / ACCEPTED ON FEATURE BRANCH `runtime/100-owned-transition-policy`; main
integration awaits explicit product-owner authorization.** Coordination only: no scheduler, lease, second lifecycle authority, or model
routing. Backend selection, NJR contents and the outer execution path
(`Intent -> Compiler -> NJR -> JobService -> SQLite -> PipelineRunner.run_njr -> backend ->
artifact/history`) are unchanged.

## 1. Problem and root cause

PR-VID-130 physically showed Wan2.2 peaking at ~11,630 MiB whole-GPU with ~1.45 GB minimum free
host RAM. Its resource-readiness guard correctly blocks Wan when another application holds too
much memory, but until now the operator had to manually close **their own StableNew-launched**
A1111 even though StableNew already had the authority to release it — the three existing owners
(`WebUIProcessManager`, `ComfyProcessManager`, `SVDService`) never coordinated with each other.

**This package does not diagnose or fix the workstation's pre-existing hard GPU resets /
black-screen failures** (see `docs/Subsystems/Video/PR-VID-110_Directed_Motion_Qualification.md`
section 9: ~15 unexplained resets, suspects DDR5-6000/power delivery/driver). It only removes
avoidable StableNew-owned contention that was previously being resolved by asking the operator
to close their own tools.

## 2. Ownership map (unchanged — this package adds no new owner)

| Runtime | Sole existing owner | Release boundary used | Start boundary (unchanged, not this package's job) |
|---|---|---|---|
| `a1111_webui` | `WebUIProcessManager` (`src/api/webui_process_manager.py`) | `stop_webui()` | `ensure_running()` / `WebUIConnectionController` |
| `comfy` | `ComfyProcessManager` (`src/video/comfy_process_manager.py`) | `stop()` | `ComfyWorkflowVideoBackend._ensure_runtime_ready()` |
| `svd_native` (cache) | `SVDService` (`src/video/svd_service.py`) | `clear_model_cache()` | `SVDRunner`/`SVDService.prepare_runtime` |

Each owner's `owns_process` (or, for SVD, the fact the cache is a plain dict) remains the single
source of truth for whether a live process/state is StableNew's to touch. This package adds a
fourth, narrow module that **delegates to these three** and owns nothing itself:
`src/services/runtime_transition_service.py` (`RuntimeTransitionCoordinator.prepare_for`).

## 3. Coordinator API and runtime identities

```python
RUNTIME_A1111_WEBUI = "a1111_webui"
RUNTIME_COMFY = "comfy"
RUNTIME_SVD_NATIVE = "svd_native"

RuntimeTransitionCoordinator().prepare_for(target: str) -> RuntimeTransitionResult
```

`RuntimeTransitionResult`: `target`, `conflicts_observed`, `ownership_state` (per runtime:
`absent` / `not_running` / `owned` / `external`), `releases_attempted`, `releases_completed`,
`status` (`ready` / `action_required` / `release_failed`), `blockers` (operator-readable).
`RuntimeTransitionError(result)` is what a backend raises when `not result.ready`.

Target-driven release policy (product decision, unchanged by implementation):

| target | conflicting residencies released |
|---|---|
| `a1111_webui` | owned `comfy`, cached SVD state |
| `comfy` | owned `a1111_webui`, cached SVD state |
| `svd_native` | owned `a1111_webui`, owned `comfy` (its own cache is not released) |

Per-runtime resolution (superseded below for external endpoints): no manager -> `absent` (nothing to do); manager exists but not running ->
`not_running` (nothing to do — **never stopped merely for existing**); `owns_process` true ->
`owned`, release attempted through that manager's own boundary, verified by the manager's own
post-condition (`not is_running()`); `owns_process` false while live -> `external`, **no method on
the manager is even called**, `status=action_required` with operator guidance. SVD cache release
uses `SVDService().clear_model_cache()` directly (the class-level `_pipeline_cache` is shared by
every `SVDService`/`SVDRunner` instance, so this is authoritative and requires no second cache).

**External endpoint correction.** A manager handle is not endpoint presence. When there is no
manager, or its handle is not running, the coordinator now makes one read-only probe of that
runtime's configured endpoint: a refused/free endpoint remains `absent` or `not_running`; a
healthy expected endpoint or any occupied/ambiguous endpoint is `external` and returns
`status=action_required`. The probes are `probe_webui_endpoint()` at the configured A1111 URL and
existing `probe_comfy_endpoint()` at the configured Comfy URL; neither discovers ports nor
identifies OS processes. No external endpoint is adopted, stopped, terminated, restarted, or killed.

Nothing is restarted afterward. The target's own existing owner remains responsible for
starting/loading what it needs; this package never centralizes startup.

## 4. Integration seam (no model-name branching in PipelineRunner)

Each backend takes an optional `transition: RuntimeTransitionCoordinator` (default a fresh
instance) and calls `prepare_for(<its own runtime id>)` once at the top of `execute()`, raising
`RuntimeTransitionError` before doing anything else if not ready:

- `A1111WebUIImageBackend.execute` -> `prepare_for(a1111_webui)`, before any `pipeline.run_*_stage` call.
- `ComfyWorkflowVideoBackend.execute` -> `prepare_for(comfy)`, after workflow governance (cheap,
  no side effects) and before `_ensure_runtime_ready()`/dependency probe/Wan resource-readiness,
  so freed VRAM is visible to the existing Wan guard.
- `SVDNativeVideoBackend.execute` -> `prepare_for(svd_native)`, before `pipeline.run_svd_native_stage`.

`PipelineRunner` is untouched: it still only calls `backend.execute(pipeline, request)` through the
PR-VID-120 resolver. No `if workflow_id == "wan..."`-style branching exists anywhere in this diff.

Wan's existing workflow-specific 10,000 MiB / 16 GB readiness guard
(`src/video/workflow_readiness.py`) is unchanged and remains the authoritative check for whether
Wan itself may proceed *after* transition; its thresholds were not moved or duplicated here.

## 5. Safety properties

- **Serialization, not a new busy/idle authority.** `prepare_for` runs synchronously inside one
  admitted job's `backend.execute()`, inside `PipelineRunner.run_njr`, inside
  `JobService`/`single_node_runner`'s existing one-job-at-a-time execution. There is nothing else
  to add: two jobs never call a backend concurrently in this architecture.
- **External immutability.** An external/ambiguous process is never called (`stop()`/`stop_webui()`
  never even invoked when `owns_process` is false); this holds identically to how
  `WebUIProcessManager.start()`/`restart_webui()` and `ComfyProcessManager.start()` already refuse
  to adopt or replace an occupied endpoint.
- **Failure semantics.** `RuntimeTransitionError` is a normal exception raised before any GPU
  dispatch; `PipelineRunner`/`single_node_runner` handle it exactly like any other backend failure
  (job -> `FAILED`, diagnostic message, no auto-fallback to another backend, no auto-replay). A
  process that exits mid-release is reported as a release failure, not a new queue lifecycle state.
- **No new NJR field, no new persistence.** The coordinator reads no stage config and writes
  nothing; `RuntimeTransitionResult` is process memory only, surfaced solely via the raised
  exception's message.

## 6. Deterministic evidence

- `tests/services/test_runtime_transition_service.py` (12 tests, fakes only): each target's exact
  release set; external managers never stopped; absent/not-running runtimes never stopped; owned
  release failure (stop returns false, or raises) blocks with `RELEASE_FAILED` and is not retried;
  SVD cache release failure blocks; alternating `a1111 -> comfy -> a1111` reuses the same fake
  managers with no restore-after-release; `RuntimeTransitionError` carries the full result; unknown
  target rejected; SVD cache release goes through the real `SVDService` class and a later job's
  cache lookup is a normal miss (not corruption).
- `tests/integration/test_pr_runtime_100_transition_queue.py` (4 tests): the **real**
  `SVDNativeVideoBackend` (only `SVDRunner` faked, matching the accepted PR-MVP-070 pattern) through
  the real `SVDController -> NJR -> JobService -> SQLite -> PipelineRunner.run_njr` path —
  (a) owned A1111 + Comfy really released via their real manager objects, job completes normally;
  (b) an external Comfy blocks with `action_required`, is never touched, job fails with no
  automatic requeue (`QUEUED`/`RUNNING` both empty afterward); (c) a release that does not actually
  succeed blocks dispatch, attempted exactly once (no retry loop).
- The endpoint-presence repair adds deterministic no-manager and idle-manager cases for both
  configured A1111 and Comfy endpoints; a live/occupied endpoint is `EXTERNAL`/`ACTION_REQUIRED`,
  a refused endpoint permits transition, and the queue-path test proves the external Comfy case
  blocks before `Pipeline.run_svd_native_stage` without retry, requeue, fallback, or mutation.
- `tests/api/test_healthcheck_v2.py` proves A1111's read-only configured-endpoint classification:
  healthy expected response, occupied/non-expected response, and refused/free endpoint.
- Regression: `tests/image_backends`, `tests/video`, `tests/pipeline`, `tests/controller` (A1111/SVD
  surfaces), and the PR-VID-120/130 queue-integration suites show the same 86 pre-existing,
  environment-dependent local failures before and after this branch (none new;
  `tests/integration/test_pr_mvp_070_svd_native_vertical_slice.py` was already failing on `main`
  for an unrelated reason — its fake `SVDRunner.run()` predates a `provenance_context` kwarg the
  executor already passes).

## 7. Bounded physical acceptance (target machine)

At the time of this check the operator's own A1111 (port 7860) and ComfyUI (port 8000) were both
live, holding ~9.16 GiB combined VRAM. Freeing those ports to launch a StableNew-managed instance
for a full owned-launch-then-release demonstration would have required closing the operator's live
sessions for no product benefit, so that was not done (per "if practical"). Instead, real production
accessors were exercised on the target machine, unmodified and undisrupted:

```
webui manager (fresh process): None
comfy manager (fresh process): None
SVD cache at rest: {}
prepare_for(svd_native) -> status=ready, ownership_state={a1111_webui: absent, comfy: absent}
```

This showed, on the real machine, that `get_global_webui_process_manager()` /
`get_global_comfy_process_manager()` correctly report **no owned process** even while the operator's
own A1111/Comfy are genuinely live and serving — so the coordinator takes zero action and calls
neither manager's stop method, exactly as designed. The owned-release code path itself (manager
`stop()`/`stop_webui()` returning to a not-running state) is proven by the existing, accepted
`WebUIProcessManager`/`ComfyProcessManager` ownership tests plus the fake-manager coordinator tests
above; those existing tests were re-run and are unaffected (section 6).

The earlier `READY` classification was a defect, not acceptance evidence: manager-only inspection
missed the genuinely live external endpoints. The repaired coordinator now observes only the two
configured endpoints and reports `EXTERNAL` / `ACTION_REQUIRED` for a healthy expected service or
occupied/ambiguous endpoint. It still invokes neither manager stop method. No GPU generation was
rerun for this repair.

## 8. Required CI

GitHub Actions run `35676810610` passed both required jobs for repair commit
`69c837d3ce76673b7364fdfc03b245ed90699c24`: Python 3.11 and Python 3.12. The
informational full-suite jobs failed outside this change surface and are not part of the required
CI verdict. Locally, the focused tests, raw Ruff, compile check, repository-completeness check,
controller-surface ratchet, and diff check passed. `tools/ci/run_pr_gate.py` was attempted once
but was blocked because the local environment lacks `mypy`; that is a tooling blocker, not a
source or test failure.

## 9. What this does not claim

PR-RUNTIME-100 reduces avoidable StableNew-owned runtime contention. It does **not** establish root
cause for, and makes no claim about fixing, `nvlddmkm` faults, watchdog bugchecks, RAM/XMP
instability, PSU/power-delivery issues, or GPU hardware instability. That remains a separate,
still-open objective (PR-VID-110 section 9).
