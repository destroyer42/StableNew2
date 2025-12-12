PR-A — Observability & Debug Harness for Job Lifecycle (V2.5).md
Discovery Reference: D-11, D-120
Date: YYYY-MM-DD HH:MM (local time)
Author: <Name or AI Agent>

1. Summary (Executive Abstract)

This PR introduces a lightweight, canonical observability layer for the StableNew job lifecycle, plus a basic in-app debug console to surface that information to the user. It wires structured logging into the key transitions of the pipeline run path—“Add to Job”, “Add to Queue”, job picked up by the runner, and job completed/failed—without changing core execution logic. These events are emitted through a centralized logging utility and displayed in a new Debug/Log pane within the GUI V2, driven via AppStateV2 so that the GUI remains a pure consumer of controller- and service-level signals.

For users, this PR makes it immediately obvious whether “Add to Job” and “Add to Queue” are actually doing anything, which job is currently running, and why a job failed. For maintainers, it provides a single, consistent stream of structured logs that can be correlated with JSONL history and queue state to debug pipeline issues without attaching a debugger. The risk is moderate (Tier 2) because the change touches the controller layer, JobService, and GUI V2, but it avoids heavy refactors and follows existing architecture boundaries.

2. Motivation / Problem Statement
Current Behavior

“Add to Job” and “Add to Queue” often appear to do nothing:

Preview doesn’t update.

Queue doesn’t visibly change.

There is no immediate, localized diagnostic signal when something fails or is a no-op.

Jobs that do run lack an obvious, user-facing event trail:

It is unclear which job the runner has picked up.

Completion vs. failure is only visible via indirect symptoms (files on disk, CPU/GPU usage, or external logs).

Debugging currently requires:

Scanning console logs in a separate terminal, or

Reading raw log files, which is high friction and difficult to correlate to GUI actions.

Pain & Impact

For you as the operator, it is very hard to answer simple questions:

“Did that button click actually enqueue anything?”

“Is this job stuck in the queue, or did the runner crash?”

“Why did this particular job fail while others succeeded?”

For development and testing:

When pipeline refactors break something, there is no in-app, structured view of:

Draft creation events.

Queue submission events.

Runner picks and completions.

This slows triage and increases the risk of shipping regressions.

Why Now

You are actively working to “once and for all” make the pipeline path reliable and observable.

Many earlier PRs (Queue/Runner DI, JobService history, queue fixes) have improved internals but still lack a user-facing debug harness.

Adding a small, well-scoped observability layer and an in-app console is a high-leverage, low-risk way to:

Reduce ambiguity.

Speed up diagnosis of remaining run-path bugs.

Provide confidence that more complex future changes (job bundling, packs, randomizer) don’t regress the basics.

3. Scope & Non-Goals
In Scope

Introduce a simple structured logging utility for job-lifecycle events.

Add logging hooks at four key points:

“Add to Job” clicked (draft updated).

“Add to Queue” clicked (draft submitted).

Job picked up by the runner (status transitions to RUNNING).

Job completed or failed (status transitions to COMPLETED / FAILED / CANCELLED).

Add a basic in-app debug/log console pane:

Read-only view backed by AppStateV2.

Scrollable list of recent structured log lines.

Focused on job lifecycle, not a full general-purpose log viewer.

Provide unit tests for:

Emission of log events.

State updates into AppStateV2 for the log buffer.

Basic GUI wiring via minimal harness tests (no full Tk integration).

Out of Scope (for this PR)

No changes to the core run logic (no new pipeline stages, no refiner/upscale behavior changes).

No deep aggregation or metrics dashboards (that is a future “Diagnostics Dashboard” PR).

No external log streaming, file rotation, or remote logging.

No attempt to capture all log types; we focus narrowly on job lifecycle events for now.

4. Architecture Alignment & Risk Tier

Risk Tier: Tier 2 (Standard)

Touches controller → service wiring and GUI V2 observability.

Does not alter JobRunner internals, queue persistence formats, or pipeline sequencing.

Architecture Compliance:

GUI remains render-only: the log console is a consumer of AppStateV2 log entries.

AppStateV2 remains the single source of truth for GUI-visible state:

New log_events buffer stored as data only.

Controllers and JobService are the only components that:

Emit job lifecycle events.

Mutate AppState.

No direct GUI → pipeline or GUI → runner calls.

5. Detailed Design / Implementation Plan
5.1 New Log Event Model

Add a small structured model for job lifecycle log entries, near existing job models:

File: src/pipeline/job_models_v2.py (or a nearby shared models module)

@dataclass
class JobLifecycleLogEvent:
    timestamp: datetime
    source: str           # e.g. "pipeline_tab", "job_service", "runner"
    event_type: str       # e.g. "add_to_job", "add_to_queue", "job_started", "job_completed", "job_failed"
    job_id: str | None    # normalized job id if available
    bundle_id: str | None # future: multi-part bundles; optional now
    draft_size: int | None
    message: str          # human-readable message

