Timestamp: 2025-11-22 19:30 (UTC-06)
PR Id: PR-#42-GUI-V2-JobHistoryPanel-001
Spec Path: docs/pr_templates/PR-#42-GUI-V2-JobHistoryPanel-001.md

# PR-#42-GUI-V2-JobHistoryPanel-001: GUI V2 Job History & Active Queue Panel (Read-Only)

## What’s new

- Adds a **read-only Job History & Active Queue panel** to GUI V2 that:
  - Shows currently queued/active jobs.
  - Lists recent completed/failed/cancelled jobs from the JobHistoryService introduced in PR-#41.
- Integrates the panel into the existing **AppLayoutV2** as an optional, non-intrusive sidebar or tabbed view:
  - Default: visible as a secondary tab/pane in advanced or “Diagnostics” section.
  - No changes to core Prompt/Preview/Config panels.
- Uses the controller’s **JobHistoryService / JobViewModel** interface to avoid direct access to queue/history internals.
- Adds GUI tests that:
  - Verify basic rendering and population of job lists using a fake JobHistoryService.
  - Ensure no direct imports from queue or persistence layers seep into GUI.
- Updates docs and rolling summary so Codex treats this as the canonical read-only job view prior to adding any advanced controls (e.g., retry, cancel from GUI).

This PR is **GUI-only**, using the controller services as its data source. It intentionally keeps the panel read-only to minimize coupling and risk.

---

## Files touched

> Names may differ slightly; align with your actual GUI V2 module layout.

### GUI V2

- `src/gui/job_history_panel_v2.py` **(new)**
  - Implements a `JobHistoryPanelV2` (name flexible) using Tk/Ttk that:
    - Accepts:
      - A `job_history_service`-like controller facade.
      - A parent container (frame or notebook/tab).
    - Displays two main sections:
      1. **Active / Queued jobs**
         - Table columns:
           - Job ID (shortened or hash).
           - Status (QUEUED/RUNNING).
           - Created/Started timestamps.
           - Payload summary (truncated).
      2. **Recent jobs**
         - Table columns:
           - Job ID.
           - Status (COMPLETED/FAILED/CANCELLED).
           - Completed timestamp.
           - Payload summary.
           - Optional last error (shortened).
    - Provides a **Refresh** button:
      - Calls into the controller facade:
        - `list_active_jobs()`
        - `list_recent_jobs(limit=N)`
      - Re-renders both sections with the returned data.
    - Handles empty states gracefully:
      - If no active jobs:
        - Displays “No active or queued jobs”.
      - If no recent jobs:
        - Displays “No recent jobs yet”.

  - No business logic beyond simple transformation/formatting of `JobViewModel` fields into strings.

- `src/gui/app_layout_v2.py`
  - Integrates `JobHistoryPanelV2` as:
    - A tab in a notebook (e.g., “Jobs/Queue”).
    - Or a collapsible diagnostics pane, based on your preferred layout.
  - Must:
    - Accept a `job_history_service` or controller facade from higher-level wiring (e.g., StableNewGUI main window).
    - Avoid importing queue/persistence modules directly.

- `src/gui/main_window.py`
  - Wires the `JobHistoryPanelV2` into the main window by:
    - Passing in the appropriate controller/service instance.
    - Ensuring it is constructed only after controllers are initialized.
  - No changes to Run button or primary workflow, beyond optionally providing a menu item/shortcut to switch to the Jobs panel.

### Controller

- `src/controller/job_history_service.py`
  - May need small, GUI-friendly helpers (if not already present), e.g.:
    - Sorting jobs by recency.
    - Formatting or aggregating status counts (e.g., “3 running, 1 queued”).

No major logic changes; only convenience methods used by GUI.

### Tests

- `tests/gui_v2/test_job_history_panel_v2.py` **(new)**
  - Uses a GUI test harness similar to other GUI V2 tests:
    - Creates a small root window or frame fixture.
    - Provides a fake JobHistoryService that returns deterministic sets of `JobViewModel` objects.
  - Verifies:
    - Active jobs section renders rows matching the fake data.
    - Recent jobs section renders rows matching the fake data.
    - Empty state messages appear when the service returns no jobs.
    - Refresh button calls back into the service.

