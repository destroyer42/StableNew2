PR-039-PIPELINE-QUEUE-INTEGRATION-V2-P1

“Job Queue MVP: JobDraft → Queue → Runner”

1. Title

PR-039 – Job Queue Integration & Run Pipeline Flow (V2-P1)

2. Summary

This PR adds the complete Pipeline execution path connecting:

Sidebar Pipeline tab → JobDraft

JobDraft → real Job (serializable payload)

Job → JobQueue → SingleNodeRunner

Run controls (Add to Queue, Run Now, Cancel, Pause, Resume)

PreviewPanelV2 reflecting queue state

This completes the missing operational layer between GUI job composition (PR-035/036) and the backend runner. It does not add the History UI (that is PR-040), but it does push job events into JobHistoryStore so PR-040 can read them later.

3. Problem Statement

Currently:

Packs can be added to a JobDraft from the Pipeline left column.

But there is no connection from JobDraft → actual Job → JobQueue → Runner.

There are no buttons to start queue execution or add the draft into queue.

The Preview panel shows job draft content but cannot display queue state.

The backend runner, queue, and history store all already exist and are tested — they’re simply not wired into the V2 GUI & controllers.

We need to complete the execution path.

4. Goals
A. Add queue submission controls

Inside the Pipeline tab / right preview panel, add:

Add to Queue

Converts current job_draft → actual Job object with config snapshots & pack_ids

Pushes into JobQueue

Run Now

Same as Add to Queue

But also instructs the runner to start immediately

Clear Draft

Clears job draft after submission

B. Start/stop/pause/resume queue execution

From the preview panel and controller:

Start Queue (if stopped)

Pause Queue

Resume Queue

Cancel Active Job

C. Wire AppController to queue services

Add an internal JobService abstraction:

Encapsulates:

JobQueue

SingleNodeRunner

JobHistoryStore

Provides:

enqueue(job)

run_now(job)

pause()

resume()

cancel_current()

Event listeners for:

job_started

job_completed

job_failed

queue_empty

D. GUI state updates

PreviewPanelV2 must show:

Current job draft (unmodified)

Queue contents

Currently running job

AppStateV2 must be extended with:

queue_state

running_job

pending_jobs

These update via listener events pushed by JobService.

5. Non-Goals

No new history UI (PR-040 will do that)

No randomizer logic execution

No redesign of pack configs or presets

No advanced scheduling or parallel execution

No cluster/queue routing

No job serialization to disk

6. Allowed Files

Controller Layer

src/controller/app_controller.py

src/controller/job_service.py (new)

Backend Integration

src/queue/job_queue.py

src/queue/single_node_runner.py

src/queue/job_model.py

src/queue/job_history_store.py

GUI Layer

src/gui/app_state_v2.py

src/gui/preview_panel_v2.py

src/gui/views/pipeline_tab_frame_v2.py

src/gui/panels_v2/pipeline_run_controls_v2.py (new mini-panel inside right pane)

Tests

tests/controller/test_job_queue_integration_v2.py

tests/gui_v2/test_pipeline_queue_preview_v2.py

7. Forbidden Files

Main window layout (main_window_v2.py)

StatusBar / WebUI logic

txt2img/img2img/upscale stage cards

Prompt tab, Learning tab

Randomizer V2 panels

All legacy V1 GUI files

8. Step-by-Step Implementation
A. Introduce JobService (new class)

Add file: src/controller/job_service.py

Features:

Constructor receives:

job_queue

job_history_store

runner (SingleNodeRunner)

Provides simple async-safe methods:

enqueue(job)

run_now(job) → push to queue + signal runner.start()

pause()

resume()

cancel_current()

Emits callbacks:

on_queue_updated

on_job_started

on_job_finished

on_job_failed

on_queue_empty

B. AppController wiring

Add internal instance:

self.job_service = JobService(...)


Add functions:

on_add_job_to_queue

on_run_job_now

on_clear_job_draft

on_pause_queue

on_resume_queue

on_cancel_current_job

Each:

Converts job draft → Job payload

Calls job_service

Updates AppStateV2

C. AppStateV2 updates

Add properties + listener support:

queue_items: List[JobSummary]
running_job: Optional[RunningJobSummary]
queue_status: Literal["idle", "running", "paused"]


Add:

set_queue_items(...)

set_running_job(...)

set_queue_status(...)

D. PreviewPanelV2 UI expansion

Add a new section under “Current Job Draft”:

Queue:
Shows pending jobs (pack names, config names)

Running:
Shows which job is running and its progress or status

Controls:
Start / Pause / Resume / Cancel for queue

E. PipelineTabFrameV2 wiring

Add new mini-panel inside the right column:

PipelineRunControlsV2

Buttons: Add to Queue, Run Now, Clear Draft

F. Tests

Controller test:

Mock JobService, farm events, assert:

enqueue → queue grows

run_now → signals runner start

GUI preview test:

Simulate job_draft → queue submission

Assert PreviewPanel updates

9. Acceptance Criteria

Packs can be added to job draft; clicking “Add to Queue” enqueues it.

Clicking “Run Now” executes job via runner.

PreviewPanel shows:

Job Draft

Queue

Running job

No Tk errors or regressions in Pipeline tab layout.

Queue runs to completion (stdout shows job execution).

All new tests pass.

10. Rollback Plan

Revert modifications to:

app_controller.py

app_state_v2.py

preview_panel_v2.py

pipeline_tab_frame_v2.py

new job_service.py

Remove tests for queue integration