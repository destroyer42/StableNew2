PR-GUI-V2-PIPELINE-PREVIEW-001-2025-11-26

Timestamp: 2025-11-26

1. Summary

The Pipeline tab currently has:

A top bar inside the tab with:

Stage checkboxes

Run scope selector

Run Now / Add to Queue buttons

A left sidebar/config panel with overlapping/partial controls

A preview sidebar that is not fully wired

A lot of unused whitespace and low-contrast text

This PR will:

Move all pipeline controls from the Pipeline tab’s top bar into the left sidebar/config panel, making it the single control surface.

Remove the Pipeline top bar entirely, freeing vertical space so left/center/right panels extend to the top of the tab.

Wire and complete the Preview sidebar (PreviewPanelV2) so it reflects:

Which stages are enabled

Run scope

Run mode (Direct vs Queue)

Number of jobs, number of images per run / total images

Make Add to Queue conditionally visible/enabled only when Run mode is Queue.

Tighten theming so all widgets/frames/labels/dropdowns within the Pipeline area use a dark grey surface with bold white text, consistent with V2 theming, reducing empty white gaps.

The goal is to make the Pipeline tab self-contained, readable, and ready for Journey tests.

2. Architectural Context

LayoutManagerV2 attaches the V2 panels to the main window via left_zone, center_notebook, and bottom_zone.

PipelinePanelV2 is re-exported from src/gui/panels_v2/pipeline_panel_v2.py.

PreviewPanelV2 (preview sidebar) is re-exported similarly.

SidebarPanelV2 (left config panel) is likewise a V2 panel.

RandomizerPanelV2 exists as its own panel module (V2 randomization UI).

LayoutManagerV2.attach_panels() wires them into the main window as attributes:

sidebar_panel_v2 on left_zone

pipeline_panel_v2 / randomizer_panel_v2 / preview_panel_v2 in center_notebook

status_bar_v2 in bottom_zone

This PR assumes those panels exist and focuses on PipelinePanelV2, SidebarPanelV2, and PreviewPanelV2.

3. Problems

Duplicated controls / split brain

Stage checkboxes exist both in the Pipeline top bar and in the preview/stage summary area.

Some checkboxes control only center-card visibility; others only affect the summary.

Run scope and Run Now/Add to Queue live in the top area instead of the left config panel.

Preview sidebar is not wired

PreviewPanelV2 does not consistently show:

Enabled stages (txt2img/img2img/upscale)

Run mode (Direct/Queue)

Run scope (single stage vs multi-stage, etc.)

Number of jobs, number of images

It likely has stub labels/frames that never update.

Run mode vs Add to Queue

The Add to Queue button is always shown, even when Run mode is not Queue.

This confuses users and suggests queue behavior even in direct mode.

Bad use of vertical space and low contrast

Pipeline inner “top bar” consumes a band of space above the three primary columns.

The layout leaves a lot of whitespace and inconsistent theming.

Text and widgets are not uniformly dark-mode friendly (dark grey + bold white text).

4. Goals / Non-Goals
4.1 Goals

Make the left SidebarPanelV2 the single source of truth for:

Stage checkboxes (which stages are enabled)

Run mode (Direct vs Queue)

Run scope (e.g., “All enabled stages”, “Selected stage only”)

Run Now / Add to Queue controls

Remove the Pipeline top bar frame entirely.

Ensure PreviewPanelV2:

Mirrors left panel state (stages, mode, scope, jobs, images).

Is updated whenever relevant settings change or when runs are queued/launched.

Make Add to Queue button conditional:

Only visible/enabled when Run mode == Queue.

Apply a dark theme style for all widgets within:

PipelinePanelV2

SidebarPanelV2

PreviewPanelV2

(and any child frames used by these)
using dark grey backgrounds and bold white text, consistent with theme.py/V2 styles.

4.2 Non-Goals

No change to pipeline execution semantics (how runs are actually executed/queued).

No change to Prompt tab or Learning tab behavior.

No new randomizer or X/Y features (just reuse existing RandomizerPanelV2 as-is).

No removal of RandomizerPanelV2 or status bar V2.

5. Files in Scope

Implementation / wiring

src/gui/pipeline_panel_v2.py

src/gui/sidebar_panel_v2.py

src/gui/preview_panel_v2.py

src/gui/layout_manager_v2.py (only if needed to adjust panel attachment behavior)

Theming

src/gui/theme.py (and any theme_v2 module if present)

Tests / docs

tests/gui_v2/test_pipeline_v2_layout_and_controls.py (new or updated)

tests/gui_v2/test_preview_panel_v2.py (new)

GUI docs:

docs/ARCHITECTURE_v2_COMBINED.md

