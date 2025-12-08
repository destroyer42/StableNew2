#CANONICAL
PR-C — Single-Prompt Preview → Queue → Run → History (V2.5).md
Discovery Reference: D-11 (Pipeline Run Controls / Queue Integration)
Upstream Dependencies: PR-A (Core Run Path & Runner DI), PR-B (Canonical JobPart/JobBundle + Builder)
Date: 2025-12-07 12:30 (local time)
Author: ChatGPT (Planner)

1. Summary (Executive Abstract)
This PR delivers a minimal but complete vertical slice for the StableNew pipeline: a single-prompt job flows from the pipeline tab through Add to Job → Preview → Add to Queue → Runner → History, using the canonical job model introduced in PR-B. It wires the GUI V2 pipeline tab and preview panel into JobBundleBuilder, connects the resulting JobBundle into JobService, and ensures that job lifecycle events move jobs cleanly from queue to history.
The scope is intentionally limited to single-prompt jobs with the current prompt field and Global Negative, leaving prompt packs and advanced stage features to later PRs. The preview panel becomes a true reflection of the current draft JobBundle, the queue shows an accurate summary of enqueued bundles, and history receives completed jobs once the runner finishes processing.
Architecturally, this PR stays within existing boundaries: GUI V2 → controllers → pipeline runtime → queue/runner, using the DI hooks and JobBundle/JobPart/PipelineConfigSnapshot data structures from earlier work. It introduces new controller methods and small GUI wiring changes, plus focused tests to prevent regressions in this critical run path.
This is a Tier 2 (Standard) change: it modifies controllers, GUI wiring, and queue/runner usage, but does not alter the core executor or pipeline runner internals.

2. Motivation / Problem Statement
Current Behavior
From the latest behavior reports and logs:


“Add to Job” appears to do nothing:


No visible change in the preview panel when clicked.


No clear draft “bundle of job parts” is being created or updated.




Preview panel:


Shows incomplete or inconsistent information.


Does not align with the stages and prompts that actually run (when a run happens).




“Add to queue”:


Does not consistently add a real job to the queue.


Preview panel does not clear when jobs are supposedly queued.




Job lifecycle:


Jobs stack up in the queue with no clear RUNNING/COMPLETED status changes.


Completed jobs are not reliably moved into the history view.




Single-prompt case (no packs) should be the simplest possible path, but even this is not behaving correctly end to end.


Why This Is Wrong


The user expectation (and product design) is that:


“Add to Job” builds up a draft job bundle in preview.


“Add to Queue” turns that draft bundle into an actual job entry in the queue.


The runner consumes that entry, executes it, and the results show up in history.




Instead, we have:


Disconnected GUI state that doesn’t reliably feed a canonical job representation.


Queue and runner paths that may be executing something, but not clearly connected to preview/queue/history UX.




Consequences of Not Fixing


You can’t reliably test or trust the main pipeline:


Users can’t tell what will be run, what is running, or what has finished.




All more advanced scenarios (prompt packs, multiple job parts, complex stage configs) are built on a shaky foundation.


Debugging is extremely difficult because the notion of “a job bundle” is implicit and scattered across controllers/GUI/pipeline.


Why Now


PR-A and PR-B lay the groundwork:


Core run-path DI hooks.


Canonical JobPart/JobBundle/PipelineConfigSnapshot/JobBundleBuilder.




The next critical step—and the one that finally makes the app feel “alive”—is to connect these pieces in a vertical slice for the simplest case: single-prompt jobs.


Once this is stable and tested, the same path can be extended to packs and richer stage configuration with much lower risk.



3. Scope & Non-Goals
In Scope


Single-prompt “Add to Job” flow:


From the top prompt field in the pipeline tab.


Optionally applying Global Negative text.




Draft job bundle wiring:


Use JobBundleBuilder to construct a draft JobBundle (single-prompt only).


Store this draft in controller/app state.




Preview panel integration:


Render the current draft bundle:


Total job parts.


Last-added prompt summary (positive/negative).


Basic config info (batch size, batch runs, estimated image count).




Enable/disable “Add to queue” based on whether the draft has at least one JobPart.


“Clear draft” clears the draft JobBundle and updates the preview accordingly.




