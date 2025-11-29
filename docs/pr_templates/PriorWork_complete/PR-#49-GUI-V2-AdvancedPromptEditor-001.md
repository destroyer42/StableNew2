Timestamp: 2025-11-22 19:44 (UTC-06:00)
PR Id: PR-#49-GUI-V2-AdvancedPromptEditor-001
Spec Path: docs/pr_templates/PR-#49-GUI-V2-AdvancedPromptEditor-001.md

---

# PR-#49-GUI-V2-AdvancedPromptEditor-001

## 1. Intent & Scope

This PR adds an **Advanced Prompt Editor V2** experience to the StableNew GUI, integrated into the existing GUI V2 layout, without changing pipeline semantics or controller behavior.

Goals:

- Provide a dedicated **advanced prompt editor** widget that supports:
  - Editing the main prompt in a larger, focused text area.
  - (Optionally) editing a separate negative prompt field, if present in the model.
  - Basic UX niceties like clear/apply buttons and character/line count display.
- Wire the editor into the existing GUI V2 prompt state so that:
  - Updates in the advanced editor reflect in the main pipeline panel prompt field.
  - Changes in the main prompt field can be loaded into the advanced editor.
- Keep the pipeline/run behavior identical: the same prompt string is sent to the controller/pipeline as before.
- Add regression tests to ensure the editor integrates cleanly with GUI V2, without introducing controller or pipeline coupling.

This PR is **GUI-only** and must not alter the pipeline, controller contracts, or queue behavior. It prepares the UX for future features (prompt presets, templating, learning notes), but does not implement those yet.

---

## 2. Current Context & Dependencies

Assume the repo baseline is the post-PR-47/48 snapshot (StableNew-main-11-22-2025-1815.zip + PR-47 + PR-48 applied), with:

- **Architecture V2** and **GUI V2** as the authoritative source of truth for layout and layering.
- `StableNewGUI` delegates layout to `AppLayoutV2`:
  - `src/gui/app_layout_v2.py`
  - `src/gui/main_window.py`
- V2 panels are already present:
  - `src/gui/pipeline_panel_v2.py`
  - `src/gui/randomizer_panel_v2.py`
  - `src/gui/sidebar_panel_v2.py`
  - `src/gui/preview_panel_v2.py`
  - `src/gui/status_bar_v2.py`
  - `src/gui/job_history_panel_v2.py`
  - `src/gui/pipeline_command_bar_v2.py` (from PR-48)
- A baseline prompt entry already exists in the pipeline panel (or equivalent), and is connected to the controller via the GUI V2 pipeline adapter.
- `PipelineConfigAssembler` and the V2 pipeline adapter already handle extracting the prompt field(s) and sending them to the controller/pipeline.

This PR must **not** change any of the above wiring except where explicitly required to connect the advanced editor to the existing prompt state.

---

## 3. High-Level Goals

1. **Advanced Prompt Editor Widget**
   - Introduce a `AdvancedPromptEditorV2` widget (or reuse/upgrade `advanced_prompt_editor.py` if already present) that:
     - Uses a multi-line text widget for the prompt.
     - Optionally uses a second multi-line text widget for the negative prompt (if the current UI has that concept).
     - Has Apply / Cancel (or Close) / Clear controls.
     - Displays a simple character or line count status.

2. **Non-invasive Integration with GUI V2 Layout**
   - Expose the editor from `AppLayoutV2` as an overlay, dialog, or sidebar section, without restructuring the entire layout.
   - Provide a clear entry-point control, such as:
     - A button near the main prompt field: “Open Advanced Editor”.
   - Ensure the editor opens with the current prompt contents preloaded.

3. **Two-way Prompt Syncing**
   - When the editor is opened, it **loads** the current prompt (and negative prompt, if applicable) from the pipeline panel.
   - When “Apply” is clicked in the advanced editor, it **pushes** its contents back into the pipeline panel’s prompt controls.
   - Cancel/Close should not modify the existing prompt fields.

4. **No Behavior Changes to the Pipeline**
   - After this PR, a pipeline run with a given prompt must behave exactly the same as before.
   - The advanced editor is only a UX layer over the same underlying prompt field(s).

---

## 4. Allowed / Forbidden Files

You MAY edit or create:

