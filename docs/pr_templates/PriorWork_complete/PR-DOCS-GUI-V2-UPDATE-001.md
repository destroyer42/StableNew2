# PR-DOCS-GUI-V2-UPDATE-001.md
**Title:** Documentation – GUI V2 Three-Tab Redesign (Prompt / Pipeline / Learning)

**Author:** ChatGPT (for Rob / StableNewV2)  
**Date:** 2025-11-25  
**Branch Target:** `docs-gui-v2-alignment`  

---

## 1. Purpose

Align all core documentation with the new **three-tab GUI V2 architecture**:

- **Prompt tab** → Authoring workspace (prompt packs, matrix syntax, LoRA/embedding placement).  
- **Pipeline tab** → Execution workspace (stages, randomizer execution, runtime LoRA strength & activation, queue/batch).  
- **Learning tab** → Experiment workspace (parameter sweeps, experiment plans, rating UI, learning records).  

This PR updates the main architecture, program plan, phase docs, active modules listing, and Codex usage SOP to reflect the new mental model and responsibilities.

---

## 2. Scope

This PR changes **documentation only**. No code changes are expected, but code references and examples in the docs must remain accurate against the current repo snapshot.

Docs in scope:

1. `docs/ARCHITECTURE_v2_COMBINED.md`  
2. `docs/StableNew_GUI_V2_Program_Plan-11-24-2025.md`  
3. `docs/ACTIVE_MODULES.md`  
4. `docs/StableNew_Phase2_GUI_Layout_Theming_and_Wiring(24NOV).md`  
5. `docs/StableNew_Phase3_Roadmap_Features_and_Learning_System(24NOV).md`  
6. `docs/StableNew_Phase4_Testing_Docs_and_Packaging(NOV24).md`  
7. `docs/CODEX_PR_USAGE_SOP.md` (or current canonical path for Codex SOP)  

If any of these live in a different folder (e.g. `docs/codex_context/`), Codex must use the actual paths but preserve the **intent** described here.

---

## 3. Changes by Document (High-Level)

### 3.1 `ARCHITECTURE_v2_COMBINED.md`

- Add a new **“GUI V2 Overview”** section explaining the three-tab layout and responsibilities: Prompt / Pipeline / Learning.  
- Document the **Hybrid LoRA/Embedding Model**:
  - Prompt tab: placement & syntax.  
  - Pipeline tab: strength & activation.  
  - Learning tab: parameter sweeps using runtime values.  
- Update architecture diagrams and data-flow descriptions to show:
  - `PromptWorkspaceState` → `PipelineState` → `LearningState`.  
  - Learning runs as decorated pipeline runs (no separate executor).  
- Clarify stage-card architecture under the Pipeline tab and how it consumes prompt metadata.

### 3.2 `StableNew_GUI_V2_Program_Plan-11-24-2025.md`

- Update milestones and roadmap items to explicitly reference:
  - **PR-GUI-V2-ADVANCED-PROMPT-TAB-001**  
  - **PR-GUI-V2-PIPELINE-TAB-002**  
  - **PR-GUI-V2-LEARNING-TAB-003**  
- Add a subsection titled **“Three-Tab UX Contract”** summarizing the single-source-of-truth model:
  - Prompt = text & structure.  
  - Pipeline = execution & runtime.  
  - Learning = experiments & ratings.  
- Remove or adjust any legacy references to a monolithic “Advanced GUI” screen without tabs.

### 3.3 `ACTIVE_MODULES.md`

- Add entries for new/renamed GUI modules, for example:
  - `PromptWorkspaceView`, `PromptWorkspaceState`, `PromptWorkspaceController`.  
  - `PipelineWorkspaceView`, `PipelineControllerV2`, `StageCardsPanel`, `PipelineConfigPanel`, `PreviewPanelV2`.  
  - `LearningTabFrame`, `ExperimentDesignPanel`, `LearningPlanTable`, `LearningReviewPanel`, `LearningController`, `LearningState`.  