Add to queue wiring:


Convert draft JobBundle into a job submitted to JobService.


Clear draft and preview after successful enqueue.




Job lifecycle updates:


When a job starts, its status changes from QUEUED → RUNNING in the queue UI.


When a job completes (or fails), it is removed from the queue and appended to history.




Tests:


Controller-level tests for “single-prompt Add to Job → enqueue → job lifecycle.”


A minimal GUI V2 test that verifies “Add to Job” causes preview to update correctly (using existing GUI test harness patterns if available).




Non-Goals (Explicit)


No prompt pack support in this PR:


“Add to Job” for packs will be handled in a follow-on PR.




No advanced stage behaviors:


ADetailer, hires/refiner defaults, Final Size updates, Face restore UX remain out of scope here.




No change to executor core / API client internals:


This PR assumes the core txt2img/img2img/upscale path already works when given appropriate payloads.




No design/UX restyling:


We will surface the needed fields in preview and queue/history, but we won’t redesign panels.





4. Architecture / Design
High-Level Flow
This PR wires the single-prompt pipeline as:
GUI (Pipeline Tab)
→ AppController / PipelineController
→ JobBundleBuilder (new from PR-B)
→ JobBundle
→ JobService.enqueue(bundle)
→ SingleNodeJobRunner consuming queue
→ JobHistoryService updating history
→ GUI (Queue + History panels) via controller/state updates.
Key Concepts and Contracts


Draft bundle:


Conceptual: A not-yet-enqueued JobBundleBuilder representing the current preview contents.


Lives in controller/app state:


e.g., AppStateV2.job_draft_bundle or similar.






Preview panel:


Renders the draft bundle in a simple, summary-oriented way:


Count of JobParts.


Last-added prompt summary.


Estimated total images.






Queue item:


Represents an enqueued JobBundle:


Queue UI shows label, status, total images.






History item:


Represents a completed job:


Derived from the same JobBundle plus completion metadata (status, timestamps).






Layer Responsibilities


GUI V2 (pipeline tab, preview panel):


Handles user interactions:


“Add to Job”, “Add to Queue”, “Clear draft.”




Delegates all semantics to controller methods; never builds JobParts/JobBundles directly.




Controllers:


Have methods like:


add_single_prompt_to_draft(...)


clear_draft_job_bundle(...)


enqueue_draft_bundle(...)




Use JobBundleBuilder to manage the draft bundle state.


Call JobService.enqueue(job_bundle) for queueing.


Update GUI-facing state models for preview, queue, history.




Pipeline/Queue:


JobService:


Accepts a JobBundle (or equivalent).


Emits events or updates state when job is enqueued/started/completed.




Runner:


Already wired via DI in previous work (PR-0114C-Tx/Ty, PR-A).


Consumes queue items and notifies JobService on completion.




JobHistoryService:


Records completed jobs and exposes them to controllers for UI.







5. Detailed Implementation Plan
Step 1 – Add draft bundle state to controller/app state


App state extension (e.g., src/gui/app_state_v2.py or controller-managed state):


Add field:


job_draft_bundle: Optional[JobBundle] or builder wrapper, depending on design.




Alternatively, controllers may hold JobBundleBuilder directly and expose a read-only DTO for preview.




Initial state:


On app start:


job_draft_bundle is None.




On Clear Draft:


Reset to None and clear preview.






Step 2 – Implement controller methods for single-prompt Add to Job
In src/controller/pipeline_controller.py and/or src/controller/app_controller.py:


Add method such as:


def add_single_prompt_to_draft(self) -> None:
    """
    Read the current positive prompt field, global negative config, and pipeline config,
    and append a JobPart to the draft JobBundle via JobBundleBuilder.
    """

Implementation outline:


Retrieve:


positive_prompt from the pipeline tab’s main prompt field.


global_negative_text + enabled/disabled flag from app state.


Current pipeline config (model, sampler, steps, batch size/count, etc.).




Build a PipelineConfigSnapshot from the current config.


If there is no current draft builder:


Create a new JobBundleBuilder with:


Base snapshot.


Global negative text and apply flag.






Call builder.add_single_prompt(positive_prompt, override_config=None, prompt_source="single").


