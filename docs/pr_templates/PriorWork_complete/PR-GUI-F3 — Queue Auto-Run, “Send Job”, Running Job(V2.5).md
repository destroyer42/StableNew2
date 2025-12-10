PR-GUI-F3 — Queue Auto-Run, “Send Job”, Running Job Card & Persistence (V2.5).md

Risk Tier: High (touches JobService/queue core; must respect PR-204A–E invariants and queue testing pitfalls)

1. Summary

This PR turns the queue into the authoritative driver of pipeline execution:

Adds a Queue Auto-Run toggle that, when enabled, automatically dispatches jobs as soon as they appear.

Introduces a “Send Job” button that manually dispatches the top job in the queue when auto-run is disabled or the queue is paused.

Consolidates queue control into a single Pause/Resume toggle that gates dispatching of new jobs.

Implements a dedicated Running Job card that shows which queued job is currently running, with:

Status

Basic progress indicator

Elapsed time and simple ETA stub

Cancel and Cancel + Return to Queue actions

Adds queue persistence using a queue_store_v2 module: queued jobs and queue state survive restarts, and the UI is repopulated on startup.

All behavior remains grounded in NormalizedJobRecord / JobSpecV2 and JobService; nothing is GUI-only magic.

2. Problem Statement

Right now, even after the 204A–D integration work:

The queue UI is visually present but not fully authoritative:

Auto-run semantics are unclear / incomplete.

There is no clear concept of “manual dispatch” for a single job.

The relationship between queue and running job is fuzzy:

Users can’t easily see which queue item is currently executing.

Pause vs. resume behavior isn’t obvious or centrally controlled.

The queue does not persist across restart:

Long job lists are lost if the app or machine restarts.

There is no concept of resuming a previous queue.

From the wishlist: you want:

Queue-first execution model (all jobs go through queue).

Auto-run queue behavior, plus manual Send Job control.

A clear, separate Running Job card.

Persistent queue that auto-resumes.

This PR addresses those gaps, on top of the normalized job pipeline from PR-204.

3. Goals

Queue-first driver:

All pipeline jobs flow through JobService’s queue, whether auto-run or manually dispatched.

Auto-run queue:

When enabled and not paused: whenever queue is non-empty and no job is running, JobService dispatches the next job automatically.

“Send Job” button:

When clicked:

If no job running → immediately dispatch the top job in the queue.

If a job is already running → mark next job as “pending” and dispatch it as soon as current job completes (i.e., queue behaves as normal, but user triggers an immediate run).

Honors pause state: if queue is paused, Send Job should not dispatch until unpaused.

Pause/Resume toggle:

Single toggle in the Queue panel:

Paused: no new jobs are dispatched from the queue, regardless of auto-run or Send Job.

Running: queue can dispatch jobs via auto-run or Send Job.

Running Job card:

Clearly shows:

Which queue entry is running (order/index, id, summary).

Status: running / paused / completed / cancelled.

A simple progress bar and elapsed time + ETA stub.

Buttons:

Pause/Resume job (per-job if supported, or just pausing the queue if that’s the only lever).

Cancel (drop job entirely).

Cancel + Return to Queue (job goes back to bottom of queue).

Queue persistence & resume:

On shutdown or significant queue changes: persist queue state + minimal queue config to disk.

On startup: load persisted queue and repopulate JobService queue and GUI.

If auto-run was enabled and not paused when last shut down, new session should re-enter that state.

4. Non-Goals

No change to:

How JobBuilderV2 or ConfigMergerV2 build NormalizedJobRecord lists.

Core pipeline/executor behavior beyond simple progress hooks.

Randomizer semantics or RunConfigV2 structure.

No changes to:

Stage-level configs (txt2img/img2img/refiner/hires/upscale).

Learning or cluster compute systems.

No new job types; only scheduling/queueing improvements.

5. Architectural Context

This PR assumes:

NormalizedJobRecord and JobBuilderV2.build_jobs() already exist and are used by PipelineController for job construction.

JobUiSummary exists and is used to render queue and preview items.

JobService / job_queue layer already provides basic:

submit_queued(job_spec) / equivalent.

Background runner that processes queued jobs asynchronously.

This PR extends JobService + GUI in a queue-centric way:

Queue UI → JobService (queue state + control flags).

JobService → Runner → JobHistory (execution and status).

