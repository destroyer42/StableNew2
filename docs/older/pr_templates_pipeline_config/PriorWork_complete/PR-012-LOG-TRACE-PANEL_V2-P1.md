# PR-LOG-004-GUI-V2-DETAILS-PANEL_V2-P1 — Collapsible Detailed Trace Panel

**Intent:**  
Add a **collapsible trace log panel** to the GUI V2 that:

- Uses the in-memory GUI log handler introduced in PR-LOG-002.
- Shows recent log entries (level, message, time).
- Can be expanded/collapsed to avoid overwhelming the user.
- Can filter by level (All / Warnings+Errors / Errors-only).

This is the “black box recorder / crime scene view” that complements `StatusBarV2`.

---

## 1. Scope & Subsystems

**Subsystems touched:**

- GUI V2
- Utils (only to read from the handler, no behavior changes)

**Files to add/modify:**

- `src/gui/log_trace_panel_v2.py` (new)
- `src/gui/main_window_v2.py` (integration)
- Optionally `src/gui/widgets/scrollable_frame_v2.py` usage (for scrolling)
- Optional tests:
  - `tests/gui_v2/test_log_trace_panel_v2.py`

---

## 2. New Panel: `LogTracePanelV2`

### 2.1 New file `src/gui/log_trace_panel_v2.py`

Add a new module with a minimal but functional panel:

```diff
diff --git a/src/gui/log_trace_panel_v2.py b/src/gui/log_trace_panel_v2.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/src/gui/log_trace_panel_v2.py
@@ -0,0 +1,140 @@
+from __future__ import annotations
+
+import tkinter as tk
+from tkinter import ttk
+from typing import Iterable, Dict, List
+
+from src.utils import InMemoryLogHandler
+
+
+class LogTracePanelV2(ttk.Frame):
+    """Collapsible panel that shows recent log entries.
+
+    This panel is backed by an InMemoryLogHandler instance exposed by the
+    app factory in GUI mode.
+    """
+
+    def __init__(self, master, log_handler: InMemoryLogHandler, *args, **kwargs):
+        super().__init__(master, *args, **kwargs)
+        self._log_handler = log_handler
+
+        self._expanded = tk.BooleanVar(value=False)
+        self._level_filter = tk.StringVar(value="ALL")
+
+        # Header row
+        header = ttk.Frame(self)
+        header.pack(side=tk.TOP, fill=tk.X)
+
+        self._toggle_btn = ttk.Button(
+            header,
+            text="Details ▸",
+            command=self._on_toggle,
+            width=12,
+        )
+        self._toggle_btn.pack(side=tk.LEFT)
+
+        ttk.Label(header, text="Level:").pack(side=tk.LEFT, padx=(8, 2))
+        self._level_combo = ttk.Combobox(
+            header,
+            textvariable=self._level_filter,
+            values=["ALL", "WARN+", "ERROR"],
+            state="readonly",
+            width=8,
+        )
+        self._level_combo.pack(side=tk.LEFT)
+
+        # Body (initially hidden)
+        self._body = ttk.Frame(self)
+        self._body.pack_forget()
+
+        self._log_list = tk.Listbox(self._body, height=6)
+        self._log_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
+
+        scrollbar = ttk.Scrollbar(self._body, orient=tk.VERTICAL, command=self._log_list.yview)
+        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
+        self._log_list.config(yscrollcommand=scrollbar.set)
+
+        # Initial refresh
+        self.refresh()
+
+    def _on_toggle(self) -> None:
+        expanded = not self._expanded.get()
+        self._expanded.set(expanded)
+        if expanded:
+            self._toggle_btn.config(text="Details ▾")
+            self._body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
+        else:
+            self._toggle_btn.config(text="Details ▸")
+            self._body.pack_forget()
+
+    def refresh(self) -> None:
+        """Refresh the log list from the handler's buffer."""
+        entries = list(self._log_handler.get_entries())
+        filtered = self._apply_filter(entries)
+
+        self._log_list.delete(0, tk.END)
+        for entry in filtered:
+            line = f"[{entry['level']}] {entry['message']}"
+            self._log_list.insert(tk.END, line)
+
+    def _apply_filter(self, entries: Iterable[Dict[str, object]]) -> List[Dict[str, object]]:
+        mode = self._level_filter.get()
+        out: List[Dict[str, object]] = []
+        for e in entries:
+            level = str(e.get("level", "INFO")).upper()
+            if mode == "ALL":
+                out.append(e)
+            elif mode == "WARN+" and level in ("WARNING", "ERROR", "CRITICAL"):
+                out.append(e)
+            elif mode == "ERROR" and level in ("ERROR", "CRITICAL"):
+                out.append(e)
+        return out
```

