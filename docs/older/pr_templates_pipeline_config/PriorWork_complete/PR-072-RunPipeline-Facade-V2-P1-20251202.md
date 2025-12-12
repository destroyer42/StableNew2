PR-072-RunPipeline-Facade-V2-P1-20251202.md
0. Snapshot & Guardrails

Authoritative snapshot for this PR

StableNew-snapshot-20251201-230021.zip

Guardrails

Operate only on the current snapshot + this PR spec.

Do not reintroduce V1/legacy codepaths.

Keep changes tightly scoped to controller/runner wiring and minimal test updates.

1. Purpose & Intent

Goal:
Introduce a public run_pipeline() facade on AppController and ensure the V2 pipeline runner is actually invoked when the app is driven either by:

The V2 Full Pipeline Journey tests, and

The Pipeline tab’s “Run” action (via controller).

This PR addresses the failures where:

AppController is missing a run_pipeline method (JT05 and others expect it), and

test_v2_full_pipeline_journey_runs_once sees len(fake_runner.run_calls) == 0 when on_run_clicked() is invoked.

We are not implementing the entire multi-stage TXT2IMG/IMG2IMG/ADetailer/Upscale logic here—just the controller → runner wiring and the public facade.

2. Scope of Changes
2.1 Files Allowed to Change

These are the only files this PR may touch:

src/controller/app_controller.py
src/app_factory.py
tests/journeys/test_v2_full_pipeline_journey.py
tests/journeys/fakes/fake_pipeline_runner.py


Only modify each file as minimally as necessary to:

Add AppController.run_pipeline(...),

Wire on_run_clicked() to that facade,

Ensure FakePipelineRunner is invoked and trackable in tests,

Adjust the full-journey test expectations for the new entrypoint (if needed).