docs/StableNew_GUI_V2_Program_Plan-*.md

docs/testing/Journey_Test_Plan_*.md (optional references to preview behavior)

6. Implementation Plan
6.1 Refactor: unify pipeline controls in SidebarPanelV2

In sidebar_panel_v2.py:

Add/confirm state fields

self.stage_states: map of stage_name → BooleanVar (e.g., "txt2img", "img2img", "upscale").

self.run_mode_var: StringVar ("direct" or "queue").

self.run_scope_var: StringVar (e.g., "all_enabled", "single_stage", etc. – follow existing semantics if already present).

self.job_count_var: IntVar (optional; may be computed vs stored).

self.images_per_job_var: IntVar (or read from config/prompt pack if already defined elsewhere).

Add/normalize UI elements

Stage checkboxes group (stays/comes here from top bar):

For each stage, create a Checkbutton:

text="Txt2Img" / "Img2Img" / "Upscale"

Bold white text on dark background (via theme style).

Run mode selector:

Radio buttons or Combobox (Direct vs Queue), bound to self.run_mode_var.

Run scope selector:

Radio group or small Combobox bound to self.run_scope_var.

Run Now + Add to Queue buttons:

Run Now always visible.

Add to Queue initial visibility controlled by run_mode_var.

Wire events

For each stage checkbox:

On change, call a callback (e.g., self._on_stage_state_changed()):

Update shared controller or view-model with active stage list.

Notify PipelinePanelV2 and PreviewPanelV2 (see sections below).

For run_mode_var:

On change:

Show or hide (or enable/disable) Add to Queue button.

Notify PreviewPanelV2 so it can update the “Mode” display.

For run_scope_var, job_count_var, images_per_job_var:

Notify PreviewPanelV2 whenever these change.

Expose convenience methods for other panels

get_stage_enabled(stage_name: str) -> bool

get_enabled_stages() -> list[str]

get_run_mode() -> str

get_run_scope() -> str

get_job_counts() -> tuple[int, int] (jobs, images per job or total images)

These methods will be used by PipelinePanelV2 and PreviewPanelV2 to fetch the current control state instead of duplicating it.

6.2 Remove Pipeline Top Bar and rewire usage

In pipeline_panel_v2.py:

Locate the top bar frame (node that currently contains:

Stage checkboxes

Run mode/scope widgets

Run/Queue buttons

Possibly other controls)

Remove:

Creation of this top bar frame

All widgets inside it

Any layout/VBox/grid that reserves vertical space for it

Wherever these widgets’ variables/callbacks were referenced:

Replace usage with calls into sidebar_panel_v2 (through self.controller.main_window.sidebar_panel_v2 or similar, depending on how the controller / main window is wired).

Adjust the layout so that:

Left, center, and right panels for the Pipeline tab start at the top of the tab area.

There is no extra blank band above them.

6.3 Wire stage checkboxes to stage cards and preview

We want a single set of stage enable flags (owned by the left panel) controlling both:

Center stage card visibility (or enabled state)

Preview summary (which stages are “in play”)

In pipeline_panel_v2.py:

On initialization or via injected references, obtain a handle to sidebar_panel_v2.

For each stage card instance (txt2img, img2img, upscale):

Tie its visible/enabled state to the corresponding BooleanVar in sidebar_panel_v2.stage_states.

Implement simple wiring:

When a stage is unchecked:

Option A: Hide its card (grid_remove()).

Option B: Grey it out / set state="disabled" but keep visible.

When a stage is checked:

Show/enable the card again (grid() or state="normal").

Confirm that stage enable flags used for pipeline execution (what actually runs) derive from the same stage_states source of truth.

In preview_panel_v2.py:

Add an update_from_controls(sidebar: SidebarPanelV2) -> None method:

Compute:

enabled_stages = sidebar.get_enabled_stages()

run_mode = sidebar.get_run_mode()

run_scope = sidebar.get_run_scope()

(jobs, images_per_job) = sidebar.get_job_counts()

Update labels:

“Stages: Txt2Img, Img2Img, Upscale”

“Mode: Direct” or “Mode: Queue”

“Scope: All enabled / Single stage: …”

“Jobs: N | Images per job: M | Total images: N*M”

(Optional) Add a small badge or per-stage label indicating enabled/disabled, using bold white text on dark grey.

In sidebar_panel_v2.py:

Call preview_panel_v2.update_from_controls(self) from:

Stage checkbox callbacks

Run mode/scope changes

Any job/images spinbox change

If a central controller object already exists that holds pipeline state, you can instead:

Update controller state in the sidebar callbacks.

