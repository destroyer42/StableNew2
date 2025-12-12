# PR-04 — Theme Engine V2 (ASWF Dark Theme)

## Summary

Implement a centralized **Theme Engine V2** for the StableNew GUI that:

- Restores a **dark, ASWF-inspired visual style** (black/gold, modern, flat).  
- Standardizes fonts, colors, paddings, and widget styles across the app.  
- Removes scattered ad-hoc styling from individual panels.  
- Provides a clean API for future panels/widgets to use consistent styles.

This PR focuses on **styling and visual consistency**, not on layout restructuring (handled in PR-05) or functional features.

---

## Goals

1. Define a single **theme module** for V2 GUI (e.g. `src/gui/theme_v2.py`).  
2. Apply the theme during GUI bootstrap so **all ttk widgets share a coherent style**.  
3. Provide **named styles** for primary/secondary buttons, panels, headings, input fields, status indicators, etc.  
4. Use a dark, modern palette that matches the intended StableNew/ASWF look.

---

## Non-Goals

- Changing widget layout or grid weights (PR-05).  
- Refactoring widgets into components (PR-06).  
- Implementing per-theme switching (light vs dark) — this PR delivers the dark theme only.  
- Rebranding or altering logos/imagery.

---

## Design Overview

The theme engine is **one module** that:

- Owns the **color palette**, **font choices**, and **spacing constants**.  
- Configures a `ttk.Style` object with named styles such as:
  - `Primary.TButton`, `Secondary.TButton`, `TLabel`, `Heading.TLabel`  
  - `Panel.TFrame`, `Card.TFrame`, `StatusBar.TFrame`  
  - `TEntry`-like styles (for dark backgrounds)  
- Exposes a single entrypoint:

```python
def apply_theme(root: tk.Tk) -> None: ...
```

which is called from `MainWindowV2._configure_root()` or similar.

The theme module should be **independent of business logic** — it simply sets visual properties on standard Tk/ttk styles.

---

## Implementation Plan

### Step 1 — Create `src/gui/theme_v2.py`

Add a new module (if not already present) with a clear API and internal helpers.

Skeleton:

