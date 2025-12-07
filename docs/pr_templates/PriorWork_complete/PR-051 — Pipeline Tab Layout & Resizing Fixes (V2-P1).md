PR-051 — Pipeline Tab Layout & Resizing Fixes (V2-P1)
Summary

The Pipeline tab’s layout is currently unstable: the top bar does not remain compact, the logging/status area does not expand as the window grows, and the three columns (left, stage cards, right) do not resize proportionally. This PR stabilizes the layout, introduces proper grid weights, and ensures a predictable vertical and horizontal resizing experience.

Goals

Make the Pipeline tab behave like a modern 3-column layout.

Logging panel expands vertically when window height increases.

Left/center/right columns resize proportionally on window width changes.

Window opens at a usable default size without immediate manual resizing.

Allowed Files

src/gui/views/pipeline_tab_frame_v2.py

src/gui/widgets/scrollable_frame_v2.py

src/gui/scrolling.py

Forbidden Files

src/gui/main_window_v2.py

src/main.py

Any controller, pipeline, API, or non-GUI modules.

Implementation Plan
1. Fix Pipeline Tab grid structure

Ensure pipeline_tab_frame_v2.py defines:

Row 0: Main 3-column content (weight=1)
Row 1: Logging/status panel (weight=1 or 2)


Columns:

Col 0: Sidebar (weight=1, minsize≈200)
Col 1: Stage cards (weight=2, minsize≈350)
Col 2: Preview/history (weight=1, minsize≈250)

2. Logging panel behavior

Logging/status frame becomes sticky in row 1.

Should expand vertically when window grows.

3. Scrollable columns

Ensure scrollable frames in each column have:

sticky="nsew"

Proper canvas/inner frame weight behavior.

4. Mousewheel

Register mousewheel scrolling for:

Left column scrollable region

Stage cards scroll region

Preview/history scroll region

Validation
Tests

Add/extend:

tests/gui_v2/test_pipeline_tab_layout_v2.py

Assert correct grid weights.

Assert logging panel occupies bottom row.

Assert columns retain minimum widths.

Manual Checks

Resize window vertically → logging panel grows.

Resize window horizontally → all three columns resize proportionally.

Definition of Done

Pipeline tab resizes cleanly.

Logging panel expands correctly.

No regressions in stage card display.

GUI boots without layout warnings.