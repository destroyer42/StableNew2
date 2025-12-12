PR-GUI-02: LeftZone Layout Polish (Preset Row & Card Structure)
===============================================================

1. Title
--------
Polish the LeftZone layout in MainWindow_v2 to fix the overlapping "Preset:" row and introduce a clean card structure (PR-GUI-02: LeftZone Layout Polish).

2. Summary
----------
After PR-0.1 and PR-GUI-01, the v2 GUI is stable and themed, but the LeftZone still has a visually awkward “Preset:” label overlapping a dropdown. This is a legacy artifact and does not match the intended card-based layout.

PR-GUI-02 makes a small, layout-only adjustment to:

- Group preset controls in a dedicated LeftZone card/frame.
- Arrange the “Preset:” label and dropdown without overlap using a simple grid.
- Keep behavior unchanged.
