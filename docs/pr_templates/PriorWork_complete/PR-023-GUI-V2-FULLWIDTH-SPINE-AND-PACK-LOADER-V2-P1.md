PR-023-GUI-V2-FULLWIDTH-SPINE-AND-PACK-LOADER-V2-P1
1. Title

PR-023-GUI-V2-FULLWIDTH-SPINE-AND-PACK-LOADER-V2-P1 — Full-width 3-column tabs + Pipeline tab pack loader + config wiring

2. Summary

Refactor the V2 GUI spine so that:

The Prompt / Pipeline / Learning tabs occupy the full window width, not just the center column.

Each tab’s own 3-column layout (left / center / right) aligns with the entire window:

Column 0 = left panel (packs, pipeline controls, etc.).

Column 1 = main work area.

Column 2 = right panel (preview, secondary info).

The **legacy “Load Pack / Edit Pack / Pack list / Preset combo” pack loader is removed from the outer left_zone and relocated into the Pipeline tab’s left column, alongside the pipeline config controls (stage selection, batch, queue, default model, etc.).

AppController keeps working by treating the new Pipeline-tab-based pack loader as its left_zone target (compat proxy), so existing pack-related tests and callbacks remain valid.

3. Problem Statement

Current behavior:

MainWindowV2 still builds an outer “spine”:

self.left_zone = LeftZone(self.root)           # packs, presets, etc.
self.center_notebook = ttk.Notebook(self.root) # Prompt / Pipeline / Learning
self.right_zone = ttk.Frame(self.root)         # placeholder


with:

left_zone in root column 0,

center_notebook in column 1,

right_zone in column 2.

Inside PipelineTabFrameV2 there is a three-column body (left_scroll + sidebar, stage_cards_panel, preview_panel), but it all lives in the notebook’s central column only, so visually:

The tab’s “left column” starts somewhere in the middle of the window,

The tab’s “right column” stops short of the real right edge.

The old pack loader (LeftZone with “Load Pack / Edit Pack / pack list / preset combo”) still lives in MainWindowV2.left_zone, separate from the tabs. The new sidebar (SidebarPanelV2) has more modern pipeline controls and pack wiring, but:

AppController’s pack logic still points at main_window.left_zone.

The “real” pipeline config (stage selector, batch, queue, default model) isn’t wired into the visible left panel the way you expect.

Net: the visual UX feels wrong (3 columns only inside the middle third), and pack/config controls are split between an outer legacy pane and the Pipeline tab.

4. Goals

Full-width tabs

center_notebook stretches from the left edge to the right edge of the main window.

The outer left_zone/right_zone frames no longer claim visible horizontal space.

Per-tab 3-column layout = actual window columns

Prompt / Pipeline / Learning tabs:

Left column touches the left border of the window.

Right column touches the right border of the window.

The existing internal 3-column layout in PipelineTabFrameV2 is preserved but now maps to the true window width.

Pack loader lives in Pipeline tab left column

The “Load Pack / Edit Pack / pack list / preset combo” controls are instantiated inside the Pipeline tab’s left column (e.g., above/within the sidebar scroll area).

The old LeftZone on the root is no longer shown.

Keep AppController pack wiring working

AppController still uses the same methods (on_load_pack, on_edit_pack, on_pack_selected, on_preset_selected, load_packs).

Instead of pointing at main_window.left_zone anchored on the root, it now points at a compat proxy object attached to the Pipeline tab’s left column, exposing the same attributes:

load_pack_button

edit_pack_button

packs_list

preset_combo

set_pack_names(...) (or an equivalent).

Make the pipeline configs visible in the Pipeline tab left column

Ensure the existing SidebarPanelV2 cards for:

Stage selection (txt2img/img2img/upscale),

Batch / job counts,

Queue/Run mode,

Default model / overrides
are actually visible in the left column under the pack loader.

5. Non-goals

No changes to:

