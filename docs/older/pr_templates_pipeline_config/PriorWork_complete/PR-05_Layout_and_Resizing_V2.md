# PR-05 — V2 Layout & Resizing Fix (De-Squish the GUI)

## Summary

The current V2 GUI **runs**, but the layout is visually broken:

- Panels are cramped or “squished” into corners.
- Large regions of unused whitespace exist (especially in “dark mode”).
- Resizing the window does not correctly redistribute space between sidebar, pipeline, and preview.
- Some content feels jammed or overlapping at default window size.

This PR focuses on **layout and resizing only** for the V2 GUI:

- Fix root grid configuration (rows, columns, weights, min sizes).
- Ensure each main region (sidebar, pipeline, preview, status) has a sensible footprint.
- Apply consistent padding and spacing rules so the UI looks intentional, not accidental.
- Set a reasonable **default window size** so the app is usable upon launch.

> This PR is strictly about layout and resizing. It does **not** archive files, alter business logic, or add new features.

---

## Goals

1. Make the V2 GUI **usable and readable** at startup without manual resizing.  
2. Ensure **resizing the window** correctly resizes the main panels.  
3. Apply **consistent spacing** (padding/margins) so the UI is not cramped or scattered.  
4. Keep all wiring and functional behavior unchanged (no new logic).

---

## Non-Goals

- No new features or controls.  
- No major theming changes (PR-04 handles colors/typography; this PR complements it).  
- No refactor of which panels exist or what they do.  
- No file moves, deletions, or archiving.

---

## Pre-Requisites

This PR assumes:

- **PR-03 (V2 App Spine)** is implemented:
  - `MainWindowV2` exists and composes the main frames.
  - `AppStateV2` / `layout_v2` helpers exist.
  - `src/main.py` launches the V2 window by default.

- **PR-04 (Theme Engine V2)** is at least partially applied:
  - Panels use `Panel.TFrame` / `Card.TFrame` styles.
  - Basic dark theme is visible.

If these are not fully in place, CODEX should adjust this PR to work against the current `main_window` but keep the same intent (fix root grid, panel frames, and resizing).

---

## Design Overview

The V2 window is structured into these major areas:

- **Sidebar** (left): packs, config, maybe quick access controls.
- **Pipeline** (center): main run controls, pipelines/stage options.
- **Preview / Output** (right): image previews, history, queue, etc.
- **Status Bar** (bottom): status text and WebUI controls.

We will:

1. Create a **clear root grid**:  
   - Columns: sidebar (fixed-ish), pipeline (flex), preview (flex).  
   - Rows: main content (flex), status bar (fixed).

2. Ensure each area has a proper container frame that:  
   - Uses `grid` with the correct weight.  
   - Is padded from the root edges.  
   - Fills its space without being jammed.

3. Normalize common padding + spacing constants to avoid ad-hoc pixel placements.

---

## Implementation Plan

### Step 1 — Root Grid & Default Sizing

In `src/gui/main_window_v2.py` (or the equivalent V2 main window module):

1. **Configure the root window size and minsize** in `_configure_root`:

```python
def _configure_root(self) -> None:
    self.root.title("StableNew V2")

    # Reasonable default size; adjust if needed after visual check
    self.root.geometry("1400x850")
    self.root.minsize(1024, 700)

    # Root grid: 2 rows (content + status), 3 columns (sidebar, pipeline, preview)
    self.root.rowconfigure(0, weight=1)   # main content row
    self.root.rowconfigure(1, weight=0)   # status bar row

    self.root.columnconfigure(0, weight=0, minsize=260)  # sidebar
    self.root.columnconfigure(1, weight=3, minsize=500)  # pipeline
    self.root.columnconfigure(2, weight=2, minsize=400)  # preview
```

2. This ensures:
   - Sidebar stays reasonably narrow.  
   - Pipeline gets the majority of the width.  
   - Preview gets significant but secondary width.  
   - Status bar stays at the bottom and doesn’t gobble height.

If `layout_v2.configure_root_grid(root)` already exists from PR-03, CODEX should **move these decisions into that helper** and have `_configure_root` simply call it.

### Step 2 — Top-Level Frames & Padding

Ensure `MainWindowV2._build_frames()` and `_compose_layout()` treat each major area as a **grid cell with inner padding**.

Example:

```python
def _build_frames(self) -> None:
    self.sidebar_frame = ttk.Frame(self.root, style="Panel.TFrame")
    self.pipeline_frame = ttk.Frame(self.root, style="Panel.TFrame")
    self.preview_frame = ttk.Frame(self.root, style="Panel.TFrame")
    self.status_frame = ttk.Frame(self.root, style="StatusBar.TFrame")
```

In `_compose_layout`:

