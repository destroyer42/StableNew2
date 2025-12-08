PR-D — Queue & History Lifecycle Alignment JobBundles (V2.5).md

Discovery Reference: D-11 (Pipeline Run Controls / Queue Integration), D-20 (JobDraft / JobBundle Ownership)
Date: 2025-12-07 12:00 (local time)
Author: GPT-5.1 Thinking (Planner)

1. Summary (Executive Abstract)

This PR aligns the queue and history lifecycle with the new JobPart / JobBundle pipeline, so that jobs created via “Add to Job” and “Add to Queue” flow deterministically from Preview → Queue → Runner → History. It introduces a controller-owned draft JobBundle, wires it into JobService, and ensures that queue and history panels are updated based on real JobService status callbacks rather than ad-hoc GUI state. The main behavior changes are: draft bundles are built in the controller, enqueued via a single code path, removed from the queue upon completion, and appended to history with a consistent summary DTO. This preserves the architectural boundary where the GUI never touches pipeline internals directly and uses controller-provided summaries only. The result is that the preview finally matches what runs, completed jobs no longer pile up in the queue, and history becomes a trustworthy record of actual execution.

2. Motivation / Problem Statement
Current Behavior

From your latest description and logs:

“Add to Job” appears to do nothing:

The preview panel does not show any prompts, stage flags, or batch counts.

No draft structure exists that accurately represents the “bundle of job parts”.

“Add to Queue” does not visibly change the preview or queue:

Jobs are submitted internally, but the queue panel does not reliably reflect which items are queued, running, or completed.

Completed jobs remain in the queue and are not moved to the history board.

History is incomplete / misleading:

Jobs may be recorded in JSONL or other history storage, but there is no stable, GUI-visible signal that a job has finished and should be removed from queue and added to history.

The queue state and GUI state are decoupled:

Queue panel contents are not derived from JobService’s canonical view of jobs.

Preview/queue/history can disagree or drift over time.

Why This Is Incorrect

Violates the “Preview = Queue = Executor” invariant from the v2.5 architecture:

The preview should show exactly what will be enqueued.

The queue should represent what the runner will execute.

History should reflect what actually ran.

Makes debugging pipeline failures extremely difficult:

You can’t easily answer “what exactly did this job do?” or “which job just completed?”.

Breaks expected UX:

Users expect “Add to Job → Add to Queue → Run → History” to be a clear, linear story.

The current behavior feels random and opaque.

Why Now

You already invested in JobService, runner DI, and a structured pipeline path; without aligned queue/history wiring, that investment doesn’t translate into a usable end-to-end flow.

Many of the remaining GUI issues (preview blank, queue piling up, history not updating) are symptoms of the same missing lifecycle wiring—fixing them together provides a “once and for all” closure for the core run path.

3. Scope & Non-Goals
In Scope

Introduce and wire a controller-owned draft JobBundle into the queue/history lifecycle:

Build a JobBundle in PipelineController from JobParts (from PR-B / PR-C).

Convert draft bundle → NormalizedJobRecord list → JobService submit.

Align queue panel and history panel with JobService’s canonical job lifecycle:

Queue shows QUEUED/RUNNING jobs with correct counts and status.

Completed jobs are removed from queue and appended to history.

Introduce minimal DTOs for GUI:

JobBundleSummaryDTO for preview.

JobQueueItemDTO / JobHistoryItemDTO as needed for queue/history.

Non-Goals

No redesign of GUI layout or visual styling (that’s covered by GUI PRs like PR-GUI-F).

No changes to WebUI API interaction or Executor logic beyond what’s needed to surface correct status/metadata.

No deep refactor of JobService internals beyond adding callbacks / DTOs already anticipated in earlier DI work.

No global changes to randomizer, prompt-pack formats, or preset files (they are consumed, not redesigned, here).

