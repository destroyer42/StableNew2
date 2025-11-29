Timestamp: 2025-11-22T19:30:19-06:00
PR Id: PR-#48-GUI-V2-CommandBar-RunStopQueue-001
Spec Path: docs/pr_templates/PR-#48-GUI-V2-CommandBar-RunStopQueue-001.md

---

# PR-#48-GUI-V2-CommandBar-RunStopQueue-001

## 1. Intent & Scope

This PR introduces a dedicated **V2 command bar** for primary pipeline actions (Run / Stop / Queue mode) in the Tkinter GUI, without changing underlying controller or pipeline semantics.

Goals:

- Group **Run Full Pipeline**, **Stop/Cancel**, and **Queue mode** controls into a clear, single command bar widget within the V2 layout.
- Keep existing **run-button wiring and tests** intact (StableNewGUI still exposes `run_button` for tests/smoke harnesses).
- Do **not** change pipeline behavior, queue semantics, or learning/randomizer logic—only how top-level controls are visually and structurally presented.
- Add focused GUI V2 tests to lock in layout and lifecycle expectations for the command bar.

This PR is **GUI-only** and must not change behavior of pipeline execution or controller state transitions beyond what is already covered by existing tests. It prepares the surface for future prompt editor and advanced UX work by making the primary controls predictable and well-encapsulated.

---

## 2. Current Context & Dependencies

Assume the repo snapshot is **StableNew-main-11-22-2025-1815.zip** with these facts in place:

- **Architecture v2** and **GUI V2** are the authoritative models.
- `StableNewGUI` delegates layout composition to `AppLayoutV2`.
- V2 panels already exist and are composed via `AppLayoutV2`:
  - `src/gui/pipeline_panel_v2.py`
  - `src/gui/randomizer_panel_v2.py`
  - `src/gui/sidebar_panel_v2.py`
  - `src/gui/preview_panel_v2.py`
  - `src/gui/status_bar_v2.py`
  - `src/gui/app_layout_v2.py`
- Queue/cluster/worker foundations are in place:
  - `src/queue/job_model.py`, `job_queue.py`, `job_execution_controller.py`, `job_history_store.py`
  - `src/controller/job_history_service.py`, `queue_execution_controller.py`, `cluster_controller.py`
  - `src/gui/job_history_panel_v2.py`