```python
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


# ---- Palette ----

BACKGROUND_DARK = "#121212"
BACKGROUND_ELEVATED = "#1E1E1E"
BORDER_SUBTLE = "#2A2A2A"

TEXT_PRIMARY = "#FFFFFF"
TEXT_MUTED = "#CCCCCC"
TEXT_DISABLED = "#777777"

ACCENT_GOLD = "#FFC805"
ACCENT_GOLD_HOVER = "#FFD94D"

ERROR_RED = "#FF4D4F"
SUCCESS_GREEN = "#52C41A"
INFO_BLUE = "#40A9FF"


# ---- Fonts ----

DEFAULT_FONT_FAMILY = "Segoe UI"
DEFAULT_FONT_SIZE = 10
HEADING_FONT_SIZE = 11
MONO_FONT_FAMILY = "Consolas"


def apply_theme(root: tk.Tk) -> None:
    """Apply the StableNew V2 dark theme to the given Tk root.

    This configures ttk.Style with named styles that the V2 GUI can use.
    """
    style = ttk.Style(master=root)

    # Use a dark base theme if available, otherwise start from 'clam'
    try:
        style.theme_use("alt")
    except tk.TclError:
        style.theme_use("clam")

    _configure_global_colors(root)
    _configure_fonts(root)
    _configure_panel_styles(style)
    _configure_button_styles(style)
    _configure_label_styles(style)
    _configure_entry_styles(style)
    _configure_treeview_styles(style)
    _configure_statusbar_styles(style)


def _configure_global_colors(root: tk.Tk) -> None:
    root.configure(bg=BACKGROUND_DARK)


def _configure_fonts(root: tk.Tk) -> None:
    # Global default font
    root.option_add("*Font", f"{DEFAULT_FONT_FAMILY} {DEFAULT_FONT_SIZE}")
    root.option_add("*TEntry.Font", f"{DEFAULT_FONT_FAMILY} {DEFAULT_FONT_SIZE}")
    root.option_add("*Text.Font", f"{DEFAULT_FONT_FAMILY} {DEFAULT_FONT_SIZE}")
    root.option_add("*Treeview.Font", f"{DEFAULT_FONT_FAMILY} {DEFAULT_FONT_SIZE}")
    root.option_add("*TNotebook.Tab.Font", f"{DEFAULT_FONT_FAMILY} {DEFAULT_FONT_SIZE}")
    root.option_add("*Heading.Font", f"{DEFAULT_FONT_FAMILY} {HEADING_FONT_SIZE} bold")


def _configure_panel_styles(style: ttk.Style) -> None:
    style.configure(
        "Panel.TFrame",
        background=BACKGROUND_DARK,
        borderwidth=0,
    )
    style.configure(
        "Card.TFrame",
        background=BACKGROUND_ELEVATED,
        borderwidth=1,
        relief="solid",
        bordercolor=BORDER_SUBTLE,
    )


def _configure_button_styles(style: ttk.Style) -> None:
    style.configure(
        "Primary.TButton",
        background=ACCENT_GOLD,
        foreground="#000000",
        borderwidth=0,
        focusthickness=1,
        focustcolor=ACCENT_GOLD_HOVER,
        padding=(8, 4),
    )
    style.map(
        "Primary.TButton",
        background=[("active", ACCENT_GOLD_HOVER), ("disabled", BORDER_SUBTLE)],
        foreground=[("disabled", TEXT_DISABLED)],
    )

    style.configure(
        "Secondary.TButton",
        background=BORDER_SUBTLE,
        foreground=TEXT_PRIMARY,
        borderwidth=0,
        padding=(8, 4),
    )
    style.map(
        "Secondary.TButton",
        background=[("active", BACKGROUND_ELEVATED), ("disabled", BORDER_SUBTLE)],
        foreground=[("disabled", TEXT_DISABLED)],
    )


def _configure_label_styles(style: ttk.Style) -> None:
    style.configure(
        "TLabel",
        background=BACKGROUND_DARK,
        foreground=TEXT_PRIMARY,
    )
    style.configure(
        "Muted.TLabel",
        background=BACKGROUND_DARK,
        foreground=TEXT_MUTED,
    )
    style.configure(
        "Heading.TLabel",
        background=BACKGROUND_DARK,
        foreground=TEXT_PRIMARY,
        font=f"{DEFAULT_FONT_FAMILY} {HEADING_FONT_SIZE} bold",
    )


def _configure_entry_styles(style: ttk.Style) -> None:
    style.configure(
        "TEntry",
        fieldbackground=BACKGROUND_ELEVATED,
        foreground=TEXT_PRIMARY,
        borderwidth=1,
        relief="solid",
    )
    style.map(
        "TEntry",
        fieldbackground=[("disabled", BACKGROUND_ELEVATED), ("readonly", BACKGROUND_ELEVATED)],
        foreground=[("disabled", TEXT_DISABLED)],
    )


def _configure_treeview_styles(style: ttk.Style) -> None:
    style.configure(
        "Treeview",
        background=BACKGROUND_ELEVATED,
        fieldbackground=BACKGROUND_ELEVATED,
        foreground=TEXT_PRIMARY,
        borderwidth=0,
    )
    style.configure(
        "Treeview.Heading",
        background=BACKGROUND_DARK,
        foreground=TEXT_PRIMARY,
    )


def _configure_statusbar_styles(style: ttk.Style) -> None:
    style.configure(
        "StatusBar.TFrame",
        background=BACKGROUND_ELEVATED,
        borderwidth=1,
        relief="solid",
        bordercolor=BORDER_SUBTLE,
    )
    style.configure(
        "StatusBar.TLabel",
        background=BACKGROUND_ELEVATED,
        foreground=TEXT_MUTED,
    )
```

> CODEX should reconcile these constants with any existing theme or color definitions if they already exist in the repo.

### Step 2 — Apply Theme During V2 Bootstrap

In `src/gui/main_window_v2.py` (or whatever the V2 entrypoint module is), ensure the theme is applied once, early in initialization.

Example:

```python
from src.gui.theme_v2 import apply_theme

class MainWindowV2:
    def __init__(..., root: tk.Tk, ...):
        self.root = root

        apply_theme(self.root)
        self._configure_root()
        self._build_frames()
        self._compose_layout()
```

If there is an existing theming mechanism, CODEX should adapt it to **delegate** to `theme_v2.apply_theme` instead of scattering style config across modules.

### Step 3 — Update Core Panels to Use Named Styles

