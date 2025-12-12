# PR-GUI-V2-LEARNING-TAB-003.md
**Title:** GUI V2 – Learning Tab (Experiment Designer, Rating UI, LoRA/Config Sweeps)

**Author:** ChatGPT (for Rob / StableNewV2)  
**Date:** 2025-11-25  
**Branch Target:** `gui-v2-layout-and-wiring`  
**Depends On:**  
- `PR-GUI-V2-ADVANCED-PROMPT-TAB-001` (Prompt workspace & metadata)  
- `PR-GUI-V2-PIPELINE-TAB-002` (Pipeline workspace & run/LoRA controls)  

**Related Docs:**  
- `ARCHITECTURE_v2_COMBINED.md`  
- `StableNew_GUI_V2_Program_Plan-11-24-2025.md`  
- `StableNew_Phase3_Roadmap_Features_and_Learning_System(24NOV).md`  
- `StableNew_Phase4_Testing_Docs_and_Packaging(NOV24).md`  
- `ACTIVE_MODULES.md`  

---

## 1. Problem / Motivation

The core Learning system (LearningPlan, LearningExecution, LearningRecord, JSONL writer, etc.) already exists at the backend/controller level, but the GUI does not yet provide:

- A dedicated **Learning workspace** to design and launch experiments.  
- A clean way to select a baseline pipeline configuration and vary exactly **one parameter** (or a controlled set) across runs.  
- A UX for **rating** resulting images and persisting those ratings as structured data for future recommendations.  
- A consistent way to reuse **prompt packs** and **LoRA/embedding metadata** from the Prompt & Pipeline tabs.  

Today, attempting to do “learning” looks exactly like normal pipeline runs: opaque sequences of jobs with no clear experimental framing, no explicit parameter sweep, and no dedicated rating flow. This PR aims to lift the existing backend capabilities into a **first-class Learning Tab** that:

- Treats experiments as **Learning Plans**.  
- Uses the existing pipeline to actually run those plans.  
- Captures structured outcomes (ratings + configs) into learning records.  

---

## 2. Objectives & Non-Objectives

### 2.1 Objectives

1. **Create a dedicated “Learning” tab** (Tab 3) in the GUI V2 main window:
   - Tab order remains: `Prompt | Pipeline | Learning`.  
   - Learning tab is focused on **experiment design, execution, and review**.  

2. Implement a **three-panel Learning layout**:
   - **Left:** Experiment design controls (baseline selection, variable-under-test, value range, number of images per value, target stage).  
   - **Center:** Plan view (table of variants/jobs, status per variant).  
   - **Right:** Rating panel & image viewer for reviewing results.  

3. Integrate tightly with **Prompt & Pipeline tabs**:
   - Use `PromptWorkspaceState` for prompt selection and LoRA/embedding placement.  
   - Use Pipeline tab’s stage and model configuration as the **baseline**.  
   - Ensure Learning runs are just **annotated pipeline runs** that feed into LearningRecordWriter.  

4. Implement **variable-under-test selection** (primary learning knob):
   - Examples:
     - CFG scale.  
     - Step count.  
     - Sampler type.  
     - Scheduler type.  
     - LoRA strength.  
     - Upscale factor or denoise strength (for later stages).  
   - Each experiment is defined as:
     - Baseline config + variable-under-test + list/range of values + images per value.  

5. Implement **rating UI**:
   - For each produced image in a learning run, allow the user to:
     - Assign a rating (e.g., 1–5 stars, or discrete “best” flags).  
     - Optionally add a short free-text note.  
   - Persist ratings into existing LearningRecord/JSONL infrastructure.  

6. Surface **Learning Plan & run state** clearly:
   - Show which plan is active, pending, or completed.  
   - Show high-level summary (e.g., “Testing CFG 3→13 step 2, 4 images each, txt2img stage”).  

### 2.2 Non-Objectives

- Implementing the full model for **automated recommendations** or “smart defaults” based on the learning data (that is a follow-on feature).  
- Adding new backend learning record formats; we will primarily adapt to the existing JSONL LearningRecordWriter.  
- Replacing the Pipeline tab execution system; Learning tab should orchestrate **via** the pipeline, not around it.  
- Implementing an advanced multi-parameter design-of-experiments system; this PR targets **single-variable sweeps** and simple combos as a first step.  

