Codex Execution Guide for PR-GUI-01b: Theme Contrast Touch-Up
=============================================================

Purpose
-------
You are refining the Tk/Ttk theme introduced in PR-GUI-01 to improve ghost button affordance and status label hierarchy. This is a **tiny, visual-only** adjustment.

High-level Rules
----------------
- Only edit `src/gui/theme.py`.
- Do not touch any other files.
- Do not change widget behavior or wiring; only visual styles.

Step-by-step Instructions
-------------------------

1. Open `src/gui/theme.py` and locate `configure_style(root)`.
2. Improve `Ghost.TButton`:
   - Use a clearer foreground color (e.g., main text color).
   - Add a subtle border or slightly different background.
   - Ensure the `"active"` state lightens the background a bit so it feels clickable.
3. Clarify status labels:
   - `StatusStrong.TLabel` → primary text color, calm (label-like, not button-like).
   - `Status.TLabel` → muted text color for secondary status.
4. Run `pytest tests/controller/test_app_controller_pipeline_flow_pr0.py -v` to confirm nothing broke.
5. Ask the human to visually confirm ghost buttons and status labels feel better.

What You Must NOT Do
--------------------
- Do not edit any file besides `src/gui/theme.py`.
- Do not change any commands, logic, or layout.