> This is a simple implementation; it can be refined later (timestamps, colors, etc.).  
> It is intentionally conservative: no periodic polling, just manual refresh triggering for now.

---

## 3. Integration in `MainWindowV2`

### 3.1 Add panel to bottom region

In `src/gui/main_window_v2.py`:

- Import and instantiate `LogTracePanelV2` using the handler attached in app factory.

Example integration sketch:

```diff
diff --git a/src/gui/main_window_v2.py b/src/gui/main_window_v2.py
index 0000000..0000000 100644
--- a/src/gui/main_window_v2.py
+++ b/src/gui/main_window_v2.py
@@ -1,6 +1,8 @@
 from .status_bar_v2 import StatusBarV2
+from .log_trace_panel_v2 import LogTracePanelV2
@@
 class MainWindowV2(tk.Tk):
@@
-        self.status_bar_v2 = StatusBarV2(self.bottom_zone, app_state=self.app_state)
-        self.status_bar_v2.pack(side=tk.BOTTOM, fill=tk.X)
+        # Bottom zone: trace panel (collapsible) above status bar
+        self.status_bar_v2 = StatusBarV2(self.bottom_zone, app_state=self.app_state)
+        self.status_bar_v2.pack(side=tk.BOTTOM, fill=tk.X)
+
+        gui_log_handler = getattr(self, "gui_log_handler", None)
+        if gui_log_handler is not None:
+            self.log_trace_panel_v2 = LogTracePanelV2(
+                self.bottom_zone,
+                log_handler=gui_log_handler,
+            )
+            self.log_trace_panel_v2.pack(side=tk.BOTTOM, fill=tk.X)
```

> This assumes `app_factory.build_v2_app` assigned `window.gui_log_handler` in PR-LOG-002.  
> If the handler lives on `app_state` instead, fetch it accordingly.

---

## 4. Optional Test

Add a minimal test to ensure the panel can be instantiated:

- `tests/gui_v2/test_log_trace_panel_v2.py`

```diff
diff --git a/tests/gui_v2/test_log_trace_panel_v2.py b/tests/gui_v2/test_log_trace_panel_v2.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/tests/gui_v2/test_log_trace_panel_v2.py
@@ -0,0 +1,30 @@
+from __future__ import annotations
+
+import tkinter as tk
+
+from src.gui.log_trace_panel_v2 import LogTracePanelV2
+from src.utils import InMemoryLogHandler, get_logger
+
+
+def test_log_trace_panel_v2_instantiates() -> None:
+    root = tk.Tk()
+    handler = InMemoryLogHandler(max_entries=10)
+    logger = get_logger(__name__)
+    logger.addHandler(handler)
+
+    panel = LogTracePanelV2(root, log_handler=handler)
+    panel.refresh()
+
+    root.destroy()
```

> This is just a smoke test to ensure basic construction works in test mode.

---

## 5. Validation

1. Run GUI tests:

   ```bash
   pytest tests/gui_v2/test_gui_v2_layout_skeleton.py -q
   pytest tests/gui_v2/test_log_trace_panel_v2.py -q
   ```

2. Manual:

   - Launch the GUI.
   - Trigger some actions (e.g., pipeline runs, WebUI healthcheck).
   - Confirm:
     - The “Details ▸” control appears above the status bar.
     - Clicking “Details ▸” expands the panel and shows recent log lines.
     - Level filter changes which messages are visible.

---

## 6. Definition of Done

This PR is complete when:

1. `LogTracePanelV2` exists and renders without errors in GUI V2.
2. The panel uses the in-memory log handler to show recent log entries.
3. The panel is collapsed by default and can be expanded by the user.
4. The status bar remains responsible for high-level status/health, while the trace panel shows details.
