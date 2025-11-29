# StableNewV2 GUI V2 – Three-Tab Redesign Summary

**Date:** 2025-11-25  
**Scope:** High-level summary of the new GUI V2 model and its impact on Prompt, Pipeline, and Learning.

---

## 1. Overview

The StableNewV2 GUI V2 is now organized into **three primary workspaces**, each with a clear domain and a single source of truth:

1. **Prompt tab** – Prompt authoring (prompt packs, matrix syntax, LoRA/embedding placement).  
2. **Pipeline tab** – Pipeline execution (stages, randomization execution, runtime LoRA strength & activation, queuing/batching).  
3. **Learning tab** – Experiment design and evaluation (parameter sweeps, rating, learning records).  

This replaces the earlier, more monolithic GUI concept and resolves long-standing ambiguity around where prompt, LoRA, and learning responsibilities live.
The legacy “Run” tab has been retired; Pipeline is the sole home for stage configuration and execution UX.

---

## 2. Prompt Tab – Authoring Workspace

### 2.1 Purpose

The Prompt tab is the **canonical place to author and manage prompts**. It focuses on structure, text, and intent, not on execution.

### 2.2 Key Responsibilities

- Manage prompt packs (load/save/delete).  
- Edit prompts in a structured grid (e.g., 10 prompts × 5 lines).  
- Insert and validate matrix syntax for text-based randomization.  
- Insert LoRA and embedding tokens at precise locations in the text using UI helpers.  
- Parse and expose metadata:
  - Detected LoRAs and embeddings.  
  - Matrix segments and structural hints.  

### 2.3 Source of Truth

The Prompt tab is authoritative for:

- **What the prompt text is.**  
- **Where** LoRA/embedding tokens appear.  
- The syntactic structure of matrix expressions.

It is **not** authoritative for:

- Whether a LoRA is active in a given run.  
- What final strength values are used at runtime.  
- How many prompt variants will actually be executed.

---

## 3. Pipeline Tab – Execution Workspace

### 3.1 Purpose

The Pipeline tab is the **center of execution**. If the user wants to know “What will happen when I hit Run?”, this tab provides the answer.

### 3.2 Key Responsibilities

- Present stage cards (txt2img, img2img/adetailer, upscale, etc.).  
- Allow stage toggling and expand/collapse behavior from the top Run bar.  
- Configure queue vs direct mode, batch size, and looping.  
- Configure randomizer modes and variant counts, consuming matrix metadata from the Prompt tab.  
- Provide runtime LoRA/embedding controls:
  - Strength sliders.  
  - On/off toggles for activation.  
- Show a Run summary indicating the number of jobs/images and which stages will run.  
- Show a preview of outputs and basic per-image metadata.  

### 3.3 Source of Truth

The Pipeline tab is authoritative for:

- **Execution behavior**: number of jobs, stages, and variants.  
- **Runtime LoRA/embedding strength and activation.**  
- **Queue and batch configuration.**  

It relies on the Prompt tab for text and LoRA placement, but it is the final arbiter of how that text is turned into actual runs.

---

## 4. Learning Tab – Experiment Workspace

### 4.1 Purpose

The Learning tab provides a **first-class experimental UX** over the existing Learning backend, letting the user run structured parameter sweeps and rate results.

### 4.2 Key Responsibilities

- Design experiments:
  - Baseline configuration (imported from Pipeline).  
  - Prompt selection (from Prompt workspace).  
  - Stage selection.  
  - Pick a **Variable Under Test** (e.g., CFG, steps, sampler, scheduler, LoRA strength, denoise strength, upscale factor).  
  - Specify values or ranges and images-per-value.  
- Build a Learning Plan and display it as a variant table.  
- Execute the plan by calling into the Pipeline executor with learning context.  
- Show per-variant and per-image results.  
- Provide rating controls and notes for each image.  
- Persist everything into LearningRecords using the existing JSONL writer.  

### 4.3 Source of Truth

The Learning tab is authoritative for:

- The definition of experiments (plans, variants, values).  
- Ratings and user feedback attached to generated images.  
- The association between a given config and its evaluation.  

Execution still flows through the Pipeline, maintaining a single execution path and consistent logs.

---

## 5. Hybrid LoRA / Embedding Model

To resolve confusion and avoid conflicting sources of truth, LoRAs and embeddings have **split responsibilities**:

- **Prompt tab:**  
  - Controls **placement** and **syntax** in the prompt text.  
  - Provides insertion tools and metadata parsing.  

- **Pipeline tab:**  
  - Controls **runtime strength** and **activation state** (on/off).  
  - Applies numeric values at execution time.  

- **Learning tab:**  
  - Varies the numeric **strength** (or other LoRA-related parameters) between runs as part of an experiment.  

This hybrid model ensures that text remains expressive and free-form, while numeric behavior remains centralized and predictable.

---

## 6. Data & State Flow

- `PromptWorkspaceState`  
  - Holds prompt packs, text, and parsed metadata (LoRAs, embeddings, matrices).  

- `PipelineState`  
  - Holds stage configurations, queue/batch settings, randomizer configuration, and runtime LoRA strengths/toggles.  
  - Consumes prompt text and metadata from `PromptWorkspaceState`.  

- `LearningState`  
  - Holds LearningExperiments, variants, and per-image references.  
  - Orchestrates LearningPlans via the pipeline.  
  - Writes LearningRecords with ratings and notes.  

Execution path for a learning run:

1. Define experiment in Learning tab.  
2. Build plan → constructs a set of parameterized pipeline runs.  
3. Run plan → Learning controller calls Pipeline executor with variant overrides.  
4. Pipeline completes jobs and emits completion events tagged with learning context.  
5. Learning controller updates plan status and LearningRecords; GUI exposes ratings.  

---

## 7. Why This Design?

- **Predictability:** Users always know where to look:
  - Text in Prompt tab.  
  - Execution behavior in Pipeline tab.  
  - Experiments in Learning tab.  

- **Extensibility:** New stages, new variables-under-test, and new learning strategies can be added without collapsing the mental model.

- **Backend Reuse:** Learning uses the same pipeline executor as normal runs, keeping the system testable and reducing divergence.

- **LoRA Clarity:** Avoids the common trap where LoRA behavior is half in text, half in config, and neither is clearly authoritative.  

---

## 8. Documentation & Next Steps

This summary is meant to be the **canonical narrative** referenced by:

- `ARCHITECTURE_v2_COMBINED.md`  
- `StableNew_GUI_V2_Program_Plan-11-24-2025.md`  
- `ACTIVE_MODULES.md`  
- Phase 2–4 docs (layout, features, testing).  
- `CODEX_PR_USAGE_SOP.md` (for multi-PR GUI workflows).  

The next step is to ensure all those docs align with this summary and that future PRs (code or docs) treat this model as the baseline.
