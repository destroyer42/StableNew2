Run Pipeline Path (V2) – Architecture Notes.md
1. High-Level Flow

At a high level, a user clicking Run in the GUI follows this path:

GUI V2

User configures stages (txt2img, img2img, refiners, hires, etc.) in the Pipeline tab.

User clicks Run / Run Now / Add to Queue.

AppController (run initiation)

The button event lands in AppController (V2 run controls helper, e.g. _start_run_v2).

AppController:

Reads current app_state.pipeline_state.

Builds a run_config (source, run_mode, prompt source / pack id, config snapshot).

Calls PipelineController.start_pipeline(run_config=run_config).

PipelineController (job creation + dispatch)

PipelineController.start_pipeline:

Validates that the pipeline is runnable (via its state manager).

Builds a PipelineConfig from the current pipeline state (stages, toggles, models, refs, etc.).

Constructs a Job with:

pipeline_config

run_mode (direct or queue)

metadata: source, prompt pack id, randomizer data, learning flags, etc.

Submits the job through the appropriate execution path depending on run_mode:

Direct: synchronous execution for “run now in this process”.

Queue: enqueue for background, possibly multi-job, execution.

Job Execution / Queue Layer

A job is pushed into the job queue abstraction and handled by:

A job execution controller / job service (JobService, JobExecutionController, or equivalent).

A single-node runner (SingleNodeJobRunner) that pulls jobs and executes them.

The queue executes the job payload, which calls back into PipelineController._run_pipeline_job(config=...).

PipelineController (job payload → pipeline runner)

_run_pipeline_job(config, pipeline_func=None) chooses the actual execution path:

Legacy hook: if run_full_pipeline(config) is provided (legacy harness/tests), use that.

Explicit pipeline_func: if a callable is passed (tests/compat), use that.

Default path: call self.run_pipeline(config), which is wired to the PipelineRunner.

PipelineRunner + Executor / API

PipelineRunner.run(config, cancel_token, log_callback):

Iterates the StageExecutionPlan derived from config.

For each stage, builds the executor payload (including refiner/hires metadata).

Calls into the Executor / API client (e.g., SD WebUI / HTTP layer).

Streams logs back via the controller’s log callback.

Accumulates generated images + metadata, including output paths.

On success, PipelineRunner.run(...) returns a result object (or dict) representing the run, including:

Per-stage outputs

Final images

Output directory references

Result Recording + GUI Update

PipelineController.run_pipeline:

Records the run in history / last-run store.

Returns the result object to _run_pipeline_job.

_run_pipeline_job normalizes this into a simple dict payload (e.g., { "result": result.to_dict() }) for the job system.

Job layer marks the job as COMPLETED (or FAILED) and signals the GUI.

GUI can then:

Refresh recent images / output browser.

Update status / logs.

Enable/disable controls based on state manager transitions.

2. Run Modes: Direct vs Queue

Direct Mode

Trigger: typical “Run” or “Run Now” use cases where the user expects immediate execution.

Behavior:

Job may still exist logically, but is executed synchronously:

JobService.submit_direct(job) → directly calls the job’s payload once.

UI blocks minimally but remains responsive (depending on how the runner thread is wired).

Best throughput for single-user, single run.

Queue Mode

Trigger: “Add to Queue” or batch/multi-job workflows.

Behavior:

Job is enqueued via JobService.submit_queued(job) or similar.

SingleNodeJobRunner loop:

Pulls the next job.

Invokes job.payload() which ultimately calls PipelineController._run_pipeline_job(config).

Transitions job state: QUEUED → RUNNING → COMPLETED / FAILED.

UI can show queue position, progress, and history.

Run Mode Source of Truth

The run_mode is selected by AppController based on which button is pressed (and/or user settings) and propagated in run_config.

PipelineController uses run_config and its state manager to:

Decide direct vs queue.

Tag job records so history can reflect how a run was initiated.

3. Config Objects and Metadata

PipelineConfig

Structured, typed representation of the full multi-stage pipeline:

Stage list (txt2img / img2img / ADetailer / upscale / refiners / hires).

Model selections, samplers, CFG / steps, image size, etc.

Stage-specific toggles and parameters.

Built from V2 pipeline state (GUI → app_state → config builder).

RunConfig (dict)

Lightweight runtime metadata bundle passed from GUI to controller:

run_mode (“direct” / “queue”)

source (“Run”, “Run Now”, “AddToQueue”, etc.)

prompt_source (free text vs prompt pack)

prompt_pack_id (if using saved prompts / packs)

Config snapshot identifiers (for reproducibility)

Stored in PipelineController (e.g., _last_run_config) for:

Last run restore

Analytics / logging

Learning system hooks (future).

4. Error Handling & Logging

Logging

PipelineController and PipelineRunner emit structured log events:

Run start (with config hash / run id)

Stage start/stop

Errors or early exits

Run complete with summary stats

Logs flow to:

On-screen GUI log panel

Structured logger (file/json) for debugging and analytics

Error Paths

If run_pipeline raises, _run_pipeline_job wraps the exception:

Returns { "error": str(exc) } to the job system.

Job is marked FAILED; GUI can show an error banner / toast and relevant log lines.

5. Legacy Hooks & Test Compatibility

To avoid breaking older tests and harnesses:

_run_pipeline_job first checks for a legacy run_full_pipeline(config) attribute:

If present and returns a dict, that result is used.

If a pipeline_func is explicitly passed (tests), it is invoked second.

Only if neither is used, does it fall back to the V2 default:

self.run_pipeline(config) → PipelineRunner.

