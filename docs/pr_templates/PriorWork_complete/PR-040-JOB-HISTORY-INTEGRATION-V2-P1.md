PR-040-JOB-HISTORY-INTEGRATION-V2-P1

“Expose Completed Jobs (History Panel)”

1. Title

PR-040 – Job History Panel Wiring & HistoryStore Integration (V2-P1)

2. Summary

This PR exposes the backend JobHistoryStore data in the GUI:

Adds a Job History panel to the rightmost column of Pipeline tab (under queue).

Automatically updates on:

job_completed

job_failed

job_cancelled

Allows user to:

View recent jobs

See image count, time, duration

Click “Open Output Folder”

Sort by time or status

No new backend logic is required — the store and runner are already implemented.

3. Problem Statement

The backend already records job history.

The GUI has a placeholder job_history_panel_v2.py, but it is unused and unwired.

Users cannot view previous runs, run durations, image counts, or open output folders.

This PR adds the missing UI + controller wiring.

4. Goals

Implement full job history rendering in GUI.

Render at least:

Completion timestamp

Job packs included

Image count (if available)

Duration

Output directory path

Provide:

“Open Output Folder” button

“Refresh History” button

Updates automatically whenever JobService emits a job_completed/job_failed event.

5. Non-Goals

No merging job history with job queue.

No long-term persistence beyond JobHistoryStore capabilities.

No advanced analytics or charts.

No integration with Learning System.

6. Allowed Files

Controller Layer

src/controller/app_controller.py

Backend Integration

src/queue/job_history_store.py

GUI Layer

src/gui/job_history_panel_v2.py

src/gui/app_state_v2.py

src/gui/views/pipeline_tab_frame_v2.py

src/gui/preview_panel_v2.py (light touch only)

Tests

tests/gui_v2/test_job_history_panel_v2.py

tests/controller/test_job_history_controller_v2.py

7. Forbidden Files

All left-column config controls

All stage cards

WebUI or StatusBar logic

Job queue core logic (except via JobService events)

Prompt tab

Learning tab

8. Step-by-Step Implementation
A. Expand AppStateV2 with history

Add:

history_items: List[JobHistoryEntry]


Add:

set_history_items(items: List[JobHistoryEntry])

add_history_item(item: JobHistoryEntry)

B. Wire AppController to JobHistoryStore

When JobService dispatches:

job_completed

job_failed

job_cancelled

AppController:

Fetches updated history list (store.list_recent(...))

Calls app_state.set_history_items(...)

C. Implement JobHistoryPanelV2

In src/gui/job_history_panel_v2.py:

Add a Treeview or list display with columns:

Time

Status

Pack(s)

Images

Duration

Output Folder

Add buttons:

Open Output Folder

Refresh

D. Integrate into PipelineTabFrameV2

Right column structure becomes:

Job Draft Summary

Queue Preview

History Panel (new section)

E. PreviewPanelV2 adjustments

PreviewPanelV2 may expose a placeholder area for queue+history, or it may simply call out to newly created subpanels. Small changes only.

F. Tests

Controller test:

Mock JobHistoryStore → fire event → assert AppState updates.

GUI test:

Construct panel with fake history data → verify rows populate.

9. Acceptance Criteria

History panel appears under Queue in right column.

Completed jobs appear with:

Timestamp

Status label

Packs included

Image count

Duration

Output folder path

Clicking “Open Output Folder” successfully launches filesystem.

History updates automatically when runner completes jobs.

All new tests pass.

10. Rollback Plan

Revert changes to:

job_history_panel_v2.py

app_state_v2.py

app_controller.py

GUI layout modifications

Remove history tests

Ensure pipeline/queue still function

If you want, I can generate downloadable .md versions of PR-039 and PR-040, or proceed directly to PR-041 once these are approved.