---

## 3. High-Level Design

### 3.1 Learning Tab Structure

`LearningTabFrame` inside `MainWindowV2` hosts:

- **Top:** Learning Plan header (current plan name, description, summary).  
- **Middle:** Three-column layout:  
  - Left: Experiment Design Panel.  
  - Center: Plan View (Variant Grid).  
  - Right: Rating & Review Panel.  
- **Bottom:** Global `StatusBarV2` + logging remains shared with other tabs.  

Conceptually:

- `LearningTabFrame`  
  - `LearningHeader` (plan title + summary)  
  - `LearningBodyFrame`  
    - `ExperimentDesignPanel` (left)  
    - `LearningPlanTable` (center)  
    - `LearningReviewPanel` (right)  
  - `StatusBarV2` (global)  

### 3.2 Experiment Design Panel (Left)

This panel is where the user defines “what exactly are we testing?”

Key elements:

- **Baseline Config Selector**:  
  - Option to “Use current Pipeline tab config as baseline”.  
  - Or load from a saved pipeline preset (if applicable).  

- **Prompt Selection**:  
  - Choose from current `PromptWorkspaceState`:  
    - Active prompt pack.  
    - Specific prompt index.  
  - Show a short preview of the chosen prompt.  

- **Stage Selection**:  
  - Dropdown or radio to pick which stage the learning applies to:  
    - txt2img, img2img/adetailer, upscale, etc.  
  - (Important: For img2img/upscale learning, the same base image must be used).  

- **Variable Under Test**:  
  - Dropdown listing supported parameters:  
    - e.g., “CFG Scale”, “Steps”, “Sampler”, “Scheduler”, “LoRA Strength: \<Name\>”, “Denoise Strength”, “Upscale Factor”.  

- **Value Specification**:  
  - For numeric variables (CFG, steps, strength):
    - Either a list of explicit values or a min/max + step field.  
  - For categorical variables (sampler, scheduler):
    - Multi-select list of options.  
  - For LoRA strength:
    - Same numeric handling as other numeric variables, but tied to a specific LoRA detected in `PromptMetadata`.  

- **Images per Value**:  
  - Number of images to generate for each parameter value.  

- **Controls**:  
  - “Build Plan” → populate the center Plan table but **do not run yet**.  
  - “Run Plan” → hand the plan to the pipeline/learning executor.  
  - “Save Plan” / “Load Plan” (optional, at least stubbed for future).  

### 3.3 Learning Plan Table (Center)

This is a tabular view of the experiment design and execution state. Each row corresponds to a **variant** (parameter setting) or, optionally, to a **single job/image** depending on granularity.

Columns (variant-level view):

- Param value (e.g., `CFG = 5`).  
- Stage.  
- Prompt identifier (pack + index).  
- # images planned.  
- # images completed.  
- Status: Pending / Running / Completed / Failed.  

Optional expansion:

- Clicking a row could show a nested grid of images produced for that variant (although the main image view lives in the right panel).  

The plan table should:

- Update as jobs are enqueued and completed.  
- Allow selection of a row, which drives what is shown in the Rating panel.  

### 3.4 Rating & Review Panel (Right)

This panel is for evaluating results and capturing learning data.

Core elements:

- **Image Viewer**:  
  - Shows the selected image (from the selected variant).  
  - Navigation controls to move across images and variants (e.g., next/previous).  

- **Config Snapshot**:  
  - Show key configs for the displayed image:  
    - Variable value (e.g., CFG).  
    - Fixed baseline parameters.  
    - Stage, prompt, seed, LoRA list.  

- **Rating Controls**:  
  - A 1–5 star rating or a discrete “quality” scale.  
  - Possibly a “Best of this variant group” toggle (for tournament-style selection).  
  - Optional notes textbox.  

- **Persistence**:  
  - On rating change, write/update a `LearningRecord` entry using the existing LearningRecordWriter.  
  - Ensure that each record includes:
    - Experiment/plan ID.  
    - Variant param value(s).  
    - Full config snapshot used for that image.  
    - Rating + notes.  