5.2 AppStateV2: Log Buffer

Extend AppStateV2 to maintain a rolling buffer of log events for the GUI:

File: src/controller/app_state_v2.py

Add fields:

@dataclass
class AppStateV2:
    # existing fields...
    log_events: list[JobLifecycleLogEvent] = field(default_factory=list)
    log_events_max: int = 500  # configurable upper bound


Add helper:

def append_log_event(self, event: JobLifecycleLogEvent) -> None:
    self.log_events.append(event)
    if len(self.log_events) > self.log_events_max:
        # Drop oldest
        self.log_events = self.log_events[-self.log_events_max:]
    self._notify("log_events")

5.3 Logging Utility / Facade

Introduce a simple facade so controllers/services don’t have to know AppState internals:

File: src/controller/logging_facade.py (new)

Responsibilities:

Provide helper functions like:

class JobLifecycleLogger:
    def __init__(self, app_state: AppStateV2, clock: Callable[[], datetime] = datetime.now):
        self._state = app_state
        self._clock = clock

    def log_add_to_job(self, source: str, draft_size: int) -> None:
        evt = JobLifecycleLogEvent(
            timestamp=self._clock(),
            source=source,
            event_type="add_to_job",
            job_id=None,
            bundle_id=None,
            draft_size=draft_size,
            message=f"Add to Job clicked; draft now has {draft_size} item(s).",
        )
        self._state.append_log_event(evt)

    def log_add_to_queue(self, job_id: str | None, draft_size: int) -> None:
        # similar...

    def log_job_started(self, job_id: str, source: str) -> None:
        # similar...

    def log_job_finished(self, job_id: str, status: str, message: str) -> None:
        # similar...


This maintains separation:

Controllers and services depend on JobLifecycleLogger, not directly on AppState.

AppState’s only role is to store the log data and notify observers.

5.4 Controller Hook: “Add to Job”

File: src/controller/pipeline_controller.py (or app_controller.py, depending on where “Add to Job” is handled today)

When “Add to Job” successfully updates the draft:

Let the existing logic update AppStateV2.job_draft.

After the draft is updated, call:

draft_size = len(self._app_state.job_draft.packs)  # or JobParts when PR-B lands
self._job_lifecycle_logger.log_add_to_job(source="pipeline_tab", draft_size=draft_size)


If the add is a no-op (e.g., missing prompt, empty pack), still log:

Either a warning event type (e.g. "add_to_job_noop") or a message field explaining why nothing changed.

5.5 Controller Hook: “Add to Queue”

Wherever the “Add to Queue” button is processed:

After building the queue job(s) and submitting them via JobService, log:

job_id = primary_job_id_or_bundle_id  # whatever identifier is available
draft_size = len(self._app_state.job_draft.packs)
self._job_lifecycle_logger.log_add_to_queue(job_id=job_id, draft_size=draft_size)


If queue submission fails (exception, validation), catch and log an "add_to_queue_failed" event with the error message.

5.6 JobService / Runner Hooks: Job Picked Up & Completed/Failed

File: src/pipeline/job_service.py (or equivalent)

When the runner starts a job (status transitions to RUNNING):

def mark_running(self, job_id: str) -> None:
    # existing status change logic...
    self._job_lifecycle_logger.log_job_started(job_id=job_id, source="job_service")


When a job completes or fails:

def mark_completed(self, job_id: str, success: bool, error_message: str | None = None) -> None:
    # existing history and status updates...
    status = "completed" if success else "failed"
    msg = "Job completed successfully." if success else (error_message or "Job failed.")
    self._job_lifecycle_logger.log_job_finished(job_id=job_id, status=status, message=msg)


Ensure these log calls are non-fatal (i.e., failures in logging must not crash the pipeline).

5.7 GUI: Debug / Log Console Pane

Add a simple log view panel that subscribes to AppStateV2.log_events:

File: src/gui/panels_v2/debug_log_panel_v2.py (new)

Features:

A tkinter Frame (or ttk.Treeview) that:

Shows a scrollable table or list:

Time (HH:MM:SS)

Source

Event type

Job ID (if any)

Message (text, truncated to a reasonable length)

API surface:

class DebugLogPanelV2(ttk.Frame):
    def bind_to_app_state(self, app_state: AppStateV2) -> None:
        self._state = app_state
        app_state.register_listener("log_events", self._on_log_events_changed)
        self._on_log_events_changed()

    def _on_log_events_changed(self, *_args) -> None:
        # read app_state.log_events, refresh display


Integrate into GUI layout without violating forbidden files:

Ideally via an existing extension point (e.g., a tabbed area or collapsible section).

