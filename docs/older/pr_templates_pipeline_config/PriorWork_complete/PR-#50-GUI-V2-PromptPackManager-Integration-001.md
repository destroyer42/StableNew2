Timestamp: 2025-11-22 20:43 (UTC-06:00)
PR Id: PR-#50-GUI-V2-PromptPackManager-Integration-001
Spec Path: docs/pr_templates/PR-#50-GUI-V2-PromptPackManager-Integration-001.md

---

# PR-#50-GUI-V2-PromptPackManager-Integration-001

## 1. Intent & Scope

This PR brings the **Prompt Pack** experience into the **GUI V2** world in a controlled, architecture-compliant way.

Today, prompt packs exist and are wired into the legacy GUI surface, but the new V2 layout (AppLayoutV2 + PipelinePanelV2 + AdvancedPromptEditorV2) is where we want serious users to live. To get there, we need prompt pack browsing and apply behavior that:

- Lives cleanly inside the **GUI V2 layer**.
- Talks only to the controller/adapter, never directly to pipeline or filesystem.
- Plays nicely with the new **Advanced Prompt Editor V2** and the main prompt field in the pipeline panel.
- Is covered by GUI tests so it doesn’t regress as we build out more UX.

**Scope** for this PR:

- Provide a V2-compatible **PromptPackManagerV2** widget or panel.
- Surface **pack list + basic pack metadata** from the existing prompt pack subsystem (no new pack file format).
- Allow “Apply pack to prompt” behavior that:
  - Loads the pack’s base prompt into the main prompt field.
  - Optionally opens or syncs with AdvancedPromptEditorV2.
- Keep all pipeline/controller semantics unchanged — this is a pure UX/GUI integration.

This is GUI-only and must not change prompt pack loading rules, pipeline behavior, or learning/queue semantics.

---

## 2. Current Context & Dependencies

Assume the repo baseline is **StableNew-main-11-22-2025-1815.zip** plus the following PRs applied:

- PR-#47 / #47B: PipelineConfigAssembler enforcement in PipelineController.
- PR-#48: PipelineCommandBarV2 and command bar wiring for Run/Stop/Queue.
- PR-#49: AdvancedPromptEditorV2 integrated with PipelinePanelV2.

Relevant pieces already in the tree (names approximate, based on prior context):

- Prompt packs:
  - `packs/` folder with JSON/TOML/YAML prompt packs.
  - A loader/registry in `src/utils/file_io.py` or `src/prompt/prompt_pack_*` modules.
  - Legacy GUI panel: `src/gui/prompt_pack_panel.py` (or similar).
- GUI V2 layout:
  - `src/gui/app_layout_v2.py`
  - `src/gui/main_window.py`
  - `src/gui/pipeline_panel_v2.py`
  - `src/gui/sidebar_panel_v2.py`
  - `src/gui/advanced_prompt_editor.py`
  - `src/gui/pipeline_command_bar_v2.py`
- Controller / adapter:
  - `src/controller/pipeline_controller.py`
  - `src/controller/pipeline_config_assembler.py`
  - `src/gui/pipeline_adapter_v2.py` (or equivalent V2 adapter)

We will **reuse** the existing prompt pack loading logic and file formats. This PR does not modify how packs are discovered or parsed; it only creates a V2 front-end and integrates it with the V2 prompt state.

---

## 3. High-Level Goals

1. **Prompt pack browsing in GUI V2**
   - Add a V2 widget/panel that lists available prompt packs and shows basic metadata:
     - Pack name
     - Description (if present)
     - Maybe the number of prompts/variants

2. **Apply pack → update V2 prompt state**
   - When the user selects a pack and clicks “Apply”:
     - The pack’s base prompt is loaded into the main prompt field used by V2.
     - If AdvancedPromptEditorV2 is open, it should either sync automatically or be easy to refresh from current prompt.

3. **Respect existing pack semantics**
   - Do not change how packs are read or interpreted.
   - Do not introduce a new pack schema.

4. **Tests for prompt-pack-to-prompt round trip**
   - GUI V2 tests should confirm that:
     - Packs are listed.
     - Applying a pack updates the pipeline panel’s prompt field.
     - (Optionally) The advanced editor can be synced with the updated prompt.

---

## 4. Non-goals

This PR will **not**:

- Introduce a new prompt pack file format or schema.
- Implement pack editing or pack creation in the UI.
- Implement randomization logic or advanced “mix packs” behavior (that stays with the randomizer layer).
- Alter learning or queue behavior.
- Alter pipeline or controller behavior beyond prompt field population in GUI.

Those can be follow-on PRs once V2 basics are solid.

---

## 5. Allowed / Forbidden Files

### Allowed

You MAY modify or create:

- GUI V2 prompt pack widgets:
  - `src/gui/prompt_pack_panel_v2.py` (new)
  - `src/gui/sidebar_panel_v2.py` (integration/placement)
  - `src/gui/app_layout_v2.py` (wiring only)
  - `src/gui/main_window.py` (wiring only)

- V2 adapter hooks (if needed for prompt-setting helpers only, no new logic):
  - `src/gui/pipeline_adapter_v2.py` (small additions for “set prompt” convenience only)

- Prompt pack loading integration (read-only plumbing only):
  - If needed, a small utility in `src/gui/prompt_pack_adapter_v2.py` (new) that wraps existing pack loader functions.

- GUI V2 tests:
  - `tests/gui_v2/test_prompt_pack_panel_v2.py` (new)
  - `tests/gui_v2/test_prompt_pack_to_prompt_roundtrip_v2.py` (new)

