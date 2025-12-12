# PR-GUI-V2-LEARNING-ENTRYPOINT-001
**Title:** GUI V2 – Learning Mode Toggle + “Review Recent Runs” Dialog (Rating-Only Passive Learning)

## 1. Intent & Scope

This PR adds the **first user-facing learning features** to GUI V2, built on top of the passive learning hooks added in PR-LEARN-V2-RECORDWRITER-001:

- A global **“Enable Learning”** toggle in settings (or equivalent) that controls the `learning_enabled` config flag.
- A simple **“Review Recent Runs”** dialog that:
  - Lists recent LearningRecords (most recent N runs).
  - Allows the user to assign a **1–5 rating** and optional short tags for each run.
  - Writes updated ratings back into the LearningRecords (e.g., by appending an updated record or updating a rating field in-place, following the Learning System spec).

This is **still L2 passive learning only**:
- No Learning Run wizard.
- No automatic preset generation.
- No cluster/distributed aspects.

Baseline: **StableNew-main-11-22-2025-0729.zip** plus completed PRs:
- PR-GUI-V2-MAINWINDOW-REDUX-001
- PR-PIPELINE-V2-EXECUTOR-STAGEEVENTS-003
- PR-LEARN-V2-RECORDWRITER-001

---

## 2. Goals

1. Expose a **Learning On/Off** control in GUI V2 that manipulates the underlying `learning_enabled` configuration.
2. Provide a **Review Recent Runs** dialog that lets users:
   - View recent LearningRecords in a simple table/list.
   - Rate each record (1–5) and add short tags.
   - Persist ratings back to learning storage.
3. Ensure learning UI is **non-intrusive**:
   - Learning stays off by default.
   - No pop-ups or modals appear unless the user opens the learning dialog deliberately.
4. Add GUI V2 tests for:
   - Learning toggle wiring (GUI → config → controller).
   - Basic dialog construction and table/list population using stub data.
   - Rating changes calling into a Learning adapter/controller layer correctly.

Non-goal: Full insights/analytics UI; this is just the entrypoint and basic feedback capture.

---

## 3. Allowed Files to Modify

GUI & adapters:

- `src/gui/main_window.py` (wiring only; no layout overhaul)
- `src/gui/app_layout_v2.py` (if needed for menu/toolbar hooks)
- `src/gui/learning_review_dialog_v2.py` (NEW Tk/Ttk dialog module)
- `src/gui_v2/learning_adapter_v2.py` (extend to support listing records & saving ratings)
- `src/controller/learning_execution_controller.py` (extend to support list/save operations)
- `src/config/app_config.py` (expose learning_enabled to GUI layer)

Tests:

- `tests/gui_v2/test_learning_toggle_and_dialog.py` (NEW)
- `tests/controller/test_learning_execution_controller_gui_contract.py` (NEW/updated)

Docs:

- `docs/Learning_System_Spec_v2.md`
- `docs/CHANGELOG.md`

You MUST NOT:

- Touch randomizer modules.
- Touch pipeline executor/sequencer.
- Touch cluster/queue modules.
- Introduce theme changes or major layout shifts.

---

## 4. Implementation Plan

### 4.1 Learning toggle in GUI V2

In `StableNewGUI` (main_window) and/or AppLayoutV2:

- Add a **“Learning”** menu item or settings checkbox such as:
  - “Enable learning (record runs for later review)”
- Wire it to:

```python
def on_learning_toggle(self, enabled: bool) -> None:
    self.learning_controller.set_learning_enabled(enabled)
```

- Ensure it:
  - Reads initial state from config on startup.
  - Updates config when toggled.
  - Propagates the flag to `PipelineController` so subsequent runs create LearningRecords only when enabled.

Add a simple status bar text or log entry on toggle, but avoid intrusive popups.

### 4.2 LearningReviewDialogV2

Create `src/gui/learning_review_dialog_v2.py` with a simple Tk/Ttk dialog that:

- Accepts:
  - A reference to a learning adapter/controller.
  - A list of LearningRecord summaries (or a fetch callback).
- Displays a table-like view with columns such as:
  - Run timestamp
  - Prompt (truncated)
  - Pipeline summary (e.g., model/steps)
  - Existing rating (1–5)
  - Tags (comma-separated)
- Provides controls to:
  - Change rating via dropdown or spinbox (1–5).
  - Edit tags via a simple text field.
  - Save changes back when user clicks “Save”/“Apply”.

The dialog does **not** display thumbnails yet; text-only is fine for this PR.

### 4.3 Learning adapter & controller extensions

In `learning_adapter_v2` and `learning_execution_controller`:

- Add methods to:
  - Fetch recent LearningRecords for display (e.g., last N; N configurable or fixed in code for now).
  - Apply rating/tag updates to a given record id (run_id).

Implementation detail:

- For storage, you can choose either:
  - (A) Update in place within the JSONL (if there is support for it).
  - (B) Append a new LearningRecord line with updated rating/tags and mark older ones as superseded via a field like `supersedes_run_id`.
- Choose the approach that aligns best with the existing Learning System spec; prefer append-only patterns when possible.

Add tests that mock/dummy the underlying file IO so GUI tests don’t touch the filesystem.

### 4.4 Wiring the “Review Recent Runs” entrypoint

In `StableNewGUI`:

- Add a menu item or button, e.g., “Learning → Review Recent Runs…”. 
- When clicked:
  - Invoke the learning adapter/controller to fetch recent records (stubbed in tests).
  - Construct and show `LearningReviewDialogV2` with the list.
  - Ensure that rating changes propagate back to the controller when saved.

### 4.5 Tests

Add GUI V2 tests (Tk-safe, using existing test patterns) that:

- Instantiate `StableNewGUI` with a stub learning controller/adapter.
- Simulate toggling the learning checkbox/menu item and assert that:
  - The stub controller receives `set_learning_enabled(True/False)` calls.
- Instantiate `LearningReviewDialogV2` with stub data and assert:
  - Proper widget creation (table, rating controls, tags field).
  - Invoking a “save” action calls the stub update method with expected parameters.

Controller tests should:

- Verify that `learning_execution_controller` correctly delegates to LearningRecord storage for list/update operations, using mocks or in-memory stubs.

---

## 5. Commands & Expected Outcomes

You MUST run at least:

- `pytest tests/gui_v2 -v`
- `pytest tests/controller -v`
- `pytest tests/learning -v`
- `pytest -v`

All existing tests must remain green, with the usual Tk skips respected.

---

## 6. Acceptance Criteria

This PR is complete when:

1. GUI V2 exposes a simple Learning On/Off toggle wired through config to the controller.
2. A “Review Recent Runs” dialog exists and can list and edit ratings/tags for LearningRecords.
3. All new tests (GUI + controller + learning adapter) pass.
4. No visual regressions to the main layout or pipeline controls occur.
5. Learning remains opt-in; default behavior is unchanged unless the user enables it.