- Queue-backed run mode is implemented and tested:
  - `queue_execution_enabled` flag in `config/app_config.py`.
  - `PipelineController` routes runs through `QueueExecutionController` when enabled (PR-#45).
  - GUI V2 already has a **queue mode toggle test** around the Run button.
- Pipeline config assembly has been consolidated around `PipelineConfigAssembler` (PR-#47), and GUI V2 adapters use structured overrides.

You do **not** need to re-implement or refactor any of the above. This PR only introduces a dedicated command bar widget and gently migrates existing controls into it.

---

## 3. High-Level Goals

1. **Command Bar Encapsulation**
   - Introduce a `PipelineCommandBarV2` widget that is responsible for:
     - Run Full Pipeline button.
     - Stop/Cancel button.
     - Queue mode indicator/toggle (hooked to `queue_execution_enabled` via existing config/controller plumbing).
   - Place this widget in a predictable position within the V2 layout (top or bottom of the pipeline panel), without changing panel hierarchy from the controller’s perspective.

2. **Preserve Existing Wiring & Tests**
   - Keep the main `StableNewGUI` API surface used by tests:
     - `StableNewGUI.run_button` must still point to the Run button widget after the refactor.
   - Do not change controller signatures or lifecycle contracts.

3. **Improve Test Coverage**
   - Add GUI V2 tests that assert:
     - The command bar exists and contains Run/Stop/Queue controls.
     - Run/Stop buttons reflect controller state (IDLE/RUNNING/STOPPING/ERROR) in the same way as before.
     - Queue mode toggle affects visual state and binds into app config/controller as expected (reusing or extending existing tests).

4. **Leave Space for Future Prompt Editor**
   - Design the command bar so it does **not** conflict with future prompt-editor placement (e.g., keep the bar compact, clearly separated from stage cards).

---

## 4. Allowed / Forbidden Files

You MAY edit or create:

- GUI V2 command bar & pipeline panel:
  - `src/gui/pipeline_panel_v2.py`
  - `src/gui/pipeline_command_bar_v2.py` (new)
  - `src/gui/panels_v2/__init__.py` (to re-export the new widget if needed)
- GUI V2 layout/wiring:
  - `src/gui/app_layout_v2.py`
  - `src/gui/main_window.py` (only for wiring `run_button` / references to the new command bar)
- GUI V2 tests:
  - `tests/gui_v2/test_command_bar_v2.py` (new)
  - `tests/gui_v2/test_run_button_queue_mode_toggle.py` (extend if necessary)
  - Any existing GUI V2 tests that need minor path/import updates, without loosening assertions.
- Docs (small factual updates only):
  - `docs/StableNew_Roadmap_v2.0.md` (GUI V2 section)
  - `docs/Known_Bugs_And_Issues_Summary.md` (update button placement/command bar section if applicable)
  - `docs/ROLLING_SUMMARY.md` (append PR-#48 entry)

You MUST NOT:

- Change pipeline behavior or APIs:
  - No edits to `src/pipeline/*` except import path fixes (which should not be necessary here).
- Change controller or queue semantics:
  - No behavioral changes in `src/controller/*` modules.
- Change learning or randomizer core logic:
  - No edits to `src/learning*` or `src/randomizer*` modules.
- Loosen safety or lifecycle tests.
- Introduce Tk/Ttk imports outside `src/gui/*`.

If you believe a non-listed file must change, **stop** and leave a clear note in the PR body rather than editing it.

---

## 5. Implementation Plan (Step-by-Step)

Implement in the following order, using TDD (tests first where feasible).

### 5.1. Introduce `PipelineCommandBarV2`

1. Create `src/gui/pipeline_command_bar_v2.py` with a small class, e.g. `class PipelineCommandBarV2(ttk.Frame):`.
2. Responsibilities:
   - Create and layout:
     - `self.run_button`
     - `self.stop_button`
     - A queue mode control, which may be:
       - A `ttk.Checkbutton` bound to a `BooleanVar`, or
       - A small toggle UI that reflects queue mode state.
   - Provide simple helper methods:
     - `set_running_state(is_running: bool)`
     - `set_queue_mode(enabled: bool)` / `get_queue_mode()`
3. Do **not** introduce any controller logic here:
   - No direct calls to controller methods.
   - Only invoke callbacks provided by the parent (pipeline panel or StableNewGUI).
4. Ensure widget hierarchy and naming is stable enough for tests to locate the buttons and queue toggle deterministically.

### 5.2. Wire Command Bar into `PipelinePanelV2`

1. In `src/gui/pipeline_panel_v2.py`:
   - Instantiate `PipelineCommandBarV2` as part of the panel layout.
   - Place it in a top or bottom region of the pipeline panel grid/pack (keep scrollbars and stage cards behavior intact).
2. Expose key attributes:
   - `self.command_bar` referencing the new widget.
   - `self.run_button` and `self.stop_button` should be forwarded or aliased from `command_bar` so existing tests that expect `pipeline_panel_v2.run_button` still work.
3. Make sure stage cards and other content remain visible and scroll correctly; do not add nested scrollbars.

### 5.3. Preserve `StableNewGUI.run_button` and Existing Wiring

1. In `src/gui/app_layout_v2.py`:
   - Where the Run button was previously created or exposed, adjust wiring so that:
     - `StableNewGUI.run_button` points to `pipeline_panel_v2.run_button` (which now comes from the command bar).
   - If there was a separate Run button widget before, migrate that responsibility to `PipelineCommandBarV2` and remove the old one, keeping tests green.
2. In `src/gui/main_window.py`:
   - Confirm that any code that refers to `self.run_button` now correctly refers to the command bar’s Run button via the pipeline panel.
   - Do not change controller logic; only adjust attribute wiring and (if necessary) type hints/docstrings.

### 5.4. Integrate Queue Mode Toggle

1. Reuse existing queue mode plumbing:
   - Queue enable/disable state is stored via `app_config` and consumed by `PipelineController` / `QueueExecutionController`.
2. In the command bar:
   - Bind the queue toggle checkbutton/indicator to a callback supplied from `StableNewGUI` / app layout:
     - On toggle, update `app_config.queue_execution_enabled` and refresh any needed status text.
   - Reflect current queue mode on startup (by reading from config and updating the toggle).
3. Ensure compatibility with existing tests in `tests/gui_v2/test_run_button_queue_mode_toggle.py`:
   - Update imports and widget traversal if needed so the test finds the queue control through the new command bar.
   - If you need to adjust the test, keep assertions equally strict or stronger.

### 5.5. Tests (TDD-first)

Before implementing heavy wiring, create or extend:

1. `tests/gui_v2/test_command_bar_v2.py` (new):
   - `test_command_bar_exposes_run_stop_and_queue_controls`:
     - Constructs a minimal Tk root and a `PipelineCommandBarV2` instance.
     - Asserts that `run_button`, `stop_button`, and queue toggle widget exist.
   - `test_command_bar_initial_queue_state_matches_boolvar_or_config_stub`:
     - Use a simple stub for config/state to verify that initial queue toggle state can be set via constructor arguments or setters.
2. Extend `tests/gui_v2/test_run_button_queue_mode_toggle.py`:
   - Ensure it still passes by locating the queue toggle via the new widget hierarchy.
   - Add an assertion that the queue toggle lives on the command bar (if feasible without over-specifying the layout).

Only after these tests are written and confirmed failing on the current repo should you implement the changes above.

### 5.6. Docs & Rolling Summary

1. Update `docs/StableNew_Roadmap_v2.0.md`:
   - Under GUI V2 / UX improvements, add a bullet describing the new command bar for primary pipeline actions.
2. Optionally update `docs/Known_Bugs_And_Issues_Summary.md`:
   - Adjust the “Button Placement & Behavioral Confusion” section to note that primary actions are now grouped in a command bar (but leave any remaining issues that still apply).
3. Append a short entry to `docs/ROLLING_SUMMARY.md` for PR-#48 (see §7).

---

## 6. Required Tests & Commands

At minimum, after implementation you MUST run:

1. Focused GUI V2 tests:
   - `pytest tests/gui_v2/test_command_bar_v2.py -v`
   - `pytest tests/gui_v2/test_run_button_queue_mode_toggle.py -v`
2. GUI V2 suite:
   - `pytest tests/gui_v2 -v`
3. Safety and controller tests (sanity):
   - `pytest tests/safety -v`
   - `pytest tests/controller -v`
4. Full suite (if runtime is acceptable):
   - `pytest -v`

Expected known outcomes:

- GUI V2 suite may still have pre-existing Tk skips depending on environment. Do **not** introduce new skips.
- Pipeline XFAILs (e.g., upscale hang diagnostics) must remain as-is; do not convert them to passes or hard failures.
- Safety tests must remain green (no new Tk imports outside `src/gui/`).

If any tests fail outside the known skips/XFAILs, fix the cause within the allowed files or back out the change.

---

## 7. Rolling Summary Update Block

When this PR is implemented and tests are passing, append the following entry to `docs/ROLLING_SUMMARY.md` under the latest date section:

> **PR-#48-GUI-V2-CommandBar-RunStopQueue-001** – Introduced a dedicated PipelineCommandBarV2 widget to host Run, Stop, and Queue mode controls inside PipelinePanelV2. StableNewGUI still exposes `run_button` for tests, but the primary pipeline actions are now grouped into a single command bar, aligning with the GUI V2 layout plan and button-placement guidance. Queue mode toggle is surfaced via the command bar using existing app_config/controller plumbing; no pipeline or controller semantics changed. New GUI V2 tests cover command bar existence and queue toggle behavior.

---

## 8. Codex Execution Block (Copy/Paste for Implementer)

Use the following instructions when handing this PR to Codex (GitHub Copilot / ChatGPT worker) for implementation.

> You are working on the StableNew repo at the snapshot corresponding to `StableNew-main-11-22-2025-1815.zip`. Implement the PR **\"PR-#48-GUI-V2-CommandBar-RunStopQueue-001\"** exactly as described in this markdown file.
>
> Key constraints:
> - Do **not** change behavior in `src/pipeline/*` or `src/controller/*` modules.
> - Do **not** modify learning or randomizer core logic.
> - Your work is confined to:
>   - `src/gui/pipeline_command_bar_v2.py` (new)
>   - `src/gui/pipeline_panel_v2.py`
>   - `src/gui/app_layout_v2.py`
>   - `src/gui/main_window.py` (wiring only)
>   - `src/gui/panels_v2/__init__.py` (if needed)
>   - `tests/gui_v2/test_command_bar_v2.py` (new)
>   - `tests/gui_v2/test_run_button_queue_mode_toggle.py` (updates only)
>   - `docs/StableNew_Roadmap_v2.0.md`, `docs/Known_Bugs_And_Issues_Summary.md`, and `docs/ROLLING_SUMMARY.md` for factual updates.
> - Keep `StableNewGUI.run_button` working exactly as before from the tests' point of view, even though its underlying widget now lives on `PipelineCommandBarV2`.
> - Do not loosen existing assertions in GUI tests; only adjust imports and widget lookups as needed.
>
> TDD sequence:
> 1. Create/extend the GUI tests listed in §6 so they fail on the current code.
> 2. Implement the new command bar widget, pipeline panel integration, and wiring.
> 3. Run the test commands in §6 and ensure they pass (aside from known skips/XFAILs).
> 4. Update the docs and rolling summary as described in §5.6 and §7.
>
> After you’re done, reply with:
> - A brief summary of changes.
> - The exact test commands you ran.
> - The full pytest results for the commands in §6.