2.2 Forbidden Files (Do NOT modify)
src/gui/*
src/pipeline/*
src/queue/*
src/main.py
src/webui/*


(Except for the one explicit controller file listed above: src/controller/app_controller.py.)

No GUI layout changes, no threading changes, no executor/queue changes in this PR.

3. Desired Behaviors (“Done” Criteria)

After this PR:

Public Facade Exists

AppController exposes a public method:

def run_pipeline(self) -> object:
    ...


This can be imported and used directly by tests and non-GUI callers.

Pipeline Runner Is Actually Called

run_pipeline() (and on_run_clicked() when invoked from GUI) must ultimately call:

self.pipeline_runner.run(...)


In the V2 Full Pipeline Journey test, the injected FakePipelineRunner must record exactly one call.

Journey Tests Expectations Are Met

test_v2_full_pipeline_journey_runs_once observes:

assert len(fake_runner.run_calls) == 1


and it passes.

test_v2_full_pipeline_journey_handles_runner_error verifies that:

The controller calls the runner once,

On error, the lifecycle transitions to the expected error state,

The test passes.

No Behavioral Regression for Existing Callers

Existing controller methods (on_run_clicked(), etc.) continue to function, but are refactored to reuse run_pipeline() instead of duplicating logic.

No additional threading or async behavior is introduced in this PR.

4. Functional Design
4.1 AppController.run_pipeline() (New Public Facade)

Location:
src/controller/app_controller.py

Signature:

class AppController(...):

    def run_pipeline(self):
        """
        High-level, public entrypoint to run the current pipeline configuration.

        Responsibilities:
        - Read the current pipeline configuration from app state / pipeline tab.
        - Construct the pipeline runner input (sequence/config).
        - Call self.pipeline_runner.run(...) synchronously.
        - Update lifecycle state / logs appropriately.
        - Return the result from the runner (or None if the runner has no return).
        """


Behavior details:

Read configuration from app state / pipeline tab

Use whatever existing method(s) currently builds a PipelineConfig or equivalent object (e.g., self.app_state.build_pipeline_config() or similar).

Do not introduce a new source-of-truth; reuse what the snapshot provides.

Lifecycle state before/after run

Before invoking the runner:

Set lifecycle to a “running” or “busy” state, reusing existing lifecycle enums or helpers (e.g., LifecycleState.RUNNING).

After success:

Set lifecycle to the corresponding “idle” or “ready” state.

After exception:

Set lifecycle to an error state and re-raise or return an error indicator, consistent with how the existing on_run_clicked() / _run_pipeline_thread() currently handle errors.

Call the injected pipeline runner

Ensure AppController.__init__ accepts and stores a pipeline_runner reference (if not already):

def __init__(..., pipeline_runner, ...):
    self.pipeline_runner = pipeline_runner


Inside run_pipeline():

result = self.pipeline_runner.run(pipeline_config)
return result


No new runner instances may be created here; always use the injected one.

Logging

Use existing controller logging facilities (e.g., _append_log) to emit basic messages like:

“Starting pipeline run”

“Pipeline run completed”

“Pipeline run failed: {error}”

Keep log messages short and high-signal.

4.2 Refactor on_run_clicked() to Use run_pipeline()

Location:
src/controller/app_controller.py

There is currently some path like:

def on_run_clicked(self):
    # existing logic (may be incomplete)


Refactor so that both GUI-driven and test-driven runs use the same core logic:

def on_run_clicked(self):
    """
    GUI callback for 'Run' button.
    Delegates to run_pipeline(); any GUI-specific side effects (buttons, etc.)
    should be minimal and non-blocking.
    """
    self.run_pipeline()


If there is an existing _run_pipeline_thread() with threading logic, do not delete it, but:

For now, call run_pipeline() synchronously.

Later PRs can reintroduce threading in a controlled way if needed.

The key is: there must be exactly one central codepath that actually calls pipeline_runner.run(...), and that path must be run_pipeline().

4.3 Ensure pipeline_runner Injection via build_v2_app

Location:
src/app_factory.py

The V2 Full Pipeline Journey test likely uses something like:

from src.app_factory import build_v2_app
app = build_v2_app(root, pipeline_runner=fake_runner)
controller = app.controller


Tasks:

Verify that build_v2_app(...) accepts a pipeline_runner argument and passes it into AppController(...).

If it does not:

Extend build_v2_app signature to accept pipeline_runner (with a sensible default for “real” application use, e.g., create the real runner when None).

Pass the pipeline_runner into the AppController constructor.

Confirm that AppController stores this runner on self.pipeline_runner.

No other factory behavior should change.

4.4 Ensure FakePipelineRunner Tracks Calls

Location:
tests/journeys/fakes/fake_pipeline_runner.py

We want the journey test to assert that the runner was invoked exactly once.

Tasks:

Confirm FakePipelineRunner exposes a list-like attribute such as run_calls.

If it does not exist, add:

class FakePipelineRunner:
    def __init__(self):
        self.run_calls = []

    def run(self, pipeline_config):
        self.run_calls.append(pipeline_config)
        return {"status": "ok"}


The exact shape of pipeline_config doesn’t matter for this PR; tests only care that run was called and resulted in one entry in run_calls.

4.5 Align test_v2_full_pipeline_journey with the New Facade

Location:
tests/journeys/test_v2_full_pipeline_journey.py

The test will do one or both of:

Drive the app via GUI callback (on_run_clicked()).

Or call the controller method directly.

Tasks:

Verify how the test currently triggers the pipeline:

If it calls app.controller.on_run_clicked(), keep that, but ensure that path now flows through run_pipeline() as described.

Optionally, add a simple assertion that controller.run_pipeline exists and is callable.

Update the assertion that checks pipeline invocation:

def test_v2_full_pipeline_journey_runs_once(fake_runner, app):
    # ... after initiating a run ...
    assert len(fake_runner.run_calls) == 1


For the error-handling test (...handles_runner_error):

Ensure the fake runner is configured to raise an exception when run is called.

Confirm the test still observes:

The runner was called once, and

The controller lifecycle transitioned to an error state as expected.

5. Non-Goals (Out of Scope for PR-072)

No changes to:

Queue/job-system behavior.

Multi-stage TXT2IMG/IMG2IMG/ADetailer/Upscale semantics.

PipelineTabFrame attributes (upscale_factor, prompt_text, etc.) that JT05 depends on.

Tk/TCL handling (that was PR-071).

No changes to threading or async design.

No changes to learning / history / JSONL logging beyond minimal log messages.

6. Test Plan

Run at minimum:

pytest tests/journeys/test_v2_full_pipeline_journey.py::test_v2_full_pipeline_journey_runs_once -q
pytest tests/journeys/test_v2_full_pipeline_journey.py::test_v2_full_pipeline_journey_handles_runner_error -q


Optionally (sanity / regression):

pytest tests/journeys/test_jt03_txt2img_pipeline_run.py::test_jt03_txt2img_pipeline_run -q
pytest tests/journeys/test_jt04_img2img_adetailer_run.py::test_jt04_img2img_adetailer_pipeline_run -q
pytest tests/journeys -q


All existing green tests must remain green.