Let PreviewPanelV2 ask controller for current pipeline state and update accordingly.

But the end-result should be the same: preview sidebar always reflects what’s set in the left config panel.

6.4 Add-to-Queue Conditional Visibility

In sidebar_panel_v2.py:

Make Add to Queue a separate button object (self.add_to_queue_btn).

When creating it, initially:

Place it in the layout but consider hiding/disabled until the run mode is known.

Add a small helper:

def _refresh_run_mode_widgets(self) -> None:
    mode = self.run_mode_var.get()
    if mode == "queue":
        self.add_to_queue_btn.grid(...)  # or .grid() if previously removed
        self.add_to_queue_btn.configure(state="normal")
    else:
        # hide or disable
        self.add_to_queue_btn.grid_remove()
        # or: self.add_to_queue_btn.configure(state="disabled")


Call _refresh_run_mode_widgets():

At the end of __init__ (after widgets created).

In the run_mode_var trace/callback.

Do not change the actual queue/execute logic; leave it wherever it already lives.

6.5 Theming and White Space Reduction

In theme.py and the three panel modules:

Identify or create dark-theme styles:

Example (adjust to what exists):

Background: DARK_SURFACE or similar dark grey

Foreground: white

Font: bold for labels, headers, and tab titles

If no such constants exist, define them using existing dark mode palette.

In SidebarPanelV2, PipelinePanelV2, and PreviewPanelV2:

Ensure their root frame(s) use a dark style, e.g.:

style = ttk.Style()
style.configure("Pipeline.TFrame", background=theme.DARK_SURFACE)
style.configure("Pipeline.TLabel", background=theme.DARK_SURFACE, foreground=theme.TEXT_ON_DARK, font=theme.BOLD_FONT)
style.configure("Pipeline.TButton", background=theme.DARK_SURFACE, foreground=theme.TEXT_ON_DARK, font=theme.BOLD_FONT)
style.configure("Pipeline.TCheckbutton", background=theme.DARK_SURFACE, foreground=theme.TEXT_ON_DARK, font=theme.BOLD_FONT)
style.configure("Pipeline.TCombobox", fieldbackground=theme.DARK_SURFACE, foreground=theme.TEXT_ON_DARK)


Set all internal frames/labels/buttons/comboboxes to use these styles:

ttk.Frame(..., style="Pipeline.TFrame")

ttk.Label(..., style="Pipeline.TLabel")

etc.

Reduce padding where whitespace is excessive:

Use uniform small/medium padding constants (e.g., theme.PAD_SM, theme.PAD_MD) rather than ad-hoc big pads.

Avoid large top/bottom padding that creates unused vertical gaps.

The net effect: every visible panel surface in the Pipeline tab feels like a coherent dark UI with bold white text, minimal whitespace, and clear grouping.

7. Testing & Validation
7.1 Manual

Open Pipeline tab:

Verify there is no inner top bar; left/center/right panels touch the top edge of the tab.

Confirm all stage checkboxes, run mode/scope, and Run / Add to Queue controls live in the left panel.

Toggling stage checkboxes:

Stages enable/disable in the preview summary.

Stage cards enable/disable or hide/show correspondingly.

Changing Run mode:

Add to Queue button appears/enables only when mode is Queue.

Preview summary mode label updates.

Trigger some runs in Direct and Queue modes:

Behavior is unchanged from previous semantics.

Preview summary accurately shows stages, scope, jobs, images.

7.2 Automated

Add tests in tests/gui_v2/test_pipeline_v2_layout_and_controls.py:

Assert there is no “Pipeline top bar” widget.

Assert controls (stage checkboxes, run mode/scope, Run/Queue buttons) are children of SidebarPanelV2.

Add tests in tests/gui_v2/test_preview_panel_v2.py:

Stub a sidebar-style object or use real SidebarPanelV2 instance.

Set stage states / mode / scope, call update_from_controls, and assert labels show expected strings.

Optionally add a test that ensures Add to Queue visibility or state toggles when run_mode_var changes.

8. Docs Updates

ARCHITECTURE_v2_COMBINED.md

Update GUI V2 section to state:

Pipeline tab comprises SidebarPanelV2 (controls), PipelinePanelV2 (stage cards), PreviewPanelV2 (summary/output).

There is no separate Pipeline “top bar”; controls are in the left sidebar.

StableNew_GUI_V2_Program_Plan-*.md

Update mockups/description of Pipeline tab to reflect:

Control cluster on the left.

Stage cards center.

Preview summary on the right.

Journey Test Plan

For JT-03/04/05, ensure instructions say:

Configure stages + run mode + scope in the Pipeline left config panel.

Verify run summary/preview in the right preview sidebar.