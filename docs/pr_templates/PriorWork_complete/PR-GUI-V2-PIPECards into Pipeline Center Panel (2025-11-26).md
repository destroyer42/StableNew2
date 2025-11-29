PR-GUI-V2-PIPELINE-MOVE-RUN-TAB-001 — Migrate Run Tab Stage Cards into Pipeline Tab Center Panel (2025-11-26)

Author: StableNew Assistant (with Rob)
Status: Draft (ready for Copilot/Codex implementation)
Area: GUI V2 – Pipeline Tab / Run Tab / Stage Configuration Cards
Related Docs:

StableNew_GUI_V2_Program_Plan-11-24-2025.md

StableNew_Phase2_GUI_Layout_Theming_and_Wiring(24NOV).md

StableNew_Phase3_Roadmap_Features_and_Learning_System(24NOV).md

Journey_Test_Plan_2025-11-26_1115.md (future JT: Pipeline Journey)

1. Summary

This PR migrates the txt2img / img2img / upscale configuration cards from the legacy Run tab into the Pipeline tab’s center panel, so that:

The Pipeline tab becomes the single place where users configure and run multi-stage pipelines.

The legacy Run tab is removed once its contents are fully re-hosted.

Legacy Run-tab-local controls (old advanced prompt builder button, Run/Stop buttons inside the tab) are removed.

Existing header Run/Stop/Preview wiring and backend pipeline execution remain unchanged.

This is a layout and wiring PR, not a behavior change for the underlying pipeline runner. It unblocks later PRs that will make each stage card fully editable and connected to PipelineConfig and ConfigManager.

2. Problem Statement

Right now:

The Pipeline tab shows inert “Stage content (Scaffold)” cards for txt2img, img2img/ADetailer, and upscale in the center column.

The Run tab holds the actual configuration UIs for these stages (combos, sliders, checkboxes, etc.), plus a per-tab Run/Stop and a legacy Advanced Prompt Builder launcher.

This duplicates concepts, splits the mental model, and makes Journey tests for the “Pipeline configuration + run” path confusing.

We want:

A single canonical place for stage configuration: Pipeline tab center pane.

No separate Run tab; header buttons (Run / Stop / Preview) remain the control surface for execution.

Removal of leftover legacy widgets that don’t fit the V2 three-tab model.

3. Goals / Non-Goals
Goals

Move stage configuration UIs for txt2img, img2img/ADetailer, and upscale:

From the Run tab implementation.

Into the Pipeline tab’s center panel, replacing the current placeholders.

Remove the Run tab once migration is complete.

Remove legacy controls inside the Run tab:

Legacy Advanced Prompt Builder launch button.

Tab-local Run / Stop / Pipeline Run buttons (header controls are the source of truth).

Keep existing header-level wiring (AppController.on_run_clicked, etc.) intact.

Non-Goals (future PRs)

Making every control in the stage cards fully data-bound into PipelineConfig / ConfigManager (that’s handled by the separate “wire pipeline configuration” PR chain).

Implementing new fields, randomizer/matrix behavior, or new stage types.

Changing pipeline execution semantics in PipelineRunner / Pipeline.

Learning system behavior or Journey test automation (that comes after the GUI is stable).

4. High-Level Design
4.1. Conceptual Layout After This PR

Within the Pipeline tab (Notebook page):

Left panel: Pipeline controls (Run mode, batch runs, randomizer mode, max variants, stage toggles, queue vs direct, etc.).

Center panel: Stage configuration cards (this PR’s main target):

txt2img Stage card (full configuration UI).

img2img / ADetailer Stage card.

Upscale Stage card.

Right panel: Preview / recent outputs (scaffold can remain as-is for now).

Bottom zone: Status bar, progress, logs, WebUI status and Launch/Retry (unchanged, already wired via WebUI connection controller).

After this PR:

The Run tab is removed from the Notebook: the Tab strip remains Prompt / Pipeline / Learning / Settings (or whatever the current 3-tab layout is, plus any extra like Settings).

4.2. Ownership

Pipeline tab module (e.g. src/gui/tabs/pipeline_tab_v2.py or similar) becomes the owner of:

Stage card widgets (frames, labels, combos, sliders, checkboxes).

Stage expand/collapse behavior (Hide/Show).

AppController remains the orchestrator for header buttons and pipeline runs; this PR does not change its public interface.

PipelineRunner / Pipeline remain unchanged; they will be wired from the Pipeline tab via the controller in a later PR.

5. Implementation Plan

All file paths are indicative; Copilot/Codex should adapt names based on the actual repo (main_window_v2.py, tabs/run_tab.py, tabs/pipeline_tab.py, etc.).

