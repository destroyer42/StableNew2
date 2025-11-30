PR-032-BOTTOM-LOGGING-SURFACE-V2-P1

Bottom log panel visibility + wiring sanity (LogTracePanelV2 + InMemoryLogHandler)

1. Title

PR-032-BOTTOM-LOGGING-SURFACE-V2-P1 – Fix V2 bottom log panel wiring and visibility

2. Summary

PR-013 gave us:

InMemoryLogHandler and GUI logging hooks.

LogTracePanelV2 as the dedicated V2 bottom logging view.

A Logging_Strategy_V2-P1.md doc and tests verifying the basic logging plumbing.

PR-030 confirmed:

LogTracePanelV2 is integrated in MainWindowV2’s bottom zone.

Its creation is conditional on a gui_log_handler.

In theory, it should show recent log entries with level filtering.

But in your current GUI:

The bottom log panel is not clearly visible or obviously updating, so you can’t see what the inner terminal/logger is saying.

The bottom area is visually cluttered/ambiguous due to overlapping status + log widgets.

This PR makes the bottom logging UX reliable and visible by:

Ensuring InMemoryLogHandler is always attached correctly to the root/application loggers when the V2 GUI starts.

Ensuring MainWindowV2 always instantiates and exposes LogTracePanelV2 in a predictable bottom zone.

Cleaning up any layout/content conflicts so you have one clear logging surface.

Tightening tests so regressions are caught.

3. Problem Statement

Observed behavior

At runtime, logs clearly show WebUI lifecycle and other info in the terminal.

However, the supposed “bottom logging panel” inside the GUI:

Is not obviously visible, or

Appears as dead space / tiny sliver with no useful content, and

Does not feel correlated with actual log output.

Likely root causes (from discovery + symptoms)

LogTracePanelV2 is conditionally created based on gui_log_handler, but:

The handler might not be attached or passed correctly from AppController / app bootstrap.

The panel may be instantiated with a None handler, so it never receives records.

MainWindowV2 bottom zone contains multiple competing widgets:

StatusBarV2 + any residual “status/console” components may be overlapping or stealing space from the actual log panel.

Existing tests (test_gui_logging_integration, test_logger_integration) only assert:

That a handler is attached and doesn’t crash the GUI,

But not that:

Logs actually appear in LogTracePanelV2,

The panel is visible at a minimum height.

We need a small, focused PR to turn the logging UX from “theoretical” to “actually useful in practice”.

4. Goals

Deterministic log handler wiring

When the V2 GUI starts, an InMemoryLogHandler (or functionally equivalent GUI log handler) is:

Created exactly once.

Attached to the application loggers (root or named logger per the logging strategy).

Passed down into MainWindowV2 so LogTracePanelV2 can consume it.

Visible and useful bottom log panel

LogTracePanelV2:

Is always present in the bottom zone when running the main V2 GUI.

Has a sane minimum height and layout (not hidden behind status or shrunk to a 1-pixel strip).

Shows recent log entries and auto-scrolls as new log entries arrive.

Clean separation: status vs logs

The bottom area clearly distinguishes:

Status (e.g., WebUI state, validation warnings)

Logs (scrolling, multi-line entries).

No redundant or conflicting extra “log-ish” widgets remain if they overlap with LogTracePanelV2.

Tests

Extend/augment logging tests to:

Confirm the handler is attached and feeding LogTracePanelV2.

Confirm basic visibility in the V2 GUI (within the limits of Tk testing).

5. Non-goals

No changes to WebUI lifecycle (start/stop, healthcheck, READY/FAILED transitions).

No changes to pipeline behavior or execution.

No changes to log formatting (timestamps, levels) unless absolutely required for the panel to function.

No redesign of the status bar itself (that was partially touched while fixing WebUI states in prior PRs; this PR only tweaks layout insofar as needed to ensure the log panel is visible).

No modifications to learning/queue/cluster logging paths; we’re only concerned with the V2 GUI main logging surface.

6. Allowed Files

Codex may edit only the following files for PR-032:

Logging core & strategy

src/utils/logging_utils.py (or equivalent logging helper module, if present)

src/gui/log_trace_panel_v2.py (LogTracePanelV2 implementation)

docs/Logging_Strategy_V2-P1.md (append clarifications only)

V2 GUI wiring

src/gui/main_window_v2.py

