from __future__ import annotations

import tkinter as tk


def configure_root_grid(root: tk.Tk) -> None:
    """Configure a 3-row, 3-column grid for V2 GUI zones."""
    # Rows: header (0), main (1), status (2)
    root.rowconfigure(0, weight=0, minsize=48)  # header
    root.rowconfigure(1, weight=1, minsize=400)  # main content
    root.rowconfigure(2, weight=0, minsize=36)  # status

    # Columns: sidebar (0), pipeline (1), preview (2)
    root.columnconfigure(0, weight=0, minsize=260)  # sidebar
    root.columnconfigure(1, weight=3, minsize=500)  # pipeline/main
    root.columnconfigure(2, weight=2, minsize=400)  # preview
