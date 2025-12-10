PR-GUI-F1 — Queue & Run Controls UI Restructure (V2.5, Phase 1)

Risk Tier: Low (UI structure only, no queue/pipeline behavior changes)

1. Summary

This PR cleans up and restructures the Queue / Run Controls / Preview area in the Pipeline tab so that:

All queue-related controls and status live in the Queue panel (right column).

The Preview panel focuses on job preview only and no longer displays queue or running-job status fields.

There is exactly one Pause Queue button, located in the Queue panel, wired to the existing pause behavior.

The Auto-run queue checkbox and Queue: (status) label move into the Queue panel and use dark-mode styling.

The now-empty Run Controls panel is removed.

No queue semantics are changed in this PR; we are only moving UI elements and deleting redundant/no-op labels.

2. Problem Statement

Currently, the Pipeline tab has:

Queue status text and “Running Job / Status” labels in the Preview panel, mixing preview with execution status.

Two separate Pause Queue buttons (one in PreviewPanelV2, one in the Run Controls area), leading to confusion and potential wiring drift.

Auto-run queue and queue status spread across multiple cards, making it unclear where to control the queue.

A legacy Run Controls panel that becomes increasingly redundant as PR-204 work centralizes all job creation via JobBuilderV2 and JobService.

This fragmentation makes the UI harder to understand and contradicts the GUI Wishlist direction:

“Queue controls should live with the queue; Preview should preview; Running job should be its own concern.”

3. Goals

Unify queue controls in the Queue panel (right column):

Pause Queue (single, correctly wired)

Auto-run queue checkbox

Queue status label

Simplify the Preview panel so it no longer contains queue/running job status text.

Remove the redundant Run Controls panel once all controls are moved.

Ensure all moved widgets retain their existing behavior (no logic changes), just a new home.

Apply dark-mode styling to the queue status label in its new location.

4. Non-Goals

No changes to queue semantics (pause/resume behavior, auto-run logic, when jobs are dispatched, etc.).

No changes to JobService, JobRunner, or pipeline execution.

No structural changes to how NormalizedJobRecord, JobBuilderV2, or ConfigMergerV2 work.

No new buttons or behaviors (e.g., Send Job) — those are reserved for PR-GUI-F3.

No layout changes to other parts of the Pipeline tab beyond the Preview/Queue/Run Controls areas.

5. Scope – Allowed Files

Exact filenames may vary slightly, but the scope should be restricted to GUI V2 layout and view code:

Preview panel & run controls:

src/gui/panels_v2/preview_panel_v2.py

src/gui/panels_v2/run_controls_panel_v2.py (or equivalent if exists)

Queue panel:

src/gui/panels_v2/queue_panel_v2.py

Pipeline tab layout / view container:

src/gui/views/pipeline_tab_frame_v2.py

Shared widget/layout helpers (if needed):

