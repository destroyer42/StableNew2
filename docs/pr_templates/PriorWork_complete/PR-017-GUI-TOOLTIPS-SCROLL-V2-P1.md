# PR-017-GUI-TOOLTIPS-SCROLL-V2-P1 — Tooltips & Scrolling Helpers (V2)

**Intent:**  
Reintroduce the **tooltip** and **scrolling helper** behaviors from the legacy GUI in a V2-aligned, modular way:

- Tooltips on key interactive controls (especially in Pipeline and Prompt tabs).
- Consistent scroll-wheel behavior in scrollable panels (Left zone lists, pipeline cards, etc.).
- No coupling to legacy `StableNewGUI` or archived modules.

---

## 1. Scope & Subsystems

**Subsystems touched:**

- GUI V2 (widgets, views)
- Utility helpers in GUI (tooltip, scrolling)

**Files to modify:**

- `src/gui/tooltip.py`
- `src/gui/scrolling.py`
- `src/gui/views/prompt_tab_frame_v2.py`
- `src/gui/views/pipeline_tab_frame_v2.py`
- `src/gui/views/learning_tab_frame_v2.py` (where appropriate)
- `src/gui/main_window_v2.py` (for global scroll wiring if needed)

---

## 2. High-Level Approach

- Keep **tooltip** and **scroll helpers** as small, reusable utilities.
- Use them directly in V2 views:

  - Prompt fields
  - Model/sampler dropdowns
  - Learning-related controls

- Avoid any type of “magic global” wiring; always pass widgets explicitly.

---

## 3. Detailed Changes

### 3.1 `src/gui/tooltip.py` — Modernize

Ensure a clean API:

```python
class Tooltip:
    def __init__(self, widget, text: str, *, delay_ms: int = 500):
        ...
```

- Attach `<Enter>` and `<Leave>` events to show/hide the tooltip.
- Use `tk.Toplevel` with a simple themed label.

Expose a helper:

```python
def attach_tooltip(widget, text: str) -> Tooltip:
    return Tooltip(widget, text=text)
```

### 3.2 `src/gui/scrolling.py` — Modern Scroll Helpers

Provide helpers:

```python
def enable_mousewheel(widget: tk.Widget) -> None:
    # Bind platform-sensitive mouse wheel events to scroll the widget.

def make_scrollable(parent, *, orient="vertical") -> tk.Widget:
    # Wrap a frame in a canvas+scrollbar pattern and return the inner frame.
```

Adapt to V2 use: ensure these functions work with ttk Frames and Listboxes used in PanelsV2.

### 3.3 Apply Tooltips in V2 Views

In:

- `prompt_tab_frame_v2.py`:

  - Attach tooltips to:

    - Main prompt input: “Main prompt used for txt2img/img2img stages.”
    - Negative prompt (if present): “Negative prompt to exclude undesired features.”

- `pipeline_tab_frame_v2.py`:

  - Attach tooltips to:

    - Model dropdown.
    - Sampler dropdown.
    - VAE dropdown.
    - Any advanced toggles.

- `learning_tab_frame_v2.py`:

  - Attach tooltips to:

    - Learning enable toggle.
    - Review/feedback buttons.

Use a consistent helper:

```python
from src.gui.tooltip import attach_tooltip

attach_tooltip(self.model_dropdown, "Select the checkpoint model for this pipeline.")
```

### 3.4 Enable Scrolling in Scrollable Areas

- Identify:

  - LeftZone lists (prompt packs, presets).
  - Pipeline panel scrolling region (multiple stage cards).
  - Any tall list containers that currently don’t scroll well.

Use `make_scrollable` to wrap and `enable_mousewheel` to bind.

Example:

```python
from src.gui.scrolling import enable_mousewheel, make_scrollable

scroll_frame = make_scrollable(self.left_zone)
enable_mousewheel(scroll_frame)
```

> Keep changes additive and localized. Do not rewrite layout; just wrap where needed.

---

## 4. Validation

### 4.1 Tests

- GUI smoke tests:

  - `tests/gui_v2/test_tooltip_helper_v2.py`:

    - Instantiates a widget, attaches tooltip, and ensures no exceptions on `<Enter>/<Leave>` event simulation.

  - `tests/gui_v2/test_scrolling_helper_v2.py`:

    - Creates a scrollable frame, calls `enable_mousewheel`, and verifies no errors.

> GUI tests remain smoke-level (no pixel assertions), but they protect against regressions.

### 4.2 Manual

- Launch GUI.
- Hover over:

  - Prompt input.
  - Model dropdown.
  - Learning toggle.

  → Tooltips should appear after delay.

- Use scroll wheel on:

  - Left zone lists.
  - Pipeline stage list.

  → Content should scroll, not the entire window.

---

## 5. Definition of Done

This PR is complete when:

1. Tooltips appear on key V2 widgets and are styled reasonably.
2. Scroll-wheel behavior works on scrollable panels without affecting unrelated parts of the GUI.
3. No legacy references to V1 main window or archived panels remain in tooltip/scrolling helpers.