4. Behavioral Changes (Before → After)
4.1 User-Facing Behavior
Area	Before	After
“Add to Job” (no pack)	Appears to do nothing; preview does not update	Adds a JobPart to the controller-owned draft bundle and updates preview summary & counts
“Add to Job” (with pack)	Same as above; pack contents not visible in preview	Adds JobParts for each prompt in the pack; preview displays bundle size and prompt previews
“Add to Queue”	Queue panel not reliably updated; completed jobs remain in place	Enqueues the current draft bundle as a single queue item; preview clears; queue shows new job entry
Queue → History	Completed jobs stay in queue; history incomplete	When a job completes, it is removed from queue and appended to history with a stable summary
Job status visibility	No clear indication of RUNNING / COMPLETED	Queue shows status transitions (QUEUED → RUNNING → COMPLETED/CANCELLED) via JobService callbacks
Draft clearing	Clear draft may do nothing / not wired	Clear draft always resets the draft bundle and empties preview; “Add to Queue” is disabled afterwards
4.2 Internal System Behavior
Subsystem	Before	After
PipelineController	No structured draft; ad-hoc pack/draft handling	Owns JobBundleBuilder, draft JobBundle, and methods for add/clear/enqueue
JobService integration	Jobs submitted via older paths; GUI not fully aligned	Jobs submitted via submit_queued_from_bundle(...) or equivalent controller method
Queue panel & history panel	Maintain their own disconnected state	Derive state exclusively from JobService callbacks + history store
DTO usage	Preview/queue/history may poke at raw job models	GUI uses DTOs (JobBundleSummaryDTO, JobQueueItemDTO, JobHistoryItemDTO) only
4.3 Backward Compatibility

Existing queue/history storage formats remain unchanged or are extended in a backward-compatible way (e.g., extra fields in JSONL).

Legacy V1 queue/state restore remains untouched, aside from ensuring any shared JobService paths remain valid.

The new lifecycle wiring is additive: older paths that bypass the GUI (if any) should continue working or be explicitly marked deprecated.

5. Design Overview
5.1 Draft JobBundle Ownership

PipelineController owns:

_job_bundle_builder: JobBundleBuilder

_draft_bundle: Optional[JobBundle]

New controller methods (high-level intent):

class PipelineController:
    def add_job_part_from_current_config(self) -> JobBundleSummaryDTO: ...
    def add_job_parts_from_pack(self, pack_id: str, prepend_text: str = "") -> JobBundleSummaryDTO: ...
    def clear_draft_bundle(self) -> JobBundleSummaryDTO | None: ...
    def enqueue_draft_bundle(self) -> Optional[str]:  # returns job_id if enqueued


These methods:

Read current pipeline config + prompts (including global negative, stage toggles, batch settings).

Use JobBundleBuilder to add JobParts and rebuild the draft bundle.

Derive a JobBundleSummaryDTO which is passed to AppController / AppState for preview rendering.

5.2 JobService Integration

Add a high-level method in JobService to accept a bundle:

Either:

submit_queued_from_bundle(bundle: JobBundle) -> str, or

Reuse existing batch submission methods but with a helper that converts bundle → NormalizedJobRecord list.

PipelineController.enqueue_draft_bundle():

Converts its _draft_bundle into one or more NormalizedJobRecords using JobBuilderV2 helpers from PR-B/C.

Calls JobService to submit the job(s) as a single logical queue item (bundle root id).

Receives a job_id (canonical identifier for queue/history).

Clears the draft bundle on success and signals GUI to refresh preview + queue.

5.3 Queue & History Synchronization via Callbacks

Leverage JobService status callbacks (existing or extended):

job_service.set_status_callback("gui_queue_history", on_status_update)


on_status_update(job: Job, status: JobStatus):

If QUEUED: ensure queue panel shows the job.

If RUNNING: update queue panel entry to show “Running”.

If COMPLETED: remove job from queue panel; append to history panel.

If CANCELLED / FAILED: remove or mark job accordingly (depending on design).

History storage:

Continue to use JobHistoryService / JSONL store; callback simply adds GUI-visible entries based on the same job metadata used to write history.

5.4 DTOs

JobBundleSummaryDTO (for preview):

