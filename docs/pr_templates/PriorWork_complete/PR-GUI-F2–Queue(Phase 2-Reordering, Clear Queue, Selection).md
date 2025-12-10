PR-GUI-F2 – Queue(Phase 2-Reordering, Clear Queue, Selection).md

Snapshot: StableNew-snapshot-20251205-231442.zip (and associated repo_inventory.json)

1. Summary

This PR makes the queue panel actually behave like a queue you can manage:

You can select queued jobs in the queue list.

You can reorder them (move up/down).

You can remove individual jobs.

You can clear the queue in one action.

The Running Job is clearly separated from and linked back to its originating queue entry.

All behavior is built on top of the existing JobBuilderV2 / NormalizedJobRecord / JobService stack from PR-204A–D and the queue-first layout work from PR-GUI-F1. No queue persistence or auto-run semantics are introduced yet (those remain in PR-GUI-F3).

2. Problem Statement

Right now, after PR-204A–D and PR-GUI-F1:

Jobs are built as NormalizedJobRecords and shown in preview/queue panels.

The queue UI is more prominent, but:

Items are not truly selectable or clearly highlighted.

There’s no way to reorder jobs once queued.

You can’t remove a single queued job, only clear via lower-level means.

A “Running Job” concept exists but is visually and behaviorally muddled with the queue list.

From the user’s point of view:

The queue still feels like a static log instead of a controllable job list.

Moving or pruning queued work is tedious or impossible.

“Which queue item is currently running?” is not obvious.

We need to make the queue panel an actual interactive queue manager—without yet touching persistence or auto-run.

3. Goals

Selectable queue list

User can click a queue row to select it.

Selection is visually obvious (dark-mode highlight, consistent with theme_v2).

Reordering controls

Move Up / Move Down controls (buttons or icon buttons) operate on the selected queue item.

Reordering updates both:

The JobService/queue ordering.

The visible ordering and “order number” shown in the queue list.

Single-job removal & clear-queue

A Remove (trash) control removes the selected job from the queue.

A Clear Queue control empties the queue.

Both update JobService/queue and the visible UI.

Running Job card clarity

A small Running Job sub-card:

Displays summary for the currently running job.

Indicates which queue index/order that job came from.

The queue list visually distinguishes:

The running job (if still present in queue).

Remaining queued items.

Correct layering

All queue operations:

Are anchored on JobService / job_queue_v2 models.

Operate on JobSpecV2 / NormalizedJobRecord (or their IDs).

No ad-hoc manipulation of arbitrary Tk widgets as the “source of truth”.

No persistence or auto-run yet

Queue contents and order are in-memory only.

On restart, the queue still resets (persistence comes in PR-GUI-F3).

4. Non-goals

No queue persistence or resume-on-start behavior.

No auto-run semantics or changes to when jobs start running (PR-GUI-F3).

No changes to JobBuilderV2, ConfigMergerV2, or randomizer behavior.

No changes to job payloads, WebUI client, or executor logic.

No changes to prompt packs, learning, or cluster/remote execution.

5. Allowed Files

You may modify:

Queue panel UI

src/gui/panels_v2/queue_panel_v2.py

Implement selection UI, reordering buttons, remove/clear operations, running-job card.

App state

src/gui/app_state_v2.py

If needed, track the currently selected queue job ID/index for GUI.

Job service / queue engine

src/controller/job_service.py

src/pipeline/job_queue_v2.py (or whichever module currently implements queue data structures)

Add small, explicit APIs:

move_job_up(job_id) / move_job_down(job_id)

remove_job(job_id)

clear_queue()

Or equivalent index-based APIs, as long as the controller/GUI always talks via stable identifiers.

Controller wiring (if required)

src/controller/app_controller.py or src/controller/pipeline_controller.py

To mediate between queue_panel_v2 callbacks and JobService operations if not already in place.

Tests

tests/gui_v2/test_queue_panel_behavior_v2.py (new)

tests/controller/test_queue_operations_v2.py (new)

Optional: extend existing test_job_service_queue_v2.py or similar if it already exists.

6. Forbidden Files

Do not modify:

Core entry points and executor:

src/main.py

src/pipeline/executor.py / src/pipeline/executor_v2.py

src/api/webui_client.py

src/api/webui_process_manager.py

src/api/healthcheck.py

Randomizer engine:

src/randomizer/randomizer_engine_v2.py

JobBuilder / ConfigMerger core:

src/pipeline/job_builder_v2.py

