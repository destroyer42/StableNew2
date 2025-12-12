# PR-GUI-V2-PIPELINE-TAB-002.md
**Title:** GUI V2 – Pipeline Tab (Stage Cards, Randomizer Execution, LoRA/Embedding Runtime Controls)

**Author:** ChatGPT (for Rob / StableNewV2)  
**Date:** 2025-11-25  
**Branch Target:** `gui-v2-layout-and-wiring`  
**Depends On:** `PR-GUI-V2-ADVANCED-PROMPT-TAB-001` (Prompt tab baseline)  
**Related Docs:**  
- `ARCHITECTURE_v2_COMBINED.md`  
- `StableNew_GUI_V2_Program_Plan-11-24-2025.md`  
- `StableNew_Phase2_GUI_Layout_Theming_and_Wiring(24NOV).md`  
- `StableNew_Phase3_Roadmap_Features_and_Learning_System(24NOV).md`  
- `ACTIVE_MODULES.md`  

---

## 1. Problem / Motivation

The current GUI V2 has many of the right pieces (stage cards, preview, randomizer panel, status bar), but they are not yet organized into a **single, authoritative Pipeline workspace**. As a result:

- It is not obvious **what will actually happen if the user hits Run**.
- Stage cards exist but are not fully wired into a clean “Run this stage / Run selected stages / Run full pipeline” control bar.
- Randomizer execution behavior (how many jobs/variants will run) is not clearly surfaced.
- LoRA and embedding behavior at runtime is not tied cleanly to the hybrid model established in the Prompt tab PR:
  - Prompt tab governs placement in text.
  - Pipeline tab should govern **strength and activation** (runtime behavior).
- Queue modes (normal vs queued, batch runs, looping) are not centralized and discoverable.

This PR creates a dedicated **Pipeline tab** that is the **single source of truth** for:

- Which stages are active and how they are configured.  
- How many images / jobs / variants will run.  
- Which LoRAs/embeddings are active and at what strengths.  
- Whether we are running in direct mode vs queued mode, with what batch and looping controls.

Execution behavior (what happens when you press Run) “belongs” here.

---

## 2. Objectives & Non-Objectives

### 2.1 Objectives

1. **Create a dedicated “Pipeline” tab layout** in the V2 GUI main window:
   - Tab order: `Prompt | Pipeline | Learning` (Pipeline is the central “home” for execution).

2. Implement a **three-panel Pipeline layout**:
   - **Left:** Pipeline configuration and job controls (run mode, queue mode, looping, batch size, etc.).
   - **Center:** Stage cards (txt2img, img2img/adetailer, upscale, plus any future stages), with expand/collapse behavior controlled by stage toggles at the top.
   - **Right:** Live preview panel (images, basic metadata for the most recent or currently running stage).

3. Implement a **Run control bar** at the top of the Pipeline tab:
   - Buttons / toggles to select which stages will participate in the next run.
   - Modes:
     - Run current stage only.
     - Run from selected stage to end.
     - Run full pipeline (all enabled stages).
   - Clearly show the next-run summary (how many images/jobs, which stages).

4. Implement **Randomizer execution behavior** in the Pipeline tab:
   - Consume prompt metadata and matrix information from `PromptWorkspaceState` (Prompt tab).  
   - Decide how many prompt variants will be used in the next run, based on:
     - Randomization mode (off / sequential / rotate / random).  
     - Variant count / fan-out settings.  
   - Update the Run summary to show effective job count and expected image count.

5. Implement **LoRA/Embedding runtime controls** per the hybrid model:
   - Read detected LoRAs/embeddings from `PromptMetadata`.  
   - For each detected LoRA/embedding, show:
     - Strength slider (numeric control).  
     - Runtime active toggle (on/off).  
   - Ensure that changes here:
     - Affect pipeline execution.  
     - Can be reflected back to prompt-strength hints without breaking text.  

6. Centralize **queue mode vs direct mode** and job batching:
   - Allow user to switch between modes from the Pipeline tab:
     - Direct mode (run immediately).  
     - Queue mode (add to job queue).  
   - Support basic batch configuration (e.g., “N runs of this configuration”) with summary.  

7. Keep the **bottom global status strip** intact:
   - Status bar, progress bar, logging output, API connection state remain global and visible across all tabs, including Pipeline.

### 2.2 Non-Objectives

