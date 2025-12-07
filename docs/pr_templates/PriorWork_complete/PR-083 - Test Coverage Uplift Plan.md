PR-083 — Test Coverage Uplift Plan (Phase 1 Implementation).md
Intent

Implement Phase 1 of a structured test coverage uplift, based on the existing coverage report, with a focus on:

High-value, high-risk modules that are currently under-tested.

Codifying a minimum coverage floor for critical areas.

Laying groundwork for follow-on coverage uplift PRs (Phase 2+), not trying to get to 90–100% in a single jump.

This PR adds tests only (or harmless configuration changes), no production logic changes aside from tiny refactorings needed to make code testable.

Scope & Risk

Risk: Medium

Subsystems: Tests, pytest config, minor “make testable” refactors

Specifically targets areas with low coverage but high importance:

app_controller

job_queue / single_node_runner

webui_process_manager

GUI V2 status bar & logging integration

Allowed Files
Test code

tests/controller/test_app_controller_config.py

tests/controller/test_app_controller_pipeline_flow_pr0.py

tests/controller/test_job_history_service.py

tests/queue/*.py

tests/api/test_webui_process_manager.py

tests/gui_v2/test_gui_logging_integration.py

tests/gui_v2/test_status_bar_v2.py (or add if missing)

New test files in tests/* as needed.

Coverage / pytest config

pytest.ini

.coveragerc (if present / introduced)

Minor refactors for testability (only if needed)

Very small changes like adding injection points, making internal functions public, or adding logging getters:

src/controller/app_controller.py (only tiny helpers; no behavior changes)

src/api/webui_process_manager.py (e.g., factoring out process creation into overridable method)

src/gui/status_bar_v2.py (public helper to get/set status text for tests)

Forbidden Files

Core pipeline logic:

src/pipeline/executor.py

src/pipeline/pipeline_runner.py

src/pipeline/stage_sequencer.py

Entry-point files:

src/main.py

src/gui/main_window_v2.py

Implementation Plan
1. Define coverage goals & thresholds

Introduce or update .coveragerc / pytest config:

Global target not enforced yet, but:

Add report: fail_under = 55 for now (just above current 51.47%) or

Start with report-only threshold and no hard fail (to avoid CI disruption initially).

Document these as comments in .coveragerc.

2. AppController: config & lifecycle coverage

Add tests to:

Validate get_current_config() includes:

Refiner/hires fields from PR-081D-4

Stage enable/disable flags

Validate lifecycle transitions:

IDLE → RUNNING → IDLE

RUNNING → ERROR → IDLE (pipeline error)

RUNNING → CANCELLED → IDLE (cancel)

These tests must not require real WebUI; use FakeRunner/FakePipeline from PR-082 helpers.

3. JobQueue / SingleNodeRunner

Expand tests to cover:

JobQueue._update_status and JobQueue._record_status with result (from PR-081D-2).

SingleNodeRunner:

mark_running, mark_completed paths

error propagation

cancellation behavior.

Ensure we have tests for:

Multiple jobs

Error state transitions

Status/history retrieval.

4. WebUIProcessManager coverage

Add tests that:

Validate correct config translation to subprocess invocation.

Check behavior on already-running, already-stopped processes.

Confirm proper error on startup failure (with DummyProcess).

Re-use the DummyProcess helper from PR-081D-3 / PR-082.

5. GUI V2 logging & status bar coverage

Add tests for:

test_gui_logging_integration.py:

Logging messages appear in the GUI log panel.

Errors propagate to status bar.

Status bar:

Generic status updates.

“Run started / completed / failed” messages reflect lifecycle transitions.

6. Update coverage report & document Phase 2 targets

At the end of PR-083:

Capture the new coverage percentage (expected modest bump).

In a brief doc or comment (or new docs/Test_Coverage_Plan_V2-P1.md), outline Phase 2 targets:

More granular tests for advanced prompt editor, randomizer, learning UIs, etc.

Acceptance Criteria

Coverage for:

src/controller/app_controller.py increases by a measurable margin.

Queue-related modules (job_queue, single_node_runner) show improved coverage.

webui_process_manager coverage at least > 65%.

GUI logging/status bar coverage > 60% (if previously lower).

All new tests pass.

No regression in existing tests.

Validation Checklist

 Coverage report shows global increase (even modest: +2–3% overall).

 No new flakiness or long-running tests introduced.

 Phase 2 coverage targets are documented for future PRs.

 No behavior changes in runtime code (beyond trivial testability shims).

🚀 Deliverables

New tests across controller/queue/GUI/API.

Updated coverage configs.

Documented path for Phase 2 coverage uplift.