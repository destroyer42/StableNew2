Timestamp: 2025-11-22 20:22 (UTC-06:00)
PR Id: PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001
Spec Path: docs/pr_templates/PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001.md

# PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001
Title: PipelineController Assembler Usage Hotfix (Enforce build_from_gui_input on all run paths)

---

1. Summary

This PR is a small, surgical hotfix that completes the intent of PR-#47 by ensuring that PipelineController actually calls PipelineConfigAssembler.build_from_gui_input on all production run paths.

Right now, the controller still accepts and uses a dummy pipeline_func callable and never invokes the assembler, so tests/controller/test_pipeline_controller_config_path.py::test_controller_uses_assembler_for_runs fails: the mocked build_from_gui_input is never called.

This PR does not change queue, job history, cluster, or pipeline behavior; it only fixes how the controller constructs PipelineConfig objects before delegating runs to the existing execution/queue machinery.

After this PR, every real pipeline run initiated via PipelineController.start_pipeline will:

- Build a PipelineConfig via PipelineConfigAssembler.build_from_gui_input (or build_for_learning_run when applicable).
- Pass that PipelineConfig into the runner/queue instead of raw dicts or dummy pipeline callables.
- Satisfy test_controller_uses_assembler_for_runs without modifying the test itself.

---

2. Problem Statement

Current state (post PR-#46 / 47 implementation in your snapshot):

- PipelineConfigAssembler is present and wired into tests.
- GuiOverrides and build_from_gui_input are implemented with megapixel clamps and metadata stubs.
- pipeline_adapter_v2 has been partially updated to work with overrides.
- test_pipeline_controller_config_path.py expects PipelineController to use the assembler:
  - It monkeypatches PipelineConfigAssembler in src.controller.pipeline_controller.
  - It instantiates PipelineController.
  - It mocks assembler.build_from_gui_input and calls controller.start_pipeline(...).
  - It asserts that build_from_gui_input was called.

Observed behavior:

- assembler.build_from_gui_input is never called.
- The controller still uses a legacy pattern where start_pipeline accepts a pipeline_func that returns a dict and directly calls that callable, bypassing the assembler entirely.

Codex suggested modifying the test; that is incorrect. The test correctly encodes the architecture rule:

All production pipeline runs must construct their PipelineConfig via PipelineConfigAssembler.

We need to fix PipelineController so that:

- It uses self._config_assembler for config building.
- start_pipeline calls into a dedicated _build_pipeline_config_from_state (or equivalent) that wraps build_from_gui_input.
- No run path bypasses the assembler.

---

3. Goals

1) Enforce assembler usage in controller:

- All production run paths in PipelineController must call self._config_assembler.build_from_gui_input (or build_for_learning_run) before submitting work to the runner or queue.

2) Keep behavior otherwise identical:

- Queue mode vs direct mode behavior must not change.
- Lifecycle and status transitions (IDLE, RUNNING, STOPPING, COMPLETED, FAILED, CANCELLED) must remain unchanged.

3) Satisfy tests without touching them:

- test_controller_uses_assembler_for_runs must pass with its current expectations.
- No controller or pipeline tests should need to be loosened or rewritten.

4) Honor Architecture_v2 and Pipeline rules:

- Controller owns lifecycle and state.
- Assembler and adapters own config building.
- Pipeline stays free of GUI concerns.

---

4. Non-goals

This PR will not:

- Modify QueueExecutionController, JobExecutionController, JobQueue, or JobHistory behavior.
- Change cluster/worker semantics (cluster_controller, worker_registry, worker_model).
- Modify GUI layouts, command bars, or prompt editors.
- Change API integration, WebUI client logic, or pipeline core stages.
- Introduce new configuration flags or learning/randomizer behaviors.

---

5. Allowed Files

You may modify ONLY the following files for this hotfix:

- Controller core:
  - src/controller/pipeline_controller.py

- Assembler wiring (if truly needed for type or small helper alignment; keep changes minimal):
  - src/controller/pipeline_config_assembler.py