src/gui/widgets_v2/* (only if lightly touched for layout helpers)

No other modules should be modified in this PR.

6. Forbidden Files

Do not modify:

Any pipeline or queue logic:

src/pipeline/*

src/pipeline/job_builder_v2.py

src/pipeline/config_merger_v2.py

src/pipeline/job_service_v2.py / job_service.py

src/pipeline/executor*.py

Any controller logic:

src/controller/pipeline_controller.py

src/controller/app_controller.py

Any core app entrypoints:

src/main.py

Any randomizer logic:

src/randomizer/randomizer_engine_v2.py

Any learning/cluster logic:

src/learning/*

src/cluster/*

Theme system core (beyond minimal label style usage):

src/gui/theme_v2.py (no new tokens, no global style changes here)

If wiring changes are required (e.g., to ensure the one remaining “Pause Queue” button calls the same callback), they must be limited to the GUI view layer and must not alter the underlying controller/queue logic.

7. Step-by-Step Implementation Plan
A. Audit current controls and wiring

In preview_panel_v2.py, identify:

Labels/fields showing:

“Queue” / “Queue Status” / “No pending jobs”

“Running Job:”

“Status:”

Any Pause Queue or Auto-run queue controls in this panel.

In run_controls_panel_v2.py (or equivalent):

Identify any Pause Queue / Run / Run Now / Mode controls.

Identify the Pause Queue button that is actually wired to the queue pause callback.

In queue_panel_v2.py:

Identify current content layout:

Queue list

Any existing labels (e.g., “Queue:”)

Any placeholder status elements.

Confirm callbacks:

The working Pause Queue button’s command (callback function).

The Auto-run queue checkbox callback.

The queue status label’s update source.

Important: The goal is to reuse the existing wiring by moving widgets, not to re-implement callbacks.

B. Remove queue / running-job status from PreviewPanelV2

In preview_panel_v2.py:

Remove (or comment out, then delete) the UI elements responsible for:

“Queue” label

“Queue Status:” label and value

“No pending jobs.” message

“Running Job:” label and any associated status field

“Status:” label and any associated status field

Ensure that the Preview panel now focuses only on:

Draft job preview (prompts, parameters, etc.)

Any non-queue-related preview UI (e.g., upcoming job summary).

Adjust layout to fill the resulting gaps:

If the removed widgets were in a subframe/row, delete or collapse that row/frame.

After this step, no queue or running job fields should remain in PreviewPanelV2.

C. Resolve duplicate Pause Queue button

Identify both Pause Queue buttons:

One in Preview/RunControls area.

One elsewhere (likely in Run Controls panel).

Determine which one is correctly wired:

The correctly wired one must be the one using the existing queue pause callback (e.g., a callback in controller/queue panel).

Confirm by tracing the callback name and making sure it reaches controller/queue, not some stub.

Choose the correctly wired button as the single source of truth:

The other button will be removed.

D. Move Pause Queue and Auto-run queue into Queue panel

In queue_panel_v2.py:

Add a new row (e.g., row 2) near the top of the queue panel layout (above the job list or just under the header) to host:

Pause Queue button

Auto-run queue checkbox

Reuse the existing button / checkbox instances if they are created in pipeline_tab_frame_v2.py or another container:

If they were created inside run_controls_panel_v2.py, refactor creation into a shared helper or into pipeline_tab_frame_v2.py:

E.g., create them in pipeline_tab_frame_v2.py, pass them as children/controls into queue_panel_v2.QueuePanelV2 or via setter methods.

Preserve the same callback functions.

Remove the old Pause Queue / Auto-run queue widgets:

From PreviewPanelV2 / RunControlsPanel, delete the now-unused widget creation and placement code.

Confirm visually:

Queue panel now shows Pause Queue + Auto-run queue near the top.

E. Move “Queue: (status)” label into Queue panel and apply dark-mode style

Locate the “Queue: (status)” label:

If it’s in Preview or RunControls, relocate it to queue_panel_v2.py.

Place it alongside current queue info:

Likely row 1, near the queue job count.

Layout example: “Queue: N jobs — Status: [text]”.

Ensure styling:

Use existing theme_v2 dark-mode label style:

No new theme tokens.

Just ensure the label uses the same style as other dark-mode labels in the queue panel.

Wire it to the same status-update logic:

Reuse the existing update method (e.g., set_queue_status(text)).

Do not create new status logic — only move the label.

F. Remove Run Controls panel (now redundant)

In run_controls_panel_v2.py:

After moving Pause Queue, Auto-run queue, and any other queue-related controls, the panel should be effectively empty or contain only legacy things you’ve already superseded.

Remove:

The RunControlsPanelV2 class (if no longer used anywhere).

Its construction and packing in pipeline_tab_frame_v2.py.

Ensure Pipeline Tab layout is updated:

If the Run Controls panel occupied a row between Preview and Queue panels, collapse that row.

Ensure Preview & Queue columns still align correctly.

After this step, there should be no visible Run Controls panel in the UI; controls have moved to Queue panel or been removed.

G. Light code cleanup & comments

Remove any now-unused attributes, instance variables, or references related to:

Old run controls panel

Old status labels in PreviewPanelV2.

Add short comments where appropriate:

E.g., above Pause Queue / Auto-run queue in queue panel:

“Queue controls (pause, auto-run) intentionally live in the QueuePanelV2. PreviewPanelV2 is display-only (no queue controls).”

Confirm all imports are still used.

8. Required Tests

GUI-related tests should be added or updated under tests/gui_v2/ (skipped if Tk unavailable).

Test 1 — PreviewPanelV2 has no queue / running-job status labels

Instantiate PreviewPanelV2.

Assert that widget tree does not contain:

“Queue Status”

“No pending jobs”

“Running Job”

“Status:”

(String-based or structural assertion depending on current test helper patterns.)

Test 2 — QueuePanelV2 contains Pause Queue & Auto-run queue

Instantiate QueuePanelV2.

Assert presence of:

A Pause Queue button.

An Auto-run queue checkbox (or equivalent labeled control).

Test 3 — Single Pause Queue button and callback reused

Search the view layer for Pause Queue button instances.

Assert only one is created (e.g., by inspecting internal state or counting).

Optionally patch the queue pause callback and assert that clicking the button calls the same callback as before.

Test 4 — Queue status label now in Queue panel

Instantiate QueuePanelV2.

Call the controller/widget API that updates queue status.

Assert the label in the queue panel updates (text matches expected).

Test 5 — No Run Controls panel instantiated

Instantiate PipelineTabFrameV2 (or main window in a test harness).

Assert there is no RunControlsPanelV2 in the widget hierarchy.

Or assert that the container where it used to live has been removed.

9. Acceptance Criteria

PR-GUI-F1 is complete when:

PreviewPanelV2:

No longer displays any queue status, “Running Job”, or generic “Status” fields.

QueuePanelV2:

Hosts the only Pause Queue button.

Hosts the Auto-run queue checkbox.

Hosts the queue status label (“Queue: (status)”) with dark-mode styling.

Run Controls panel:

Is completely removed from the layout.

All queue-related behavior:

Works exactly as before (pause/resume, auto-run behavior unchanged).

All new/updated tests pass:

tests/gui_v2/test_preview_panel_v2_queue_cleanup.py (or equivalent)

tests/gui_v2/test_queue_panel_v2_controls.py (or equivalent)

No pipeline/controller/queue logic files were modified.

10. Rollback Plan

To rollback PR-GUI-F1:

Restore:

src/gui/panels_v2/preview_panel_v2.py

src/gui/panels_v2/run_controls_panel_v2.py

src/gui/panels_v2/queue_panel_v2.py

src/gui/views/pipeline_tab_frame_v2.py

to their previous versions.

Remove or revert new GUI tests:

tests/gui_v2/test_preview_panel_v2_queue_cleanup.py

tests/gui_v2/test_queue_panel_v2_controls.py

Confirm UI is back to:

Queue status + running job status in Preview panel.

Two Pause Queue buttons.

Run Controls panel visible.

11. Potential Pitfalls (for Copilot/Codex)

Accidentally modifying queue behavior instead of just moving controls

Do not change callback functions or queue logic.

Only move widgets and re-target them to the same callbacks.

Creating a new Pause Queue implementation instead of reusing existing wiring

Reuse the one correct callback.

Don’t invent a new method or controller path.

Sneaking in “Send Job” behavior or other new semantics prematurely

“Send Job” belongs in PR-GUI-F3, not F1.

No new buttons with novel behavior in this PR.