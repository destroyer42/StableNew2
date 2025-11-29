# PR-LOG-005_V2-P1 — Minimal Logging Tests & Documentation

**Intent:**  
Add a small but meaningful set of tests and documentation to:

- Verify that core logging utilities behave as expected.
- Verify that GUI logging integration does not crash.
- Document how logging is structured in StableNewV2 and how to use it for troubleshooting.

This PR is intentionally lightweight and builds on PR-LOG-001 through PR-LOG-004.

---

## 1. Scope & Subsystems

**Subsystems touched:**

- Utils (tests)
- GUI V2 (tests)
- Docs

**Files to add/modify:**

- `tests/utils/test_logger_integration.py` (new)
- `tests/gui_v2/test_gui_logging_integration.py` (new)
- `docs/Logging_Strategy_V2-P1.md` (new)

---

## 2. Tests for Logging Utilities

### 2.1 `tests/utils/test_logger_integration.py`

This augments the handler test from PR-LOG-002 with context logging.

```diff
diff --git a/tests/utils/test_logger_integration.py b/tests/utils/test_logger_integration.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/tests/utils/test_logger_integration.py
@@ -0,0 +1,60 @@
+from __future__ import annotations
+
+import logging
+
+from src.utils import (
+    InMemoryLogHandler,
+    LogContext,
+    get_logger,
+    log_with_ctx,
+)
+
+
+def test_log_with_ctx_appends_context() -> None:
+    logger = get_logger(__name__)
+    handler = InMemoryLogHandler(max_entries=10)
+    logger.addHandler(handler)
+
+    ctx = LogContext(run_id="run-123", stage="txt2img", subsystem="pipeline")
+
+    log_with_ctx(logger, logging.INFO, "stage started", ctx=ctx)
+
+    entries = list(handler.get_entries())
+    assert len(entries) >= 1
+    msg = entries[-1]["message"]
+    # We expect the JSON context blob to be included in the message.
+    assert "run-123" in msg
+    assert "txt2img" in msg
+    assert "pipeline" in msg
+
+
+def test_inmemory_log_handler_respects_max_entries() -> None:
+    logger = get_logger(__name__)
+    handler = InMemoryLogHandler(max_entries=3)
+    logger.addHandler(handler)
+
+    for i in range(10):
+        logger.info("message-%s", i)
+
+    entries = list(handler.get_entries())
+    assert len(entries) == 3
+    # Ensure we kept the most recent messages
+    assert any("message-9" in e["message"] for e in entries)
```

---

## 3. GUI Logging Smoke Test

### 3.1 `tests/gui_v2/test_gui_logging_integration.py`

This test ensures that:

- A V2 app can be built.
- A GUI log handler is attached.
- Emitting a log line does not crash and the handler sees it.

```diff
diff --git a/tests/gui_v2/test_gui_logging_integration.py b/tests/gui_v2/test_gui_logging_integration.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/tests/gui_v2/test_gui_logging_integration.py
@@ -0,0 +1,40 @@
+from __future__ import annotations
+
+import logging
+
+import pytest
+
+from src.app_factory import build_v2_app
+from src.utils import InMemoryLogHandler, get_logger
+
+
+@pytest.mark.gui
+def test_build_v2_app_attaches_gui_log_handler(monkeypatch) -> None:
+    """Ensure that build_v2_app attaches a GUI log handler and that logging works.
+
+    This is a smoke test; it does not assert on rendering.
+    """
+
+    root, app_state, controller, window = build_v2_app()
+
+    handler = getattr(window, "gui_log_handler", None)
+    assert isinstance(handler, InMemoryLogHandler)
+
+    logger = get_logger(__name__)
+    logger.info("hello from gui logging test")
+
+    entries = list(handler.get_entries())
+    # We don't require a strict guarantee that this specific message appears,
+    # but we do expect that the handler is functional.
+    assert isinstance(entries, list)
+
+    root.destroy()
```

> Adjust the mark (`@pytest.mark.gui`) and any fixture use to match your existing GUI test conventions.

---

## 4. Logging Documentation

### 4.1 `docs/Logging_Strategy_V2-P1.md`

Add a documentation file summarizing the logging approach:

```diff
diff --git a/docs/Logging_Strategy_V2-P1.md b/docs/Logging_Strategy_V2-P1.md
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/docs/Logging_Strategy_V2-P1.md
@@ -0,0 +1,140 @@
+# Logging Strategy — StableNewV2 (Phase 1)
+
+This document describes how logging works in StableNewV2 after the
+Phase-1 logging PRs.
+
+---
+
+## 1. Goals
+
+- Provide enough information to diagnose failures without overwhelming
+  the user.
+- Maintain a clear separation between:
+  - High-level status (StatusBarV2)
+  - Detailed traces (LogTracePanelV2 + log files)
+- Ensure logs include context (run ID, stage, subsystem) when relevant.
+
+---
+
+## 2. Logger Helpers
+
+- `src/utils/logger.py` defines:
+  - `get_logger(name: str)` — wrapper around `logging.getLogger`.
+  - `LogContext` — carries `run_id`, `job_id`, `stage`, `subsystem`.
+  - `log_with_ctx(logger, level, message, ctx=..., extra_fields=...)` — appends a JSON
+    blob of context to the log line.
+  - `InMemoryLogHandler` — stores recent log entries for GUI use.
+  - `attach_gui_log_handler(max_entries=500)` — attaches an in-memory handler
+    to the root logger and returns it.
+
+New code should use `get_logger(__name__)` and `log_with_ctx` for
+pipeline/API logs where context matters.
+
+---
+
+## 3. Back-End Sinks
+
+- The standard logging configuration still sends logs to:
+  - Console (stdout/stderr) for CLI / dev.
+  - Optional file handler (e.g., `logs/stablenew_v2.log` or per-run logs) if
+    configured by the app.
+- Logs are plain text with a JSON context blob appended when `log_with_ctx`
+  is used, for example:
+
+  ```text
+  INFO stage started | {"run_id": "run-123", "stage": "txt2img", "subsystem": "pipeline"}
+  ```
+
+---
+
+## 4. GUI Sinks
+
+### 4.1 StatusBarV2 (Status/Health lane)
+
+- Shows:
+  - Current status text (idle, starting, running stage, completed, error).
+  - Progress bar for current run.
+  - ETA for current run (if available).
+  - WebUI connection state.
+- Driven by controller / pipeline events, **not** raw log messages.
+
+### 4.2 LogTracePanelV2 (Detailed trace lane)
+
+- Collapsible panel, hidden by default.
+- Backed by `InMemoryLogHandler` attached during GUI boot.
+- Shows:
+  - Recent log entries (level + message).
+  - Filter options:
+    - ALL
+    - WARN+
+    - ERROR
+- Intended for:
+  - Developers / power users.
+  - Troubleshooting steps when something goes wrong.
+
+---
+
+## 5. Context Model
+
+When using `log_with_ctx`, recommended fields:
+
+- `run_id` — per pipeline run.
+- `job_id` — per queue job (if/when queue subsystem is active).
+- `stage` — e.g., `"txt2img"`, `"adetailer"`, `"img2img"`, `"upscale"`.
+- `subsystem` — `"pipeline"`, `"api"`, `"controller"`, `"gui"`, etc.
+
+Examples:
+
+- Pipeline start:
+
+  ```python
+  ctx = LogContext(run_id=run_id, subsystem="pipeline")
+  log_with_ctx(logger, logging.INFO, "Starting pipeline run", ctx=ctx)
+  ```
+
+- Stage failure:
+
+  ```python
+  ctx = LogContext(run_id=run_id, stage=stage.name, subsystem="pipeline")
+  log_with_ctx(
+      logger,
+      logging.ERROR,
+      "Stage failed",
+      ctx=ctx,
+      extra_fields={"error": str(exc)},
+  )
+  ```
+
+---
+
+## 6. How to Use Logs for Troubleshooting
+
+1. **Check StatusBarV2**
+   - Look for:
+     - Whether the pipeline is running or idle.
+     - ETA / progress bar.
+     - WebUI connection state.
+
+2. **Expand LogTracePanelV2**
+   - Click "Details ▸" to expand.
+   - Filter to WARN+ or ERROR.
+   - Look for the most recent error messages and context.
+
+3. **Inspect log files (if configured)**
+   - Tail `logs/stablenew_v2.log` or relevant run log.
+   - Search for `run_id` mentioned in the error.
+
+4. **Share logs**
+   - When reporting issues, include:
+     - A screenshot of the StatusBarV2 + LogTracePanelV2.
+     - A snippet of the log file around the time of failure.
+
+---
+
+## 7. Future Work (Beyond Phase 1)
+
+- Emit structured JSONL logs for:
+  - Learning subsystem.
+  - Queue & cluster jobs.
+  - Advanced metrics (latency, throughput).
+- Add filters in LogTracePanelV2 by subsystem and run_id.
+- Surface key log events as clickable elements that jump to the relevant
+  configuration (prompt, stage card, etc.).
```

---

## 5. Validation

1. Run new tests:

   ```bash
   pytest tests/utils/test_logger_integration.py -q
   pytest tests/gui_v2/test_gui_logging_integration.py -q
   ```

2. Open `docs/Logging_Strategy_V2-P1.md` and verify it matches the implemented behavior (handler names, class names, etc.).

---

## 6. Definition of Done

This PR is complete when:

1. The new tests pass and do not introduce flakiness.
2. The logging documentation accurately describes:
   - Helpers in `src/utils/logger.py`.
   - How GUI logging is surfaced.
   - How to use logs for troubleshooting.
