# PR-05A — V2 Scrollable Areas (Make Panels Usable on Smaller Screens)

## Summary

With the V2 spine, theme engine, and baseline layout in place (PR-03, PR-04, PR-05), the app now:

- boots into a proper V2 window,
- looks like a dark, modern application, and
- resizes logically between sidebar / pipeline / preview.

However, some panels still become **cramped or unusable on smaller windows** because their content has no scroll support (or scrollbars are wired inconsistently). This PR focuses on:

- Ensuring key V2 panels become **scrollable where appropriate**, and
- Normalizing the scroll pattern so it’s consistent across the app.

> This PR does **not** change business logic or “what” is displayed, only **how** the content is wrapped and scrolled.

---

## Goals

1. Make key V2 panels usable on smaller and medium-sized displays by adding scrollable containers.  
2. Use a **consistent scroll pattern** (same helper, same structure) to avoid ad-hoc scrollbar hacks.  
3. Ensure scrollbars do not break layout or theming (respect `theme_v2` styles and PR-05 layout).  
4. Keep all existing widgets and logic intact, only re-parented into scrollable frames where needed.

---

## Non-Goals

- No new functional features (no new controls, no new data).  
- No changes to pipeline/queue behavior.  
- No deletion or archiving of any GUI modules.  
- No wholesale redesign of panels — we are wrapping existing content into scrollable shells.

---

## Target Panels for Scrolling

Focus on V2 panels that naturally accumulate content and can overflow on smaller resolutions:

- `SidebarPanelV2`
  - Packs, config tiles, or multiple sections stacked vertically.
- `PipelinePanelV2`
  - Multiple stages / controls, multiple buttons, advanced options.
- `PreviewPanelV2`
  - Image preview + metadata + history (if applicable).
- Optionally: any V2 job/history list or detailed inspector panel if they are not already scrollable.

> Do **not** add scrollbars to small, self-contained widgets where scrolling would be confusing (e.g., a tiny button bar).

---

## Design Overview

We will introduce a reusable **“scrollable frame” helper** and apply it consistently.

Pattern:

```text
Outer TFrame (styled, placed in grid)
└── Canvas
    ├── Inner TFrame (actual content)
    └── Vertical Scrollbar
```

The panel’s existing content will be moved into the inner frame. The outer frame will handle sizing and scrolling.

We also ensure:

- Mouse wheel scrolling works when hovered.  
- Theme colors apply to the canvas + scrollbar background.  
- Scroll region updates if content size changes.

---

## Implementation Plan

### Step 1 — Add a ScrollableFrame Helper

Create a helper class in a new module, for example:

```text
src/gui/widgets/scrollable_frame_v2.py
```

Skeleton:

```python
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class ScrollableFrame(ttk.Frame):
    """Reusable scrollable frame for V2 panels.

    Provides a vertical scrollbar and a canvas containing a single inner frame
    where content can be packed or gridded.
    """

    def __init__(self, master: tk.Misc, *, style: str | None = None, **kwargs) -> None:
        super().__init__(master, style=style, **kwargs)

        self._canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self._canvas.grid(row=0, column=0, sticky="nsew")

        self._vsb = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._vsb.grid(row=0, column=1, sticky="ns")

        self._canvas.configure(yscrollcommand=self._vsb.set)

        # Inner frame that actual content lives in
        self.inner = ttk.Frame(self._canvas)
        self._inner_window = self._canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        self._bind_mousewheel_events()

    def _on_inner_configure(self, event: tk.Event) -> None:
        # Update scrollregion to match inner frame size
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        # Make the inner frame width follow the canvas width
        canvas_width = event.width
        self._canvas.itemconfigure(self._inner_window, width=canvas_width)

    def _bind_mousewheel_events(self) -> None:
        # Basic mousewheel binding (platform differences can be handled later)
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event: tk.Event) -> None:
        # Windows / most platforms: event.delta is a multiple of 120
        delta = int(-1 * (event.delta / 120))
        self._canvas.yview_scroll(delta, "units")
```

> Note: CODEX should adapt mousewheel binding for Linux / macOS if needed, but simple Windows behavior is sufficient for this PR.

### Step 2 — Apply ScrollableFrame to SidebarPanelV2

In `src/gui/sidebar_panel_v2.py`:

1. Import the helper:

   ```python
   from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame
   ```