If main_window_v2.py needs changes, call out clearly as a Tier 1 GUI-only layout update in a follow-up PR if necessary.

6. Data Structures & API Changes

New:

JobLifecycleLogEvent dataclass.

JobLifecycleLogger class in logging_facade.py.

AppStateV2.log_events, AppStateV2.log_events_max, and append_log_event.

Modified:

PipelineController / AppController constructor to accept a JobLifecycleLogger (DI-friendly).

JobService (or equivalent) to accept a JobLifecycleLogger.

No breaking API changes are expected; new parameters should be defaulted and wired via dependency injection where possible.

7. User Experience & UI Details

New Debug / Log pane in GUI V2:

Likely a new tab or subpanel in the pipeline/queue section.

Shows the most recent ~200–500 log events.

Read-only; no editing, no filters in this PR.

Typical UX flow:

Click “Add to Job” → log line appears:

12:03:15 | pipeline_tab | add_to_job | draft=3 | "Add to Job clicked; draft now has 3 item(s)."

Click “Add to Queue” → log line:

12:03:20 | pipeline_tab | add_to_queue | job=abcd... | "Submitted draft to queue with 3 part(s)."

When runner picks the job:

12:03:25 | job_service | job_started | job=abcd... | "Job picked up by runner."

On completion/failure:

12:03:40 | job_service | job_completed | job=abcd... | "Job completed successfully."

Or

12:03:40 | job_service | job_failed | job=abcd... | "Upscale stage failed: WebUI returned no data."

This gives you a clear, linear narrative for each job’s lifecycle.

8. Testing Strategy
8.1 Unit Tests

File: tests/controller/test_job_lifecycle_logging.py (new)

Verify that:

log_add_to_job appends to AppStateV2.log_events.

log_add_to_queue includes the correct job_id and draft_size.

log_job_started and log_job_finished emit expected event_type and message.

File: tests/pipeline/test_job_service_logging.py (new or extended)

Use a stub JobLifecycleLogger that records calls.

Assert that mark_running and mark_completed call the logger exactly once with the correct parameters.

8.2 Light GUI Harness Tests

File: tests/gui_v2/test_debug_log_panel_v2.py (new)

Use a headless Tk harness to:

Instantiate DebugLogPanelV2.

Bind it to a test AppStateV2.

Append log events and assert that widget rows/labels update.

8.3 Non-Regression

Ensure that when JobLifecycleLogger is not passed (older code paths or tests), defaults are no-ops:

For example, a NullLogger implementation that silently discards events.

9. Risks & Mitigations

Risk: Logging introduces new crashes if AppState is None or miswired.

Mitigation:

All methods in JobLifecycleLogger must be defensive (check _state is not None).

Logging must never raise; any errors are caught and logged to standard logger only.

Risk: Performance overhead from logging at high frequency.

Mitigation:

Log only at key lifecycle boundaries, not per step.

Cap log_events in AppState with log_events_max.

Risk: GUI layout clutter or confusion.

Mitigation:

Keep the log pane optional and clearly labeled (e.g. “Debug Log”).

No change to default pipeline layout semantics beyond adding the new panel/tab.

Risk: Test brittleness if log messages change text.

Mitigation:

Tests should assert on event_type, job_id, and presence of a message, not exact wording.

10. Rollout / Migration Plan

Implement JobLifecycleLogEvent, JobLifecycleLogger, and AppState extension.

Wire logging into:

“Add to Job” flow.

“Add to Queue” flow.

JobService status transitions.

Implement DebugLogPanelV2 and plug it into the GUI V2 layout.

Add tests and run:

Unit tests for controllers and JobService.

GUI harness tests for log panel.

Existing journey tests (preview → queue → run) to confirm no regressions.

Dogfood:

Run a few jobs and verify:

Log lines appear.

Job IDs match queue/history.

No crashes if pipeline fails.

No data migrations are required; this is purely additive.

11. Performance Considerations

In-memory log buffer is capped at a small size (e.g. 500 entries), so memory impact is negligible.

Event frequency is limited to:

One add_to_job per click.

One add_to_queue per draft submission.

One job_started + one job_finished per job.

Rendering the log pane is a simple list redraw; no heavy layout algorithms.

12. Documentation Updates

Update:

ARCHITECTURE_v2.5.md

Add a short subsection under the Job lifecycle describing:

JobLifecycleLogEvent

JobLifecycleLogger

AppStateV2.log_events

The Debug Log panel.

StableNew_Coding_and_Testing_v2.5.md

Add guidelines:

How to log new job lifecycle milestones.

When not to log (avoid spammy, per-step logs).

Testing expectations for logging.

GUI V2 Usage / README

Add a short “Debug Log” section showing how to:

Open the debug pane.

Interpret basic entries.

Use it when “Add to Job” or “Add to Queue” seem broken.