Running Job card is a read-only projection of JobService’s “current job” state plus control buttons calling JobService methods.

6. Scope — Allowed Files

Queue / Service layer

src/pipeline/job_queue_v2.py (or equivalent queue backing module)

src/controller/job_service.py (or equivalent JobService implementation)

Persistence

src/services/queue_store_v2.py (new module)

Or src/pipeline/queue_store_v2.py if that’s more consistent with repo layout.

GUI / App State

src/gui/app_state_v2.py

To add queue control flags (auto_run, paused) and persisted state hooks.

src/gui/panels_v2/queue_panel_v2.py

To wire Auto-run, Pause/Resume, Send Job controls and queue status.

src/gui/panels_v2/running_job_panel_v2.py

To render Running Job card and handle per-job controls.

src/gui/views/pipeline_tab_frame_v2.py

To compose Queue + Running Job panels and wire callbacks to AppController.

Controller

src/controller/app_controller.py

To translate GUI events (Auto-run toggle, Pause/Resume, Send Job, Cancel, Cancel+Return) into calls to JobService.

src/controller/pipeline_controller.py

Only if very small changes are required to integrate with new JobService methods (e.g., updated queue control calls).

Tests

tests/pipeline/test_job_queue_persistence_v2.py (new)

tests/controller/test_job_service_queue_controls_v2.py (new)

tests/gui_v2/test_queue_panel_autorun_and_send_job_v2.py (new)

tests/gui_v2/test_running_job_panel_controls_v2.py (new)

7. Forbidden Files

Do not modify:

src/main.py

src/pipeline/executor*.py (beyond minimal non-logic progress hook wiring if absolutely necessary)

