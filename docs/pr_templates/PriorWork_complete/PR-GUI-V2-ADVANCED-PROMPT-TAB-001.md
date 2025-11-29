# PR-GUI-V2-ADVANCED-PROMPT-TAB-001.md
**Title:** GUI V2 – Advanced Prompt Editor Tab (LoRA/Embedding Hybrid Model)

**Author:** ChatGPT (for Rob / StableNewV2)
**Date:** 2025-11-25
**Branch Target:** `gui-v2-layout-and-wiring`
**Related Docs:**
- `ARCHITECTURE_v2_COMBINED.md`
- `StableNew_GUI_V2_Program_Plan-11-24-2025.md`
- `StableNew_Phase2_GUI_Layout_Theming_and_Wiring(24NOV).md`
- `ACTIVE_MODULES.md`

---

## 1. Problem / Motivation

The current GUI V2 wiring exposes pieces of the Advanced Prompt Editor, Randomizer, and Pipeline, but:

- There is no **single, coherent Prompt Workspace tab** that acts as the canonical place to author prompt packs.
- LoRAs and embeddings are currently treated inconsistently as either pure text or pure config, which makes it hard to:
  - Maintain **correct order and placement** in the prompt text.
  - Expose **strength sliders and on/off toggles** in a pipeline-friendly way.
  - Reuse this structure later for the **Learning tab** (LoRA strength sweeps, etc.).
- Randomization and matrix tools are partially defined at the pipeline level, but we also need a clean **prompt-centric authoring experience** for matrix syntax and prompt packs.

This PR establishes a **dedicated “Prompt” tab** (Tab 1) and the corresponding components needed to make prompt authoring first-class, while conforming to the hybrid LoRA/Embedding model we agreed on:

- Prompt tab is **authoritative** for **textual placement and ordering** of LoRAs/embeddings.
- Pipeline tab will later be authoritative for **strength and activation** (runtime behavior).

This PR is **GUI-only & wiring-first**: no changes to backend pipeline execution behavior beyond what’s needed to surface prompt metadata cleanly.

---

## 2. Objectives & Non‑Objectives

### 2.1 Objectives

1. **Create a dedicated “Prompt” tab** in the GUI V2 main window:
   - Tab order: **Prompt | Pipeline | Learning** (Learning tab stub may exist but is not implemented here).
2. Implement an **Advanced Prompt Editor layout** with a clear three-column structure:
   - **Left:** Prompt pack browser & prompt-level tools.
   - **Center:** Prompt pack editor (5 lines × 10 prompts as the default visual model).
   - **Right:** Prompt→Pipeline preview (how prompts map into the pipeline).
3. Implement **LoRA/Embedding hybrid integration (Prompt side)**:
   - Prompt tab controls **where** LoRAs/embeddings appear in the text.
   - Provides dropdowns/menus for valid LoRA/embedding names (from model inventory).
   - Ensures prompt text encoding uses consistent syntax that **can be parsed** and surfaced later to the pipeline tab.
4. Implement **prompt-centric randomization authoring tools**:
   - Matrix syntax helpers (e.g. `{style|lighting}`) with inline preview.
   - Per-line randomization preview to ensure users see “what this matrix would expand into.”
   - No changes to pipeline-level randomizer execution behavior in this PR.
5. Provide **clear interfaces / data structures** that downstream PRs (Pipeline tab and Learning tab) can consume:
   - A unified `PromptWorkspaceState` / `PromptPackModel` that exposes:
     - Raw prompt text (by line / slot).
     - Structured metadata: detected LoRAs, embeddings, and matrix sections.
     - Versioning / dirty state for save/load.

### 2.2 Non‑Objectives

- Implementing the **Pipeline tab UI** or its randomizer execution logic (will be a separate PR).
- Implementing the **Learning tab UI** or learning experiment flows (separate PR).
- Changing the **core backend pipeline execution** beyond minimal metadata plumbing.
- Complex prompt-pack file format migrations; we will continue using existing formats but add **non-breaking metadata** where feasible.
- Implementing image previews or running jobs from the Prompt tab; all execution remains a Pipeline-tab concern.