Update major panels to use named styles instead of default `ttk` look.

Examples:

- Sidebar:

```python
self.container = ttk.Frame(parent, style="Panel.TFrame")
```

- Cards / sections:

```python
self.card = ttk.Frame(parent, style="Card.TFrame")
heading = ttk.Label(self.card, text="Prompt", style="Heading.TLabel")
```

- Primary action buttons (e.g., “Run”, “Plan Experiment”):

```python
self.run_button = ttk.Button(parent, text="Run", style="Primary.TButton", command=self._on_run)
```

- Secondary buttons (“Reset”, “Open Folder”):

```python
self.reset_button = ttk.Button(parent, text="Reset", style="Secondary.TButton")
```

- Status bar:

```python
self.status_frame = ttk.Frame(root, style="StatusBar.TFrame")
self.status_label = ttk.Label(self.status_frame, style="StatusBar.TLabel", text="Ready")
```

This PR does **not** need to touch every single panel; prioritize:

- Status bar  
- Main Run/Controls area  
- Prompt editor container  
- Sidebar sections  
- Job queue / treeview background + heading

### Step 4 — Remove/Unify Ad-hoc Styling

Search for places where panels currently:

- Set their own background colors directly on frames/labels (`bg=...` on `tk` widgets).  
- Set fonts individually with `font=...` on every widget.

For each such instance:

- Replace `tk.Label`/`tk.Frame` with `ttk.Label`/`ttk.Frame` where possible and use named styles.  
- Keep `tk.Text` where necessary (for multi-line prompt entry), but align background/foreground with theme constants by importing from `theme_v2`.

Example for prompt text widgets:

```python
from src.gui import theme_v2

self.prompt_text = tk.Text(
    parent,
    bg=theme_v2.BACKGROUND_ELEVATED,
    fg=theme_v2.TEXT_PRIMARY,
    insertbackground=theme_v2.TEXT_PRIMARY,  # caret color
)
```

### Step 5 — Add a Simple “Theme Self-Test” Helper (Optional)

Add a tiny helper function in `theme_v2.py` or a small test module to ensure:

- `apply_theme` does not raise.  
- Expected styles are present in `ttk.Style().theme_names()` / `style.layout(style_name)`.

This can be a simple unit test to catch regressions when theme changes in the future.

---

## Files Expected to Change / Be Added

**New:**

- `src/gui/theme_v2.py` (if not already present, or normalized to this structure)

**Updated:**

- `src/gui/main_window_v2.py` (to call `apply_theme`)  
- Key V2 GUI panels to use named styles:
  - `src/gui/sidebar_panel_v2.py`
  - `src/gui/pipeline_panel_v2.py`
  - `src/gui/preview_panel_v2.py`
  - `src/gui/status_bar_v2.py`
  - `src/gui/webui_controls_panel_v2.py` (from PR-00A)
  - Any other high-visibility panel

No changes to:

- Archived V1 GUI modules  
- Pipeline logic, controllers, learning system

---

## Tests & Validation

1. **Manual Visual Check**
   - Run `python -m src.main`.  
   - Confirm:
     - Background is dark across the main application.  
     - Primary buttons (e.g., Run) are gold with readable text.  
     - Panels use consistent, subtle borders.  
     - Status bar looks visually distinct from the main body.  

2. **Widget Sanity**
   - Interact with prompts, buttons, job queue, etc.  
   - Ensure there are no unreadable text areas (e.g., dark text on dark background).  
   - Confirm disabled/readonly states still look legible.

3. **Automated Tests (Lightweight)**
   - Add/extend a test under `tests/gui_v2` that:
     - Creates a `tk.Tk()` in a safe/headless mode.  
     - Calls `apply_theme(root)`.  
     - Asserts that key styles exist (`Primary.TButton`, `Panel.TFrame`, `StatusBar.TFrame`).  
   - Run `pytest tests/gui_v2 -v` and confirm pass.

---

## Acceptance Criteria

- `theme_v2.apply_theme` exists and is called during V2 GUI startup.  
- Major panels and controls use named theme styles instead of ad-hoc per-widget styling.  
- The GUI appears in a coherent dark ASWF-style theme (no large patches of default gray/white remaining in primary areas).  
- GUI tests still pass after the theme refactor, and a small theme sanity test exists to guard against regression.