src/api/*

Randomizer engine:

src/randomizer/randomizer_engine_v2.py

Core theme:

src/gui/theme_v2.py (no new tokens; reuse existing styles)

Any V1/legacy queue or GUI code.

Any change that would require touching these must be split into a separate, explicit PR.

8. Step-by-Step Implementation
A. Queue Persistence: queue_store_v2

New module: src/services/queue_store_v2.py

Define a simple, versioned persistence schema:

Base unit is a serializable snapshot derived from NormalizedJobRecord:

@dataclass
class QueueSnapshotV1:
    jobs: list[dict]  # each dict is NormalizedJobRecord.to_queue_snapshot()
    auto_run_enabled: bool
    paused: bool


Use existing NormalizedJobRecord.to_queue_snapshot() / equivalent; do not invent fields ad-hoc.

Implement functions:

load_queue_snapshot() -> QueueSnapshotV1 | None

save_queue_snapshot(snapshot: QueueSnapshotV1) -> None

Backed by a JSON file in a predictable location (e.g., under app config dir).

Error handling:

If file missing or malformed → return None (start with empty queue).

Keep I/O minimal and synchronous; no threads here.

B. Extend JobService / Job Queue for Auto-Run & Pause

In job_queue_v2.py and/or job_service.py:

Introduce queue control flags in JobService:

class JobService:
    def __init__(...):
        self._auto_run_enabled: bool = False
        self._queue_paused: bool = False


Add getter/setter APIs:

def set_auto_run(self, enabled: bool) -> None: ...
def is_auto_run_enabled(self) -> bool: ...
def set_queue_paused(self, paused: bool) -> None: ...
def is_queue_paused(self) -> bool: ...


Integrate with dispatch loop:

Wherever the queue worker decides “should I dispatch the next job?”, ensure it only does so when:

Queue is not paused, and

Either:

Auto-run is enabled, or

A manual “Send Job” call explicitly triggered a dispatch (see below).

Expose convenience methods for controller:

def send_next_job(self) -> None:
    """
    Dispatch the next job in queue *once*, respecting pause state.
    Used when auto_run is False and user clicks 'Send Job'.
    """


Implementation:

If _queue_paused → no-op.

Pop top job and pass to existing runner dispatch path.

Persistence hooks:

Add:

def to_queue_snapshot(self) -> QueueSnapshotV1: ...
def load_from_queue_snapshot(self, snapshot: QueueSnapshotV1) -> None: ...


Use underlying queue’s queued JobSpecV2 / NormalizedJobRecord snapshots.

C. Wire Persistence into Startup / Shutdown

In an appropriate app boot/shutdown location (likely in JobService or controller/app initialization):

On JobService initialization:

Call queue_store_v2.load_queue_snapshot().

If present:

Recreate queue jobs from stored snapshots using existing JobSpecV2 / NormalizedJobRecord reconstruction logic.

Restore auto_run_enabled and paused flags.

On significant queue events:

After:

Job added

Job removed

Clear queue

Auto-run toggle

Pause/Resume toggle

Call save_queue_snapshot(...) with updated snapshot.

D. Running Job Card Behavior

In running_job_panel_v2.py:

Define a clear public API:

class RunningJobPanelV2(...):
    def update_running_job(self, job_summary: JobUiSummary | None) -> None: ...
    def update_progress(self, progress: float | None, eta_seconds: float | None) -> None: ...
    def set_controls_enabled(self, can_pause: bool, can_cancel: bool, can_return: bool) -> None: ...


UI elements:

Labels:

“Running Job #<queue_index>”

Model / prompt snippet from JobUiSummary.

Progress:

Simple progress bar (0–100%), with optional text.

Timing:

“Elapsed: 00:00:12, ETA: ~00:01:20” (ETA can be naive: proportion of steps completed, or None → display “ETA: —”).

Buttons:

Pause/Resume job (if JobService supports per-job pause; otherwise forward to queue pause).

Cancel (drop job completely).

Cancel + Return To Queue (requeue job at bottom).

Callbacks:

Exposed as constructor parameters or setters, e.g.:

def __init__(..., on_pause_resume, on_cancel, on_cancel_and_return): ...


Integration with JobService:

AppController listens to JobService “job started / job finished / job cancelled” events (whatever event bus or polling is available) and updates RunningJobPanelV2 accordingly.

E. Queue Panel Controls: Auto-Run, Pause/Resume, “Send Job”

In queue_panel_v2.py:

Add controls near the top of the panel:

Auto-run Queue checkbox.

Pause/Resume Queue toggle button (single button, text changes).

Send Job button.

Behavior:

Auto-run checkbox:

On toggle → call AppController → JobService set_auto_run(...).

Pause/Resume:

On toggle:

If currently running → set paused = True.

If paused → set paused = False.

Call AppController → JobService set_queue_paused(...).

Send Job:

Calls AppController → JobService send_next_job().

Should be:

Disabled when queue empty.

Disabled when a job is running and auto-run is already enabled (optional UX to avoid confusion).

Must honor paused state:

JobService handles this; if paused, send_next_job() is a no-op.

Keep state mirrored in AppStateV2:

app_state_v2.py should keep queue_auto_run and queue_paused flags so GUI can be rehydrated across sessions.

F. Controller Wiring

In app_controller.py (and minimally in pipeline_controller.py if necessary):

Add handlers:

def on_queue_auto_run_toggled(self, enabled: bool) -> None: ...
def on_queue_pause_toggled(self, paused: bool) -> None: ...
def on_queue_send_job(self) -> None: ...
def on_running_job_cancel(self) -> None: ...
def on_running_job_cancel_and_return(self) -> None: ...


Each handler:

Updates AppStateV2 flags.

Calls the appropriate JobService method.

Running job state updates:

On job start / completion / cancel / return:

AppController updates both:

Queue panel (to reflect which job is now running / removed).

RunningJobPanelV2 (with new summary and controls).

Ensure consistency with KNOWN_PITFALLS_QUEUE_TESTING:

GUI tests must always interact via:

GUI → AppController → PipelineController → JobService → Runner → JobHistory.

G. Progress & ETA Integration

If runner already exposes progress events:

JobService subscribes and tracks per-job progress.

AppController relays progress to RunningJobPanelV2.

If not:

Implement a minimal stub:

Progress jumps: 0 → 100 on start/finish.

ETA shown as “—”.

This keeps UI semantics stable and allows later enhancement without schema changes.

9. Required Tests

Follow patterns in KNOWN_PITFALLS_QUEUE_TESTING.md (no direct runner driving, no sleep-based timing, etc.).

A. Pipeline / Service Tests

File: tests/pipeline/test_job_queue_persistence_v2.py

test_queue_persist_and_load_roundtrip

Build a small list of NormalizedJobRecord / JobSpecV2 queued via JobService.

Set auto_run and paused flags.

Persist via to_queue_snapshot() + save_queue_snapshot().

Recreate JobService in a fresh instance using load_queue_snapshot().

Assert:

Same number of queued jobs with same ids/config snapshot.

Flags (auto_run_enabled, paused) restored.

test_send_next_job_respects_pause_state

Queue several jobs.

Set paused=True.

Call send_next_job(); assert no job dispatched (use JobHistory or mocked runner).

Set paused=False, call send_next_job(); assert exactly one job dispatched.

test_auto_run_dispatches_until_empty

Queue N jobs.

Set auto_run=True, paused=False.

Let JobService run; poll JobHistory until all jobs completed.

Assert:

All N jobs eventually reached a terminal state.

Queue empty at the end.

B. Controller Tests

File: tests/controller/test_job_service_queue_controls_v2.py

test_auto_run_toggle_updates_job_service

Simulate GUI auto_run toggle via AppController.

Assert JobServiceset_auto_run called with correct value.

test_pause_resume_toggle_updates_job_service

Simulate clicking Pause, then Resume.

Assert set_queue_paused(True/False) calls.

test_send_job_calls_send_next_job

Queue non-empty.

Simulate “Send Job” click.

Assert JobService’s send_next_job() called.

test_cancel_and_return_requeues_job

Simulate running job.

Trigger Cancel+Return via RunningJobPanel callback.

Assert:

Current job is aborted.

A new queued job with same id appears at end of queue.

C. GUI Tests

File: tests/gui_v2/test_queue_panel_autorun_and_send_job_v2.py

Ensure (skipped if Tk not available):

Auto-run checkbox reflects state from AppStateV2 and updates via callback.

Pause/Resume button text flips correctly.

Send Job button disabled when queue empty.

Send Job invokes the correct callback when enabled.

File: tests/gui_v2/test_running_job_panel_controls_v2.py

test_running_job_panel_renders_summary

Pass a fake JobUiSummary.

Assert label text shows id + prompt snippet.

test_running_job_panel_buttons_call_callbacks

Connect fake callbacks for pause/resume, cancel, cancel+return.

Simulate button presses and assert callbacks invoked exactly once.

10. Acceptance Criteria

PR-GUI-F3 is complete when:

Queue:

Has working Auto-run toggle, persisted across restarts.

Has working Pause/Resume toggle that gates dispatch.

Has working Send Job button that dispatches exactly one job from top of queue, honoring pause state.

Running job:

Dedicated Running Job card shows current job info.

Cancel and Cancel+Return update queue and JobHistory correctly.

Basic progress and elapsed time displayed (even if ETA is naive).

Persistence:

Restarting the app with queued jobs preserves:

Queue content.

Auto-run flag.

Paused state.

Tests:

All new tests pass.

Existing pipeline/controller tests (including PR-204A–E) remain green.

No violations of KNOWN_PITFALLS_QUEUE_TESTING patterns.

11. Rollback Plan

To revert PR-GUI-F3:

Restore originals for:

job_service.py

job_queue_v2.py

app_state_v2.py

queue_panel_v2.py

running_job_panel_v2.py

pipeline_tab_frame_v2.py

Remove:

services/queue_store_v2.py

All new tests under tests/pipeline, tests/controller, tests/gui_v2 related to this PR.

Delete any persisted queue state file created by queue_store_v2.

Confirm:

Queue reverts to non-persistent, non-auto-run behavior.

No UI elements for Auto-run, Send Job, or Running Job card remain.

12. Potential Pitfalls (for Copilot / Codex)

Mixing manual dispatch with background worker incorrectly

Don’t bypass JobService’s existing queue runner with ad-hoc “run_next_now” calls.

send_next_job() must go through the same path as auto-run dispatch; it should not invent a new runner path or directly call executor.

Follow the guidance in KNOWN_PITFALLS_QUEUE_TESTING.md: drive via JobService, not runner.

Persisting the wrong structure

Do not serialize entire rich objects (with Tk handles, controllers, etc.).

Persist only queue snapshots built from NormalizedJobRecord.to_queue_snapshot() / JobSpecV2 fields, as in PR-204’s conventions.

On load, rebuild queue entries using existing factories; don’t bake serialized GUI-specific state into the queue.

Letting UI flags drift from JobService state

The queue auto-run and paused flags must be single sources of truth, anchored in JobService.

AppState and GUI should mirror JobService, not maintain independent state.

After startup and after each control change, verify that GUI, AppState, and JobService all agree (add tests asserting that the controller syncs them).