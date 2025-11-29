# PR-00A — WebUI GUI Controls (Start / Stop / Restart / Status)

## Summary

Now that **PR-00** has cleanly separated WebUI process management into
`WebUIProcessManager` (owned by `src/api/webui_process_manager.py` and wired from
`src/main.py`), this PR adds **thin GUI controls** to:

- Start WebUI (via the manager)
- Stop WebUI
- Restart WebUI
- Display basic WebUI status (running/stopped, pid, last exit code)

All policy remains in the process manager and config; the GUI just exposes
simple buttons + indicators so the user can see and control WebUI without
manual restarts.

> This PR is intentionally small and focused: **no layout/theming changes**,
> only wiring to already-existing manager methods.

---

## Goals

1. Provide explicit **Start / Stop / Restart WebUI** controls in the V2 GUI.
2. Show a **lightweight status indicator** (running/stopped and optional pid).
3. Ensure GUI remains responsive (no blocking calls).
4. Preserve existing connection-check logic, but route all launches
   through the manager.

---

## Non-Goals

- Changing WebUI config or autostart policy (still handled in PR-00).
- Implementing a complex monitoring dashboard.
- Changing any non-WebUI parts of the GUI.
- Re-theming or resizing major layouts (Phase 2 handles that).

---

## Design Overview

### High-Level

- The GUI already receives an instance of `WebUIProcessManager` as a dependency.
- This PR adds a **WebUI control subpanel** in the existing V2 layout (e.g. bottom of the sidebar or status bar).
- Controls call:
  - `webui_manager.start()`
  - `webui_manager.stop()`
  - `webui_manager.start(force=True)` for Restart
- Status polling uses `webui_manager.get_status()` on a timer (`root.after(...)`).

### Where to Place Controls

There are two straightforward options; CODEX can pick based on the current structure:

1. **Sidebar Panel** — A “WebUI” section at the bottom of the sidebar:
   - Cleaner for power-users who think of WebUI as part of environment config.
2. **Status Bar** — A “WebUI:” status segment in the footer with a context menu or small buttons.

For this PR, keep it simple and **put a small control group into whichever panel currently owns status-ish UI** (likely `status_bar_v2` or similar).

---

## Implementation Plan

### Step 1 — Add a Small WebUI Control Widget Class

Create a new widget module in the V2 GUI to keep this logic isolated.

Example path:

```text
src/gui/webui_controls_panel_v2.py
```

Skeleton:

```python
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

from src.api.webui_process_manager import WebUIProcessManager, WebUIStatus


class WebUIControlsPanel(ttk.Frame):
    """Small widget that exposes WebUI start/stop/restart + status."""

    def __init__(self, master: tk.Misc, webui_manager: WebUIProcessManager, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._webui_manager = webui_manager

        self._build_widgets()
        self._layout_widgets()
        self._schedule_status_poll()

    def _build_widgets(self) -> None:
        self._status_label = ttk.Label(self, text="WebUI: unknown")  # TODO: style
        self._start_button = ttk.Button(self, text="Start", command=self._on_start_clicked)
        self._stop_button = ttk.Button(self, text="Stop", command=self._on_stop_clicked)
        self._restart_button = ttk.Button(self, text="Restart", command=self._on_restart_clicked)

    def _layout_widgets(self) -> None:
        # Simple horizontal layout for now; Phase 2 can refine
        self._status_label.grid(row=0, column=0, padx=4, pady=2, sticky="w")
        self._start_button.grid(row=0, column=1, padx=2, pady=2)
        self._stop_button.grid(row=0, column=2, padx=2, pady=2)
        self._restart_button.grid(row=0, column=3, padx=2, pady=2)

        self.columnconfigure(0, weight=1)

    def _on_start_clicked(self) -> None:
        # Delegate to manager
        self._webui_manager.start()
        self._refresh_status_label()

    def _on_stop_clicked(self) -> None:
        self._webui_manager.stop()
        self._refresh_status_label()

    def _on_restart_clicked(self) -> None:
        self._webui_manager.start(force=True)
        self._refresh_status_label()

    def _schedule_status_poll(self) -> None:
        # Re-run every few seconds without blocking UI
        self.after(2000, self._poll_status)

    def _poll_status(self) -> None:
        self._refresh_status_label()
        self._schedule_status_poll()

    def _refresh_status_label(self) -> None:
        status: WebUIStatus = self._webui_manager.get_status()
        if status.is_running:
            # Keep text short; Phase 2 can add icons/colour
            pid_text = f" pid={status.pid}" if status.pid is not None else ""
            self._status_label.config(text=f"WebUI: running{pid_text}")
        else:
            if status.last_exit_code is None:
                extra = ""
            else:
                extra = f" (last exit={status.last_exit_code})"
            self._status_label.config(text=f"WebUI: stopped{extra}")
```