The internal behavior of SidebarPanelV2 cards beyond what’s required for layout and pack-loader compat handles.

The WebUI lifecycle logic (launch/retry) — that’s PR-022.

Learning system back-end behavior (ratings, experiments, etc.).

No new modules or package-level reorganization.

No changes to the outer entrypoint (src/main.py).

6. Allowed Files

This PR may modify only:

src/gui/main_window_v2.py

src/gui/panels_v2/layout_manager_v2.py

src/gui/views/pipeline_tab_frame_v2.py

src/controller/app_controller.py

tests/controller/test_app_controller_packs.py

tests/controller/test_app_controller_config.py

tests/gui_v2/test_gui_v2_workspace_tabs_v2.py

7. Forbidden Files

Do not modify in this PR:

src/main.py

src/gui/theme_v2.py

src/gui/views/prompt_tab_frame_v2.py

src/gui/views/learning_tab_frame_v2.py

src/gui/sidebar_panel_v2.py (other than what’s strictly necessary; prefer doing pack-loader compat in PipelineTabFrameV2)

src/gui/status_bar_v2.py

Any archive/gui_v1/* files

Any docs (markdown) — no doc updates in this PR

If Codex thinks a forbidden file must be touched, it should stop and report instead of editing.

8. Step-by-step Implementation
8.1 Flatten the outer spine so the notebook spans full width

File: src/gui/main_window_v2.py

Stop gridding LeftZone and right_zone as separate columns

In __init__, remove or comment out:

self.left_zone = LeftZone(self.root)
self.left_zone.grid(row=1, column=0, sticky="nsew")

self.center_notebook = ttk.Notebook(self.root)
self.center_notebook.grid(row=1, column=1, sticky="nsew")

self.right_zone = ttk.Frame(self.root)
self.right_zone.grid(row=1, column=2, sticky="nsew")


Replace with:

self.center_notebook = ttk.Notebook(self.root)
self.center_notebook.grid(row=1, column=0, columnspan=3, sticky="nsew")


Keep header_zone (row 0, columnspan 3) and bottom_zone (row 2, columnspan 3) as they are.

Preserve compatibility attributes

Do not remove the LeftZone/RightZone classes themselves.

After LayoutManagerV2.attach_panels() is called (already happens in __init__):

# After layout_manager_v2.attach_panels()
self.left_zone = getattr(self.pipeline_tab, "pack_loader_compat", None) or getattr(
    self.pipeline_tab, "left_compat", None
)
self.right_zone = getattr(self.pipeline_tab, "preview_panel", None)


This ensures:

AppController’s _attach_to_gui still sees header_zone, left_zone, and bottom_zone attributes.

But visually, the content lives inside the Pipeline tab’s left/right columns, not in separate root columns.

Keep update_pack_list behavior but make it talk to the compat loader

update_pack_list(self, packs: list[str]) already tries left.set_pack_names(...) and then falls back to packs_list on left_zone.

After introducing pack_loader_compat on the Pipeline tab (see next section), this logic should work unchanged:

The compat proxy object should implement set_pack_names or expose packs_list.

Do not call _wire_left_zone_callbacks from MainWindowV2

It’s currently unused; leave it in place as legacy helper but keep it uninvoked.

All real wiring is handled by AppController._attach_to_gui (see below).

8.2 Attach pack loader into Pipeline tab’s left column and expose compat handles

File: src/gui/views/pipeline_tab_frame_v2.py

Goal: create a pack loader sub-panel in the left column, and expose compat attributes that look like the old LeftZone to the rest of the app.

Add a pack loader frame inside left_inner

At the top of __init__ after self.left_inner is created:

self.pack_loader_frame = ttk.Frame(self.left_inner, style="Panel.TFrame")
self.pack_loader_frame.pack(fill="x", pady=(0, 8))


Add pack loader widgets

Inside pack_loader_frame, add:

self.load_pack_button = ttk.Button(self.pack_loader_frame, text="Load Pack")
self.edit_pack_button = ttk.Button(self.pack_loader_frame, text="Edit Pack")
self.packs_list = tk.Listbox(self.pack_loader_frame, exportselection=False, height=6)
self.preset_combo = ttk.Combobox(self.pack_loader_frame, values=[])

self.load_pack_button.pack(fill="x", padx=4, pady=2)
self.edit_pack_button.pack(fill="x", padx=4, pady=2)
self.packs_list.pack(fill="both", expand=True, padx=4, pady=4)
ttk.Label(self.pack_loader_frame, text="Preset").pack(anchor="w", padx=4)
self.preset_combo.pack(fill="x", padx=4, pady=(0, 4))


This effectively recreates the legacy LeftZone pack loader inside the Pipeline tab’s left column.

Expose a compat proxy for MainWindowV2.left_zone

At the end of __init__, define:

class _PackLoaderCompat:
    def __init__(self, outer: "PipelineTabFrame") -> None:
        self.load_pack_button = outer.load_pack_button
        self.edit_pack_button = outer.edit_pack_button
        self.packs_list = outer.packs_list
        self.preset_combo = outer.preset_combo

    def set_pack_names(self, names: list[str]) -> None:
        lb = self.packs_list
        lb.delete(0, "end")
        for name in names:
            lb.insert("end", name)

self.pack_loader_compat = _PackLoaderCompat(self)
self.left_compat = self.pack_loader_compat  # optional alias


This gives MainWindowV2 and AppController a clean object that quacks like the old LeftZone.

Keep existing sidebar & stage cards layout

Ensure the existing code that builds:

self.left_scroll / self.left_inner

self.sidebar

self.stage_scroll / self.stage_cards_frame

self.stage_cards_panel

self.preview_panel

still runs, but now the new pack_loader_frame appears above the sidebar in the left column.

8.3 Teach LayoutManagerV2 to hook up compat handles

File: src/gui/panels_v2/layout_manager_v2.py

After building the tabs and before the existing compatibility wiring lines, add:

# Compat aliases for legacy left/right zones
if hasattr(mw.pipeline_tab, "pack_loader_compat"):
    mw.left_zone = mw.pipeline_tab.pack_loader_compat


Keep the existing V2 compat wiring:

mw.sidebar_panel_v2 = getattr(mw.pipeline_tab, "sidebar", None)
stage_panel = getattr(mw.pipeline_tab, "stage_cards_panel", None)
mw.pipeline_panel_v2 = stage_panel
mw.randomizer_panel_v2 = getattr(mw.pipeline_tab, "randomizer_panel", None)
mw.preview_panel_v2 = getattr(mw.pipeline_tab, "preview_panel", None)
mw.status_bar_v2 = getattr(getattr(mw, "bottom_zone", None), "status_bar_v2", None)


We do not change how the notebook is created; MainWindowV2 already owns that. LayoutManager just attaches frames and compat attributes.

8.4 Let AppController treat the Pipeline-tab pack loader as left_zone

File: src/controller/app_controller.py

The goal is to preserve the existing public behavior but make it agnostic to where left_zone lives (root vs Pipeline tab).

In _attach_to_gui, keep:

missing = [name for name in ("header_zone", "left_zone", "bottom_zone") if not hasattr(mw, name)]


but now left_zone will be the pack_loader_compat object we created.

The subsequent wiring:

header = mw.header_zone
left = mw.left_zone
bottom = mw.bottom_zone

# Left zone events
left.load_pack_button.configure(command=self.on_load_pack)
left.edit_pack_button.configure(command=self.on_edit_pack)
left.packs_list.bind("<<ListboxSelect>>", self._on_pack_list_select)
left.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_combo_select)


should continue to work unchanged, as pack_loader_compat exposes those attributes.

In _on_preset_combo_select and _on_pack_list_select, you can optionally make them more robust:

combo = getattr(self.main_window.left_zone, "preset_combo", None)
if combo is None:
    return


but this is optional; the compat object guarantees the attributes.

load_packs should continue to call:

self.main_window.update_pack_list(pack_names)


which now uses pack_loader_compat.set_pack_names under the hood.

No behavioral change for controllers/tests; only the location of the underlying widgets changes.

8.5 Minimal test updates

Files:

tests/controller/test_app_controller_packs.py

tests/controller/test_app_controller_config.py

tests/gui_v2/test_gui_v2_workspace_tabs_v2.py

Controller pack tests

Ensure tests do not assert that left_zone is a child of the root; they should only care that:

AppController._attach_to_gui wires the callbacks.

load_packs() populates packs_list via update_pack_list.

Adjust any direct widget path assumptions (e.g. root.children["!leftzone"]) to instead use app_controller.main_window.left_zone.

Workspace tabs test

Add/adjust an assertion that:

The Notebook now spans the full width:

For example, check center_notebook.grid_info()["column"] == 0 and ["columnspan"] == 3.

Optional: check that main_window.left_zone is not a direct child frame on root, but is a compat object attached to pipeline_tab (this can be done by:

assert hasattr(window, "pipeline_tab")
assert window.left_zone is window.pipeline_tab.pack_loader_compat


if that doesn’t break existing expectations).

9. Required Tests (Failing first)

Before code changes, Codex should:

Add / adjust tests such that at least one fails on the baseline, e.g.:

A test asserting that center_notebook must be column 0 with columnspan 3.

A test asserting that AppController.load_packs() populates pipeline_tab.pack_loader_compat.packs_list.

Run:

pytest tests/controller/test_app_controller_packs.py -q
pytest tests/gui_v2/test_gui_v2_workspace_tabs_v2.py -q


Then implement the changes and re-run until green.

10. Acceptance Criteria

Layout

When the app runs, the Prompt / Pipeline / Learning tabs visually fill the entire width of the window.

The Pipeline tab shows:

Left column: Load Pack, Edit Pack, pack list, preset combo; plus pipeline control cards beneath (stage selection, batch, queue, default model).

Center column: the stage cards (txt2img / img2img / upscale).

Right column: the preview panel, touching the right edge.

Pack loader behavior

Clicking “Load Pack” / “Edit Pack” triggers AppController.on_load_pack / on_edit_pack.

Selecting a pack in the left-column list triggers on_pack_selected with the correct index.

Selecting a preset from the combo fires on_preset_selected.

AppController compatibility

AppController._attach_to_gui sees header_zone, left_zone, bottom_zone and wires them without errors.

load_packs() populates the left-column list inside the Pipeline tab.

Tests

All updated tests in:

tests/controller/test_app_controller_packs.py

tests/controller/test_app_controller_config.py

tests/gui_v2/test_gui_v2_workspace_tabs_v2.py
pass.

11. Rollback Plan

If this PR causes regressions:

Revert changes in:

src/gui/main_window_v2.py

src/gui/panels_v2/layout_manager_v2.py

src/gui/views/pipeline_tab_frame_v2.py

src/controller/app_controller.py

Modified tests

Re-run:

pytest tests/controller/test_app_controller_packs.py \
       tests/controller/test_app_controller_config.py \
       tests/gui_v2/test_gui_v2_workspace_tabs_v2.py -q


You’ll return to the previous behavior: tabs living in center only, and the legacy LeftZone panel on the far left.

12. Codex Execution Constraints

When you hand this to Codex:

Emphasize:

No new modules or packages.

Preserve public method names and signatures.

Maintain AppController’s pack-related methods and their semantics.

Keep diffs minimal and focused on:

root layout (MainWindowV2),

Pipeline tab pack loader,

compat wiring in LayoutManager/AppController,

tests.

If Codex thinks it must touch forbidden files, it should stop and report, not proceed.