- Implementing the **Learning tab UI** or learning experiment designer (deferred to the third PR).  
- Changing the underlying **job queue engine** beyond what is needed to wire in the new controls.  
- Implementing complex new visualization modes in the preview panel beyond what currently exists (keep changes minimal and structural).  
- Adding new pipeline stages beyond what is already in V2, though we will design the layout to be extensible.  

---

## 3. High-Level Design

### 3.1 Pipeline Tab Structure

In `MainWindowV2` (or equivalent), the Pipeline tab hosts:

- **Top Region:** Run Control Bar and Stage Toggles.  
- **Middle Region:** Three-column layout:
  - Left: Pipeline Config Panel.  
  - Center: Stage Cards Panel.  
  - Right: Preview Panel.  
- **Bottom Region:** Shared `StatusBarV2` and log output (global, not per-tab).  

Conceptually:

- `PipelineTabFrame`
  - `RunControlBar` (top)  
  - `PipelineBodyFrame` (middle)
    - `PipelineConfigPanel` (left)
    - `StageCardsPanel` (center)
    - `PreviewPanelV2` (right)
  - `StatusBarV2` (global, already owned by main window)  

### 3.2 Run Control Bar & Stage Toggles

The top bar is where the user answers the question: **“What exactly am I about to run?”**

Controls:

- Per-stage toggle buttons, e.g.:  
  - `[txt2img] [img2img / adetailer] [upscale]`  
  - Toggling affects:
    - Whether that stage participates in the run.  
    - Whether the corresponding stage card is expanded/collapsed in the center panel.  

- Run mode selector:
  - `Run Selected Stage Only`  
  - `Run From Selected Stage Forward`  
  - `Run Full Pipeline`  

- Run buttons:
  - `Run Now` (direct)  
  - `Add to Queue` (queue mode)  

- Next-run summary label:
  - Shows key info derived from config and randomizer:
    - “Will run 3 stages, 40 total images, 10 jobs (queue mode)”  

### 3.3 Stage Cards Panel (Center)

This panel hosts the actual stage configuration editors. It should reuse as much of the existing V2 stage-card work as possible.

Per stage (txt2img, img2img/adetailer, upscale):

- Card contains:  
  - Stage enable/disable state (mirrors top toggle).  
  - Key per-stage controls (resolution, sampler, steps, etc.).  
  - If applicable, a local “use previous stage output as input” checkbox (for chains).  

Behavior:

- When stage toggle at top is off:
  - Card collapses to a minimal row (or is visually dimmed).  
  - Stage is excluded from Run summary and from pipeline execution.  

- When stage toggle at top is on:
  - Card expands and is fully editable.  

### 3.4 Pipeline Config Panel (Left)

This panel centralizes overall run behavior unrelated to any single stage:

Controls could include:

- **Run Mode:**  
  - Direct vs queued.  
  - If queue mode, whether to auto-start queue processing.

- **Batch / Looping Controls:**  
  - Number of runs / iterations (for the same config).  
  - Optional “loop until stopped” mode, if supported.  

- **Randomizer Execution Controls:**  
  - Randomization mode (off / sequential / rotate / random).  
  - Maximum variants per prompt.  
  - Whether to combine prompt variants with multiple seed values or keep seeds fixed.  

- **Queue Summary:**  
  - Number of pending jobs.  
  - Basic control to pause/resume queue processing (if supported by backend).  

This panel should not duplicate per-stage settings; it is strictly about **global pipeline behavior** and **job management**.

### 3.5 Preview Panel (Right)

The Preview panel is the “visual heartbeat” of the Pipeline tab. It should:

- Show the most recent image(s) produced by the pipeline.  
- For the selected image, show minimal metadata:  
  - Stage, prompt, seed, key config highlights (e.g., sampler, steps, CFG).  
- Optional layout:  
  - Main image view.  
  - Thumbnail strip below for recent outputs (if already implemented in V2).  

This PR should focus on wiring the panel to the stage events and job completion events that already exist, rather than introducing complex new gallery logic.

### 3.6 Randomizer Execution Behavior (Pipeline-Side)

This is where the Pipeline tab consumes prompt metadata (including matrix expressions) from the Prompt tab via `PromptWorkspaceState` and translates it into **job counts and run behavior**.

Key behaviors:

