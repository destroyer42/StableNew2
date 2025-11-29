PR-GUI-WINDOW-01: Default Window Geometry & LeftZone Width
=========================================================

1. Title
--------
Improve default window size and LeftZone width so Pack names are readable (PR-GUI-WINDOW-01).

2. Summary
----------
The v2 GUI currently opens in a relatively narrow, short window. As a result:

- The LeftZone Pack list is cramped and many pack names are truncated.
- The overall layout feels more like a debug/skeleton window than a production-ready app.

We already have:

- A stable v2 entrypoint (MainWindow_v2 + AppController + DummyPipelineRunner).
- Themed header and status bar.
- A LeftZone Pack card that will soon (or now) display real pack names.

This PR adjusts **window geometry and grid weights only** so that:

- The default window opens wider and taller (more like the Figma layout).
- The LeftZone has enough width for typical pack names without excessive truncation.
- Resizing behavior remains sensible.

No new widgets, no behavior changes, and no pipeline/controller modifications.
