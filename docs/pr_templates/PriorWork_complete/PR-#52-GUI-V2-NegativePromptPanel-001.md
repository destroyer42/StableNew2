Timestamp: 2025-11-22 20:59 (UTC-06:00)
PR Id: PR-#52-GUI-V2-NegativePromptPanel-001
Spec Path: docs/pr_templates/PR-#52-GUI-V2-NegativePromptPanel-001.md

# PR-#52-GUI-V2-NegativePromptPanel-001: Dedicated Negative Prompt Panel V2 + Assembler Path

## 1. Title

**PR-#52-GUI-V2-NegativePromptPanel-001: Dedicated Negative Prompt Panel V2 + Assembler Path**

---

## 2. Summary

This PR introduces a **Negative Prompt Panel V2** that:

- Provides a dedicated, multi-line UI surface for **negative prompts**.
- Integrates cleanly into the **GUI V2 sidebar/layout**.
- Drives a single source of truth for negative prompt text that flows through:
  - `GuiOverrides` → `PipelineConfigAssembler` → `PipelineConfig` → WebUI API.

Key outcomes:

- Users have a clear and discoverable place to edit negative prompts.
- The negative prompt path is **explicit and test-backed**, not a side-effect of legacy GUI.
- Negative prompt handling becomes consistent across GUI V2, learning, and queue modes.

Assumed baseline: repo state after PR-#47B, PR-#48, PR-#49, and PR-#51 (Core Config Panel) on top of `StableNew-main-11-22-2025-1815.zip`.

---

## 3. Problem Statement

### 3.1 Symptoms & Gaps

Currently:

- Negative prompts may be:
  - Embedded in a small inline field.
  - Hidden behind legacy GUI or prompt pack handling.
- GUI V2 lacks a **dedicated negative prompt editing surface**.
- Because of this:
  - Users can’t easily see or tune negative prompts alongside the main prompt.
  - Pipelines may run with default or stale negative prompts, causing quality issues.

From an architecture standpoint:

- Negative prompt is a **first-class input** to the text-to-image pipeline.
- But the GUI V2 treatment lags behind the main prompt and other core config controls.

### 3.2 Design Constraints (Architecture_v2)

- GUI must remain:
  - Pure UI.
  - No direct pipeline or API logic.
- Negative prompt must be:
  - Represented in `GuiOverrides`.
  - Mapped by `PipelineConfigAssembler` into `PipelineConfig`.
  - Testable and deterministic.

Therefore, this PR must:

- Implement the Negative Prompt Panel fully within GUI V2.
- Wire it into the existing `GuiOverrides`/assembler path.
- Avoid any direct pipeline or WebUI calls from GUI.

---

## 4. Goals

1. Provide a **NegativePromptPanelV2** widget:
   - Multi-line text editing for negative prompt.
   - Clear (reset) button.
   - Optional “Apply from selection” hook if integrated with prompt packs or templates later.
2. Integrate the panel into:
   - `SidebarPanelV2` (or a similar host).
   - `AppLayoutV2`, so it appears in the V2 layout.
3. Ensure negative prompt flows via:
   - GUI → `GuiOverrides` → `PipelineConfigAssembler` → `PipelineConfig`.
4. Add tests to:
   - Verify panel behavior.
   - Verify assembler mapping of negative prompt.
5. Update docs to record this as the canonical negative prompt entry point in GUI V2.

---

## 5. Non-goals

This PR will **not**:

- Add sophisticated formatting, templating, or randomization for negative prompts.
- Change how negative prompts are used inside the pipeline stages or WebUI API.
- Implement per-stage negative prompts.
- Implement negative prompt presets or history.

Those belong in future UX and learning/randomization-focused PRs.

---

## 6. Allowed Files

Codex may modify **only** the following files for this PR:

**GUI V2 – Negative Prompt Panel + Layout**

- `src/gui/negative_prompt_panel_v2.py`  *(new)*
- `src/gui/sidebar_panel_v2.py`
- `src/gui/app_layout_v2.py`
- `src/gui/main_window.py` *(wiring only)*

**Adapter / Assembler Integration**

- `src/gui/pipeline_adapter_v2.py`   *(ensure `GuiOverrides` includes negative_prompt)*
- `src/controller/pipeline_config_assembler.py` *(map negative_prompt into `PipelineConfig`)*

**Config Defaults (if necessary)**

- `src/config/app_config.py` *(optional: default negative prompt string)*

**Tests**

- `tests/gui_v2/test_negative_prompt_panel_v2.py` *(new)*
- `tests/controller/test_pipeline_config_assembler_negative_prompt.py` *(new)*

**Docs**

- `docs/PIPELINE_RULES.md`
- `docs/ARCHITECTURE_v2_COMBINED.md`
- `docs/codex_context/ROLLING_SUMMARY.md`

---

## 7. Forbidden Files

Do **not** modify:

- `src/pipeline/*`
- `src/queue/*`
- `src/controller/job_history_service.py`
- `src/controller/job_execution_controller.py`
- `src/controller/cluster_controller.py`
- `src/cluster/*`
- `src/learning*`
- `src/randomizer*`
- `src/api/*`
- Legacy GUI panels, except for trivial import adjustments if unavoidable.