Store/refresh the builder/draft bundle in controller state.


Notify preview panel via state update or callback.




Add a clear_draft_job_bundle method:


def clear_draft_job_bundle(self) -> None:
    """Clear the current draft JobBundle and notify the preview panel."""



Resets the builder, or sets draft to None.


Updates preview state to reflect “no jobs in draft.”


Step 3 – Wire GUI “Add to Job”, “Clear draft” to controller methods
In src/gui/pipeline_tab_v2.py and/or src/gui/preview_panel_v2.py:


Ensure there are callbacks (from main_window_v2 or existing controller wiring) to:


Call add_single_prompt_to_draft() when the “Add to Job” button is pressed.


Call clear_draft_job_bundle() when “Clear draft” is pressed.




After each controller call, the GUI should request the updated preview summary from controller/app state:


e.g., controller.get_draft_job_preview_summary() returning a small DTO:


num_parts: int


last_positive_prompt_preview: str


last_negative_prompt_preview: str


total_estimated_images: int




Preview panel then updates its labels, counts, and enables/disables buttons accordingly.




Add logic in preview panel to:


Disable “Add to queue” when num_parts == 0.


Enable “Clear draft” only if there is at least one part.




Step 4 – Implement Add to Queue from draft JobBundle
In the controller layer:


Add method enqueue_draft_bundle(run_mode: str = "queue") -> None:


Outline:


If there is no draft builder or no parts:


No-op or raise a user-friendly error log.




Call builder.to_job_bundle(label=optional_label, run_mode=run_mode).


Pass JobBundle to JobService.enqueue(job_bundle).


Reset draft builder and preview state.


Optionally, log:


Number of parts.


Total estimated images.






Wire GUI preview panel’s “Add to queue” button to this method.


Queue panel controller/GUI:


On successful enqueue, update queue UI to show:


New row with:


Label.


Status = QUEUED.


Total image count.








Step 5 – Ensure job lifecycle flows Queue → Runner → History
Assuming queue + runner DI hooks exist from prior work:


JobService enhancements (if needed) in src/pipeline/job_service.py:




Ensure enqueue(job_bundle):


Creates a queue item with:


status = QUEUED.


bundle_id, label, total_images, etc.






When SingleNodeJobRunner picks up the job:


Update status to RUNNING.


Notify any listeners / controller hooks.




When job completes:


Update status to COMPLETED (or FAILED).


Remove from queue list.


Forward job info to JobHistoryService.






JobHistoryService in src/pipeline/job_history_service.py:




Ensure it can accept completed JobBundle + metadata and append to history store (in-memory or JSONL).


Provide method(s) for controllers to retrieve history entries.




Controller update for queue & history:




On job lifecycle events, controllers:


Refresh queue UI from JobService.


Refresh history UI from JobHistoryService.




Step 6 – Preview/Queue/History UI updates


Preview panel:


Show:


Number of job parts.


Short preview of last positive/negative prompt (truncated).


Estimated total images.






Queue panel:


Show:


Bundle label.


Status (QUEUED/RUNNING).


Total images.






History panel:


Show:


Bundle label.


Completion status (COMPLETED/FAILED).


Completion time.







6. Files & Modules Touched

Exact paths should be confirmed against the latest repo_inventory.json and snapshot. Names below follow the prior v2 conventions.

Controllers / State


src/controller/app_controller.py


Add public methods: add_single_prompt_to_draft, clear_draft_job_bundle, enqueue_draft_bundle.


Wire these to existing controller → GUI callbacks.




src/controller/pipeline_controller.py


Implement logic to:


Extract current pipeline config into PipelineConfigSnapshot.


Access Global Negative config from app state.


Call into JobBundleBuilder.






src/gui/app_state_v2.py


Add fields for:


Draft job bundle or builder reference.


Preview summary DTO.






GUI V2


src/gui/pipeline_tab_v2.py


Wire “Add to Job,” “Add to queue,” and “Clear draft” buttons to AppController methods.




src/gui/preview_panel_v2.py


Add rendering logic for:


Number of job parts.


Last prompt summary.


Estimated image count.




Adjust button enablement state based on preview summary.




