PR-050 — GUI V2 Scaffold & ZoneMap Fixes (Updated)
Purpose: complete the V2 GUI scaffolding by creating a declarative “zone map” and removing V1-style layout glue. This reduces drift + ensures the GUI is fully deterministic.
1. Summary

The GUI V2 stack (main_window_v2, top_level_v2, stage_cards_panel, sidebar_panel_v2, etc.) is functional but uses mixed patterns inherited from V1. There is no declarative “zone map” describing:

Which panel loads where

Layout rules

Parent-child container relationships

Order of stage cards

Resizing/weight behavior

This PR introduces a single source of truth ZoneMap and updates all V2 GUI panels to obey it.

2. Allowed Files

src/gui/main_window_v2.py

src/gui/layout_v2.py

src/gui/panels_v2/sidebar_panel_v2.py

src/gui/panels_v2/stage_cards_panel_v2.py

src/gui/views/prompt_tab_frame_v2.py

src/gui/views/pipeline_tab_frame_v2.py

src/gui/views/learning_tab_frame_v2.py

New: src/gui/zone_map_v2.py

3. Forbidden Files

src/main.py

src/pipeline/*

Controller (app_controller.py)

All V1 GUI (src/gui/*.py without _v2)

Design system files (PR-041 series)

4. Implementation Details
4.1 Add zone_map_v2.py

Define:

ZONE_MAP = {
  "root": {
    "prompt_tab": {...},
    "pipeline_tab": {
        "left": "sidebar_panel_v2",
        "center": "stage_cards_panel_v2",
        "right": "preview_panel_v2"
    },
    "learning_tab": {...}
  }
}


This becomes the authoritative placement map.

4.2 Update main_window_v2.py & layout_v2.py

Replace any ad-hoc layout logic with zone map lookups.

Implement helper:

build_gui_from_zonemap(root, ZONE_MAP)


All V2 widgets are inserted according to the declarative map.

4.3 Cleanup Old V1 Behaviors

Remove dead layout helpers in V2 files that mimic V1 patterns.

Remove old panel creation ordering scattered across modules.

Ensure weight configuration (row/column) is centralized.

4.4 Enforce Card Order Rules

Stage cards panel:

Read order from zone map:

ZONE_MAP["root"]["pipeline_tab"]["center"]["stages_order"]


Cards appear in deterministic order defined by map.

5. Tests

Add:

tests/gui_v2/test_zone_map_v2.py

Asserts correct parent containers

Asserts correct tab → panel → card structure

tests/gui_v2/test_zone_map_card_order_v2.py

6. Definition of Done

Zone map exists and is respected.

No stray ad-hoc GUI wiring remains.

All containers resolved through a single map.

Stage card ordering is deterministic.

GUI boots cleanly using only the new pattern.