- Docs:
  - `docs/StableNew_Roadmap_v2.0.md` (GUI V2 section)
  - `docs/Known_Bugs_And_Issues_Summary.md` (update any “prompt pack UX” items)
  - `docs/codex_context/ROLLING_SUMMARY.md` (append PR-#50 entry)

### Forbidden

You MUST NOT modify:

- `src/controller/*` (no behavior changes)
- `src/pipeline/*`
- `src/queue/*`
- `src/learning*`
- `src/randomizer*`
- `src/api/*`
- Prompt pack discovery/parse logic (beyond trivial import refactors)

If you truly need a change outside the allowed set, it should be a separate PR, not this one.

---

## 6. Implementation Plan (Step-by-Step)

### 6.1. New PromptPackPanelV2

- Create `src/gui/prompt_pack_panel_v2.py`:
  - Likely a `ttk.Frame`-based widget: `class PromptPackPanelV2(ttk.Frame): ...`
  - Responsibilities:
    - Display a list of packs (Listbox, Treeview, or similar).
    - Show basic metadata (name, description, maybe a small preview snippet).
    - Have an “Apply to prompt” button that triggers a callback supplied from the parent.

- The panel itself should not read from disk directly; it should be given a list of simple DTOs (e.g., `PromptPackSummary` objects) from a small adapter/helper that calls existing loaders.

### 6.2. Prompt pack adapter (GUI-friendly)

- Option A: Embed adapter logic in the V2 panel or sidebar.
- Option B (preferred): Add a small V2 adapter module:
  - `src/gui/prompt_pack_adapter_v2.py`  
  that:
    - Calls existing prompt pack loader(s).
    - Produces a list of `PromptPackSummary` objects for the V2 panel.
    - Provides an API to fetch the base prompt for a selected pack.

- No new file format. Use the existing loader and structures as-is.

### 6.3. Integrate panel into Sidebar / AppLayoutV2

- In `src/gui/sidebar_panel_v2.py` and `src/gui/app_layout_v2.py`:
  - Decide where PromptPackPanelV2 lives:
    - Likely in a sidebar region alongside other “secondary tools” like randomizer controls, job history, etc.
  - Provide:
    - A callback for “Apply pack” that:
      - Updates the main pipeline prompt entry in `PipelinePanelV2`.
      - Optionally triggers a sync with `AdvancedPromptEditorV2` (e.g., via a “Reload from prompt field” call).

- Ensure the integration:
  - Keeps GUI threading rules (no pipeline calls).
  - Only manipulates GUI state and calls controller-approved setters.

### 6.4. Sync with AdvancedPromptEditorV2 (non-invasive)

- If the advanced editor has a simple method like `load_prompt(text: str)`, call it when a pack is applied and the editor is open.
- If not, do not deeply refactor; instead, ensure:
  - The source of truth is the pipeline panel’s prompt field.
  - The advanced editor can be manually reopened to pick up the new prompt (we can improve this in a follow-on PR).

### 6.5. Tests

- `tests/gui_v2/test_prompt_pack_panel_v2.py`:
  - Test that the panel:
    - Renders a list of mock packs.
    - Calls the provided “apply” callback with the right pack selection.

- `tests/gui_v2/test_prompt_pack_to_prompt_roundtrip_v2.py`:
  - Use a minimal Tk root and a small harness that wires:
    - PromptPackPanelV2
    - PipelinePanelV2
  - Simulate:
    - “Select pack” → “Apply” → assert that pipeline panel’s prompt entry now has the pack’s base prompt.

Tests should avoid real disk reads; use fake pack summaries or small adapter fakes.

---

## 7. Required Tests & Commands

At minimum, run:

1. New GUI V2 tests:
   - `pytest tests/gui_v2/test_prompt_pack_panel_v2.py -v`
   - `pytest tests/gui_v2/test_prompt_pack_to_prompt_roundtrip_v2.py -v`

2. Full GUI V2 suite:
   - `pytest tests/gui_v2 -v`

3. Safety & controller sanity:
   - `pytest tests/safety -v`
   - `pytest tests/controller -v`

4. (Recommended) Full suite:
   - `pytest -v`

Tk skips are expected where already present; do not introduce new skips.

---

## 8. Acceptance Criteria

This PR is complete when:

1. GUI V2 has a PromptPackPanelV2 that lists packs and can apply a selected pack to the main prompt field.
2. Applying a pack updates the prompt used by the V2 pipeline (via the same GUI fields as before).
3. The advanced editor remains functional and compatible (even if not auto-synced).
4. No controller/pipeline behavior changes are detectable by tests.
5. Tests listed above all pass (modulo pre-existing skips).
6. Docs and rolling summary are updated.

---

## 9. Rollback Plan

If this PR causes regressions:

1. Revert:
   - `src/gui/prompt_pack_panel_v2.py`
   - `src/gui/prompt_pack_adapter_v2.py` (if created)
   - Edits in `sidebar_panel_v2.py`, `app_layout_v2.py`, and `main_window.py`
   - New tests under `tests/gui_v2`
   - PR-#50 doc entries

2. Re-run:
   - `pytest tests/gui_v2 -v`
   - `pytest -v`

to confirm we are back to the pre-PR-50 baseline.

---

## 10. Rolling Summary Update (docs/codex_context/ROLLING_SUMMARY.md)

Append:

> **PR-#50-GUI-V2-PromptPackManager-Integration-001** – Added a PromptPackPanelV2 and supporting adapter to surface existing prompt packs in the GUI V2 sidebar. Users can browse packs and apply a selected pack’s base prompt directly into the V2 pipeline prompt field, without changing pack formats or pipeline behavior. New GUI V2 tests cover prompt pack listing and “apply pack to prompt” roundtrips.


