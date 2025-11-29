# PR-LOG-002_V2-P1 — GUI Mode Logging & In-Memory Handler

**Intent:**  
When the GUI is running, attach a dedicated logging handler that:

- Captures recent log records in memory (ring buffer).
- Makes them available to GUI components (e.g., a detailed trace panel).
- Does **not** change existing console/file logging behavior.

This PR does not add any new GUI widgets yet. It only wires up the handler.

---

## 1. Scope & Subsystems

**Subsystems touched:**

- Utils (logging)
- GUI V2 wiring / app factory

**Files to modify:**

- `src/utils/logger.py`
- `src/app_factory.py` (or whichever module builds the V2 GUI)
- Possibly `src/gui/main_window_v2.py` (for handler plumbing)

---

## 2. In-Memory Log Handler

### 2.1 Add handler class in `src/utils/logger.py`

Extend `src/utils/logger.py` with an in-memory handler:

```diff
diff --git a/src/utils/logger.py b/src/utils/logger.py
index 0000000..0000000 100644
--- a/src/utils/logger.py
+++ b/src/utils/logger.py
@@ -1,6 +1,10 @@
-from dataclasses import dataclass
-from typing import Any, Dict, Mapping, Optional
+from collections import deque
+from dataclasses import dataclass
+from threading import RLock
+from typing import Any, Deque, Dict, Iterable, Mapping, Optional

@@
 class LogContext:
@@
 def log_with_ctx(...):
@@
+class InMemoryLogHandler(logging.Handler):
+    """Logging handler that stores recent log records in memory.
+
+    Intended for GUI usage where the user can expand a details pane to
+    inspect recent messages without tailing a log file.
+    """
+
+    def __init__(self, max_entries: int = 500) -> None:
+        super().__init__()
+        self._max_entries = max_entries
+        self._lock = RLock()
+        self._entries: Deque[Dict[str, Any]] = deque(maxlen=max_entries)
+
+    def emit(self, record: logging.LogRecord) -> None:
+        try:
+            msg = self.format(record)
+        except Exception:
+            # If formatting fails, fall back to the raw message.
+            msg = record.getMessage()
+
+        entry = {
+            "level": record.levelname,
+            "name": record.name,
+            "message": msg,
+            "created": record.created,
+        }
+
+        with self._lock:
+            self._entries.append(entry)
+
+    def get_entries(self) -> Iterable[Dict[str, Any]]:
+        """Return a snapshot of the current entries.
+
+        The returned iterable is safe for read-only iteration.
+        """
+        with self._lock:
+            return list(self._entries)
+
+
+def attach_gui_log_handler(max_entries: int = 500) -> InMemoryLogHandler:
+    """Attach an in-memory log handler to the root logger for GUI mode.
+
+    Returns the handler instance so the GUI can read log entries.
+    """
+    handler = InMemoryLogHandler(max_entries=max_entries)
+    root = logging.getLogger()
+    root.addHandler(handler)
+    return handler
```

> Ensure imports (`deque`, `RLock`, typing) are not duplicated if they already exist.

### 2.2 Export handler helpers from `src/utils/__init__.py`

Append:

```diff
diff --git a/src/utils/__init__.py b/src/utils/__init__.py
index 0000000..0000000 100644
--- a/src/utils/__init__.py
+++ b/src/utils/__init__.py
@@ -1,4 +1,7 @@
-from .logger import get_logger, LogContext, log_with_ctx  # noqa: F401
+from .logger import (  # noqa: F401
+    get_logger,
+    LogContext,
+    log_with_ctx,
+    InMemoryLogHandler,
+    attach_gui_log_handler,
+)
```

---

## 3. Attach Handler in GUI Boot

### 3.1 `src/app_factory.py` — attach handler when building V2 app

Locate `build_v2_app(...)` (or equivalent function that constructs the GUI).  
Extend it to attach the handler and store it on the window or app_state.

Example patch sketch (adapt to existing code):

```diff
diff --git a/src/app_factory.py b/src/app_factory.py
index 0000000..0000000 100644
--- a/src/app_factory.py
+++ b/src/app_factory.py
@@ -1,6 +1,8 @@
-import tkinter as tk
+import tkinter as tk
@@
-from src.utils import ConfigManager, PreferencesManager
+from src.utils import (
+    ConfigManager,
+    PreferencesManager,
+    attach_gui_log_handler,
+)
@@
 def build_v2_app(...):
@@
-    # existing window / controller wiring...
+    # existing window / controller wiring...
+
+    # Attach GUI-aware logging handler so the window can surface logs.
+    gui_log_handler = attach_gui_log_handler()
+
+    # Expose the handler to the GUI / app state. Adjust attribute names
+    # to match the actual window / state objects.
+    try:
+        window.gui_log_handler = gui_log_handler  # type: ignore[attr-defined]
+    except Exception:
+        # If the window does not support dynamic attributes, this can be
+        # adapted later to use app_state or a dedicated adapter.
+        pass
@@
-    return root, app_state, controller, window
+    return root, app_state, controller, window
```

> Keep this patch robust: attach the handler and expose it, but avoid assuming too much about `window` internals. If `app_state` is the better place, attach there instead (`app_state.set("gui_log_handler", handler)`).

---

## 4. Minimal Tests

Add a small test to ensure the handler works:

- `tests/utils/test_inmemory_log_handler.py` (new)

```diff
diff --git a/tests/utils/test_inmemory_log_handler.py b/tests/utils/test_inmemory_log_handler.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/tests/utils/test_inmemory_log_handler.py
@@ -0,0 +1,40 @@
+from __future__ import annotations
+
+import logging
+
+from src.utils import InMemoryLogHandler, get_logger
+
+
+def test_inmemory_log_handler_captures_messages() -> None:
+    logger = get_logger(__name__)
+    handler = InMemoryLogHandler(max_entries=10)
+    logger.addHandler(handler)
+
+    logger.info("hello world")
+
+    entries = list(handler.get_entries())
+    assert len(entries) == 1
+    assert entries[0]["message"]
+    assert entries[0]["level"] == "INFO"
```

> Keep this test simple and side-effect–free.

---

## 5. Validation

1. Run the new test:

   ```bash
   pytest tests/utils/test_inmemory_log_handler.py -q
   ```

2. Launch the GUI (`python -m src.main`) and trigger some actions.
   - Confirm the application starts without logging-related errors.
   - Confirm that `attach_gui_log_handler` did not interfere with existing file/console logging.

---

## 6. Definition of Done

This PR is complete when:

1. `InMemoryLogHandler` and `attach_gui_log_handler` exist and are exported from `src/utils`.
2. `build_v2_app` (or equivalent) attaches a GUI log handler at startup.
3. The new test passes.
4. The GUI can introspect recent log entries via the handler (even if no GUI widget consumes it yet).