### 3.5 How Learning Uses the Pipeline

The Learning tab **never bypasses** the Pipeline tab’s execution engine. Instead:

- When the user clicks “Run Plan”:  
  - Learning controller builds a set of jobs (a LearningPlan) describing each variant and associated runs.  
  - For each variant and each image to be generated:  
    - It invokes the same pipeline execution path used by the Pipeline tab.  
    - It passes a “learning context” object that includes:
      - Experiment/plan ID.  
      - Variant value(s).  
      - Variable-under-test name.  
  - As the pipeline completes each job, it emits events that the Learning tab subscribes to, enabling:  
    - Updating plan table counts.  
    - Storing initial un-rated LearningRecords.  

This ensures:

- No duplication of pipeline logic.  
- Learning is just a decorated form of normal pipeline execution.  

### 3.6 Data Flow & State

**States involved:**

- `PromptWorkspaceState`:  
  - Provides prompt text, LoRA placement, and basic metadata.  

- `PipelineState`:  
  - Provides baseline model config, stage config, LoRA strengths and activation, queue mode, etc.  

- `LearningState` (new):  
  - Current experiment definition (baseline, variable, values, images-per-value).  
  - Current plan and per-variant status.  
  - Ratings and mapping from images to LearningRecord IDs.  

Data flow outline:

1. User configures experiment in `ExperimentDesignPanel`.  
2. User clicks “Build Plan”; Learning controller populates `LearningState.plan`.  
3. User clicks “Run Plan”; Learning controller iterates over `plan` and calls pipeline executor with per-variant overrides on top of baseline.  
4. Pipeline completion events, annotated with learning context, feed back into Learning controller:  
   - Learning controller updates `plan` status counts.  
   - Learning controller creates LearningRecords with default rating (e.g., unrated).  
5. Rating UI writes updates back to LearningRecord store.  

---

## 4. File-Level Plan

### 4.1 New GUI Components

- `src/gui/views/learning_tab_frame.py` (new):
  - Top-level layout for Learning tab.  

- `src/gui/views/experiment_design_panel.py` (new):
  - Left panel for experiment configuration and plan building.  

- `src/gui/views/learning_plan_table.py` (new):
  - Center panel for variant plan grid.  

- `src/gui/views/learning_review_panel.py` (new):
  - Right panel for image viewer and rating controls.  

### 4.2 Controllers / State

- `src/gui/controllers/learning_controller.py` (new):
  - Owns LearningState.  
  - Builds LearningPlans from ExperimentDesignPanel input + Prompt/Pipeline states.  
  - Submits jobs via pipeline executor with learning context.  
  - Consumes completion events and updates plan status + LearningRecords.  

- `src/gui/state/learning_state.py` (new):
  - Data structures for:
    - `LearningExperiment` (baseline, variable, values, per-value image count).  
    - `LearningVariant` (specific parameter setting, status, counts).  
    - `LearningImageRef` (link between generated image, variant, and LearningRecord ID).  

### 4.3 Backend Integration

- `src/learning/learning_plan.py` and `src/learning/learning_execution.py` (existing, adjust as needed):
  - Ensure GUl-level LearningPlan structures can be converted into backend plans, or reuse these directly if alignment is already good.  

- `src/learning/learning_record_writer.py` (existing):
  - Confirm API usage from Learning controller.  
  - Ensure rating updates are supported (either appending new records or updating previous ones depending on how records are modeled).  

- `src/pipeline/execution_controller.py` (or equivalent):
  - Accept a “learning context” optional parameter so learning runs can be identified.  

---

## 5. Implementation Steps (For Codex)

1. **Add LearningTabFrame to MainWindowV2:**
   - Ensure Notebook/tab control has a `Learning` tab.  
   - Mount `LearningTabFrame` into it.  

2. **Implement LearningTabFrame layout:**
   - Header at top with simple labels for:
     - Plan name/ID.  
     - Variable-under-test.  
     - Stage and prompt summary.  
   - Middle row with three panels (experiment design, plan table, review panel).  