> NOTE: In the real code, use your existing theme styles rather than default `ttk` look.

### Step 2 — Wire the Widget into the Main Window Layout

In the V2 main window (e.g. `src/gui/main_window_v2.py` or equivalent):

1. Import the new panel:

   ```python
   from src.gui.webui_controls_panel_v2 import WebUIControlsPanel
   ```

2. When building the layout, pass in the existing `webui_manager`:

   ```python
   class MainWindowV2(...):
       def __init__(self, root: tk.Tk, webui_manager: WebUIProcessManager, ...):
           self.root = root
           self.webui_manager = webui_manager
           # ...
           self._build_layout()

       def _build_layout(self) -> None:
           # existing layout code...

           self.webui_controls = WebUIControlsPanel(
               master=self.some_status_or_footer_frame,
               webui_manager=self.webui_manager,
           )
           self.webui_controls.pack(side="right", padx=4)  # or grid, depending on layout
   ```

3. Do **not** change any existing business logic; simply add this panel in a reasonable visible area.

### Step 3 — Respect Existing Connection Checks

The GUI currently performs connection checks and surfaces errors if WebUI is not reachable.

This PR should **not** remove that; instead:

- The connection checker should continue to poll connectivity (e.g., HTTP or socket).
- If WebUI is **not running** according to the manager, connection failures should result in a gentle hint like: *“WebUI is not running; click Start to launch it.”*
- If WebUI **is running** but connection fails, existing error surfacing should remain.

This can be as simple as annotating your connection error handler to also query `webui_manager.is_running()` and adjust the message.

### Step 4 — Optional: Disable Buttons Based on State

To tighten UX, CODEX can add a small enhancement:

- When WebUI is running: disable `Start`; keep `Stop` and `Restart` enabled.  
- When WebUI is stopped: enable `Start`; disable `Stop`; keep `Restart` enabled (as “start fresh”).

Skeleton additions inside `_refresh_status_label`:

```python
if status.is_running:
    self._start_button.config(state=tk.DISABLED)
    self._stop_button.config(state=tk.NORMAL)
    self._restart_button.config(state=tk.NORMAL)
else:
    self._start_button.config(state=tk.NORMAL)
    self._stop_button.config(state=tk.DISABLED)
    self._restart_button.config(state=tk.NORMAL)
```

---

## Files Expected to Change / Be Added

**New:**

- `src/gui/webui_controls_panel_v2.py` (or similar path)

**Updated:**

- `src/gui/main_window_v2.py` (or whichever module composes the main V2 layout)
- Any status bar / footer module that owns the bottom-row widgets (if you integrate with a status bar)

No changes to:

- `src/api/webui_process_manager.py` logic (only reused)  
- WebUI core code  
- Pipeline logic

---

## Tests & Validation

- **Manual:**
  - Start app with WebUI autostart disabled:
    - GUI loads, status says “stopped” (or similar).  
    - Clicking **Start** launches WebUI; status becomes “running (pid=…)”.  
    - Clicking **Stop** stops WebUI; status becomes “stopped (last exit=0)” or similar.  
    - Clicking **Restart** does stop+start behaviour as expected.
  - Confirm buttons enable/disable appropriately if implemented.

- **Existing tests:**
  - `tests/gui_v2` should still pass.
  - If there are GUI snapshot tests, update them to include the new WebUI control area if necessary.

---

## Acceptance Criteria

- The V2 GUI exposes visible WebUI controls (Start/Stop/Restart) wired to `WebUIProcessManager`.
- Status indicator correctly reflects running/stopped state, including after crashes and manual stops.
- No blocking calls or regressions in GUI responsiveness.
- Existing connection checks remain functional, now informed by manager status.
