PR-021 — 3-column layout for all tabs

Title
PR-021-GUI-V2-TABS-THREE-COLUMN-LAYOUT-V2-P1

1. Summary

Make the Prompt, Pipeline, and Learning tabs each use a consistent, full-width 3-column grid:

Column 0 → “Left panel”

Column 1 → “Center panel”

Column 2 → “Right panel”

For the Pipeline tab specifically:

Move the pack loader into the left column of the Pipeline tab (instead of the outer V2 “left_zone” spine).

Keep the stage cards in the center, preview on the right.

Same 3-column pattern applies to all 3 tabs so UX is consistent.

2. Problem Statement

Right now:

You do have Prompt / Pipeline / Learning tabs again (via LayoutManagerV2), but:

Each tab’s internal layout is still using whatever ad-hoc layout it had before.

The “3-panel mental model” (left/center/right) is not consistently mapped across tabs.

The pack loader is still visually off to the side (outer left), instead of living in the Pipeline tab’s left column, which makes the UX feel fragmented and wastes horizontal space.

We want the window to read like this, for any tab:

Left column = navigation / packs / filters
Center column = primary work area
Right column = preview / secondary details

3. Goals

Three-column grid per tab
Each of PromptTabFrame, PipelineTabFrame, and LearningTabFrame uses a grid with 3 columns (0, 1, 2) spanning the full width of the tab frame.

Pipeline tab pack loader left
The pack loader UI is explicitly placed in column 0 of PipelineTabFrame, not in the outer left_zone.

Consistent semantics across tabs

Prompt tab:

Left: packs / workspace selectors / quick helpers.

Center: main prompt editors.

Right: preview / prompt metadata / helper info (whatever you already have).

Pipeline tab:

Left: pack loader, pipeline sidebar / toggles.

Center: stage cards (txt2img, img2img, upscale).

Right: preview / run feedback.

Learning tab:

Left: experiment design controls.

Center: learning plan table.

Right: review / ratings / notes.

No change to outer V2 spine
We don’t touch MainWindowV2 or the outer left_zone/center_notebook/right_zone grid – this is all inside the tab frames.

4. Non-goals

No change to:

src/gui/main_window_v2.py

src/main.py

AppController behavior

WebUI wiring (that’s the next PR bundle)

No new visual “features” or widgets; this is layout only.

No change to logging, learning back-end, or pipeline execution logic.

5. Allowed / Forbidden Files

Allowed to modify

src/gui/views/prompt_tab_frame_v2.py

src/gui/views/pipeline_tab_frame_v2.py

src/gui/views/learning_tab_frame_v2.py

(Optional, if needed) tests/gui_v2/test_gui_v2_workspace_tabs_v2.py

Forbidden in this PR

src/main.py

src/gui/main_window_v2.py

src/gui/theme_v2.py

src/gui/panels_v2/layout_manager_v2.py

src/controller/app_controller.py

Any archive/ or legacy files

If Codex finds it “needs” to change any of the forbidden ones, it should stop and report why instead of editing them.

6. Step-by-step Implementation
6.1 PromptTabFrameV2: 3-column grid

In PromptTabFrame (from prompt_tab_frame_v2.py):

At the end of __init__, set up the grid:

self.grid_columnconfigure(0, weight=1)
self.grid_columnconfigure(1, weight=2)
self.grid_columnconfigure(2, weight=1)
self.grid_rowconfigure(0, weight=1)


Identify existing widgets:

Pack / workspace selector panel (whatever holds pack list / slots).

Main prompt editor container (pos/neg editors, matrices).

Any preview / metadata / helper panel.

Place them explicitly:

# Example pseudo-code; Codex must use real widget names
self.pack_panel.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
self.editor_panel.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
self.preview_panel.grid(row=0, column=2, sticky="nsew", padx=4, pady=4)


Remove or convert any conflicting pack()/place() calls for these main panels; everything top-level in the tab should use grid.

6.2 PipelineTabFrameV2: pack loader left, 3-column grid

In PipelineTabFrame (from pipeline_tab_frame_v2.py):

Same grid config:

self.grid_columnconfigure(0, weight=1)
self.grid_columnconfigure(1, weight=2)
self.grid_columnconfigure(2, weight=1)
self.grid_rowconfigure(0, weight=1)


Identify widgets:

Pack loader / sidebar: if there’s already a pack loader widget, use it; otherwise, Codex should reuse the V2 pack loader panel that’s currently living in the outer left zone (probably a PromptPackPanelV2 or similar), instantiated in the tab instead of the outer zone.

Stage cards / pipeline config area.

Preview panel.

Place them:

self.pack_loader_panel.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
self.stage_cards_panel.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
self.preview_panel.grid(row=0, column=2, sticky="nsew", padx=4, pady=4)


If there is an existing internal layout doing something like “sidebar left, center stage, preview right” within a nested frame:

Collapse that into this root 3-column grid so there isn’t a confusing double-nesting.

Keep public attributes (sidebar, stage_cards_panel, preview_panel) unchanged so LayoutManagerV2 and tests continue to work.

Make sure pack loader is in column 0, not wired to MainWindowV2.left_zone.

6.3 LearningTabFrameV2: 3-column grid

In LearningTabFrame (from learning_tab_frame_v2.py):

Same grid config:

self.grid_columnconfigure(0, weight=1)
self.grid_columnconfigure(1, weight=2)
self.grid_columnconfigure(2, weight=1)
self.grid_rowconfigure(0, weight=1)


Map existing panels:

Left column: experiment design panel (inputs, toggles, config options).

Center column: learning plan table.

Right column: review / rating / notes panel.

Something like:

self.experiment_panel.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
self.plan_table.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
self.review_panel.grid(row=0, column=2, sticky="nsew", padx=4, pady=4)


Remove any conflicting .pack() calls on those top-level panels.

6.4 Optional: lightweight layout assertion tests

In tests/gui_v2/test_gui_v2_workspace_tabs_v2.py (or a small new test file):

After building the app with the existing gui_app_factory fixture:

def test_tabs_have_three_columns(gui_app_factory):
    app = gui_app_factory()

    for frame_attr in ("prompt_tab", "pipeline_tab", "learning_tab"):
        frame = getattr(app, frame_attr)
        # Ensure columnconfigure weights are set
        weights = [frame.grid_columnconfigure(c)["weight"] for c in range(3)]
        assert any(w > 0 for w in weights), f"{frame_attr} must configure grid columns"


Don’t over-assert details; just ensure the 3-column grid exists and the app still builds.

7. Required Tests

Codex should run:

pytest tests/gui_v2/test_gui_v2_workspace_tabs_v2.py -q


(and whatever Phase-1 subset you’ve been using) to confirm:

Tabs still instantiate.

No Tk errors.

Old workspace tests continue to pass.