- `tests/gui_v2/test_app_layout_jobs_tab.py` **(new, optional)**
  - Confirms:
    - AppLayoutV2 instantiates `JobHistoryPanelV2` when JobHistoryService is provided.
    - The panel appears in the correct tab/section without interfering with existing layout tests.

---

## Behavioral changes

- For users:
  - A **new Jobs/Queue view** becomes available:
    - Gives visibility into:
      - Which jobs are currently queued or running.
      - What has recently completed or failed.
    - Useful for:
      - Longer-running pipelines.
      - Future cluster scenarios where multiple jobs may be pending.
  - The panel is read-only:
    - No new controls to cancel or retry jobs from the GUI yet.
    - Future PRs may add such controls once the underlying semantics are fully stable.

- For developers:
  - This panel provides an **immediate visual feedback loop** for:
    - Manual testing of the queue system.
    - Troubleshooting stuck jobs or unexpected statuses.
  - It validates that the JobHistoryService contracts are usable from GUI without violating layering rules.

---

## Risks / invariants

- **Invariants**
  - GUI must **not** import or depend on:
    - `JobQueue`, `JobHistoryStore`, or low-level queue/persistence types.
  - All data must flow through:
    - `JobHistoryService` / controller-level facades.
  - Panel must not:
    - Trigger job mutations (no cancel/retry actions in this PR).
  - Layout constraints:
    - AppLayoutV2 must remain consistent with current architecture guidelines:
      - No tight coupling between jobs panel and pipeline/randomizer panels.

- **Risks**
  - If the panel is incorrectly wired:
    - It might perform excessive refresh calls, causing performance issues.
    - Or it might block the GUI while waiting on controller/service calls.

- **Mitigations**
  - Ensure:
    - Refresh calls are:
      - Cheap and/or performed via non-blocking mechanisms (e.g., short main-thread operations retrieving in-memory data).
    - No long-running I/O happens in GUI callbacks; JobHistoryService should already keep queries cheap or use pre-loaded data.

---

## Tests

Run at minimum:

- GUI tests:
  - `pytest tests/gui_v2/test_job_history_panel_v2.py -v`
  - `pytest tests/gui_v2/test_app_layout_jobs_tab.py -v` (if present)

- Regression:
  - `pytest tests/gui_v2 -v`
  - `pytest tests/controller/test_job_history_service.py -v` (from PR-#41)
  - `pytest -v`

Expected results:

- New tests confirm:
  - The panel correctly displays data from JobHistoryService.
  - Empty states and refresh behavior work as expected.
- Existing GUI and controller tests remain green; no regression in main workflows.

---

## Migration / future work

This panel is the foundation for more advanced job management UX:

- Potential future enhancements:
  - Add context-menu or button actions:
    - Cancel running job.
    - Retry failed job (submitting a new job with same config).
  - Add filters:
    - By status (Running, Failed, Completed).
    - By time window.
  - Add detail view:
    - Show full payload summary, job logs, and learning metadata for a selected job.
- In a cluster context:
  - JobHistoryPanelV2 can be extended to:
    - Display worker node information.
    - Show job distribution across nodes.

By keeping this PR read-only and controller-facade-based, those features can be added incrementally with minimal risk.

---

## Rolling summary update (for `docs/codex_context/ROLLING_SUMMARY.md`)

Append under the appropriate date (e.g., `## 2025-11-22`):

- Added a **GUI V2 Job History & Active Queue panel** that surfaces active and recent jobs via the controller’s JobHistoryService, providing visibility into queue activity without exposing queue internals to the GUI.
- Integrated the jobs panel into AppLayoutV2 in a non-intrusive way, preserving existing prompt/pipeline/preview workflows while giving power users and developers a diagnostics-oriented view.
- Strengthened GUI → controller → queue/history layering by verifying that all job data flows through controller facades and not directly from GUI into queue or persistence layers.