---

## 3. High‑Level Design

### 3.1 New “Prompt” Tab in Main Window

- Add a top-level tab control (if not already wired) to the V2 GUI main window:
  - `PromptTab`
  - `PipelineTab`
  - `LearningTab` (stub or placeholder view)

- The **Prompt tab** will host:
  - `PromptWorkspaceView` (the main three-column layout).
  - Shared status bar remains **global** (same as other tabs).

**Skeleton (conceptual):**
- `MainWindowV2`
  - `ttk.Notebook` or equivalent container
    - `PromptTabFrame` → `PromptWorkspaceView`
    - `PipelineTabFrame` → (future PR)
    - `LearningTabFrame` → (future PR stub)
  - `StatusBarV2` (shared across tabs)

### 3.2 Prompt Workspace Layout

Inside `PromptWorkspaceView`:

- **Left Panel – Prompt Packs & Tools**
  - Prompt pack file list / tree (e.g., `.txt`, `.json`, `.promptpack`).
  - Controls:
    - New pack, Save, Save As, Delete.
    - Import/export (exact options minimal for this PR).
  - Optional filters/tags for packs (basic for now, extensible later).

- **Center Panel – Prompt Pack Editor**
  - A grid of prompt “slots,” default visual pattern:
    - 10 prompts per pack (rows).
    - Each prompt = up to 5 lines (multi-line text widget).
  - Each prompt slot includes:
    - Line text editor.
    - Indicators for matrix sections.
    - Right-click or inline menu for inserting LoRAs/embeddings at cursor.

- **Right Panel – Prompt→Pipeline Preview**
  - Read-only summary of how the currently selected prompt will flow into the pipeline:
    - Which line will become “Base Prompt” for txt2img.
    - How/if negative prompts are derived.
    - How prompts map to stages (this PR: read-only, derived from existing mapping rules).
  - A small “Current Run Summary” stub (non-binding) just to show:
    - Selected pack.
    - Selected prompt index.
  - This panel must not execute or queue jobs; it’s a **preview-only** view.

### 3.3 Hybrid LoRA / Embedding Model (Prompt Side Responsibilities)

The Prompt tab is **authoritative for placement** of LoRAs and embeddings in text.

#### 3.3.1 Insertion & Editing

- When user clicks “Insert LoRA” (context menu or toolbar):
  - Show a dropdown/tree of **available LoRA names** from the currently selected model profile.
  - Insert a canonical syntax token at the cursor, e.g.:
    - LoRA: `{lora:<name>:{strength_hint}}`
    - Embedding: `<embedding:<name>>`
  - `strength_hint` defaults from pipeline profile or a local per-LoRA setting; actual runtime strength is governed later by the Pipeline tab.

- When editing prompt text, these tokens must remain valid even when copied/pasted between lines.

#### 3.3.2 Detection & Metadata

- Implement a **LoRA/embedding scanner** for prompt text in the Prompt tab:
  - Parses for known patterns (e.g., `{lora:name:weight}`, `<embedding:name>`).
  - Emits a `PromptMetadata` object containing:
    - `detected_loras: List[LoraReference]`
    - `detected_embeddings: List[EmbeddingReference]`
    - Mapping from token location → prompt line/slot.
- This metadata is:
  - Displayed in a small “LoRAs in this pack” sidebar or quick summary in the right panel.
  - Exposed to the Pipeline tab via shared state (see §3.5).

> **Key rule:** The Prompt tab does **not** decide whether a LoRA is active or what final strength will be used. It only controls the **presence and placement** of the LoRA tokens in the prompt text.

### 3.4 Prompt-Centric Randomization Authoring

We need prompt-centric tools for authoring matrix/randomization syntax without taking over pipeline-run behavior.

#### 3.4.1 Matrix Syntax Helpers

- Add an “Insert Matrix…” tool that:
  - Lets user define a set of options for a segment of text:
    - Example: `{style|lighting|camera angle}`.
  - Inserts the generated `{…|…|…}` syntax at the cursor.
