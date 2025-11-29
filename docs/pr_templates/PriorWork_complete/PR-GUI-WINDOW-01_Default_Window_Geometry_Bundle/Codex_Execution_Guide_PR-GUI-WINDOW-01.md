Codex Execution Guide for PR-GUI-WINDOW-01: Default Window Geometry & LeftZone Width
====================================================================================

Purpose
-------
You are implementing PR-GUI-WINDOW-01 to make the StableNew v2 GUI window open at a more practical size and give the LeftZone enough width to display pack names clearly.

Scope
-----
You may only modify:

- `src/gui/main_window_v2.py`

Implementation Steps
--------------------
1. Set a larger default geometry for the Tk root (e.g., 1200x800) and an appropriate minimum size.
2. Adjust the main grid column weights so LeftZone keeps a stable width, while Center/Right expand.
3. Ensure the LeftZone Pack list and Preset combobox use `sticky="ew"` and a column with `weight=1` so they fill available width.
4. Run `pytest tests/controller/test_app_controller_pipeline_flow_pr0.py -v`.
5. Ask the human to visually confirm that the window opens larger and pack names are more readable, while behavior is unchanged.
