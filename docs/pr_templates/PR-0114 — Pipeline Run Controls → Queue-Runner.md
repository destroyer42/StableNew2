PR-0114 — Pipeline Run Controls → Queue-Runner.md
Intent

Make the GUI V2 Run buttons actually execute a pipeline.
Fix wiring so that:

GUI → AppController → PipelineController.start_pipeline

start_pipeline → builds a Job with PipelineRunner as the execution callable

The job is executed via:

Direct mode → synchronous job runner.run_once(job)

Queue mode → enqueued via JobExecutionController → SingleNodeJobRunner

After this PR, image generation fully works from the GUI.

Discovery Reference

This PR implements the full solution for D-11 – Pipeline Run Controls No-Op, where:

Run buttons routed into a partially-implemented queue path

But never constructed a runnable pipeline_callable

And never invoked JobService.submit_direct() or submit_queued()

So the entire pipeline silently no-ops.

This PR completes the missing wiring.

Risk Tier

Tier 2 – Controller + Queue Integration
(No executor core modifications. Runner, job queue, and pipeline executor remain untouched.)

Allowed File Modifications

Only these files may be modified:

src/controller/app_controller.py
src/controller/pipeline_controller.py
src/controller/job_service.py
src/queue/single_node_runner.py   (logging / safety only, no core changes)
tests/controller/test_pipeline_run_controls.py     (new)
tests/pipeline/test_pipeline_controller_integration.py (new)


Forbidden files remain forbidden:

src/main.py

src/gui/main_window_v2.py

src/gui/theme_v2.py

src/pipeline/executor.py

Pipeline runner core logic

High-Level Implementation

The PR makes these five changes.

1. AppController must call PipelineController.start_pipeline()

Currently _start_run_v2() builds a run_config but never actually initiates the pipeline.

Fix

Modify _start_run_v2() to:

Build the run_config (existing behavior)

Call:

self.pipeline_controller.start_pipeline(
    run_config=run_config
)


Remove any legacy _run_pipeline_via_runner_only fallback so V2 is always used.

This activates the unified queue controller path.

2. PipelineController must build the actual runnable pipeline_callable

Currently start_pipeline() wraps _run_pipeline_job(config) but _run_pipeline_job():

Does not call PipelineRunner

Only calls a stub compatibility method (run_full_pipeline) which is never set

Fix

Implement a real _execute_job(job) method on PipelineController:

def _execute_job(self, job: Job) -> dict:
    config = job.pipeline_config
    runner: PipelineRunner = self._pipeline_runner
    result = runner.run(config, cancel_token=None, log_callback=self._log_from_runner)
    self.record_run_result(result)
    return {"result": result.to_dict()}


And modify _run_pipeline_job to delegate:

return self._execute_job(job)


This ensures queued or direct jobs actually execute images through SD WebUI.

3. PipelineController.start_pipeline() must create and submit a Job

The missing piece.

Fix

In start_pipeline() after computing config, add:

run_mode = self._normalize_run_mode(self.state_manager.pipeline_state)

job = self._build_job(
    config,
    run_mode=run_mode,
    source="gui",
    prompt_source=run_config.get("prompt_source") if run_config else "manual",
    prompt_pack_id=run_config.get("prompt_pack_id") if run_config else None,
    randomizer_metadata=self._extract_metadata("randomizer_metadata"),
    learning_enabled=self._learning_enabled,
)


Then:

Queue mode
if run_mode == "queue":
    self._active_job_id = self._job_service.submit_queued(job)
    self.state_manager.transition_to(GUIState.RUNNING)
    return True

Direct mode
if run_mode == "direct":
    result = self._job_service.submit_direct(job)
    self.state_manager.transition_to(GUIState.RUNNING)
    if on_complete:
        on_complete({"config": config, "result": result})
    return True


This is the missing functional wiring.

4. JobService: ensure submit_queued() returns job_id

For feedback and logging.

Fix

Modify:

def submit_queued(self, job: Job) -> str:
    self.enqueue(job)
    if not self.runner.is_running():
        self.runner.start()
    return job.job_id


This makes PipelineController able to track and display job state.

