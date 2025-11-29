PR 1 — GUI V2 Zones & Panel Wiring (Fix Blank Window).md

Goal:
MainWindowV2 creates the V2 “zone map” (header, left, center, bottom — with a placeholder right_zone), LayoutManagerV2 actually attaches panels into those zones, and the window is no longer blank.

PR Header (for your PR template)

PR-ID: PR-GUI-V2-ZONES-001

Scope: GUI V2 (MainWindowV2 + LayoutManagerV2 + layout grid + smoke test)

Baseline Snapshot: StableNew-snapshot-20251128-111334.zip

PR Type: Fix-only + Wiring

Summary (1 sentence):
“Create the V2 zone layout in MainWindowV2, implement LayoutManagerV2.attach_panels, and ensure the GUI shows sidebar/pipeline/randomizer/preview/status panels instead of a black window.”

Files to Modify (ONLY)
src/gui/main_window_v2.py
src/gui/layout_v2.py
src/gui/panels_v2/layout_manager_v2.py
tests/gui_v2/test_gui_v2_layout_skeleton.py

Forbidden Files (MUST NOT TOUCH)
src/main.py
src/gui/main_window.py          # legacy entrypoint shell
src/gui/theme_v2.py
src/pipeline/executor.py
src/controller/app_controller.py
src/api/*                        # all API/WebUI client modules
tests/gui_v1_legacy/*            # legacy tests


Note: This PR explicitly unlocks src/gui/main_window_v2.py from the generic “forbidden files” list so we can wire the V2 GUI correctly. Everything else in the general forbidden matrix stays locked.

High-Level Design (What Copilot Should Do)

Define Root Zones in MainWindowV2

In src/gui/main_window_v2.py, inside class MainWindowV2.__init__:

After:

self.root.title(...)

apply_theme(self.root)

configure_root_grid(self.root)

Create and attach the core zone frames as attributes on self:

# Pseudocode structure (no exact code here)
self.header_zone = HeaderZone(self.root)
self.left_zone = ttk.Frame(self.root, style="Panel.TFrame")
self.center_notebook = ttk.Notebook(self.root)   # real Notebook, even if only one tab for now
self.right_zone = ttk.Frame(self.root, style="Panel.TFrame")  # placeholder for future usage
self.bottom_zone = BottomZone(self.root, controller=self.app_controller, app_state=self.app_state)


Grid them into root using the V2 3-column layout:

header_zone → row 0, columns 0–2, sticky="nsew".

Main content row (row 1):

left_zone → row 1, col 0.

center_notebook → row 1, col 1.

right_zone → row 1, col 2.

bottom_zone → row 2, columns 0–2.

This aligns with the architecture/roadmap where sidebar, pipeline, and preview occupy 3 columns and status bar sits at the bottom.

Make sure self.header_zone, self.left_zone, self.center_notebook, and self.bottom_zone exist before any controller wiring (AppController._attach_to_gui) runs, so it doesn’t bail out with the “missing zones; deferring wiring” message.

Update configure_root_grid for Header + Main + Status

In src/gui/layout_v2.py:

Adjust configure_root_grid(root) to explicitly support three rows:

row 0 — header (weight 0).

row 1 — main content (weight 1).

row 2 — status bar (weight 0).

Keep the existing 3-column design:

column 0 — sidebar (minsize ~260, small weight).

column 1 — pipeline/main (higher weight).

column 2 — preview/right workspace (medium weight).

This solves the “no header row” issue that left the window as a pure theme background.

Implement LayoutManagerV2.attach_panels (No More ...)

In src/gui/panels_v2/layout_manager_v2.py:

Replace the stub/ellipsis implementation with a real layout manager:

Store self.main_window in __init__.

Implement attach_panels(self, **kwargs: Any) -> None to:

Use mw = self.main_window.

Sidebar:

If not hasattr(mw, "sidebar_panel_v2") and hasattr(mw, "left_zone"):

Instantiate SidebarPanelV2 in mw.left_zone with:

controller=getattr(mw, "controller", None) or mw.app_controller

app_state=mw.app_state

theme=getattr(mw, "theme", None) if present.

Pack/fill vertically and set mw.sidebar_panel_v2 = <instance>.

Center pipeline + randomizer:

Ensure mw.center_notebook exists and is a ttk.Notebook.

Create a single initial tab (e.g., "Pipeline") that acts as the Pipeline workspace:

Inside that tab:

Create PipelinePanelV2 and RandomizerPanelV2 in a sensible layout (e.g., stacked or split).

Set mw.pipeline_panel_v2 and mw.randomizer_panel_v2.

If PipelinePanelV2 exposes run controls, surface them on mw as:

mw.pipeline_controls_panel

mw.run_pipeline_btn

This keeps the existing tests (test_gui_v2_layout_skeleton) happy.

Preview:

Prefer placing PreviewPanelV2 in the right side of the Pipeline tab or into mw.right_zone.

Ensure mw.preview_panel_v2 is set and the widget is actually gridded/packed.

Status bar:

If not hasattr(mw, "status_bar_v2") and hasattr(mw, "bottom_zone"):

Instantiate StatusBarV2 in mw.bottom_zone and set mw.status_bar_v2.

Keep the guard checks so attach_panels is idempotent (safe to call once in __init__ and not re-do work).

Call LayoutManagerV2 After Zones Exist

Back in MainWindowV2.__init__:

After creating/zoning the frames (header, left, center_notebook, right, bottom) and before _wire_toolbar_callbacks:

from src.gui.panels_v2.layout_manager_v2 import LayoutManagerV2
self.layout_manager_v2 = LayoutManagerV2(self)
self.layout_manager_v2.attach_panels()


Then:

Call self._wire_toolbar_callbacks() to hook up header buttons.

Call self._wire_left_zone_callbacks() so AppController integrations (packs list, presets) work once available.

Call self._wire_status_bar() if such helper exists (if not, leave this in place for future wiring).

Remove any redundant root.rowconfigure calls that conflict with configure_root_grid (or adjust them to only tweak weights, not rows).

Expose center_notebook and Panels for Tests

Make sure MainWindowV2 exposes:

self.center_notebook

self.sidebar_panel_v2

self.pipeline_panel_v2

self.randomizer_panel_v2

self.preview_panel_v2

self.status_bar_v2

self.pipeline_controls_panel

self.run_pipeline_btn

Either directly (by creating them in MainWindowV2) or via the layout manager and simple attribute aliases.

Update GUI V2 Layout Smoke Test

In tests/gui_v2/test_gui_v2_layout_skeleton.py:

Keep the existing assertions:

isinstance(app.sidebar_panel_v2, SidebarPanelV2)

isinstance(app.pipeline_panel_v2, PipelinePanelV2)

isinstance(app.randomizer_panel_v2, RandomizerPanelV2)

isinstance(app.preview_panel_v2, PreviewPanelV2)

isinstance(app.status_bar_v2, StatusBarV2)

app.pipeline_controls_panel.winfo_exists()

app.run_pipeline_btn.winfo_exists()

Optionally add assertions that directly protect against the “blank window” regression:

assert getattr(app, "header_zone", None) is not None

assert getattr(app, "left_zone", None) is not None

assert getattr(app, "center_notebook", None) is not None

assert getattr(app, "bottom_zone", None) is not None

This gives us the early warning you asked for – if zones disappear again, tests break immediately.

Done Criteria for PR 1

App starts via python -m src.main and no longer shows a blank/black window.

Header, sidebar, pipeline, randomizer, preview, and status panels are visible and interactive.

MainWindowV2 exposes header_zone, left_zone, center_notebook, bottom_zone (and a right_zone placeholder).

AppController._attach_to_gui no longer logs the “missing zones; deferring wiring” message on startup.

All of the following tests pass:

pytest tests/gui_v2/test_gui_v2_layout_skeleton.py -q
pytest tests/gui_v2/test_entrypoint_uses_v2_gui.py -q


No changes to forbidden files.