- The Prompt tab can show:
  - Inline validation highlighting (e.g., mismatched braces).
  - A **preview popover** listing a sample of expanded variants for the current line.

#### 3.4.2 Non-authoritative on Execution

- The Prompt tab never decides:
  - How many variants will actually be run.
  - Whether matrix expansion is enabled globally.
- It only ensures the **syntax is correct** and previewable, leaving the execution semantics to the Pipeline tab’s Randomizer panel (future PR).

### 3.5 Shared Prompt State & APIs for Other Tabs

Introduce (or update) a state object to mediate between GUI layers and backend:

- `PromptWorkspaceState` (or similar), which includes:
  - Current pack metadata (name, path, dirty flag).
  - Prompt slot data (per-prompt text, multi-line structure).
  - Parsed metadata (`PromptMetadata`):
    - LoRAs, embeddings, matrix segments with positions.
- This state is exposed via a **controller/service object**, e.g.:
  - `PromptWorkspaceController` or `PromptService`.
- Other tabs (Pipeline and Learning) will consume **read-only** views of this state for:
  - Knowing which LoRAs/embeddings exist in the prompt.
  - Mapping prompt slots to pipeline stages.
  - Running learning experiments with stable prompt baselines.

---

## 4. File-Level Plan

> **Note:** Exact paths/names may vary slightly depending on the current repo snapshot. Codex should adapt names if the actual files/types differ, but keep the conceptual split identical.

### 4.1 New / Updated GUI Components

**Likely updates:**
- `src/gui/main_window_v2.py` (or equivalent):
  - Add `Prompt` tab to the Notebook/tab control.
  - Wire `PromptWorkspaceView` into the Prompt tab.
- `src/gui/views/prompt_workspace_view.py` (new):
  - Implements the three-column layout:
    - Left: packs & tools
    - Center: editor grid
    - Right: preview

**Potential supporting modules:**
- `src/gui/models/prompt_pack_model.py` (new or extended):
  - `PromptPackModel`, `PromptSlot`, `PromptMetadata` types.
- `src/gui/controllers/prompt_workspace_controller.py` (new):
  - Encapsulates loading/saving packs and scanning for LoRAs/embeddings.
- `src/gui/utils/lora_embedding_parser.py` (new):
  - Regex and parsing utilities for `{lora:...}` and `<embedding:...>` tokens.
- `src/gui/widgets/prompt_editor_grid.py` (new):
  - Custom widget for the 10×5 prompt slot layout.
- `src/gui/widgets/matrix_helper_widget.py` (new):
  - Dialog/widget for defining matrix options and previewing expansions.

### 4.2 Integration Points

- Update any existing Advanced Prompt Editor components to either:
  - Be embedded inside `PromptWorkspaceView`.
  - Or be refactored into reusable widgets used by the new view.

- Ensure `StatusBarV2` and global logging remain unaffected:
  - No per-tab duplication of status elements.

- Hook `PromptWorkspaceState` into existing state management layer (`AppState`, `GuiState`, or equivalent) so the Pipeline and Learning tabs can access it later.

### 4.3 Non-goal Changes (Explicitly Avoid)

- Do **not** remove or break existing simple prompt input fields used today.
  - Instead, clearly wire them to consume data from `PromptWorkspaceState` when appropriate (or leave them as-is until Pipeline tab PR refactors them).
- Do **not** introduce execution buttons in the Prompt tab.

---

## 5. Implementation Steps (For Codex)

1. **Add the Prompt tab:**
   - Locate the main V2 GUI window class.
   - Introduce a tab control if not present; add a `Prompt` tab as the first tab.
   - Create `PromptWorkspaceView` and mount it in the Prompt tab.

2. **Implement `PromptWorkspaceView`:**
   - Use a layout manager that supports three resizable columns.
   - Left: pack list with basic CRUD buttons.
   - Center: prompt editor grid with multi-line text widgets.
   - Right: read-only pipeline preview (stubbed summary for now).