- Mark outdated GUI V1 modules as legacy / deprecated where appropriate.  
- Ensure module descriptions reference the correct tab (Prompt/Pipeline/Learning) and responsibility.

### 3.4 `StableNew_Phase2_GUI_Layout_Theming_and_Wiring(24NOV).md`

- Update the layout diagrams and textual descriptions to show:
  - A **top-level Notebook/tab control** with 3 tabs.  
  - Per-tab three-column layouts where applicable (especially Prompt and Pipeline).  
  - The shared bottom `StatusBarV2` that is visible across all tabs.  
- Clarify that per-stage cards live exclusively under the Pipeline tab, not scattered across other views.  
- Refer explicitly to the Prompt workspace as the **canonical prompt pack editor**.

### 3.5 `StableNew_Phase3_Roadmap_Features_and_Learning_System(24NOV).md`

- Map Learning features to the new **Learning tab** UI:
  - Experiment design.  
  - LearningPlan / LearningExecution GUI integration.  
  - Rating flows tied to LearningRecordWriter.  
- Remove or update any language that implies learning is a “hidden mode” of the pipeline; it is now a **first-class tab** built on top of the pipeline.

### 3.6 `StableNew_Phase4_Testing_Docs_and_Packaging(NOV24).md`

- Add explicit GUI V2 test cases for:
  - Prompt tab: LoRA/embedding detection, matrix syntax authoring, prompt pack persistence.  
  - Pipeline tab: stage toggles, randomizer modes, run summary accuracy, LoRA strength/toggle behavior.  
  - Learning tab: plan building, plan execution, rating persistence, and correct association of ratings with configs.  
- Outline a **journey test** that exercises all three tabs in a realistic workflow:

  1. Author prompt pack with LoRA placements and matrix syntax in Prompt tab.  
  2. Configure a three-stage pipeline + randomization + LoRAs in Pipeline tab.  
  3. Design a CFG or LoRA-strength sweep in Learning tab, run the plan, and rate resulting images.  
  4. Verify learning records are correctly written.

### 3.7 `CODEX_PR_USAGE_SOP.md`

- Add a section **“GUI V2 Multi-PR Patterns”** detailing how Codex should implement:
  - Feature work split across Prompt, Pipeline, and Learning PRs.  
  - Respect for each tab’s boundaries and sources of truth.  
- Add guidance for Codex on:
  - Where to wire new GUI components in `MainWindowV2`.  
  - How to touch `ARCHITECTURE_v2_COMBINED.md` and `ACTIVE_MODULES.md` whenever new modules or major GUI structures are introduced.  

---

## 4. Implementation Steps (For Codex)

1. **Update `ARCHITECTURE_v2_COMBINED.md`:**
   - Add sections and diagrams for the three-tab GUI V2 model.  
   - Document state flows between Prompt, Pipeline, and Learning.  

2. **Update GUI Program Plan:**
   - Insert the three PR IDs and align milestones with them.  
   - Update UI/UX rationale to the tabbed model and hybrid LoRA approach.  

3. **Refresh `ACTIVE_MODULES.md`:**
   - Add new GUI modules and states.  
   - Mark legacy GUI V1 components as deprecated if they are no longer used.  

4. **Align Phase 2–4 docs:**
   - Phase 2 → Layout and wiring reflect the three-tab design.  
   - Phase 3 → Learning feature roadmap explicitly uses Learning tab.  
   - Phase 4 → Testing scenarios cover all three tabs and end-to-end workflow.  

5. **Update Codex SOP:**
   - Document the expected multi-PR implementation pattern for GUI work.  
   - Encode rules about LoRA/Embedding responsibilities across tabs.  

---

## 5. Definition of Done

- All listed docs compile a **consistent story** of the GUI V2 design.  
- There are **no remaining references** to a single-screen monolithic GUI for V2.  
- LoRA/Embedding behavior and ownership is described identically across all docs.  
- The three main domains (Prompt, Pipeline, Learning) are clearly named and consistently used.  
- Codex SOP gives clear instructions on how to work within this model for future PRs.