If a forbidden file appears to require changes, Codex must stop and surface that need as a separate PR.

---

## 8. Step-by-step Implementation

### 8.1. Implement NegativePromptPanelV2

Create `src/gui/negative_prompt_panel_v2.py`:

- `class NegativePromptPanelV2(ttk.Frame):`
  - Contains a `tk.Text` or `ttk`-compatible multi-line widget for the negative prompt.
  - Optional label and character count.
  - Buttons:
    - **Clear**: empties the text box.
    - (Optional) **Reset to default**: loads a default negative prompt from `app_config` if defined.

- Public methods:
  - `get_negative_prompt() -> str`
  - `set_negative_prompt(text: str) -> None`

No network or pipeline logic.

### 8.2. Integrate Panel into Sidebar/Layout

In `src/gui/sidebar_panel_v2.py`:

- Instantiate `NegativePromptPanelV2` as a dedicated section (e.g., “Negative Prompt”).

In `src/gui/app_layout_v2.py`:

- Ensure the sidebar (or layout region) that hosts the negative panel is created and arranged.
- Provide any necessary references so that `pipeline_adapter_v2` can fetch values (e.g., via a state manager or direct callback).

### 8.3. Extend GuiOverrides

In `src/gui/pipeline_adapter_v2.py`:

- Ensure `GuiOverrides` includes a `negative_prompt: str | None` field.
- When building `GuiOverrides`:
  - Read the current negative prompt from `NegativePromptPanelV2` (or fallback to legacy/inlined field if needed).

### 8.4. Map negative_prompt in PipelineConfigAssembler

In `src/controller/pipeline_config_assembler.py`:

- Ensure `build_from_gui_input` accepts `negative_prompt` from `GuiOverrides`.
- Set the corresponding field in `PipelineConfig` and/or downstream WebUI payload structures.

No change to how the pipeline uses negative prompt beyond ensuring the field is correctly populated.

### 8.5. Tests

1. `tests/gui_v2/test_negative_prompt_panel_v2.py`:

   - `test_negative_panel_set_and_get`:
     - Instantiate the panel.
     - Set a negative prompt string.
     - Assert `get_negative_prompt()` matches.

   - `test_negative_panel_clear_button`:
     - Type into the widget.
     - Trigger Clear.
     - Assert text is empty.

2. `tests/controller/test_pipeline_config_assembler_negative_prompt.py`:

   - `test_negative_prompt_roundtrip`:
     - Construct `GuiOverrides` with `negative_prompt="bad hands, low quality"`.
     - Call assembler.
     - Assert resulting `PipelineConfig` / WebUI payload includes this string.

---

## 9. Required Tests (Failing First)

Codex must run:

1. New tests:

   - `pytest tests/gui_v2/test_negative_prompt_panel_v2.py -v`
   - `pytest tests/controller/test_pipeline_config_assembler_negative_prompt.py -v`

2. Suites:

   - `pytest tests/gui_v2 -v`
   - `pytest tests/controller -v`

3. Regression (recommended):

   - `pytest -v`

Pre-existing Tk skips are OK; no new skips should be added.

---

## 10. Acceptance Criteria

This PR is complete when:

1. NegativePromptPanelV2 is present, integrated, and visible in GUI V2.
2. Editing the negative prompt via this panel:
   - Updates `GuiOverrides`.
   - Results in `PipelineConfig` containing the correct negative prompt.
3. All tests in §9 pass (modulo known skips).
4. No controller, pipeline, or queue behavior regressions are introduced.
5. Docs and rolling summary describe the new negative prompt path.

---

## 11. Rollback Plan

To revert:

1. Remove or revert:

   - `src/gui/negative_prompt_panel_v2.py`
   - Changes in `sidebar_panel_v2.py`, `app_layout_v2.py`, `main_window.py`
   - `pipeline_adapter_v2.py` additions related to `negative_prompt`
   - Assembler changes for negative prompt
   - New tests
   - PR-#52 doc entries

2. Re-run:

   - `pytest tests/gui_v2 -v`
   - `pytest tests/controller -v`
   - `pytest -v`

to confirm system behavior is back to pre-PR-#52 state.

---

## 12. Codex Execution Constraints

Codex must:

- Stay within the **Allowed Files** list.
- Treat existing tests as **immutable specifications** (do not weaken them).
- Avoid introducing GUI-to-pipeline or GUI-to-API coupling.
- Keep changes focused and minimal.

Before finishing, Codex must:

1. List all tests run.
2. Paste the outputs for:
   - `pytest tests/gui_v2/test_negative_prompt_panel_v2.py -v`
   - `pytest tests/controller/test_pipeline_config_assembler_negative_prompt.py -v`
   - `pytest tests/gui_v2 -v`
   - `pytest tests/controller -v`
   - `pytest -v` (if run).

---

## 13. Smoke Test Checklist

A human operator should:

1. Launch StableNew (GUI V2).
2. Locate the **Negative Prompt** area in the sidebar.
3. Type a distinctive negative prompt (e.g., `"bad anatomy, lowres"`).
4. Run the pipeline.
5. Confirm (via logs/manifest or API debug) that the negative prompt used matches the entered value.
6. Clear the negative prompt and run again, confirming the old text is not reused.

If all steps behave as expected and tests are green, PR-#52 is successful.