3. **Implement ExperimentDesignPanel:**
   - Form fields for:
     - Baseline config selection (“Use current Pipeline config”).  
     - Prompt selection (from PromptWorkspaceState).  
     - Stage selection.  
     - Variable-under-test selection.  
     - Value specification controls (numeric vs categorical).  
     - Images-per-value.  
   - Buttons:
     - “Build Plan” → call into Learning controller.  
     - “Run Plan” → start execution.  

4. **Implement LearningState & Learning controller:**
   - Define data classes for experiments, variants, and image refs.  
   - On “Build Plan”, create a structured plan with variants.  
   - On “Run Plan”, for each variant and required image:
     - Call the pipeline executor with:
       - Baseline config from PipelineState.  
       - Overridden parameter(s) for this variant.  
       - Learning context (experiment ID, variant ID, variable name, value).  

5. **Implement LearningPlanTable:**
   - Table that binds to `LearningState.plan.variants`.  
   - Columns for variable value, stage, prompt ID, image counts, status.  
   - Row selection event triggers update of LearningReviewPanel.  

6. **Implement LearningReviewPanel:**
   - Image view bound to the currently selected variant and image index.  
   - Controls:
     - Next / Previous image.  
     - Next / Previous variant (optional).  
   - Rating controls:
     - 1–5 stars or discrete rating.  
     - Notes textbox.  
   - Persist ratings via Learning controller into LearningRecordWriter.  

7. **Wire up pipeline completion events:**
   - Modify pipeline execution event system (if needed) to include learning context.  
   - In Learning controller, subscribe to these events:
     - Update variant completed image count in LearningState.  
     - Create or update LearningRecord entries with initial unrated status.  

8. **Ensure global StatusBarV2 and logs work with Learning runs:**
   - Learning runs should be indistinguishable from normal runs at the status/log layer, except that the Learning tab shows them grouped into experiments.  

---

## 6. Testing & Validation

### 6.1 Manual Testing

- **Experiment design & plan building:**
  - Create a CFG sweep (e.g., CFG = 3, 7, 11, 15) on txt2img with 2 images per CFG.  
  - Confirm the plan table shows 4 variants with 2 images each planned.  

- **Plan execution:**
  - Run the plan and verify that:  
    - Jobs are submitted correctly.  
    - Plan table updates status and completed counts.  
    - Preview and Rating panels receive the images.  

- **Rating behavior:**
  - Assign different ratings to images.  
  - Confirm they are persisted in the learning records (via file inspection or logs).  

- **img2img/upscale learning:**
  - Create a denoise or upscale factor sweep on a fixed base image.  
  - Confirm the same base image is used, with only the target parameter changing.  

### 6.2 Automated Tests (If feasible)

- Unit tests for Learning controller plan building given various experiment definitions.  
- Tests asserting that given a baseline PipelineState + variable-under-test, the overrides for each variant are constructed correctly.  
- Tests that LearningRecordWriter is invoked with proper metadata when ratings are applied.  

---

## 7. Risks & Mitigations

- **Risk:** Learning UX may feel disconnected from the main pipeline.  
  - **Mitigation:** Ensure baseline config always comes from the Pipeline tab and that users can see that linkage clearly in the header.  

- **Risk:** Rating updates and LearningRecords could become inconsistent if multiple runs reuse the same experiment ID.  
  - **Mitigation:** Use unique experiment IDs per plan build or per run; encode versioning in records.  

- **Risk:** Complexity creep (many knobs) could make Learning daunting.  
  - **Mitigation:** Start with single-variable sweeps and a small set of supported parameters, extend later as needed.  

---

## 8. Definition of Done

- Learning tab exists and is selectable in the main GUI V2 window.  
- Experiment Design Panel allows definition of baseline config, prompt, stage, variable-under-test, value ranges, and images-per-value.  
- LearningPlanTable shows a clear, variant-level plan with statuses updating during execution.  
- LearningReviewPanel enables viewing outputs and rating them, with ratings persisted into the learning records.  
- Learning runs are implemented as decorated pipeline runs; no hidden or duplicate execution paths.  
- No regression of existing prompt or pipeline behavior, and Learning runs do not interfere with normal non-learning runs.  