@dataclass(frozen=True)
class JobBundleSummaryDTO:
    num_parts: int
    estimated_images: int
    positive_preview: str
    negative_preview: str
    stage_summary: str
    batch_summary: str


JobQueueItemDTO:

@dataclass(frozen=True)
class JobQueueItemDTO:
    job_id: str
    label: str
    status: str
    estimated_images: int
    created_at: datetime


JobHistoryItemDTO:

@dataclass(frozen=True)
class JobHistoryItemDTO:
    job_id: str
    label: str
    completed_at: datetime
    total_images: int
    stages: str


GUI panels never touch Job, JobBundle, or NormalizedJobRecord directly; they receive DTOs from AppController / PipelineController.

6. Files & Subsystems
Primary Files (Allowed)

src/controller/pipeline_controller.py

src/controller/app_controller.py

src/controller/job_service.py (or equivalent JobService module)

src/controller/job_history_service.py / history modules

src/pipeline/job_builder_v2.py

src/pipeline/job_models_v2.py (for DTO definitions; no breaking changes)

src/gui/preview_panel_v2.py

src/gui/queue_panel_v2.py

src/gui/history_panel_v2.py

tests/controller/test_pipeline_controller_jobbundle_lifecycle.py (new)

tests/gui_v2/test_preview_queue_history_flow_v2.py (new or extended)

CHANGELOG.md

ARCHITECTURE_v2.5.md (append “JobDraft/JobBundle lifecycle” section)

StableNew_Coding_and_Testing_v2.5.md (add test guidance)

Forbidden / Do-Not-Touch

src/gui/main_window_v2.py

src/gui/theme_v2.py

src/main.py

Core pipeline runner internals (src/pipeline/pipeline_runner.py, executor core) except for minimal helper additions if absolutely unavoidable.

Healthcheck core.

7. Implementation Plan (Step-by-Step)

Introduce DTOs in pipeline/job models:

Add JobBundleSummaryDTO, JobQueueItemDTO, JobHistoryItemDTO to job_models_v2.py (or new DTO module) without modifying existing models.

Add simple constructors/helpers for building these from JobBundle and Job/NormalizedJobRecord.

Extend PipelineController with draft bundle management:

Add _job_bundle_builder and _draft_bundle fields.

Implement add_job_part_from_current_config, add_job_parts_from_pack, clear_draft_bundle, enqueue_draft_bundle as thin wrappers around:

Reading current config (stages, prompts, configs).

Using JobBundleBuilder from PR-B/C to mutate the draft.

Converting to summary DTO.

Wire AppController to PipelineController for preview actions:

In AppController, implement handlers for:

“Add to Job” (no pack): call pipeline_controller.add_job_part_from_current_config() and push summary DTO into AppState/preview.

“Add to Job” (with pack): call add_job_parts_from_pack.

“Clear Draft”: call clear_draft_bundle.

“Add to Queue”: call enqueue_draft_bundle.

Ensure these handlers are used by the GUI wiring (button callbacks).

Wire PreviewPanelV2 to DTOs:

Add update_from_summary(summary: JobBundleSummaryDTO) and clear_preview() helpers.

Make AppController pass DTOs in rather than raw models/state.

Show prompt previews, counts, stages, etc., according to the DTO.

Align QueuePanelV2 with JobService callbacks:

Implement methods like upsert_job(dto: JobQueueItemDTO) and remove_job(job_id: str).

Register a JobService status callback in AppController or PipelineController that:

On QUEUED/RUNNING: upserts the queue item.

On COMPLETED/CANCELLED: removes from queue and forwards a DTO to HistoryPanelV2.

Align HistoryPanelV2 with JobService / History store:

Implement append_history_item(dto: JobHistoryItemDTO).

In JobService status callback, when job transitions to COMPLETED, create the DTO and call into history panel.

Documentation & changelog:

Update ARCHITECTURE_v2.5.md with a concise section describing:

Draft bundle ownership.

Preview → Queue → History lifecycle.

Update StableNew_Coding_and_Testing_v2.5.md with:

Guidance on using DTOs in GUI tests.

How to add new job metadata without violating the boundary.