- GUI V2 prompt editor & integration:
  - `src/gui/advanced_prompt_editor.py` (if present; otherwise create it)
  - `src/gui/pipeline_panel_v2.py`
  - `src/gui/sidebar_panel_v2.py` (if used as a host for the editor toggle/entry point)
  - `src/gui/app_layout_v2.py`
  - `src/gui/main_window.py` (wiring only, no controller logic)

- GUI V2 tests:
  - `tests/gui_v2/test_advanced_prompt_editor_v2.py` (new)
  - `tests/gui_v2/test_pipeline_prompt_integration_v2.py` (new or extend from an existing test file)
  - Any small adjustments to existing GUI V2 tests to account for new widgets, without loosening assertions.

- Docs (small factual updates only):
  - `docs/StableNew_Roadmap_v2.0.md` (GUI V2 section)
  - `docs/Known_Bugs_And_Issues_Summary.md` (if there are known prompt-editing pain points to mark as partially addressed)
  - `docs/codex_context/ROLLING_SUMMARY.md` (append PR-#49 entry)

You MUST NOT:

- Edit `src/controller/*` modules for logic changes (no new methods, no signature changes).
- Edit `src/pipeline/*` modules.
- Edit `src/queue/*`, `src/learning*`, or `src/randomizer*` modules.
- Introduce any new tight coupling from GUI → pipeline or GUI → queue beyond the existing controller interfaces.
- Modify any WebUI API client behavior.

If a non-listed file must be changed to resolve an import or attribute error, keep the change minimal and document it explicitly.

---

## 5. Implementation Plan (Step-by-Step)

### 5.1. Implement `AdvancedPromptEditorV2` Widget

File: `src/gui/advanced_prompt_editor.py`

If the file exists already, upgrade it to fit V2; otherwise create it.

- Implement a class such as:

  ```python
  class AdvancedPromptEditorV2(ttk.Frame):
      def __init__(self, parent, *, initial_prompt: str = "", initial_negative_prompt: str | None = None, on_apply: Callable[[str, str | None], None] | None = None, on_cancel: Callable[[], None] | None = None):
          ...
  ```

- Requirements:
  - Contains a multi-line text widget for the main prompt (`self.prompt_text`).
  - Optionally contains a multi-line text widget for the negative prompt if the rest of the GUI supports it (`self.negative_prompt_text`).
  - Provides buttons:
    - Apply: calls `on_apply(prompt, negative_prompt)` if provided.
    - Cancel/Close: calls `on_cancel()` if provided.
    - Clear: clears the main prompt (and negative prompt if present).
  - A small label or status area that shows character or line count; this does not need to be fancy.

### 5.2. Integrate Editor into GUI V2 Layout

Files:

- `src/gui/pipeline_panel_v2.py`
- `src/gui/app_layout_v2.py`
- `src/gui/main_window.py`

- Add an “Open Advanced Editor” control near the main prompt input in `PipelinePanelV2` or via a button in the sidebar panel.
- Choose a hosting strategy:
  - Simple approach: create the editor in a new `ttk.Toplevel` window that is owned by the root.
  - Alternate approach: embed it into a dedicated region in the sidebar or under the prompt field, shown/hidden as needed.
- Wire `on_apply` callback so that it:
  - Writes the updated prompt/negative prompt back into the main prompt widgets in `PipelinePanelV2`.
- Ensure that:
  - Opening the editor loads current values from the pipeline panel.
  - Cancel/close does not change the prompt fields.

### 5.3. Keep Controller and Pipeline Behavior Unchanged

- Confirm that the code path that reads the prompt when constructing `GuiOverrides` (and ultimately the `PipelineConfig`) still reads from the same pipeline panel entry widgets as before.
- Do not change any controller method signatures or pipeline calls.
- The advanced editor is a pure UX layer that reads/writes the same underlying prompt fields used by the existing adapter.

### 5.4. Tests (TDD-first where feasible)

Create or extend:

1. `tests/gui_v2/test_advanced_prompt_editor_v2.py` (new):
   - `test_editor_applies_prompt_back_to_pipeline_panel`:
     - Create a minimal Tk root.
     - Instantiate `AdvancedPromptEditorV2` with an `on_apply` callback hooked to a dummy target variable.
     - Simulate user text changes, call Apply, and assert that the callback receives updated prompt text.
   - `test_editor_cancel_does_not_apply_changes`:
     - Ensure that Cancel leaves the target text unchanged.

2. `tests/gui_v2/test_pipeline_prompt_integration_v2.py` (new or extended):
   - `test_opening_editor_prefills_from_pipeline_panel`:
     - Instantiate a minimal `PipelinePanelV2` or equivalent test harness.
     - Set the pipeline panel’s prompt entry.
     - Open the advanced editor via the entry point button.
     - Assert that the editor’s text widget is initialized with the same prompt.
   - `test_applying_in_editor_updates_pipeline_panel_prompt`:
     - Change text in the editor, click Apply, and assert that the main prompt entry in the pipeline panel updates accordingly.

Run these tests and confirm they initially fail before implementing the full wiring, then implement until they pass.

### 5.5. Docs & Rolling Summary

- `docs/StableNew_Roadmap_v2.0.md`:
  - Add a bullet under GUI V2/UX about the advanced prompt editor.
- `docs/Known_Bugs_And_Issues_Summary.md`:
  - If there was a known issue about cramped prompt input, reference this as partially addressed.
- `docs/codex_context/ROLLING_SUMMARY.md`:
  - Append a PR-49 entry (see §8).

---

## 6. Required Tests & Commands

After implementation, you MUST run at least:

1. Focused GUI V2 tests:
   - `pytest tests/gui_v2/test_advanced_prompt_editor_v2.py -v`
   - `pytest tests/gui_v2/test_pipeline_prompt_integration_v2.py -v`
2. GUI V2 suite:
   - `pytest tests/gui_v2 -v`
3. Safety and controller sanity (to ensure nothing else broke):
   - `pytest tests/safety -v`
   - `pytest tests/controller -v`
4. Full suite (if runtime is acceptable):
   - `pytest -v`

Expected known outcomes:

- GUI V2 suite may still have pre-existing Tk skips depending on environment.
- No new skips should be introduced.
- No behavior changes in controller or pipeline tests should appear; they should remain green.

If tests fail, keep fixes within the allowed files and the boundaries of this PR.

---

## 7. Acceptance Criteria

This PR is complete when:

1. The advanced prompt editor exists, is integrated into GUI V2, and can be opened from the main prompt area.
2. Opening the editor pre-fills with the current prompt (and negative prompt, if applicable).
3. Applying in the editor updates the main prompt field(s); cancel does not.
4. No changes to pipeline/controller behavior are detectable by the test suite.
5. All tests in §6 pass (modulo pre-existing skips).
6. Docs and rolling summary entries have been updated.

---

## 8. Rollback Plan

If this PR causes regressions or UX issues:

1. Restore previous versions of:
   - `src/gui/advanced_prompt_editor.py`
   - `src/gui/pipeline_panel_v2.py`
   - `src/gui/app_layout_v2.py`
   - `src/gui/main_window.py`
   - Any newly added tests under `tests/gui_v2`.
2. Re-run `pytest tests/gui_v2 -v` and `pytest -v` to ensure behavior is back to the pre-PR-49 baseline.
3. Remove or revert the PR-49 entries from docs and rolling summary if necessary.

Because this PR is GUI-only and does not touch controller or pipeline logic, rollback is limited to a small set of GUI and test files.

---

## 9. Codex Execution Constraints

When implementing this PR, Codex must:

- Operate strictly within the **Allowed** files list.
- Keep changes **small and focused** on the advanced editor and its integration.
- Not introduce new controller or pipeline dependencies into GUI.
- Maintain or strengthen tests (never weaken assertions).

Before finishing, Codex must:

1. List the tests it ran.
2. Paste the full output of the key pytest runs from §6.
3. Confirm that no non-GUI modules’ behavior changed.

---

## 10. Rolling Summary Update (for `docs/codex_context/ROLLING_SUMMARY.md`)

Append the following under the appropriate date section:

- **PR-#49-GUI-V2-AdvancedPromptEditor-001** – Added an AdvancedPromptEditorV2 widget and integrated it with the GUI V2 pipeline panel so users can edit prompts in a larger, focused text area. Opening the editor pre-fills from the current prompt input; applying changes feeds updated text back into the main pipeline prompt field(s) without changing pipeline or controller behavior. New GUI V2 tests cover editor callback behavior and prompt roundtrip between the pipeline panel and the advanced editor.