Bottom zone layout and LogTracePanelV2 instantiation.

src/gui/status_bar_v2.py

Only to the extent needed to avoid layout conflicts or to share the bottom zone cleanly.

src/controller/app_controller.py

Only to wire/create the GUI log handler and expose it to MainWindowV2.

Tests

tests/utils/test_logger_integration.py

Extend to cover new behavior/expectations.

tests/gui_v2/test_gui_logging_integration.py

Extend to assert that:

LogTracePanelV2 is present when GUI log handler is configured.

The handler feeds at least one log entry into the GUI buffer.

If file names differ slightly (e.g., log_trace_panel_v2.py vs log_trace_panel.py for V2), use the V2 version identified in PR-013/PR-030.

7. Forbidden Files

For this PR, do not modify:

src/main.py

src/api/* (WebUI process manager, healthcheck, resource service, etc.)

src/pipeline/*

src/gui/theme_v2.py

src/gui/views/*_tab_frame_v2.py (Prompt/Pipeline/Learning tab frames)

src/gui/panels_v2/sidebar_panel_v2.py / pipeline_config_panel_v2.py (those are PR-031 domain)

Any *_v1.py or archived/legacy GUI modules

Any CI configs or pyproject.toml

If you discover that logging UX can’t be fixed without touching a forbidden file, stop and report that explicitly instead of proceeding.

8. Step-by-step Implementation
Step 1 – Centralize creation of the GUI log handler

File: src/controller/app_controller.py (or the existing logging entrypoint module for the GUI)

Ensure there is exactly one place where the GUI log handler (InMemoryLogHandler or equivalent) is created:

self.gui_log_handler = InMemoryLogHandler(max_records=..., level=logging.INFO)


Attach it to the primary logger(s):

logger = logging.getLogger()  # or app-specific logger
logger.addHandler(self.gui_log_handler)


Provide a simple accessor used by the GUI:

def get_gui_log_handler(self) -> Optional[InMemoryLogHandler]:
    return self.gui_log_handler


Do not introduce new global state; keep the handler owned by the controller and passed down.

Step 2 – Wire handler into MainWindowV2

File: src/gui/main_window_v2.py

Update GUI construction so:

The MainWindowV2 constructor (or factory) receives the gui_log_handler from AppController:

main_window = MainWindowV2(
    controller=app_controller,
    app_state=app_state,
    gui_log_handler=app_controller.get_gui_log_handler(),
    ...
)


Inside MainWindowV2, ensure:

self.gui_log_handler is stored.

When building the bottom zone, LogTracePanelV2 is instantiated with this handler:

if self.gui_log_handler is not None:
    self.log_panel = LogTracePanelV2(
        parent=self.bottom_zone,
        log_handler=self.gui_log_handler,
        ...
    )


If LogTracePanelV2 previously used a global or module-level handler lookup, replace it with the explicit log_handler argument.

Step 3 – Ensure LogTracePanelV2 actually consumes and displays records

File: src/gui/log_trace_panel_v2.py

Confirm or implement:

A periodic refresh (e.g., via after() callback) that pulls records from InMemoryLogHandler into a text widget or listbox:

def _refresh_from_handler(self):
    records = self.log_handler.get_recent_records()
    # update widget


A basic log-level filter (if present in the design) that:

Doesn’t block everything by default.

Defaults to INFO or DEBUG according to Logging_Strategy_V2-P1.

Ensure:

Auto-scroll is enabled when new records are appended.

The widget is read-only (no accidental edits).

No exceptions are thrown if the handler is None (but in this PR we ensure handler is not None in real GUI runs).

Step 4 – Fix bottom layout so logs are actually visible

File: src/gui/main_window_v2.py and, if needed, src/gui/status_bar_v2.py

In MainWindowV2 bottom zone layout:

Ensure StatusBarV2 and LogTracePanelV2 are arranged so that:

Status bar is a slim strip (one row) at the very bottom.

Log panel occupies the remaining height above it with a minimum height.

Example layout intent (not literal code):

self.bottom_zone.rowconfigure(0, weight=1)  # log panel
self.bottom_zone.rowconfigure(1, weight=0)  # status bar

self.log_panel.grid(row=0, column=0, sticky="nsew")
self.status_bar.grid(row=1, column=0, sticky="ew")


Remove or downgrade any additional log-like widgets in the bottom zone that conflict with LogTracePanelV2 (e.g., a second text widget that mirrors logs) so there’s one canonical log panel.

Do not change the behavior of the status bar itself beyond layout adjustments.

Step 5 – Update logging strategy doc (append only)

File: docs/Logging_Strategy_V2-P1.md

Append a short section:

“V2 GUI Log Panel Behavior”

The app always attaches InMemoryLogHandler when the V2 GUI starts.

MainWindowV2 always creates LogTracePanelV2 when gui_log_handler is present.

Users can expect:

The bottom panel to show recent logs.

Logs from WebUI, pipeline, and GUI events to appear there.

Do not rewrite existing sections; add a new subsection at the end.

Step 6 – Tighten tests

File: tests/utils/test_logger_integration.py

Extend to cover:

Creation of InMemoryLogHandler with a fixed capacity.

Emitting logs via root logger and verifying get_recent_records() (or equivalent) returns them in order.

File: tests/gui_v2/test_gui_logging_integration.py

Extend the GUI logging test to assert:

Building the V2 app with AppController produces a MainWindowV2 that:

Has log_panel / LogTracePanelV2 attribute.

That panel has a non-None log_handler.

After emitting a test log record:

A subsequent refresh call (or simulated after callback) results in the internal widget containing at least one log entry.

Mark the test as GUI (pytest.mark.gui) and skip gracefully if Tk is unavailable, as PR-013 already did.

9. Required Tests (Failing first)

Before implementation:

Run existing logging tests to verify baseline:

python -m pytest tests/utils/test_logger_integration.py -q
python -m pytest tests/gui_v2/test_gui_logging_integration.py -q


After implementation:

Re-run the same tests (with extended assertions):

python -m pytest tests/utils/test_logger_integration.py -q
python -m pytest tests/gui_v2/test_gui_logging_integration.py -q


All must pass or skip cleanly.

No additional non-logging tests are required for this PR.

10. Acceptance Criteria

PR-032 is complete when:

Handler wiring

Starting the V2 GUI always attaches a GUI log handler (InMemoryLogHandler or equivalent).

MainWindowV2 receives this handler and passes it to LogTracePanelV2.

Visible log panel

The bottom area of the GUI clearly shows a log panel with:

Visible text area,

Scrollable, and

Not overlapped or shrunk by the status bar.

Log flow

When you:

Start the app,

Launch WebUI,

Trigger a few UI actions,

The bottom log panel shows entries reflecting those events (WebUI lifecycle, resource refresh, etc.).

Clean separation from status

There is a distinct status bar (one row) and a distinct log panel (scrolling view).

No duplicate “log” widgets exist in the bottom zone.

Tests

tests/utils/test_logger_integration.py passes.

tests/gui_v2/test_gui_logging_integration.py passes or skips (Tk-less CI).

11. Rollback Plan

If PR-032 causes regressions:

Revert the changes to:

src/controller/app_controller.py (logging-related edits)

src/gui/main_window_v2.py

src/gui/log_trace_panel_v2.py

src/gui/status_bar_v2.py (if changed)

docs/Logging_Strategy_V2-P1.md (remove appended section)

tests/utils/test_logger_integration.py

tests/gui_v2/test_gui_logging_integration.py

Re-run:

python -m pytest tests/utils/test_logger_integration.py tests/gui_v2/test_gui_logging_integration.py -q


Confirm:

The GUI still boots.

No Tk/logging exceptions are thrown.

Logging will return to the pre-PR-032 behavior (handler and panel may still exist but remain inconsistent).

12. Codex Execution Constraints

Keep diffs minimal and targeted:

No refactors of unrelated GUI or logging code.

No changes to non-logging tests or modules.

Do not introduce new singletons, global state, or cross-module imports that break the existing layering.

Follow the existing logging strategy doc as the source of truth.

If any change appears to require touching a forbidden file, stop and report, don’t improvise.

13. Smoke Test Checklist

After PR-032 is applied and tests pass, manually do:

Start the app:

python -m src.main


Verify:

Bottom area has:

A recognizable status bar row.

A larger log panel above it.

Perform some actions:

Launch WebUI.

Trigger a pipeline dropdown refresh (which should log).

Hit a couple of buttons that log info or warnings.

Look at the bottom log panel:

New entries appear as you interact.

The panel autoscrolls to show latest entries.

Switch tabs and come back:

Log panel remains visible and still updates.