Add an entry to CHANGELOG.md for this PR.

8. Testing Strategy
8.1 Unit Tests

PipelineController lifecycle tests:

test_add_job_part_from_current_config_updates_draft_and_summary.

test_add_job_parts_from_pack_accumulates_multiple_job_parts.

test_clear_draft_bundle_resets_state_and_summary_is_none.

test_enqueue_draft_bundle_submits_job_and_clears_draft (with stub JobService).

DTO tests:

test_job_bundle_summary_dto_from_bundle_basic.

test_job_queue_item_dto_from_job.

test_job_history_item_dto_from_job.

8.2 Integration / Controller Tests

test_pipeline_controller_preview_queue_history_flow:

Simulate:

Add JobPart from config.

Enqueue draft bundle.

Simulate JobService status transitions via stub runner.

Assert queue and history observers receive correct DTOs.

8.3 GUI Tests (Headless / Tk Harness)

test_preview_panel_updates_on_add_to_job.

test_queue_panel_updates_on_job_status_changes.

test_history_panel_receives_completed_jobs_and_queue_clears.

8.4 Regression Tests

Ensure legacy tests that interact with JobService still pass:

No changes to method signatures without backward compatibility.

Any new parameters must have defaults.

9. Risks & Mitigations

Risk: Misaligned DTOs and real job objects (e.g., preview says one thing, runner does another).
Mitigation: Build DTOs from the same JobBundle / NormalizedJobRecord structures used for execution, not from GUI state.

Risk: Callback threading issues (updating Tkinter from non-main thread).
Mitigation: Ensure JobService callbacks scheduled for GUI updates use after() or an event queue processed on the main thread.

Risk: Breaking legacy tests that expect different queue/history behavior.
Mitigation: Add tests specifically asserting the new lifecycle; run full suite; where legacy expectations conflict, explicitly update tests and mark behavior as “v2.5 canonical”.

Risk: Overloading AppState with too much derived information.
Mitigation: Keep AppState limited to DTOs and flags; all heavy logic remains in controller/pipeline layers.

10. Rollback Plan

The changes are largely additive and localized:

Draft bundle ownership in PipelineController.

DTOs and new callbacks in JobService/GUI.

To roll back:

Revert changes to pipeline_controller.py, AppController handlers, and GUI panels to previous commit.

Remove new DTO definitions if they are unused elsewhere.

No schema migrations or destructive data operations are involved; rollback is a straightforward Git revert.

11. Migration / Data Considerations

Existing JSONL history files remain valid:

If DTOs add fields, they’ll be derived from existing job metadata; missing fields fall back to sensible defaults.

Existing queue state:

Any persisted queue from pre-PR-D may have slightly different behavior/labels in the GUI; at worst, user can clear queue and re-run.

12. Telemetry / Observability

Reuse the logging improvements from PR-A (Observability & Debug Harness):

Log:

Draft bundle size after each “Add to Job”.

Job IDs and bundle metadata when enqueued.

Status transitions and their origins.

Consider a debug toggle to dump DTO contents (preview/queue/history) to logs when investigating issues.

13. Documentation Updates

ARCHITECTURE_v2.5.md

Add a short “JobDraft / JobBundle Ownership & Lifecycle” subsection:

Draft lives in PipelineController.

Preview reads DTOs only.

Queue/history panels are driven by JobService callbacks.

StableNew_Coding_and_Testing_v2.5.md

Document how to:

Add new fields to job DTOs safely.

Write tests that assert preview/queue/history alignment.

Developer Notes

Add a short “How to debug job lifecycle” note (tie-in with PR-A logging).

14. Additional Notes / Assumptions

Assumes PR-B (JobPart/JobBundle + Builder) and PR-C (job draft ownership & preview wiring) are either implemented or at least structurally available so this PR can use them.

Assumes JobService already supports registering status callbacks and has a stable source of job metadata for history.

If the snapshot reveals different names or module paths for job/queue/history services, this PR’s implementation details should be adapted while preserving the same architectural intent and GUI/pipeline boundary.