- Read the selected prompt pack and prompt index from shared state.  
- Read any matrix or variant information defined in the prompt text.  
- Combine with:
  - Randomization mode (off / sequential / rotate / random).  
  - Variant and batch controls from the Pipeline Config panel.  

The result:  

- A **concrete list of jobs** to enqueue or run immediately (e.g., 10 jobs, each with prompt variant X and seed Y).  
- The Run summary label is updated to reflect this plan before execution.  

The Prompt tab remains the source of truth for prompt text and syntax; the Pipeline tab is solely responsible for turning that into **a run plan**.

### 3.7 LoRA/Embedding Runtime Controls

Using `PromptMetadata` from the Prompt tab, the Pipeline tab:

- Displays a list of detected LoRAs and embeddings for the current prompt pack + selection.  
- For each LoRA:
  - Strength slider (e.g., range 0.0 to 1.5 or similar).  
  - On/off toggle (runtime activation).  

Runtime semantics:

- If toggle is off:
  - The LoRA participates in prompt text placement (for consistency) but is effectively given zero influence at runtime (weight 0).  
- If toggle is on:
  - The LoRA uses the strength from the slider.  

Data flow:

- Prior to execution, pipeline execution builder:  
  - Combines base model config with the list of active LoRAs and their strengths.  
  - Applies these values before sending requests to WebUI / backend.  

Optional synchronization:

- If configured, the Pipeline tab may write updated strength values back as “hints” into the prompt tokens, but this must be done carefully and non-destructively (for now, this can be deferred or implemented as a manual “sync strength back to prompt” button).  

---

## 4. File-Level Plan

> Exact paths may differ slightly; Codex should adapt based on the actual repo layout while preserving the architecture and responsibilities described here.

### 4.1 Likely GUI Files to Update

- `src/gui/main_window_v2.py` (or equivalent):
  - Ensure `Pipeline` tab exists and is wired as the central execution workspace.  
  - Mount `PipelineWorkspaceView` or equivalent into the tab.  

- `src/gui/views/pipeline_workspace_view.py` (new or heavily refactored):
  - Implements:
    - Run Control Bar.  
    - Three-column body layout.  
    - Integration with `StatusBarV2` and logging.  

- `src/gui/views/stage_cards_panel.py` (new or reused):
  - Hosts stage card widgets for txt2img, img2img/adetailer, upscale.  

- `src/gui/views/pipeline_config_panel.py` (new):
  - Hosts global run/queue/randomization config controls.  

- `src/gui/views/preview_panel_v2.py` (existing or new):
  - Implements the right-side preview behavior in a Pipeline-aware way.  

### 4.2 Controllers / State

- `src/gui/controllers/pipeline_controller_v2.py` (new or extended):
  - Orchestrates:
    - Building the run plan from shared Prompt state and local pipeline config.  
    - Submitting jobs to the job queue or direct-run executor.  
    - Updating the Run summary.  
    - Managing queue mode vs direct mode.  

- `src/gui/state/app_state.py` or equivalent:
  - Ensure accessors exist for:
    - `PromptWorkspaceState` (read-only).  
    - `PipelineState` (new): captures run mode, queue settings, stage active states, LoRA strength/activation, etc.  

### 4.3 Randomizer Integration

- `src/pipeline/randomizer_v2.py` or similar (new or extended):  
  - Provide a clean API for:
    - Taking prompt text plus matrix metadata.  
    - Current randomizer mode and variant limits.  
    - Producing a list of prompt variants / jobs for execution.  

The GUI should call into this layer, not implement matrix expansion logic itself.

### 4.4 LoRA/Embedding Runtime Integration

- `src/pipeline/model_profile.py` or similar:
  - Ensure there is a data structure to hold:
    - Active LoRAs and strengths for a given run.  
- `src/gui/controllers/pipeline_controller_v2.py`:
  - Map LoRA slider/toggle values into the run configuration.  

---

## 5. Implementation Steps (For Codex)

1. **Create / refine PipelineWorkspaceView:**
   - Establish a frame with:
     - Top Run Control Bar.  
     - Middle body with three columns.  
   - Embed existing Stage card components into the center column.  
   - Embed existing Preview panel into the right column (if available).  

2. **Implement Run Control Bar:**
   - Stage toggles that:
     - Control the expanded/collapsed state of stage cards.  
     - Mark stages as included/excluded in execution.  
   - Run mode selector and Run buttons (Run Now / Add to Queue).  
   - Run summary label that pulls from `PipelineState` and randomizer results.  