2. Wrap existing content:

   - Replace the panel’s direct content container with `ScrollableFrame`.

   Example:

   ```python
   class SidebarPanelV2(ttk.Frame):
       def __init__(self, master, app_state, **kwargs):
           super().__init__(master, **kwargs)

           self._scroll = ScrollableFrame(self, style="Panel.TFrame")
           self._scroll.pack(fill="both", expand=True, padx=4, pady=4)

           # Use self._scroll.inner as the parent for existing widgets
           self._build_content(parent=self._scroll.inner)
   ```

3. Update `_build_content` (or similar) to accept `parent` and attach widgets to that instead of `self`.

This makes the sidebar scroll when its content exceeds available vertical space.

### Step 3 — Apply ScrollableFrame to PipelinePanelV2

In `src/gui/pipeline_panel_v2.py`:

- Use the same pattern as sidebar:

```python
self._scroll = ScrollableFrame(self, style="Panel.TFrame")
self._scroll.pack(fill="both", expand=True, padx=4, pady=4)
self._build_content(parent=self._scroll.inner)
```

- Ensure stage configurations, main run controls, and any advanced options attach to `parent` (inner frame).

This allows pipelines with many options to remain usable even when the window is smaller.

### Step 4 — Apply ScrollableFrame to PreviewPanelV2 (Where Appropriate)

In `src/gui/preview_panel_v2.py`:

- Determine which content needs scrolling:
  - If there is a single large image view, scrolling might not be ideal.  
  - If there are multiple thumbnails / history list + metadata, a scroll container is reasonable.

- For text/metadata/history sections, wrap the main content area in a `ScrollableFrame`:

```python
self._scroll = ScrollableFrame(self, style="Panel.TFrame")
self._scroll.pack(fill="both", expand=True, padx=4, pady=4)
self._build_content(parent=self._scroll.inner)
```

- For pure image canvases, you may leave them non-scrollable for now or defer to a later “image viewport” PR.

### Step 5 — Theme Integration

Ensure the scrollable areas respect `theme_v2`:

- Canvas background:
  - After `apply_theme` is called, set the canvas background color to `BACKGROUND_DARK` or `BACKGROUND_ELEVATED` from `theme_v2`.
- Optionally integrate scrollbar colors if desired, but keeping default ttk scrollbars is acceptable for this PR.

Example:

```python
from src.gui import theme_v2

self._canvas.configure(bg=theme_v2.BACKGROUND_DARK)
```

(Or `BACKGROUND_ELEVATED` depending on where it’s used.)

### Step 6 — Sanity Tests

Add or extend tests in `tests/gui_v2/` to:

- Create each panel (sidebar, pipeline, preview) within a `Tk` root in test mode.
- Ensure `ScrollableFrame` can be instantiated without exceptions.
- Optionally, assert that `panel._scroll.inner` exists and can accept children.

This doesn’t test visual behavior, but catches regressions in imports/wiring.

---

## Files Expected to Change / Be Added

**New:**

- `src/gui/widgets/scrollable_frame_v2.py` (or similar path)

**Updated (layout-only changes):**

- `src/gui/sidebar_panel_v2.py`
- `src/gui/pipeline_panel_v2.py`
- `src/gui/preview_panel_v2.py` (to the extent scroll is appropriate)
- Optionally `src/gui/theme_v2.py` (if color constants are imported into scrollable_frame_v2)

No changes to:

- Business logic or controllers.  
- Stage cards or pipeline execution.  
- Archiving or tests outside `tests/gui_v2/`.

---

## Tests & Validation

**Manual:**

1. Launch the app (`python -m src.main`).  
2. Resize the window smaller in height.  
3. Confirm:
   - Sidebar content can be scrolled vertically.  
   - Pipeline controls are scrollable and not cut off.  
   - Preview content that overflows is scrollable (where implemented).  

**Automated:**

- Run:

  ```bash
  pytest tests/gui_v2 -v
  ```

- Ensure all existing tests still pass and any new scrollability tests are green.

---

## Acceptance Criteria

- Sidebar and pipeline panels remain fully usable on smaller screens via vertical scrolling.  
- Scroll behavior is consistent and predictable across V2 panels.  
- No regressions to layout (PR-05) or theme (PR-04).  
- All GUI V2 tests pass.
