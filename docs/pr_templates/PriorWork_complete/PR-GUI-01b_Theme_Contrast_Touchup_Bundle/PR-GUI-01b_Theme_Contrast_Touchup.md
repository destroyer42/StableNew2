PR-GUI-01b: Theme Contrast Touch-Up (Ghost Buttons & Status Hierarchy)
=====================================================================

1. Title
--------
Refine Tk/Ttk theme contrast for ghost buttons and status labels (PR-GUI-01b: Theme Contrast Touch-Up).

2. Summary
----------
PR-GUI-01 introduced a centralized theme module (`src/gui/theme.py`) and applied it to the v2 GUI header and status bar. It successfully styled the Run and Stop buttons and wired a dark-base theme, but the initial contrast choices made:

- Preview/Settings/Help buttons appear like plain text on a dark background (weak affordance).
- `Status: Idle` visually as strong as the primary actions (Run/Stop), competing for attention.

PR-GUI-01b makes **small, surgical adjustments to `theme.py` only** to:
- Make ghost buttons clearly look clickable.
- Clarify the hierarchy between main status (`Status: Idle`) and secondary status (`API: Unknown`).

This PR does not change layout, behavior, wiring, or any other modules.