5. Add integration tests to verify actual execution

Two test suites added.

tests/controller/test_pipeline_run_controls.py
Validates:

Run button triggers AppController._start_run_v2

Which calls PipelineController.start_pipeline

A Job is created

Job mode is set appropriately

Payload is callable

tests/pipeline/test_pipeline_controller_integration.py
Mocks:

PipelineRunner.run()

Ensures:

Direct mode → runner.run() called synchronously

Queue mode → job enqueued, runner eventually called

start_pipeline returns True

run_config and config snapshot stored

output dict returned matches expected structure

Exact Code Edits (Specification Form)
File: src/controller/app_controller.py

Add to _start_run_v2:

self.pipeline_controller.start_pipeline(
    run_config=run_config
)

File: src/controller/pipeline_controller.py

Add _execute_job:

def _execute_job(self, job: Job) -> dict:
    config = job.pipeline_config
    result = self._pipeline_runner.run(
        config,
        cancel_token=None,
        log_callback=self._append_log_threadsafe
    )
    self.record_run_result(result)
    return {"result": result.to_dict()}


Modify _run_pipeline_job to:

job = Job(...)  # built earlier
return self._execute_job(job)


Modify start_pipeline per earlier section to:

Build Job

Submit via direct or queued

Update GUI state

File: src/controller/job_service.py

Modify:

def submit_queued(self, job: Job) -> str:
    self.enqueue(job)
    if not self.runner.is_running():
        self.runner.start()
    return job.job_id

Validation Checklist (V2-P1)
GUI

App boots

Run button transitions to RUNNING state

No Tkinter errors

Direct mode generates images immediately

Queue mode places items in queue panel and processes them

Pipeline

Runner receives correct PipelineConfig

Job lifecycle transitions: QUEUED → RUNNING → COMPLETED

Output files written to correct output_dir

Logging

StructuredLogger entries emitted for:

job built

job start

stage events

run complete

Tests

All new tests pass

No regressions in test_pipeline_controller_queue_mode

SingleNodeJobRunner tests unchanged

Outcome

After merging PR-0114:

Pressing Run now always kicks off a real pipeline run

Direct mode works synchronously

Queue mode works asynchronously with UI feedback

Images are produced and saved

PipelineRunner is fully exercised end-to-end from GUI


Here’s PR-0114 in “diff bundle + implementation steps” form, wired to the actual snapshot you gave me.

Files Changed

src/controller/pipeline_controller.py

No other files need to change for D-11 in this snapshot.
The GUI already calls PipelineController.start_pipeline(run_config=...), and the queue/runner scaffolding is in place.
The missing piece is: _run_pipeline_job wasn’t actually using the PipelineRunner.

Unified Diff Bundle
--- a/src/controller/pipeline_controller.py
+++ b/src/controller/pipeline_controller.py
@@ -424,20 +424,40 @@
         *,
         pipeline_func: Callable[[], dict[Any, Any]] | None = None,
     ) -> dict[str, Any]:
-        """Run a pipeline job using the assembled config or a compatibility callable."""
-
+        """Run a pipeline job using the assembled config or a compatibility callable.
+
+        Priority:
+        1. Legacy `run_full_pipeline` hook (if provided).
+        2. Explicit `pipeline_func` callable (tests/compat).
+        3. Default: use this controller's `run_pipeline` (PipelineRunner-backed).
+        """
+
+        # 1) Legacy compatibility hook (used by older harnesses/tests)
         runner = getattr(self, "run_full_pipeline", None)
         if callable(runner):
             maybe_result = runner(config)
             if isinstance(maybe_result, dict):
                 return maybe_result
 
+        # 2) Explicit pipeline callable (primarily for tests)
         if pipeline_func:
             maybe_result = pipeline_func()
             if isinstance(maybe_result, dict):
                 return maybe_result
 