- Tests (only if absolutely required for import paths or trivial type fixes; do not change behavior expectations):
  - tests/controller/test_pipeline_controller_config_path.py
  - tests/controller/test_pipeline_config_assembler.py

- Docs:
  - docs/PIPELINE_RULES.md
  - docs/ARCHITECTURE_v2_COMBINED.md
  - docs/codex_context/ROLLING_SUMMARY.md

If you believe any other file must change, stop and document the reason instead of editing it.

---

6. Forbidden Files

Do NOT modify any of the following in this PR:

- src/queue/*
- src/controller/job_history_service.py
- src/controller/job_execution_controller.py
- src/controller/cluster_controller.py
- src/cluster/*
- src/gui/*
- src/pipeline/*
- src/learning/*
- src/randomizer/*
- src/api/*

Also do not change:

- Test behavior in tests/controller/* beyond aligning with expected imports.
- Any xfail/skip markers outside this PR’s test file.

If a change appears necessary in a forbidden file, stop and surface that as a separate PR proposal.

---

7. Step-by-step Implementation Plan

7.1 Inspect current PipelineController

- Open src/controller/pipeline_controller.py.
- Identify:
  - Where self._config_assembler is created or stored (from PR-47).
  - The implementation of start_pipeline (and any wrappers).
  - Any private helper like _run_pipeline_impl or _run_full_pipeline_impl.
  - Any remaining use of pipeline_func callables that return dicts.

You should confirm that start_pipeline currently does not call build_from_gui_input and instead uses pipeline_func directly.

7.2 Introduce a dedicated config-building helper

Still in src/controller/pipeline_controller.py, implement a helper method if it does not already exist (or update an existing one). For example:

- _build_pipeline_config_from_state(self) -> PipelineConfig:

  - Reads the current GUI/controller state via the already-defined adapter or overrides source. This may be:
    - A stored GuiOverrides instance, or
    - A call into a GUI-agnostic adapter that returns GuiOverrides.
  - Calls self._config_assembler.build_from_gui_input(overrides, learning_metadata=..., randomizer_metadata=...).
  - Returns the resulting PipelineConfig.

Key requirement:

- The controller must use the assembler instance stored on self (which the test monkeypatches via PipelineConfigAssembler and/or via dependency injection constructor argument).

If PR-47 already introduced such a helper but did not wire it into start_pipeline, reuse it and ensure it calls self._config_assembler.

7.3 Rewire start_pipeline to use assembler

Update PipelineController.start_pipeline to:

1) Eliminate use of any dummy pipeline_func returning dicts for production logic.
2) Instead:

- Build a PipelineConfig using _build_pipeline_config_from_state.
- If queue execution is enabled and QueueExecutionController is present:
  - Submit the PipelineConfig to the queue controller (e.g., submit_pipeline_job(config)).
- If queue execution is disabled:
  - Submit the PipelineConfig directly to the synchronous/asynchronous runner (e.g., via JobExecutionController).

3) Ensure that the status/lifecycle wiring remains unchanged:
- Running, completed, failed, cancelled, queued status handling should not be altered, only the payload (PipelineConfig vs dict/callable).

7.4 Ensure test path uses the assembler instance

The test in tests/controller/test_pipeline_controller_config_path.py:

- Monkeypatches PipelineConfigAssembler in src.controller.pipeline_controller.
- Instantiates PipelineController.
- Replaces assembler.build_from_gui_input with a mock.
- Calls controller.start_pipeline(dummy_pipeline).

Your implementation must ensure that:

- During that call, controller.start_pipeline invokes self._config_assembler.build_from_gui_input(...).
- Because PipelineConfigAssembler was monkeypatched before controller creation, self._config_assembler is the same object as assembler in the test.
- Therefore, the mock’s call count increments and assert_called passes.

Do not change the test’s logic to make this happen; change the controller to behave correctly.

7.5 Documentation updates

- docs/PIPELINE_RULES.md:
  - Clarify that PipelineController must never construct configs manually; it must always call PipelineConfigAssembler for config building.
- docs/ARCHITECTURE_v2_COMBINED.md:
  - In the controller/pipeline flow section, ensure the sequence explicitly shows:
    - Controller -> PipelineConfigAssembler -> Runner/Queue -> Pipeline.
- docs/codex_context/ROLLING_SUMMARY.md:
  - Add a short entry describing PR-#47B (see section 12).

---

8. Required Tests

You must run at least the following tests and ensure they are green:

8.1 Targeted controller/assembler tests

- pytest tests/controller/test_pipeline_controller_config_path.py -v
- pytest tests/controller/test_pipeline_config_assembler.py -v

Expectation:

- test_controller_uses_assembler_for_runs passes without modifying the test file’s expectations.
- Assembler tests remain green.

8.2 Controller suite

- pytest tests/controller -v

Expectation:

- No regressions in any controller tests; lifecycle, queue mode, learning hooks, and cluster-related tests remain green.

8.3 Full suite (recommended)

- pytest -v

Expectation:

- All existing tests remain green, except for any pre-existing Tk skips or known xfails.

If any test outside the target ones fails, analyze the failure and apply the minimal fix within src/controller/pipeline_controller.py or, if absolutely necessary, src/controller/pipeline_config_assembler.py.

---

9. Acceptance Criteria

This PR is complete when:

1) Assembler usage is enforced:

- PipelineController.start_pipeline calls self._config_assembler.build_from_gui_input (or equivalent) on every production run path.

2) Test passes without modification:

- tests/controller/test_pipeline_controller_config_path.py::test_controller_uses_assembler_for_runs passes without changing the test’s expectations.

3) No behavior regressions:

- All controller and pipeline tests continue to pass.
- Queue mode, learning mode, and randomizer integration behave as before from the perspective of existing tests and any manual smoke tests.

4) Docs and rolling summary are updated:

- PIPELINE_RULES and ARCHITECTURE_v2_COMBINED reflect the enforced assembler usage.
- ROLLING_SUMMARY has an entry for PR-#47B.

---

10. Rollback Plan

If this PR introduces regressions (failing tests, unexpected behavior), you can roll back by:

1) Reverting changes to:

- src/controller/pipeline_controller.py
- src/controller/pipeline_config_assembler.py (if touched)
- docs/PIPELINE_RULES.md
- docs/ARCHITECTURE_v2_COMBINED.md
- docs/codex_context/ROLLING_SUMMARY.md (removing PR-#47B entry)

2) Re-running:

- pytest tests/controller -v
- pytest -v

to confirm that the previous state (with the failing enforcement test) is restored.

Because this PR is narrowly scoped to config-building in the controller, rollback is straightforward and low-risk.

---

11. Codex Execution Constraints

When implementing this PR, Codex must:

- Only modify the allowed files listed in section 5.
- Treat the tests as correct; do not relax or rewrite their expectations.
- Keep diffs small and focused on:
  - start_pipeline
  - any config-building helpers in PipelineController
  - minimal doc updates and rolling summary entry.

Codex must:

- Before coding, summarize what it plans to change in pipeline_controller.py to make the test pass.
- After coding, list the exact commands it ran and paste full output for:
  - pytest tests/controller/test_pipeline_controller_config_path.py -v
  - pytest tests/controller -v
  - pytest -v (if run).

No changes to queue internals, job history, cluster, or GUI are allowed in this PR.

---

12. Rolling Summary Update (for docs/codex_context/ROLLING_SUMMARY.md)

Append the following entry under the appropriate date heading:

- PR-#47B-PIPELINE-V2-AssemblerEnforcement-Hotfix-001 – Tightened PipelineController’s config construction so all production run paths now call PipelineConfigAssembler.build_from_gui_input (or equivalent) before submitting work to the runner/queue. This resolves the failing controller config-path test without modifying tests, and aligns controller behavior with the assembler-centric rules in PIPELINE_RULES and ARCHITECTURE_v2. Queue, history, cluster, and pipeline semantics remain unchanged.