src/pipeline/config_merger_v2.py

Theme core:

src/gui/theme_v2.py (respect existing theme tokens; use them, don’t edit them here)

Any V1 / legacy files:

src/utils/randomizer.py

Any *_legacy.py or V1 GUI files.

If you discover a truly unavoidable need to touch any forbidden file, that change must be spun out into a separate, explicitly-scoped PR.

7. Step-by-step Implementation Plan
A. Enhance queue data model & JobService API

In job_queue_v2.py (or equivalent)

Ensure the queue maintains a stable list of job entries (e.g., List[JobSpecV2] or equivalent).

Add explicit reordering/removal methods, keyed by job ID or index:

class JobQueueV2:
    def move_up(self, job_id: str) -> None: ...
    def move_down(self, job_id: str) -> None: ...
    def remove(self, job_id: str) -> None: ...
    def clear(self) -> None: ...


If job IDs are not easily available, define an internal, stable queue_id field on each queued job (e.g., via uuid4() at enqueue time).

Each method must:

Update the internal list order.

Be a no-op if job_id isn’t present.

Not alter job payloads or metadata.

In job_service.py

Expose thin wrapper methods:

class JobService:
    def move_job_up(self, job_id: str) -> None: ...
    def move_job_down(self, job_id: str) -> None: ...
    def remove_job(self, job_id: str) -> None: ...
    def clear_queue(self) -> None: ...


Ensure there’s an existing method to enumerate the current queue in a form the GUI can consume (e.g., list of NormalizedJobRecord or derived JobUiSummary). If not:

Add get_queue_jobs() that returns List[NormalizedJobRecord] or equivalent, built off the same snapshots used in PR-204D.

B. Wire queue operations into controller

In app_controller.py or pipeline_controller.py

Add methods that the GUI can call:

def on_queue_move_up(self, job_id: str) -> None: ...
def on_queue_move_down(self, job_id: str) -> None: ...
def on_queue_remove(self, job_id: str) -> None: ...
def on_queue_clear(self) -> None: ...


In each handler:

Call the corresponding JobService method.

Re-fetch queue contents via get_queue_jobs().

Push the updated list into QueuePanelV2.set_normalized_jobs(...) (or equivalent):

jobs = self._job_service.get_queue_jobs()
self._queue_panel.set_normalized_jobs(jobs)


If a Running Job concept is already surfaced in controller state:

Ensure it continues to be updated exactly as before.

Later, in the GUI, we’ll read that to highlight the running entry.

C. Add selection & controls in queue_panel_v2.py

Ensure the main queue list widget (likely a Treeview or listbox) supports:

Single selection.

Programmatic selection based on job ID.

When set_normalized_jobs(jobs: list[NormalizedJobRecord]) is called (from PR-204D):

Render one row per job, including:

Order number (1-based index based on current queue order).

Prompt summary.

Model + key config summary, via JobUiSummary.

Rebuild an internal map: row_id → job_id.

Track the currently selected job:

On selection change events, update a private self._selected_job_id: Optional[str].

Expose a read-only property or helper:

def _get_selected_job_id(self) -> Optional[str]:
    return self._selected_job_id


Add UI controls for queue operations (buttons or icon buttons in the queue card header/footer):

Move Up

Move Down

Remove

Clear Queue

Wire their command callbacks to private methods like:

def _on_move_up_clicked(self) -> None:
    if not self._selected_job_id: return
    self._on_move_up(self._selected_job_id)


The panel should be constructed with controller callbacks:

class QueuePanelV2(Frame):
    def __init__(
        self,
        parent,
        on_move_up,
        on_move_down,
        on_remove,
        on_clear,
        ...
    ):
        self._on_move_up = on_move_up
        ...


Button enabled/disabled states:

Disable Move Up if selected item is already at top.

Disable Move Down if at bottom.

Disable Remove if nothing is selected.

Clear Queue remains enabled if there is at least one job.

D. Running Job card alignment

Add a dedicated Running Job subframe/card inside queue_panel_v2.py (or a companion panel, depending on current implementation):

Fields:

Running: <order #> (if linked to a queue item).

Prompt summary.

Model.

Seed or seed label.

Add a method on QueuePanelV2:

def set_running_job(self, job: NormalizedJobRecord | None) -> None:
    ...


When non-None:

Update labels with summary (via JobUiSummary).

If that job still appears in the queue list, visually indicate it:

E.g., a subtle icon or highlight for the row.

