Timestamp: 2025-11-22 16:05 (UTC-06)

PR Id: PR-#34-GUI-V2-LearningToggleAndReviewDialog-001
Spec Path: docs/pr_templates/PR-#34-GUI-V2-LearningToggleAndReviewDialog-001.md

# Title: GUI V2 – Learning Mode Toggle and “Review Recent Runs” Dialog (Passive L2 Entry Point)

1. Summary

This PR introduces the first user-facing learning features into GUI V2, built on top of the passive-learning hooks wired in PR-#33-LEARNING-V2-RecordWriterIntegration-001.

Specifically, it adds:

- A global Learning-enabled toggle in GUI V2 (wired to the controller/config learning_enabled flag).
- A “Review Recent Runs” dialog that:
  - Lists recent LearningRecords (most recent N runs).
  - Lets the user assign a 1–5 rating and free-text tags for each run.
  - Persists rating/tag updates back into the LearningRecord storage in an append-safe way.

This remains strictly L2 passive learning:

- No active-learning plans/runs.
- No analytics or recommendations.
- No cluster integration.

GUI V2 is still the single-node UX; this PR only exposes the learning capabilities already present in the controller and pipeline layers.

2. Problem Statement

After PR-#33:

- PipelineRunner and PipelineController can emit LearningRecords in JSONL when learning_enabled is true.
- LearningRecord and LearningRecordWriter are wired and tested.
- However, there is no way for the user to:
  - Turn learning on/off from the GUI.
  - Inspect or rate previous runs.
  - Add qualitative tags that make LearningRecords more useful for future insights.

Without a GUI entry point:

- Learning remains effectively invisible and unused.
- No user feedback (ratings/tags) can be collected.
- Future Learning and Insights PRs have no UX surface to build on.

We need a minimal, non-disruptive GUI V2 entry point that:

- Lets users opt into learning.
- Provides a simple “Review runs” experience for rating/tagging.

3. Goals

3.1 Functional Goals

- Add a clearly-labeled Learning toggle in GUI V2 that:
  - Reads its initial state from the existing learning_enabled config field.
  - Updates that field when the user toggles it.
  - Ensures future runs respect the learning_enabled flag.

- Add a Learning Review dialog that:
  - Shows a list/table of recent LearningRecords (most recent N, configurable or hard-coded).
  - Displays key metadata: timestamp, prompt/prompt pack identifier, basic pipeline summary, current rating, and tags.
  - Allows the user to edit rating (1–5) and tags (comma-separated or free-text).
  - Sends updates back through a learning adapter/controller facade to persist ratings/tags.

3.2 UX Goals

- Learning must remain opt-in and non-intrusive:
  - Learning is OFF by default.
  - No pop-ups or forced dialogs.
  - Users explicitly open the Review dialog from a menu item or button.

- The “Review Recent Runs” dialog should:
  - Be text-first (no thumbnails required in this PR).
  - Be clearly labeled and simple to understand.
  - Work even if there are zero LearningRecords (show an empty state message).

3.3 Testing Goals

- GUI V2 tests must verify:
  - Learning toggle reads/writes the controller/config state correctly.
  - The Review dialog is constructed correctly and can display stubbed LearningRecords.
  - Rating/tag edits call the appropriate learning adapter/controller methods.

- Controller/adapter tests must verify:
  - Recent LearningRecords can be requested and returned for GUI consumption.
  - Rating/tag updates are correctly written using the LearningRecord storage strategy (append-only or equivalent).

3.4 Non-Goals

- No active learning workflows (plans, per-parameter experiments).
- No thumbnails or advanced visualization; text-only is sufficient.
- No changes to pipeline execution or learning record emission logic.
- No cluster/queue integration.

4. Baseline and Dependencies

This PR assumes the repo is at the snapshot:

- StableNew-main-11-22-2025-0729.zip

With the following PRs applied:

- PR-GUI-V2-MAINWINDOW-REDUX-001 (StableNewGUI delegates panel composition to AppLayoutV2).
- PR-PIPELINE-V2-EXECUTOR-STAGEEVENTS-003 (StageEvents and stage-plan wiring in pipeline).
- PR-#33-LEARNING-V2-RecordWriterIntegration-001 (LearningRecord, builder, writer, and controller/pipeline hooks).

We rely on:

- Learning_System_Spec_v2 for LearningRecord semantics.
- ARCHITECTURE_v2 for the GUI → controller → pipeline → learning layering.
- Testing_Strategy_v2 for GUI V2 and learning test expectations.

5. Scope: Allowed and Forbidden Files

5.1 Allowed Files

You MAY modify or create the following, or their equivalent V2 paths if naming differs slightly:

GUI / Layout:

- src/gui/main_window.py
- src/gui/app_layout_v2.py
- src/gui/learning_review_dialog_v2.py (NEW; dialog implementation)
- src/gui/menus_v2.py or equivalent (if a dedicated menu module exists)

Learning Adapters / Controller:

- src/controller/learning_execution_controller.py
- src/learning/learning_adapter_v2.py or equivalent adapter module (NEW or extended)
- src/config/app_config.py (expose learning_enabled to GUI/config layer)