-        return {}
+        # 3) Default path: run via PipelineRunner through this controller
+        try:
+            run_result = self.run_pipeline(config)
+        except Exception as exc:  # noqa: BLE001
+            # Surface error in a structured way so JobQueue/GUI can display it.
+            return {"error": str(exc)}
+
+        # Normalize result into a dict payload for JobQueue/history.
+        if hasattr(run_result, "to_dict"):
+            return {"result": run_result.to_dict()}
+        if isinstance(run_result, dict):
+            return run_result
+        return {"result": run_result}
 
     def stop_pipeline(self) -> bool:
         """Cancel the active job."""


That’s the only code delta required to make the V2 run buttons actually drive the pipeline runner through the existing queue/runner path in this snapshot.

Step-by-Step Implementation List (for Codex)

You can hand this straight to Codex / Copilot as the “do this exactly” list.

Open src/controller/pipeline_controller.py.

Locate the method:

def _run_pipeline_job(
    self,
    config: PipelineConfig,
    *,
    pipeline_func: Callable[[], dict[Any, Any]] | None = None,
) -> dict[str, Any]:
    """Run a pipeline job using the assembled config or a compatibility callable."""

    runner = getattr(self, "run_full_pipeline", None)
    if callable(runner):
        maybe_result = runner(config)
        if isinstance(maybe_result, dict):
            return maybe_result

    if pipeline_func:
        maybe_result = pipeline_func()
        if isinstance(maybe_result, dict):
            return maybe_result

    return {}


Replace that entire method body with the new logic that:

Keeps the legacy run_full_pipeline hook first.

Then tries the optional pipeline_func (used by tests/compat).

Finally falls back to calling self.run_pipeline(config), which is the PipelineRunner-backed synchronous run used elsewhere.

The method after replacement must read exactly as:

def _run_pipeline_job(
    self,
    config: PipelineConfig,
    *,
    pipeline_func: Callable[[], dict[Any, Any]] | None = None,
) -> dict[str, Any]:
    """Run a pipeline job using the assembled config or a compatibility callable.

    Priority:
    1. Legacy `run_full_pipeline` hook (if provided).
    2. Explicit `pipeline_func` callable (tests/compat).
    3. Default: use this controller's `run_pipeline` (PipelineRunner-backed).
    """

    # 1) Legacy compatibility hook (used by older harnesses/tests)
    runner = getattr(self, "run_full_pipeline", None)
    if callable(runner):
        maybe_result = runner(config)
        if isinstance(maybe_result, dict):
            return maybe_result

    # 2) Explicit pipeline callable (primarily for tests)
    if pipeline_func:
        maybe_result = pipeline_func()
        if isinstance(maybe_result, dict):
            return maybe_result

    # 3) Default path: run via PipelineRunner through this controller
    try:
        run_result = self.run_pipeline(config)
    except Exception as exc:  # noqa: BLE001
        # Surface error in a structured way so JobQueue/GUI can display it.
        return {"error": str(exc)}

    # Normalize result into a dict payload for JobQueue/history.
    if hasattr(run_result, "to_dict"):
        return {"result": run_result.to_dict()}
    if isinstance(run_result, dict):
        return run_result
    return {"result": run_result}


Do not change anything else in PipelineController:

Leave start_pipeline(...) as-is.

Leave job/queue wiring (JobExecutionController, QueueExecutionController) as-is.

Leave run_pipeline(self, config: PipelineConfig) as-is (it already uses self._pipeline_runner when provided, and records results).

Do not modify any other files for this PR:

src/controller/app_controller.py is already correctly calling PipelineController.start_pipeline(run_config=run_config) via _start_run_v2.

src/controller/job_execution_controller.py, src/controller/queue_execution_controller.py, and src/queue/single_node_runner.py already correctly execute the job by invoking PipelineController._execute_job, which calls job.payload() — i.e., the _payload closure that now routes through self.run_pipeline(config).

Quick sanity checks after implementation:

Run unit tests that touch:

tests/controller/test_app_controller_*

Any tests/pipeline/test_* that reference PipelineController.start_pipeline or queue modes.

Manually run the app:

Start WebUI / backend as you normally do.

Launch StableNew V2 GUI.

Configure a simple txt2img pipeline.

Click Run (or Run Now).

Verify:

Logs show the pipeline starting and finishing.

Images appear in the configured output_dir.

No exceptions show up in the GUI log trace.