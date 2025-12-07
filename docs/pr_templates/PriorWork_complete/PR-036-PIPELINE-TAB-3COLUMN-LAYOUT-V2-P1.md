PR-036-PIPELINE-TAB-3COLUMN-LAYOUT-V2-P1

Align physical layout with the logical left–center–right architecture

1. Title

PR-036-PIPELINE-TAB-3COLUMN-LAYOUT-V2-P1 — Enforce Proper Left/Center/Right Structure for Pipeline Tab

2. Summary

Now that PR-035 gives the Pipeline pack selector a clear job/config role, this PR fixes the actual layout:

Left column:

Pack selector + job actions (from PR-035)

Preset combobox + preset actions

Core pipeline config (model/vae/sampler/output/randomization shell)

Global negative config

Center column:

Stage cards (txt2img, img2img, upscale; ADetailer later)

Right column:

Job preview (current JobDraft summary)

Existing status/progress elements (WebUI, etc.)

This PR is about geometry and placements, not new behavior.

3. Problem Statement

Currently:

The Pipeline tab’s layout is still a bit of a Frankenstein:

Left column is not cleanly segmented into:

Pack selection

Preset selector

Config panels

Some left-column content may still be floating as unlabeled frames.

Center column might not be the exclusive owner of stage cards.

Right column preview/status may not be clearly separated from config.

Given the conceptual layout we’ve been converging on:

Left = pack + config controls

Center = stage cards

Right = job + status preview

We need a single, deterministic layout so future PRs (job queue, history, randomizer panels) have a stable home.

4. Goals

G1 – Enforce a 3-column grid for Pipeline tab:

Column 0 = left config spine

Column 1 = center stage area

Column 2 = right preview/status

G2 – Ensure left column has:

Pack selector + actions (from PR-035).

Preset combobox + actions.

Core config panel (model/vae/sampler/output/randomization shell).

Global negative card.

G3 – Ensure center column has:

StageCardsPanelV2 (txt2img/img2img/upscale; later ADetailer).

G4 – Ensure right column has:

Job preview (JobDraft summary).

Room for queue + history in later PRs.

WebUI status elements in a consistent, non-duplicated way.

5. Non-goals

Implementing job queue, history, or more advanced preview content.

Changing WebUI launch behavior or lifecycle logic.

Altering actual pipeline run logic.

Adding/removing stage types (ADetailer comes later in its own PR).

6. Allowed Files

src/gui/views/pipeline_tab_frame_v2.py

The main orchestrator of the three columns.

src/gui/panels_v2/pipeline_config_panel_v2.py

src/gui/panels_v2/sidebar_panel_v2.py

src/gui/panels_v2/stage_cards_panel_v2.py

src/gui/panels_v2/preview_panel_v2.py

src/gui/panels_v2/status_bar_v2.py (layout only)

Tests:

tests/gui_v2/test_pipeline_tab_layout_v2.py

No new modules should be introduced here; just reuse existing V2 panels and containers.

7. Forbidden Files

src/main.py

src/gui/main_window_v2.py (beyond any absolutely minimal tab-container plumbing, which should not be needed if layout is contained inside Pipeline tab)

Any pipeline, API, or controller modules.

Legacy/V1 GUI modules.

8. Step-by-step Implementation
Step 1 — Define the 3-column grid in PipelineTabFrameV2

In pipeline_tab_frame_v2.py:

Configure the root frame:

self.columnconfigure(0, weight=0, minsize=LEFT_WIDTH)   # left
self.columnconfigure(1, weight=1)                       # center (expand)
self.columnconfigure(2, weight=0, minsize=RIGHT_WIDTH)  # right


Create containers:

self.left_column = ttk.Frame(self, style=... )
self.center_column = ttk.Frame(self, style=... )
self.right_column = ttk.Frame(self, style=... )

self.left_column.grid(row=0, column=0, sticky="nsew")
self.center_column.grid(row=0, column=1, sticky="nsew")
self.right_column.grid(row=0, column=2, sticky="nsew")


(Use consistent theme styles (SURFACE_FRAME_STYLE, CARD_FRAME_STYLE) once PR-041 is in.)

Step 2 — Place specific panels into each column

Left column:

Contains (stacked vertically):

Pack Selector Card (from PR-035):

Pack list (multi-select).

Prompt preview text field under list.

Buttons:

Load current config

Apply config to pack(s)

Add to Job

Preset Card:

Preset combobox.

Buttons:

Apply to default

Apply to selected pack(s)

Load to stages

Save

Delete

Core Config Card (PipelineConfigPanelV2):

Model, VAE, Sampler, Scheduler.

Output dir, filename template, format.

Batch size/seed mode.

“Refresh” button.

Global Negative Card:

Toggle + text area (if already implemented; otherwise a shell with TODO comment).

Center column:

Contains StageCardsPanelV2 only:

self.stage_cards_panel = StageCardsPanelV2(
    self.center_column,
    controller=self.controller,
    app_state=self.app_state,
    theme=self.theme,
)
self.stage_cards_panel.grid(row=0, column=0, sticky="nsew")


Optionally configure row/column weight to make it expand:

self.center_column.rowconfigure(0, weight=1)
self.center_column.columnconfigure(0, weight=1)


Right column:

Contains:

Job Preview Card:

Displays contents of JobDraft (pack names, randomization flags, etc.).

Space reserved below for:

Future Job queue

Future History

Optionally integrate WebUI status labels into a small status area if that’s where they belong (consistent with status bar).

Step 3 — Remove stray/duplicated elements

If any leftover prompt-pack controls are still floating in PipelineTabFrameV2 (from pre-PR-035 era), remove them.

Ensure there is exactly:

One pack selector card in left column.

One preset card in left column.

One core config card in left column.

StageCardsPanelV2 in center.

Preview panel in right.

Step 4 — Add layout test

tests/gui_v2/test_pipeline_tab_layout_v2.py:

Build the main window and focus Pipeline tab.

Introspect its child structure to assert:

There are three top-level column frames in the Pipeline tab.

Left column contains widgets for:

pack selector

preset combobox

core config (we can check via child class name or layout)

Center column contains StageCardsPanelV2.

Right column contains a preview panel that can show JobDraft info (via its method or label text).

No Tk errors thrown during construction.

9. Required Tests (Failing first)

tests/gui_v2/test_pipeline_tab_layout_v2.py
Initially fails because:

3-column grid and expected panels are not yet in place.

10. Acceptance Criteria

Pipeline tab visually shows:

Left config spine

Center stage area

Right preview area

Left column:

Pack selector + actions (from PR-035).

Preset section.

Core config + global negative card.

Center column:

StageCardsPanelV2 fills center.

Right column:

Job draft preview card present (content wired via PR-035’s JobDraft).

No duplicated pack selectors, preset combos, or config cards.

test_pipeline_tab_layout_v2.py passes.

No new Tk errors.

11. Rollback Plan

Revert changes to:

pipeline_tab_frame_v2.py

sidebar_panel_v2.py

pipeline_config_panel_v2.py

stage_cards_panel_v2.py

preview_panel_v2.py

status_bar_v2.py

tests/gui_v2/test_pipeline_tab_layout_v2.py

12. Codex Execution Constraints

Do not add new behavior; just move/reparent widgets.

No controller/pipeline changes in this PR.

Keep layout changes minimal and incremental; no refactors of unrelated widgets.