5.1. Introduce a reusable “Stage Card” container (if not already present)

Files:

src/gui/widgets/stage_card.py (new, or reuse existing pattern if there is already a StageCard/CollapsibleFrame helper).

src/gui/tabs/pipeline_tab_v2.py (or equivalent).

Steps:

Create/standardize a StageCard widget:

Props:

title: str

parent: tk.Widget

on_toggle: Optional[Callable[[bool], None]] (called when Hide/Show toggled).

Layout:

Header row:

Label: <Stage Name>

Toggle button: Hide / Show (updates internal bool expanded + event).

Content frame:

Child frame that can host arbitrary controls (packed/ gridded as needed).

Behavior:

“Hide” collapses the content frame but does not destroy child widgets.

“Show” restores geometry so the same widgets remain active.

Ensure theming matches GUI V2:

Use existing colors, fonts, and padding from Phase 2 theming docs.

If there already is a common style helper (e.g., theme.py), wire StageCard to use it.

If a StageCard-like helper already exists, adapt it instead of creating a new one.

5.2. Extract stage configuration UIs from Run tab into helper builders

Files (indicative):

src/gui/tabs/run_tab_v2.py

src/gui/tabs/pipeline_tab_v2.py

Possibly src/gui/panels/stage_panels.py (new)

Steps:

Locate existing Run tab stage layouts:

Identify the frames/widgets that currently build:

txt2img configuration (model, sampler, scheduler, steps, cfg scale, width/height, batch size, seed, HR settings, etc.).

img2img / ADetailer configuration (denoise, steps, cfg, source image selector, etc.).

Upscale configuration (mode, upscaler, resize factor, safety toggles, etc.).

Extract the widget creation into reusable builder functions, e.g.:

# src/gui/panels/stage_panels.py

def build_txt2img_stage_panel(parent, controller) -> tk.Frame: ...
def build_img2img_stage_panel(parent, controller) -> tk.Frame: ...
def build_upscale_stage_panel(parent, controller) -> tk.Frame: ...


These functions:

Create and lay out the widgets on the given parent.

Wire command callbacks to the controller (or pass in callbacks as explicit arguments) in a non-breaking way.

Do not reference the Run tab directly.

Update Run tab to use these helpers (intermediate step so we don’t break existing behavior while migrating):

Replace inline construction in Run tab with build_* calls.

Keep layout identical for now.

Once Pipeline tab uses these helpers (next step), we can delete Run tab.

5.3. Host stage panels in Pipeline tab center column

Files:

src/gui/tabs/pipeline_tab_v2.py

src/gui/main_window_v2.py (for Notebook wiring if needed)

Steps:

In the Pipeline tab implementation, locate the center panel where current scaffold cards live (labels like "txt2img Stage Content (Scaffold)").

Replace scaffold content with StageCards + panel builders:

self.txt2img_card = StageCard(center_panel, title="txt2img Stage")
txt2img_body = self.txt2img_card.body  # or content_frame
build_txt2img_stage_panel(txt2img_body, controller=self.controller)

self.img2img_card = StageCard(center_panel, title="img2img / ADetailer Stage")
img2img_body = self.img2img_card.body
build_img2img_stage_panel(img2img_body, controller=self.controller)

self.upscale_card = StageCard(center_panel, title="Upscale Stage")
upscale_body = self.upscale_card.body
build_upscale_stage_panel(upscale_body, controller=self.controller)


Keep existing Hide buttons semantics consistent:

Either reuse the new StageCard toggle or wire the existing “Hide” buttons to call StageCard.set_expanded(False).

Ensure self.controller is passed correctly to the stage builders:

The Pipeline tab should either:

Receive controller in its constructor, or

Have a connect_controller() method called from main_window_v2/StableNewGUI after the AppController is attached.

Validate layout:

With all three cards expanded, the center panel should roughly match the current screenshot (stacked full-width cards).

Scroll behavior (if any) remains acceptable; if needed, wrap the center panel in a Canvas + scrollbar frame but that can be deferred to a later PR.

5.4. Remove Run tab content and tab itself

Files:

src/gui/tabs/run_tab_v2.py

src/gui/main_window_v2.py (Notebook tab registration)

Any Run-tab-specific menu items

Steps:

Remove/empty the Run tab module:

If the file only contained the layout we just extracted, we can:

Delete the file, or

Convert it to a small shim that raises a comment “Retired; see Pipeline tab” (if tests import it).

Remove Run tab from Notebook:

In main_window_v2.py, where the Notebook is initialized:

Remove creation/adding of the Run tab to the Notebook (self.notebook.add(run_frame, text="Run"), etc.).

Ensure tab order is now: Prompt | Pipeline | Learning | Settings (or whatever the final set is).