When None:

Hide or gray the running-job card.

In the controller:

Reuse whatever state currently tracks the running job.

Call queue_panel.set_running_job(...) when that state changes.

Ensure the queue list itself does not lose selection when the running job changes, unless the running job is removed from the queue.

E. App state tweaks (if necessary)

In app_state_v2.py

If the controller needs a stable place to store the selected queue job ID (e.g., to restore selection after a refresh):

Add a field (e.g., selected_queue_job_id: Optional[str]).

Add getters/setters.

Have QueuePanelV2 callbacks update state through controller, not directly.

This is optional; only implement if selection restoration is needed for a clean UX or tests.

8. Tests
A. Controller / JobService tests

File: tests/controller/test_queue_operations_v2.py (new)

test_move_job_up_reorders_queue

Arrange:

Create 3 queued jobs with IDs ["j1", "j2", "j3"] in that order.

Act:

Call controller.on_queue_move_up("j2").

Assert:

Job order becomes ["j2", "j1", "j3"].

JobService.move_job_up("j2") called exactly once.

test_move_job_down_reorders_queue

Similar to above; confirm ["j1", "j2", "j3"] → ["j1", "j3", "j2"] when moving j2 down.

test_remove_job_removes_from_queue

Arrange:

Queue ["j1", "j2"].

Act:

controller.on_queue_remove("j1").

Assert:

Queue now contains only ["j2"].

QueuePanelV2.set_normalized_jobs(...) called with one job.

test_clear_queue_empties_queue

Arrange:

Non-empty queue.

Act:

controller.on_queue_clear().

Assert:

JobService.clear_queue() called.

QueuePanelV2.set_normalized_jobs([]) invoked.

test_running_job_state_propagates_to_queue_panel

Simulate a running job with ID j2.

Controller updates running job.

Assert:

queue_panel.set_running_job(...) called with the correct NormalizedJobRecord.

B. GUI tests (queue panel)

File: tests/gui_v2/test_queue_panel_behavior_v2.py (new, Tk-skipped if unavailable)

test_selection_tracks_selected_job_id

Instantiate QueuePanelV2 with fake callbacks.

Populate with 3 NormalizedJobRecords with known job_ids.

Simulate user selecting the second row.

Assert:

_get_selected_job_id() returns second job ID.

Move Up, Move Down, and Remove buttons are enabled appropriately.

test_move_buttons_call_callbacks_with_correct_id

With a selection, click Move Up.

Assert:

on_move_up mock called with that job ID.

test_clear_queue_button_calls_callback_without_selection

Ensure Clear Queue works even if nothing is selected.

Assert:

on_clear called exactly once.

test_running_job_card_updates_labels

Call set_running_job(job) with a fake NormalizedJobRecord.

Assert:

Running job labels show expected prompt/model/seed summary.

Call set_running_job(None) and assert:

Running job card is hidden or shows “No job running”.

test_running_job_row_highlighted_when_present

When running job is also in queue list:

set_running_job() should mark the corresponding row visually (check style tag or config in test).

9. Acceptance Criteria

PR-GUI-F2 is complete when:

Selection & controls

User can click a queued job to select it.

Move Up, Move Down, Remove, Clear Queue all function correctly against the selected job or entire queue.

The queue list order visually matches the underlying JobService order.

Running job clarity

A dedicated Running Job card shows:

A summary of the active job.

Its queue index/order if applicable.

The running job is visually distinguished in the queue list when present.

Layering & invariants

Queue operations are implemented via JobService/job_queue_v2, not ad-hoc GUI-only lists.

All job payload fields and metadata remain unchanged when reordering.

No new persistence or auto-run behavior is introduced.

Tests

All new controller and GUI tests pass.

All previously passing tests from PR-204A–E and PR-GUI-F1 remain green.

10. Rollback Plan

If PR-GUI-F2 causes regressions or unwanted behavior:

Revert changes to:

src/gui/panels_v2/queue_panel_v2.py

src/gui/app_state_v2.py (if modified)

src/controller/job_service.py

src/pipeline/job_queue_v2.py

src/controller/app_controller.py / pipeline_controller.py (if modified)

All new test files under tests/controller/ and tests/gui_v2/ added by this PR.

Re-run tests:

python -m pytest -q


Confirm the system returns to the PR-GUI-F1 state:

Queue is visually present but behaves as a non-interactive list.

No selection-based reordering/removal actions are available.

Running Job is rendered as it was prior to F2.