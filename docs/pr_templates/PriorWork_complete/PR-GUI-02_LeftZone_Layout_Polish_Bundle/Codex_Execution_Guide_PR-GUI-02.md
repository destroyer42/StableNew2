Codex Execution Guide for PR-GUI-02: LeftZone Layout Polish
===========================================================

Purpose
-------
Fix the overlapping "Preset:" label/dropdown and introduce a simple card container for preset controls in the LeftZone of `MainWindow_v2`.

Scope
-----
- Modify `src/gui/main_window_v2.py` only (or add a tiny LeftZone helper module if needed).
- No controller/pipeline/theme/test changes.

Steps
-----
1. Inspect how the LeftZone and the “Preset:” widgets are currently created and placed.
2. Add a dedicated preset card frame inside the LeftZone (e.g., `self.left_zone_preset_frame = ttk.Frame(..., padding=...)`).
3. Move the “Preset:” label and combobox into this frame.
4. Use a simple grid:
   - Label above combobox (two rows), or
   - Label and combobox on the same row with two columns.
5. Ensure there is no overlap by using proper row/column indices and padding.
6. Keep all commands/behavior unchanged.
7. Run `pytest tests/controller/test_app_controller_pipeline_flow_pr0.py -v` to confirm logic is intact.
8. Ask the human to visually confirm that the Preset row looks clean in the LeftZone.

Do NOT
------
- Touch controller, pipeline, API, theme, or tests.
- Add new features or change behavior.