```python
def _compose_layout(self) -> None:
    # Top-level frames in root grid
    self.sidebar_frame.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=(8, 4))
    self.pipeline_frame.grid(row=0, column=1, sticky="nsew", padx=4, pady=(8, 4))
    self.preview_frame.grid(row=0, column=2, sticky="nsew", padx=(4, 8), pady=(8, 4))

    self.status_frame.grid(row=1, column=0, columnspan=3, sticky="ew", padx=8, pady=(0, 8))

    # Allow frames to expand within their grid cells
    self.sidebar_frame.rowconfigure(0, weight=1)
    self.sidebar_frame.columnconfigure(0, weight=1)

    self.pipeline_frame.rowconfigure(0, weight=1)
    self.pipeline_frame.columnconfigure(0, weight=1)

    self.preview_frame.rowconfigure(0, weight=1)
    self.preview_frame.columnconfigure(0, weight=1)
```

This removes the “floating” feel and ensures each main panel has breathable margins.

### Step 3 — Panel Internal Layouts

Within each of the major frames, ensure that their internal content uses `pack(fill="both", expand=True)` or a proper `grid` with weights.

Examples:

- `SidebarPanelV2`:

```python
# in SidebarPanelV2.__init__ or build method
self.container = ttk.Frame(self, style="Panel.TFrame")
self.container.pack(fill="both", expand=True, padx=4, pady=4)
```

- `PipelinePanelV2`:

```python
self.container = ttk.Frame(self, style="Panel.TFrame")
self.container.pack(fill="both", expand=True, padx=4, pady=4)
```

- `PreviewPanelV2`:

```python
self.container = ttk.Frame(self, style="Panel.TFrame")
self.container.pack(fill="both", expand=True, padx=4, pady=4)
```

If a panel uses `grid` internally:
- Make sure its **internal rows/columns have weights set correctly.**
- Avoid mixing `grid` and `pack` in the same container.

### Step 4 — Status Bar & WebUI Controls Layout

The status bar often looks especially broken if not laid out carefully.

Inside `StatusBarV2` + `WebUIControlsPanel` (from PR-00A):

- Ensure the status bar frame uses a horizontal layout where:
  - The left side is status text (expands).  
  - The right side holds WebUI controls.

Example in `MainWindowV2._build_frames()` / `_compose_layout()`:

```python
# inside status_frame
self.status_bar.pack(side="left", fill="x", expand=True, padx=(4, 0), pady=2)
self.webui_controls.pack(side="right", padx=(0, 4), pady=2)
```

Make sure `StatusBar.TFrame` has a subtle border and slightly raised background (handled in PR-04’s theme).

### Step 5 — Scrollable Areas (Optional but Recommended)

Some panels (e.g., pipeline, history, packs) may need scrolling when the window is small.

In this PR, we don’t need to implement all scroll patterns, but we **should not break existing scrollbars**. Where scrollable frames already exist:

- Ensure their container frames are allocated enough space:
  - They should be in grid cells with `weight=1` or in `pack(fill="both", expand=True)`.
- Avoid placing scrollable frames inside zero-weight parents.

If time allows, CODEX can normalize scrollable areas to a helper pattern, but this is not strictly required for this PR.

---

## Files Expected to Change

**Updated:**

- `src/gui/main_window_v2.py` (or the current V2 main window module)
  - `_configure_root` (window sizing + root grid)
  - `_build_frames` (use `Panel.TFrame` / `StatusBar.TFrame`)
  - `_compose_layout` (pad, grid weights, sticky flags)

- `src/gui/layout_v2.py`
  - If root grid configuration lives here, port the new size/weights logic into it.
  - Optionally add helpers for standard padding.

- Key V2 panels (layout only, no logic changes):
  - `src/gui/sidebar_panel_v2.py`
  - `src/gui/pipeline_panel_v2.py`
  - `src/gui/preview_panel_v2.py`
  - `src/gui/status_bar_v2.py`
  - `src/gui/webui_controls_panel_v2.py` (if spacing adjustments are needed)

No new files. No files are deleted or moved.

---

## Tests & Validation

### Manual Validation

1. **Startup Check**
   - Run `python -m src.main`.
   - Confirm:
     - Window opens at ~1400x850 (or your chosen default).
     - Sidebar has a reasonable fixed-ish width.
     - Pipeline controls are fully visible (no major overlap, no tiny strip).
     - Preview panel has a visible usable area.
     - Status bar is visible but not huge.

2. **Resize Behavior**
   - Resize window narrower and wider.
   - Confirm:
     - Sidebar width is relatively stable but not exploding.
     - Pipeline and preview grow/shrink appropriately.
     - Status bar remains at the bottom.

3. **Visual Sanity with Theme Applied**
   - Confirm that panel paddings (8px outer, ~4px inner) look intentional.
   - Confirm there are no big white/gray TK defaults showing up where we expect dark panels.

### Automated Validation

- Run existing GUI tests:

  ```bash
  pytest tests/gui_v2 -v
  ```

- Optional: add a small smoke test that creates a `Tk` root, instantiates `MainWindowV2`, and immediately destroys it to catch layout-related exceptions.

---

## Acceptance Criteria

- On startup, the V2 GUI is **readable and not squished**:
  - Sidebar, pipeline, and preview all have visible, usable space.
- Resizing the window causes panels to resize in a **predictable, intentional way**.
- Status bar and WebUI controls are visible and well-positioned at the bottom.
- No changes to business logic or pipelines; only layout and sizing adjustments.
- All existing GUI V2 tests continue to pass.