(Optional) src/gui/queue_panel_v2.py, src/gui/history_panel_v2.py


Ensure they can consume controller-provided DTO lists for queue and history items.




Pipeline / Queue / History


src/pipeline/job_models_v2.py


Minor adjustments if necessary to support controller usage of JobBundleBuilder.




src/pipeline/job_service.py


Ensure enqueue runs with JobBundle, and status changes propagate.




src/pipeline/job_history_service.py


Ensure it can record completed bundles and expose them as DTOs.




Tests


tests/controller/test_single_prompt_draft_to_queue_v2.py (new)


Unit/integration-level tests for controller behavior.




tests/gui_v2/test_pipeline_single_prompt_preview_v2.py (new)


GUI harness test to verify preview changes on Add to Job (single-prompt).




tests/pipeline/test_job_lifecycle_single_prompt_v2.py (new)


Test that a job enqueued via JobService transitions through QUEUED → RUNNING → COMPLETED and ends up in history.





7. Test Plan
7.1 Unit / Controller Tests
File: tests/controller/test_single_prompt_draft_to_queue_v2.py
Scenarios:


test_add_single_prompt_to_draft_creates_job_part_and_updates_preview


Given:


Empty draft.


Positive prompt "castle in the sky".


Global negative "bad_anatomy" enabled.




When add_single_prompt_to_draft() is called.


Then:


Draft bundle has exactly 1 JobPart.


positive_prompt matches input.


negative_prompt includes global negative.


Preview summary reports num_parts == 1.






test_clear_draft_job_bundle_resets_preview


Given:


A draft bundle with at least one JobPart.




When clear_draft_job_bundle() is called.


Then:


Draft is empty/None.


Preview summary indicates 0 parts and disables “Add to queue.”






test_enqueue_draft_bundle_submits_job_to_job_service_and_clears_draft


Given:


A draft with 1 JobPart.




When enqueue_draft_bundle() is invoked.


Then:


JobService.enqueue is called once with a JobBundle.


Draft is cleared.


Preview summary indicates no parts.


Queue view can see the new job.






7.2 Pipeline / Queue Tests
File: tests/pipeline/test_job_lifecycle_single_prompt_v2.py
Scenarios:


test_job_lifecycle_moves_from_queue_to_history


Given:


A stubbed runner (using DI) that simulates successful execution.


JobService with queue and history services.




When:


A single-prompt JobBundle is enqueued.


The runner processes the queue.




Then:


Job appears in queue with status=QUEUED.


Transitions to RUNNING while executing.


Ends with:


Not present in queue.


Present in history with status=COMPLETED.








7.3 GUI Tests
File: tests/gui_v2/test_pipeline_single_prompt_preview_v2.py
Scenarios:


test_add_to_job_updates_preview_and_enables_add_to_queue


Use existing Tkinter GUI harness for headless testing.


Simulate entering a prompt and clicking “Add to Job.”


Assert:


Preview panel reflects 1 job part.


“Add to queue” button becomes enabled.






test_clear_draft_from_preview_resets_state


After adding at least one prompt to draft:


Click “Clear draft.”


Assert:


Preview shows zero parts.


“Add to queue” is disabled.









Note: GUI tests should ensure they do not launch real WebUI jobs; they should rely on stubbed JobService/runner via DI hooks added in earlier PRs.


8. Risks & Mitigations
Risk 1 – Tight coupling between GUI and controller APIs


Concern: Direct GUI calls to new controller methods may introduce brittle dependencies.


Mitigation:


Follow existing pattern for controller callbacks (e.g., pass controller into GUI panels rather than global imports).


Ensure GUI only uses a small, well-defined interface, e.g., IPipelineRunController.




Risk 2 – Draft state getting out of sync with preview


Concern: It’s possible for draft bundle state and preview view-model to diverge if updates are missed.


Mitigation:


Centralize preview summary in controller/app state as a single DTO.


Always re-render preview based on that DTO after any state change (add, clear, enqueue).




Risk 3 – Queue and history updates not being reflected in GUI


Concern: Queue/history lists in the GUI might not refresh correctly when JobService events fire.


Mitigation:


Implement or reuse an event/listener mechanism (or a periodic refresh) for queue/history.