This allows the new queue-backed run path to work without invalidating older test harnesses that haven’t yet been migrated.
1. High-Level Flow

At a high level, a user clicking Run in the GUI follows this path:

GUI V2

User configures stages (txt2img, img2img, refiners, hires, etc.) in the Pipeline tab.

User clicks Run / Run Now / Add to Queue.

AppController (run initiation)

The button event lands in AppController (V2 run controls helper, e.g. _start_run_v2).

AppController:

Reads current app_state.pipeline_state.

Builds a run_config (source, run_mode, prompt source / pack id, config snapshot).

Calls PipelineController.start_pipeline(run_config=run_config).

PipelineController (job creation + dispatch)

PipelineController.start_pipeline:

Validates that the pipeline is runnable (via its state manager).

Builds a PipelineConfig from the current pipeline state (stages, toggles, models, refs, etc.).

Constructs a Job with:

pipeline_config

run_mode (direct or queue)

metadata: source, prompt pack id, randomizer data, learning flags, etc.

Submits the job through the appropriate execution path depending on run_mode:

Direct: synchronous execution for “run now in this process”.

Queue: enqueue for background, possibly multi-job, execution.

Job Execution / Queue Layer

A job is pushed into the job queue abstraction and handled by:

A job execution controller / job service (JobService, JobExecutionController, or equivalent).

A single-node runner (SingleNodeJobRunner) that pulls jobs and executes them.

The queue executes the job payload, which calls back into PipelineController._run_pipeline_job(config=...).

PipelineController (job payload → pipeline runner)

_run_pipeline_job(config, pipeline_func=None) chooses the actual execution path:

Legacy hook: if run_full_pipeline(config) is provided (legacy harness/tests), use that.

Explicit pipeline_func: if a callable is passed (tests/compat), use that.

Default path: call self.run_pipeline(config), which is wired to the PipelineRunner.

PipelineRunner + Executor / API

PipelineRunner.run(config, cancel_token, log_callback):

Iterates the StageExecutionPlan derived from config.

For each stage, builds the executor payload (including refiner/hires metadata).

Calls into the Executor / API client (e.g., SD WebUI / HTTP layer).

Streams logs back via the controller’s log callback.

Accumulates generated images + metadata, including output paths.

On success, PipelineRunner.run(...) returns a result object (or dict) representing the run, including:

Per-stage outputs

Final images

Output directory references

Result Recording + GUI Update

PipelineController.run_pipeline:

Records the run in history / last-run store.

Returns the result object to _run_pipeline_job.

_run_pipeline_job normalizes this into a simple dict payload (e.g., { "result": result.to_dict() }) for the job system.

Job layer marks the job as COMPLETED (or FAILED) and signals the GUI.

GUI can then:

Refresh recent images / output browser.

Update status / logs.

Enable/disable controls based on state manager transitions.

2. Run Modes: Direct vs Queue

Direct Mode

Trigger: typical “Run” or “Run Now” use cases where the user expects immediate execution.

Behavior:

Job may still exist logically, but is executed synchronously:

JobService.submit_direct(job) → directly calls the job’s payload once.

UI blocks minimally but remains responsive (depending on how the runner thread is wired).

Best throughput for single-user, single run.

Queue Mode

Trigger: “Add to Queue” or batch/multi-job workflows.

Behavior:

Job is enqueued via JobService.submit_queued(job) or similar.

SingleNodeJobRunner loop:

Pulls the next job.

Invokes job.payload() which ultimately calls PipelineController._run_pipeline_job(config).

Transitions job state: QUEUED → RUNNING → COMPLETED / FAILED.

UI can show queue position, progress, and history.

Run Mode Source of Truth

The run_mode is selected by AppController based on which button is pressed (and/or user settings) and propagated in run_config.

PipelineController uses run_config and its state manager to:

Decide direct vs queue.

Tag job records so history can reflect how a run was initiated.

3. Config Objects and Metadata

PipelineConfig

Structured, typed representation of the full multi-stage pipeline:

Stage list (txt2img / img2img / ADetailer / upscale / refiners / hires).

Model selections, samplers, CFG / steps, image size, etc.

Stage-specific toggles and parameters.

Built from V2 pipeline state (GUI → app_state → config builder).

RunConfig (dict)

Lightweight runtime metadata bundle passed from GUI to controller:

run_mode (“direct” / “queue”)

source (“Run”, “Run Now”, “AddToQueue”, etc.)

prompt_source (free text vs prompt pack)

prompt_pack_id (if using saved prompts / packs)

Config snapshot identifiers (for reproducibility)

Stored in PipelineController (e.g., _last_run_config) for:

Last run restore

Analytics / logging

Learning system hooks (future).

4. Error Handling & Logging

Logging

PipelineController and PipelineRunner emit structured log events:

Run start (with config hash / run id)

Stage start/stop

Errors or early exits

Run complete with summary stats

Logs flow to:

On-screen GUI log panel

Structured logger (file/json) for debugging and analytics

Error Paths

If run_pipeline raises, _run_pipeline_job wraps the exception:

Returns { "error": str(exc) } to the job system.

Job is marked FAILED; GUI can show an error banner / toast and relevant log lines.

5. Legacy Hooks & Test Compatibility

To avoid breaking older tests and harnesses:

_run_pipeline_job first checks for a legacy run_full_pipeline(config) attribute:

If present and returns a dict, that result is used.

If a pipeline_func is explicitly passed (tests), it is invoked second.

Only if neither is used, does it fall back to the V2 default:

self.run_pipeline(config) → PipelineRunner.

This allows the new queue-backed run path to work without invalidating older test harnesses that haven’t yet been migrated.