Remove Run-tab-local Run/Stop buttons:

Delete the per-tab run/stop button definitions and their callback bindings.

Confirm that no unique logic lived on those callbacks; they should have been thin wrappers over the controller’s on_run_clicked / on_stop_clicked. If they contained extra behavior, copy that into the controller or Pipeline tab where appropriate.

Remove legacy Advanced Prompt Builder button:

Remove the button and its callback wiring from the Run tab.

If its callback is only used there, delete the callback; if it is reused elsewhere, leave the shared callback but ensure no dead references remain.

5.5. Keep controller & pipeline behavior stable

Files:

src/controller/app_controller.py

src/pipeline/pipeline_runner.py

src/pipeline/executor.py

No code changes are expected here; this section is just to make it explicit.

AppController:

Continues to own header Run/Stop/Preview buttons and to build PipelineConfig for PipelineRunner.run.

PipelineRunner + Pipeline:

Remain unchanged; they already encapsulate multi-stage execution (txt2img → img2img → adetailer → upscale).

Any “wiring” of individual GUI fields into these configs will be handled in the next set of “Pipeline configuration wiring” PRs.

6. File-Level Change List (for Codex)

Note: exact module names may differ; adapt to real paths.

New / updated GUI widgets

src/gui/widgets/stage_card.py (new)

src/gui/panels/stage_panels.py (new or repurposed)

Pipeline tab

src/gui/tabs/pipeline_tab_v2.py

Replace scaffold stage frames with StageCards + build_*_stage_panel calls.

Run tab

src/gui/tabs/run_tab_v2.py

Temporary: use build_*_stage_panel while we migrate.

Final: remove contents; file may be deleted if no imports.

Main window / Notebook

src/gui/main_window_v2.py

Remove Run tab from Notebook.

Ensure Pipeline tab still receives the controller reference needed for callbacks.

Cleanup

Any AdvancedPromptBuilder launch wiring tied only to the Run tab.

Any per-Run-tab Run/Stop button wiring.

7. Testing Plan
7.1. Manual Smoke Tests

Startup

Launch StableNew V2 (Spine) from the repo.

Confirm:

Notebook tabs show Prompt / Pipeline / Learning / Settings (no Run tab).

No exceptions on startup.

Pipeline tab layout

Navigate to Pipeline tab.

Verify:

Left panel shows Run Mode, Batch Runs, Randomizer, Max Variants, Stage toggles.

Center panel shows three Stage cards:

txt2img Stage

img2img / ADetailer Stage

Upscale Stage

Each card contains the same controls that previously appeared on the Run tab.

“Hide” button collapses card content; clicking again restores it.

Header Run/Stop still work

With WebUI available:

Select a simple configuration in txt2img.

Click Run in the header.

Confirm:

Status bar transitions from “Idle” → “Running…” → “Idle”.

At least one image is generated and stored in the expected runs directory (same behavior as before).

Click Stop mid-run (if possible); confirm it doesn’t crash and returns to Idle.

No broken references

Confirm no menu or button still references:

The deleted Run tab.

The Advanced Prompt Builder launcher.

Confirm no “TclError: bad window path name” or similar occurs when switching tabs or closing the app.

7.2. Automated Tests (if present)

Update any GUI tests that:

Assert on the number of Notebook tabs.

Look up widgets by tab name "Run".

Add one light-weight test (if there's an existing Tkinter test harness) to ensure:

A PipelineTab instance creates three stage cards and they are children of the center panel container.

8. Risks & Mitigations

Risk: Run tab deletion breaks imports or tests that still reference it.

Mitigation: Search for "RunTab" or "Run" tab usages and clean up; add at least one test that instantiates the main window and enumerates notebook tabs.

Risk: Stage widgets accidentally share the same Tk parent across tabs (if we tried to reuse them directly).

Mitigation: Use builder functions that create new widgets instead of trying to reparent existing ones.

Risk: Pipeline tab may become too tall if all cards are expanded.

Mitigation: Acceptable for now; future PR can wrap center column in a scrolling container.

9. Follow-On Work

This PR is step 1 of making the Pipeline tab truly functional. After it lands:

PR-GUI-V2-PIPELINE-CONFIG-WIRING-00x
Bind all stage card controls on the Pipeline tab to a unified GUI state → PipelineConfig / ConfigManager.

Journey Tests (JT-0x Pipeline)
Use the new layout as the baseline for:

“Configure and run txt2img pipeline” JT.

“Configure multi-stage txt2img → img2img → upscale pipeline” JT.

Advanced Prompt integration
The future Prompt tab work will feed prompt configuration into the Pipeline tab; this PR simply ensures the Pipeline side is ready to host configuration UIs.