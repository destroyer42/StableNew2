# PR-A — Core Run Path & Runner DI (V2.5)

## 1. Summary

- Centralizes JobService construction in AppController so every normalized job flows through the runner factory/`_execute_job` callable, matching the canonical NormalizedJobRecord → JobService → JobQueue → Runner path.
- PipelineController now depends on that JobService instance and the shared DI path; controller tests use the `stub_runner_factory` helper to verify job submissions without spinning worker threads or touching WebUI.
- Adds docs and tests that codify this canonical path (`tests/controller/test_core_run_path_v2.py`), allowing later GUI or learning workstreams to hook into a stable execution pipeline.

## 2. Context

- Discovery D-11 and PR-0114C-Tx introduced job service DI hooks, but AppController/PipelineController still built runner/queue state ad hoc. That made it hard to ensure "Run Now" and queued jobs used the same canonical path and complicated tests.
- PR-A finishes the story: controller code now funnels everything through JobService constructed via the new runner factory, while tests verify the path with `StubRunner`.

## 3. Scope

### In Scope
- `src/controller/app_controller.py`: new `_single_node_runner_factory` plus updated `_build_job_service` that uses the shared DI path and `self._execute_job`.
- `src/controller/pipeline_controller.py`: reuses the injected JobService instead of rebuilding it directly, keeping controller wiring thin.
- `tests/controller/test_core_run_path_v2.py`: new tests covering the AppController job service helper and PipelineController submission contract.
- docs: `docs/ARCHITECTURE_v2.5.md`, `docs/StableNew_Coding_and_Testing_v2.5.md`, and `CHANGELOG.md`.

### Out of Scope
- Runner internals, executor behavior, or GUI layout changes.

## 4. Testing

- `tests/controller/test_core_run_path_v2.py` exercises the helper and pipeline controller wiring.
- `tests/controller/test_job_service_di_v2.py` already ensures stub runner and history DI works.

## 5. Documentation

- Add canonical run-path note to `docs/ARCHITECTURE_v2.5.md`.
- Mention DI testing expectations in `docs/StableNew_Coding_and_Testing_v2.5.md`.
- Record the PR in `CHANGELOG.md`.