Keep the queue/history panels driven by controller-provided DTOs.




Risk 4 – Test flakiness in GUI tests


Concern: Tkinter harness tests may be flaky or slow if they accidentally trigger real runner behavior.


Mitigation:


Use stubbed JobService and runner via DI hooks.


Limit GUI tests to state changes and button enablement, not actual image generation.





9. Rollout / Migration Plan


Step 1 – Implement controller and state changes.


Add draft bundle and preview summary logic.


Add new controller methods.




Step 2 – Wire GUI buttons and preview panel.


Connect Add to Job / Add to Queue / Clear Draft.


Validate preview updates manually.




Step 3 – Integrate queue & history updates.


Ensure job lifecycle events drive UI lists.




Step 4 – Add and stabilize tests.


Get controller and pipeline tests passing.


Introduce GUI tests only once DI is in place.




Step 5 – Manual verification.


Start StableNew.


Enter a single prompt (no pack).


Add to Job.


Confirm preview is correct.


Add to queue and run.


Confirm queue updates and job appears in history.




Rollback is straightforward: revert controller/GUI changes, and the new methods/state can be safely removed without impacting existing queue/runner core.

10. Telemetry & Debugging
To make this path debuggable:


Add structured debug logs in controller methods:


On add_single_prompt_to_draft:


Log positive/negative prompt lengths, number of parts before/after.




On enqueue_draft_bundle:


Log bundle ID, number of parts, total estimated images.






Use consistent tags (e.g., subsystem=preview, subsystem=job_service, subsystem=history) so logs can be filtered in a future debug console.


No additional telemetry backends are introduced in this PR; this is for local debugging.

11. Documentation Updates


ARCHITECTURE_v2.5.md:


Add a short subsection under pipeline/GUI integration:


“Single-Prompt Vertical Slice: Pipeline Tab → Preview → Queue → Runner → History.”




Describe:


The role of JobBundleBuilder for single-prompt jobs.


The draft bundle concept.


How queue and history reflect the same JobBundle.






Optionally, in a separate design note (e.g., docs/older/JobFlow_SinglePrompt_v2.5.md):


Provide a step-by-step flow diagram or bullet list of the lifecycle.





12. Open Questions


Naming of controller methods:


Confirm final names:


add_single_prompt_to_draft


clear_draft_job_bundle


enqueue_draft_bundle




Ensure they align with existing naming conventions.




Exact preview summary fields:


Decide final schema (e.g., num_parts, total_images, last_positive_preview, last_negative_preview).


Document in code and (optionally) in a small doc.




Where to store draft bundle: app state vs controller-only:


Option A: Store builder/bundle directly in app state.


Option B: Keep in controller and expose read-only summary to UI.


Recommendation: Start with controller-held builder, exposing summary-only DTO to UI.





13. Out of Scope / Future Work


Extending Add to Job for:


Prompt packs.


Multiple job parts.


Advanced randomizer modes.




Wiring advanced stage behaviors (ADetailer, hires/refiner, Final Size, Face Restore) into the PipelineConfigSnapshot and preview details.


Implementing the detailed “Job-part cards” modal UI for deep inspection and delete-per-part editing.


History replay: ability to re-run or clone jobs from history.


These will be addressed in later PRs once the single-prompt vertical slice is stable.

14. Checklist


 Add draft bundle and preview summary to app/controller state.


 Implement add_single_prompt_to_draft, clear_draft_job_bundle, and enqueue_draft_bundle in controllers.


 Wire pipeline tab + preview panel buttons to the new controller methods.


 Ensure preview summary is correctly rendered for single-prompt jobs.


 Ensure Add to Queue enqueues JobBundle and clears draft/preview.


 Ensure queue panel reflects QUEUED/RUNNING status changes.


 Ensure history panel receives completed jobs and removes them from queue.


 Add controller tests (test_single_prompt_draft_to_queue_v2).


 Add pipeline lifecycle tests (test_job_lifecycle_single_prompt_v2).


 Add minimal GUI test (test_pipeline_single_prompt_preview_v2).


 Update ARCHITECTURE_v2.5.md and CHANGELOG.md with PR-C entry.

