# GUI V2 Docs Alignment – File-Level Change Guide

**Date:** 2025-11-25  
**Context:** Aligning all documentation with the new three-tab GUI architecture (Prompt / Pipeline / Learning) and the hybrid LoRA/Embedding model.

This guide is intended as a **change checklist** for Codex or any human editor when updating the docs. It focuses on *what* needs to change, not the final prose.

---

## 1. `ARCHITECTURE_v2_COMBINED.md`

### 1.1 Add New Section: GUI V2 Overview

- Insert a new high-level section, e.g. `## GUI V2 Overview – Prompt, Pipeline, Learning`.  
- Bullet-point responsibilities:
  - Prompt tab: authoring, prompt packs, matrix syntax, LoRA/embedding placement.  
  - Pipeline tab: stages, randomizer execution, runtime LoRA strength/toggles, queue/batch.  
  - Learning tab: experiments, parameter sweeps, rating, and learning records.  

### 1.2 Document Hybrid LoRA/Embedding Model

- Add a subsection, e.g. `### Hybrid LoRA / Embedding Ownership`:
  - Prompt tab owns **where** tokens appear in text.  
  - Pipeline tab owns **if** a LoRA is active and with what **strength**.  
  - Learning tab varies numerical strengths as part of sweeps.  
- Ensure no other sections contradict this ownership.

### 1.3 Update Diagrams / Flows

- Any prior diagrams that show a “flat” or single-screen GUI need to be redrawn/refactored to include:  
  - `PromptWorkspaceState` → `PipelineState` → `LearningState`.  
  - Learning runs as decorated pipeline runs (identical execution path, extra context).  

### 1.4 Note on Stage Cards and Randomizer

- Explicitly describe Stage cards as **Pipeline tab** components.  
- Clarify that randomizer execution logic is owned by the Pipeline layer, not the Prompt tab.

---

## 2. `StableNew_GUI_V2_Program_Plan-11-24-2025.md`

### 2.1 Milestones

- For the GUI V2 section, add milestones that match the three PRs:
  - Prompt tab PR.  
  - Pipeline tab PR.  
  - Learning tab PR.  

### 2.2 UX Rationale

- Add a short subsection explaining why the GUI is split into three tabs instead of one:  
  - Avoids multiple sources of truth.  
  - Keeps “what will run” centralized.  
  - Enables clean learning UX without polluting normal runs.

### 2.3 Remove/Adjust Legacy Language

- Search for any text implying “one advanced GUI screen”.  
- Replace with references to the 3-tab layout and its responsibilities.

---

## 3. `ACTIVE_MODULES.md`

### 3.1 Add New Modules

- Under GUI/Views and GUI/Controllers, add items for (names approximate; adjust to actual code):  
  - `PromptWorkspaceView`, `PromptWorkspaceController`, `PromptWorkspaceState`.  
  - `PipelineWorkspaceView`, `PipelineControllerV2`, `StageCardsPanel`, `PipelineConfigPanel`, `PreviewPanelV2`.  
  - `LearningTabFrame`, `ExperimentDesignPanel`, `LearningPlanTable`, `LearningReviewPanel`, `LearningController`, `LearningState`.  

### 3.2 Mark Legacy Components

- Mark legacy V1 GUI components (if still present) as:  
  - “Legacy – see GUI V2 docs for current architecture.”

### 3.3 Cross-Reference

- For each major GUI module, add a one-line note linking back to the relevant doc sections (e.g., “See `ARCHITECTURE_v2_COMBINED.md – GUI V2 Overview`”).

---

## 4. `StableNew_Phase2_GUI_Layout_Theming_and_Wiring(24NOV).md`

### 4.1 Layout Updates

- Replace any single-screen layout references with:  
  - Top-level tabbed layout: Prompt / Pipeline / Learning.  
  - Per-tab three-column patterns (left / center / right) where used.  
- Make sure the bottom `StatusBarV2` is documented as **global**, not per-tab.

### 4.2 Wiring Notes

- Ensure wiring notes explicitly mention:  
  - Prompt tab wires to PromptWorkspaceState and model scanner for LoRAs/embeddings.  
  - Pipeline tab wires to PipelineState, Stage cards, Randomizer, and LoRA runtime controls.  
  - Learning tab wires to LearningState and LearningRecordWriter via the pipeline.

---

## 5. `StableNew_Phase3_Roadmap_Features_and_Learning_System(24NOV).md`

### 5.1 Map Features to Learning Tab

- For each learning roadmap item, add a note if it is:  
  - Implemented via the Learning GUI.  
  - Implemented purely backend-side.  
- Adjust language so “Learning” is not described as a hidden mode, but as a dedicated tab on top of the pipeline.

### 5.2 Variable-Under-Test Concept

- Introduce/update a concept section for “Variable Under Test” to match:  
  - CFG, Steps, Sampler, Scheduler, LoRA Strength, Denoise, Upscale Factor, etc.  
- Clarify that Learning experiments vary **only one primary parameter** per plan (for now).

---

## 6. `StableNew_Phase4_Testing_Docs_and_Packaging(NOV24).md`

### 6.1 Add GUI V2 Functional Test Cases

- Prompt tab tests:
  - Prompt pack CRUD.  
  - LoRA/embedding token insertion + detection.  
  - Matrix syntax validation & preview.  

- Pipeline tab tests:
  - Stage toggles & expand/collapse.  
  - Randomizer modes and job count correctness.  
  - LoRA strength / toggle behavior influencing outputs.  
  - Queue vs direct mode.  

- Learning tab tests:
  - Plan building for a numeric sweep.  
  - Running the plan and verifying counts.  
  - Rating images and confirming learning records are written.

### 6.2 Add End-to-End Journey Test

- One scripted scenario that walks through all three tabs in sequence and validates the entire loop from authoring → running → learning → records.

---

## 7. `CODEX_PR_USAGE_SOP.md`

### 7.1 Multi-PR GUI Pattern

- Add a section describing the **three-PR approach**:  
  - Prompt tab PR → authoring.  
  - Pipeline tab PR → execution.  
  - Learning tab PR → experiments.  

### 7.2 Edit Discipline

- Add explicit rules for Codex:  
  - When adding new GUI modules, also update `ARCHITECTURE_v2_COMBINED.md` and `ACTIVE_MODULES.md`.  
  - When touching LoRA/Embedding behavior, always re-affirm the hybrid model in code comments and avoid shifting responsibilities between tabs.  

---

## 8. General Notes

- Wherever docs talk about “randomization,” ensure:  
  - Prompt tab is described as **authoring** matrix syntax.  
  - Pipeline tab is described as **executing** randomization.  
- Ensure terminology is consistent:
  - “Prompt Workspace / Prompt tab” vs “Pipeline Workspace / Pipeline tab” vs “Learning tab / Experiment Designer”.  