3. **Implement PipelineConfigPanel:**
   - Controls for:
     - Direct vs queue mode.  
     - Batch size / number of runs.  
     - Looping (if supported).  
   - Randomizer controls for:
     - Mode selection (off / sequential / rotate / random).  
     - Variant count.  
   - Wire these controls into `PipelineState`.  

4. **Wire PromptWorkspaceState into Pipeline:**
   - From main app state, obtain the currently selected prompt pack and prompt.  
   - Obtain `PromptMetadata` (LoRAs, embeddings, matrix info).  
   - Make this available to the Pipeline controller.  

5. **Implement Randomizer integration:**
   - In the Pipeline controller:
     - Use the prompt text and `PromptMetadata` plus current randomizer settings to call into a Randomizer helper.  
     - Derive a concrete run plan (list of jobs).  
     - Update Run summary with job count and expected image count.  

6. **Implement LoRA/Embedding runtime control UI:**
   - Add a section in the PipelineConfigPanel (or a dedicated panel) listing detected LoRAs and embeddings.  
   - For each entry, render:
     - Strength slider.  
     - On/off toggle.  
   - Persist these settings in `PipelineState`.  
   - Ensure the pipeline execution builder uses these values when constructing WebUI/backend requests.  

7. **Connect Run Buttons to Execution:**
   - `Run Now`:
     - Build run plan from current state.  
     - Submit jobs directly to executor.  
   - `Add to Queue`:
     - Build run plan.  
     - Push jobs into queue without starting them immediately (unless auto-start is configured).  

8. **Wire Preview Panel to Stage Events:**
   - Subscribe the Preview panel to job completion events.  
   - On completion, update displayed image and metadata.  
   - Ensure it behaves reasonably with multi-stage runs (e.g., show the final stage by default, with the option to inspect earlier-stage outputs later if the support exists).  

---

## 6. Testing & Validation

### 6.1 Manual Testing

- Verify that:
  - Stage toggles expand/collapse their corresponding cards.  
  - Enabling/disabling a stage correctly affects Run summary and execution behavior.  
  - Randomizer settings affect job counts as expected (sanity-check with simple prompts).  
  - LoRA strength sliders visibly change behavior in runs (where LoRAs are configured).  
  - Queue vs Direct mode behaves as configured.  
  - Preview updates as jobs complete and shows correct stage and basic metadata.  

- Confirm that Prompt tab changes (prompt text, LoRA placement) are reflected in Pipeline tab behavior after state sync.  

### 6.2 Automated Tests (If feasible in this PR)

- Unit tests for Randomizer helper:
  - Given matrix metadata and settings, it returns expected job counts and combinations.  
- Unit tests for Pipeline controller:
  - Run plan building given different stage enable configurations and randomizer settings.  
- Basic tests for LoRA/embedding application at runtime, ensuring toggles and strengths map into effective run configuration.  

---

## 7. Risks & Mitigations

- **Risk:** Confusion if some run-related controls remain outside Pipeline tab.  
  - **Mitigation:** As part of this PR, audit existing run controls and either relocate them into Pipeline tab or clearly mark them as deprecated.  

- **Risk:** Randomizer and LoRA/embedding logic becomes fragmented between GUI and backend.  
  - **Mitigation:** Enforce that matrix expansion and LoRA application are implemented in dedicated helper or pipeline modules, with the GUI only configuring them.  

- **Risk:** Large, complex runs are created accidentally due to high variant counts.  
  - **Mitigation:** Add soft safeguards (e.g., warning label if job count exceeds a threshold, but this could be deferred to a later PR).  

---

## 8. Definition of Done

- Pipeline tab exists and is the primary workspace for running jobs.  
- Stage cards are clearly visible, expandable, and toggle-able from the top bar.  
- Run Control Bar is implemented and correctly builds run plans based on:  
  - Stage selection.  
  - Randomizer settings.  
  - Queue vs Direct mode.  
- Randomizer execution behavior is centralized in the Pipeline tab and clearly reflected in a Run summary.  
- LoRA/Embedding runtime controls are implemented per the hybrid model, using prompt metadata from the Prompt tab.  
- Preview panel updates based on pipeline execution events.  
- No regressions in existing run behavior; legacy paths either map into the new Pipeline tab or remain functional until explicitly deprecated in later PRs.  