3. **Introduce `PromptPackModel` + `PromptMetadata`:**
   - Define data classes for:
     - Prompt pack (name, path, prompts).
     - Prompt slots (id/index, text).
     - Metadata (detected LoRAs, embeddings, matrix segments).
   - Implement save/load methods consistent with existing prompt storage formats.

4. **Implement LoRA/embedding parsing utility:**
   - Create regex-based parser for `{lora:name:weight}` and `<embedding:name>`.
   - Ensure it is robust to minor variations (spaces, decimals).
   - Produce structured objects (e.g., `LoraReference`, `EmbeddingReference`).

5. **Wire metadata scanning into the Prompt workspace:**
   - Whenever a prompt changes, mark pack as dirty and rescan for metadata.
   - Update:
     - A small “LoRAs in pack” summary view.
     - The right-hand preview panel to list detected LoRAs/embeddings.

6. **Add matrix helper widget:**
   - Provide a dialog:
     - User enters a list of options (one per line).
     - Widget generates `{opt1|opt2|opt3}` syntax.
     - Show a small preview of expanded variants (e.g., first N).

7. **Add insertion menus for LoRAs/embeddings:**
   - Context menu or toolbar button in the center editor:
     - “Insert LoRA…” → show dropdown of available LoRAs (for now, mock static list or minimal integration with model inventory; full integration can be extended later).
     - “Insert Embedding…” → same pattern.
   - Insert canonical token at cursor.

8. **Expose `PromptWorkspaceState` for other tabs:**
   - Make the workspace controller/state object accessible via the main controller or shared state registry.
   - Add minimal public API (e.g., `get_current_prompt_pack()`, `get_prompt_metadata()`).

---

## 6. Testing & Validation

### 6.1 Manual Testing

- Verify that:
  - You can create a new prompt pack, add/edit prompts, and save/reload.
  - LoRA tokens inserted via UI appear in prompt text in the correct place.
  - Embedding tokens inserted via UI behave similarly.
  - LoRAs/embeddings are correctly detected and listed in the metadata summary.
  - Matrix helper inserts valid `{…|…|…}` syntax and preview behaves as expected.
  - Switching tabs does not lose prompt changes (unless intentionally unsaved and user discards).

- Confirm that **no actual pipeline execution behavior changes**:
  - Existing runs still work as before.
  - Prompt text used for runs is either unchanged or clearly mapped to the new Prompt workspace output.

### 6.2 Automated Tests (If feasible in this PR)

- Unit tests for `lora_embedding_parser`:
  - Correctly detects single/multiple LoRAs.
  - Handles missing weights gracefully.
  - Detects embeddings with expected syntax.
- Unit tests for `PromptPackModel` save/load behavior.
- Optional GUI tests / smoke tests for PromptWorkspaceView instantiation.

---

## 7. Risks & Mitigations

- **Risk:** Prompt workspace introduces state divergence from existing simple prompt fields.
  - **Mitigation:** For this PR, keep existing simple prompt inputs as-is, and only wire integration paths where low-risk. Future Pipeline tab PR will consolidate.
- **Risk:** LoRA/embedding parsing might mis-detect or break exotic user syntax.
  - **Mitigation:** Keep parser conservative, treat unknown patterns as plain text, and ensure no hard failures on parse errors.
- **Risk:** Too much logic in the Prompt tab could tempt coders to put runtime controls there.
  - **Mitigation:** Clearly document (in code comments) that Prompt tab is **non-authoritative** for LoRA activation and strength; pipeline tab will own that.

---

## 8. Definition of Done

- A **Prompt** tab exists and is selectable in the main GUI V2 window.
- Prompt tab shows a three-column **Prompt Workspace** with:
  - Pack list & basic CRUD on the left.
  - Prompt pack editor grid in the center.
  - Read-only preview + LoRA/embedding metadata on the right.
- LoRAs and embeddings:
  - Can be inserted via UI into prompt text at specific positions.
  - Are parsed and surfaced in metadata.
- Matrix helper exists and can insert `{…|…|…}` segments with a basic preview.
- No regression of existing pipeline execution behavior.
- `PromptWorkspaceState` and metadata are accessible to other tabs via a shared API for use in follow-on PRs.