Tests:

- tests/gui_v2/test_learning_toggle.py (NEW)
- tests/gui_v2/test_learning_review_dialog.py (NEW)
- tests/controller/test_learning_execution_controller_gui_contract.py (NEW or updated)
- tests/learning/test_learning_adapter_v2.py (NEW, if adapter module is introduced)

Docs:

- docs/Learning_System_Spec_v2.md (note new GUI entry point)
- docs/CHANGELOG.md (add entry for PR-#34)

If some of these files differ in name, follow the existing V2 GUI and learning module patterns and keep changes strictly within this scope.

5.2 Forbidden Files

Do NOT modify:

- Pipeline core:
  - src/pipeline/pipeline_runner.py
  - Any src/pipeline/* stage implementation
- Randomizer:
  - src/utils/randomizer*
- API client:
  - src/api/*
- Cluster / queue:
  - src/queue/*
- Theme / style:
  - src/gui/theme.py
- GUI V1 / legacy tests:
  - tests/gui_v1_legacy/*

Any need to modify these should be handled in a separate PR.

6. High-Level Design

6.1 Learning Toggle in GUI V2

- Add a Learning section to the main menu or settings panel, e.g.:
  - Menu: Learning → Enable Learning (checkbox)
  - Or a small “Learning” checkbox in an existing settings pane (as long as it is clearly labeled).

- StableNewGUI should, on startup:
  - Query the current learning_enabled value from app_config (or equivalent).
  - Initialize the checkbox checked/unchecked accordingly.

- When the user toggles the checkbox:
  - Call a method on a learning/controller facade, e.g.:
    - learning_controller.set_learning_enabled(enabled: bool)
  - The controller then:
    - Updates app_config / runtime state.
    - Ensures new runs use the updated flag.

6.2 “Review Recent Runs” Dialog

Implement src/gui/learning_review_dialog_v2.py as a Tk/Ttk dialog class, e.g.:

- LearningReviewDialogV2(tk.Toplevel or ttk.Frame embedded in a modal dialog helper).

Responsibilities:

- On creation:
  - Request recent LearningRecord summaries from the learning adapter/controller.
  - Populate a table-like widget with one row per run.

- Columns:
  - Timestamp
  - Prompt (shortened or pack + prompt id)
  - Pipeline summary (e.g., model/steps, or a “details” column)
  - Rating (1–5, editable via Spinbox or Combobox)
  - Tags (Entry or Text field for comma-separated tags)

- Controls:
  - Save / Apply: Writes edits back via learning adapter/controller.
  - Close / Cancel: Closes without applying changes (or at least without applying pending unsaved edits).

- Empty state:
  - If there are no LearningRecords, show a friendly message (e.g., “No learning data yet. Enable learning and run a few pipelines to see them here.”) and a Close button.

6.3 Learning Adapter / Controller Contract

Add or extend a learning adapter layer (pure/non-GUI) to avoid GUI code dealing with JSONL or IO:

- An interface something like:

  - list_recent_records(limit: int) -> List[LearningRecordSummary]
  - update_record_feedback(run_id: str, rating: Optional[int], tags: Sequence[str]) -> None

- LearningRecordSummary should be lightweight:
  - run_id
  - timestamp
  - prompt_summary: str
  - pipeline_summary: str
  - rating: Optional[int]
  - tags: List[str]

The controller implementation:

- Resides in learning_execution_controller.py (or similar).
- Uses existing LearningRecord JSONL storage to:
  - Read latest N records (e.g., by scanning from the end, or simply scanning forward for now).
  - Apply rating/tag edits using the project’s chosen write pattern:
    - Option A (preferred): Append a new record that supersedes rating/tags for the run_id.
    - Option B: Update in-place if the LearningRecordWriter supports safe rewriting (only if already implemented by PR-#33).

For this PR, keep it as simple as possible while remaining consistent with Learning_System_Spec_v2’s append-only orientation. If in doubt, prefer appending a new record with updated feedback fields and a supersedes_run_id pointer.

7. Detailed Implementation Steps

7.1 Learning Toggle Wiring

1) In app_config.py:

- Ensure a boolean learning_enabled exists with a default of False.
- Expose get_learning_enabled() and set_learning_enabled(enabled: bool) helpers.

2) In learning_execution_controller.py:

- Add a property backing the toggle:
  - def get_learning_enabled(self) -> bool
  - def set_learning_enabled(self, enabled: bool) -> None
- These functions should delegate to app_config and ensure any in-memory state remains consistent.

3) In StableNewGUI / AppLayoutV2:

- On initialization:
  - Read learning_enabled via the controller.
  - Create a menu checkbox or settings checkbox tied to a callback.
- Implement a callback like:
  - on_learning_toggle(self, enabled: bool) that calls learning_controller.set_learning_enabled(enabled).

4) Tests:

- tests/gui_v2/test_learning_toggle.py:
  - Construct StableNewGUI with a fake learning_controller that tracks calls.
  - Assert:
    - Initial checkbox state matches fake controller’s get_learning_enabled() return value.
    - Toggling the checkbox invokes set_learning_enabled(True/False) with correct arguments.

7.2 LearningReviewDialogV2

1) Create src/gui/learning_review_dialog_v2.py:

- Dialog construction:
  - Accept a learning_adapter/controller and a parent window.
  - Fetch recent LearningRecordSummary objects (limit, e.g., 50).
  - Build a table using ttk.Treeview or equivalent grid pattern.

- Editing behavior:
  - Provide rating cells as either:
    - Combobox in a separate pane bound to the selected row; or
    - Inline editing pattern as current GUI test patterns allow.
  - Provide tags editing via a simple Entry widget bound to the selected record.
  - When user clicks “Save”:
    - For each record with changed rating/tags, call update_record_feedback(run_id, rating, tags).

- Tests:
  - tests/gui_v2/test_learning_review_dialog.py:
    - Use a fake adapter that returns 2–3 stub LearningRecordSummary objects.
    - Instantiate the dialog in a test-harness-safe way (following existing GUI V2 test patterns).
    - Assert:
      - Rows match stub data (run_id, timestamp, etc.).
      - Simulated rating/tag changes cause update_record_feedback() to be called with expected parameters when Save is triggered.

7.3 Learning Adapter / Controller

1) Define a small summary dataclass:

- e.g., LearningRecordSummary in learning_adapter_v2.py:

  - run_id: str
  - timestamp: datetime or string
  - prompt_summary: str
  - pipeline_summary: str
  - rating: Optional[int]
  - tags: List[str]

2) Implement:

- list_recent_records(limit: int) -> List[LearningRecordSummary]
- update_record_feedback(run_id: str, rating: Optional[int], tags: Sequence[str]) -> None

These functions:

- Should NOT import any GUI modules.
- Should use existing LearningRecord JSONL reading/writing behavior from PR-#33, or at least use shared helpers to parse/write records.

3) tests/learning/test_learning_adapter_v2.py:

- Use in-memory JSONL or temporary file fixtures.
- Write a few synthetic LearningRecords.
- Assert that:
  - list_recent_records returns the expected summaries.
  - update_record_feedback appends or updates records according to the chosen strategy.

8. Required Tests

At minimum, add or update tests so the following run cleanly:

- pytest tests/gui_v2/test_learning_toggle.py -v
- pytest tests/gui_v2/test_learning_review_dialog.py -v
- pytest tests/controller/test_learning_execution_controller_gui_contract.py -v
- pytest tests/learning/test_learning_adapter_v2.py -v
- pytest tests/learning -v
- pytest tests/gui_v2 -v
- pytest -v

Existing tests for learning, pipeline, and controller must remain green; GUI V2 tests must only fail/skip in known Tk/Tcl environments as previously configured.

9. Acceptance Criteria

This PR is complete when:

- Learning toggle:
  - GUI V2 exposes an “Enable Learning” control.
  - The control correctly reflects and updates the underlying learning_enabled config state.
  - Toggling the control affects subsequent runs (via controller wiring), but does not retroactively affect previous LearningRecords.

- Review dialog:
  - “Review Recent Runs” is accessible via a menu item or button.
  - The dialog lists recent LearningRecords in a readable textual table.
  - The user can change rating and tags and save them.
  - Changes are persisted via the learning adapter/controller without corrupting JSONL storage.

- Tests:
  - All new GUI V2 and learning adapter/controller tests pass.
  - Full pytest run is green (with only known/expected skips).

- Safety:
  - No changes were made to forbidden modules (pipeline stages, randomizer, API client, cluster).
  - The GUI remains responsive; the dialog and toggle do not block or interfere with normal operation.

10. Rollback Plan

If issues arise (e.g., dialog crashes, learning toggle misbehavior):

1) Revert changes in:

- src/gui/main_window.py
- src/gui/app_layout_v2.py
- src/gui/learning_review_dialog_v2.py
- src/controller/learning_execution_controller.py
- src/learning/learning_adapter_v2.py (if created)
- tests/gui_v2/test_learning_toggle.py
- tests/gui_v2/test_learning_review_dialog.py
- tests/controller/test_learning_execution_controller_gui_contract.py
- tests/learning/test_learning_adapter_v2.py

2) Remove the corresponding entries in:

- docs/Learning_System_Spec_v2.md
- docs/CHANGELOG.md

3) Re-run:

- pytest tests/gui_v2 -v
- pytest tests/learning -v
- pytest tests/controller -v
- pytest -v

4) Confirm behavior returns to the pre-PR state (learning remains backend-only, with no GUI controls or dialogs).

11. Notes for Codex (Implementer)

- Work strictly within the Allowed Files.
- Follow TDD:
  - Add/update tests first.
  - Run them and paste failing output when requested.
  - Then implement code to satisfy the tests.
- Use existing GUI V2 harness patterns for creating dialogs and menus.
- Do not introduce new dependencies or frameworks; use Tk/Ttk and project-standard utilities only.
- Keep the LearningReviewDialogV2 text-focused; thumbnails and advanced layouts are future work, not part of this PR.
