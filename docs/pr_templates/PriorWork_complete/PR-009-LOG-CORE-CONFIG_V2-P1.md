# PR-LOG-001_V2-P1 — Core Logging Config & Context Helpers

**Intent:**  
Stabilize and standardize logging across StableNewV2 by:

- Centralizing logger creation and configuration.
- Providing helpers for context-aware logging (run_id, stage, etc.).
- Ensuring key subsystems (API, pipeline, controller, CLI) emit useful INFO/ERROR logs at critical points.

This PR does **not** change GUI behavior or add new UI. It only affects back-end logging behavior.

---

## 1. Scope & Subsystems

**Subsystems touched:**

- Utils (logging helper)
- API
- Pipeline
- Controller
- CLI / entrypoint (light touch)

**Files to modify:**

- `src/utils/logger.py` (or create if missing)
- `src/utils/__init__.py` (export helper(s))
- `src/api/client.py`
- `src/api/healthcheck.py`
- `src/api/webui_process_manager.py`
- `src/pipeline/pipeline_runner.py`
- `src/pipeline/executor.py`
- `src/controller/pipeline_controller.py`
- `src/cli.py` (if present and used)

> IMPORTANT: Keep diffs as small and additive as possible. Do not refactor function signatures, change imports wholesale, or alter core behavior beyond logging.

---

## 2. Changes in `src/utils/logger.py`

If `src/utils/logger.py` already exists, extend it. Otherwise, create it with the following structure.

### 2.1 Provide a central logger helper

Add:

```diff
diff --git a/src/utils/logger.py b/src/utils/logger.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/src/utils/logger.py
@@ -0,0 +1,120 @@
+"""Central logging utilities for StableNewV2.
+
+Phase-1 goal:
+    - Provide a single place to configure and obtain loggers.
+    - Provide helpers for context-aware logging (run_id, stage, etc.).
+"""
+
+from __future__ import annotations
+
+import json
+import logging
+from dataclasses import dataclass
+from typing import Any, Dict, Mapping, Optional
+
+
+def get_logger(name: str) -> logging.Logger:
+    """Return a module logger.
+
+    This wraps logging.getLogger so we have a single place to evolve
+    logging behavior later if needed.
+    """
+    return logging.getLogger(name)
+
+
+@dataclass
+class LogContext:
+    """Contextual information for logging.
+
+    This can be attached to pipeline runs, stages, or API calls.
+    """
+
+    run_id: Optional[str] = None
+    job_id: Optional[str] = None
+    stage: Optional[str] = None
+    subsystem: Optional[str] = None
+
+    def to_dict(self) -> Dict[str, Any]:
+        data = {}
+        if self.run_id:
+            data["run_id"] = self.run_id
+        if self.job_id:
+            data["job_id"] = self.job_id
+        if self.stage:
+            data["stage"] = self.stage
+        if self.subsystem:
+            data["subsystem"] = self.subsystem
+        return data
+
+
+def log_with_ctx(
+    logger: logging.Logger,
+    level: int,
+    message: str,
+    *,
+    ctx: Optional[LogContext] = None,
+    extra_fields: Optional[Mapping[str, Any]] = None,
+) -> None:
+    """Log a message with optional structured context.
+
+    The context is rendered as a JSON blob appended to the message so
+    that plain-text logs remain readable while machines can still parse
+    the structure.
+    """
+    payload: Dict[str, Any] = {}
+    if ctx is not None:
+        payload.update(ctx.to_dict())
+    if extra_fields:
+        payload.update(extra_fields)
+
+    if payload:
+        logger.log(level, "%s | %s", message, json.dumps(payload, sort_keys=True))
+    else:
+        logger.log(level, "%s", message)
```

> If a logger helper already exists, adapt this patch to extend it instead of overwriting. Preserve any existing behavior that callers rely on.

### 2.2 Ensure `src/utils/__init__.py` exports helpers

Append (if not already present):

```diff
diff --git a/src/utils/__init__.py b/src/utils/__init__.py
index 0000000..0000000 100644
--- a/src/utils/__init__.py
+++ b/src/utils/__init__.py
@@ -1,3 +1,8 @@
+"""Utility package for StableNewV2."""
+
+from .logger import get_logger, LogContext, log_with_ctx  # noqa: F401
+
+# existing imports / exports below...
```

Be careful **not** to remove existing imports from this module.

---

## 3. API Layer Logging

### 3.1 `src/api/client.py`

Goal: ensure core WebUI interactions emit useful logs at INFO/ERROR and optionally DEBUG.

Key changes:

- At top of file, import helpers:

```diff
@@ -1,6 +1,8 @@
-import logging
+import logging
@@
-from src.utils import ...
+from src.utils import get_logger, LogContext, log_with_ctx
```

- Replace `logging.getLogger(__name__)` usage with:

```diff
-logger = logging.getLogger(__name__)
+logger = get_logger(__name__)
```

- Around key call sites (for example, where HTTP requests are made to WebUI), wrap logs:

```diff
@@ def _do_request(self, method: str, path: str, **kwargs) -> requests.Response:
-    logger.debug("Requesting %s %s", method, url)
+    ctx = LogContext(subsystem="api")
+    log_with_ctx(
+        logger,
+        logging.DEBUG,
+        f"Requesting {method} {url}",
+        ctx=ctx,
+        extra_fields={"timeout": timeout, "has_payload": bool(json_body)},
+    )
@@
-    logger.error("Request to %s failed: %s", url, exc)
+    log_with_ctx(
+        logger,
+        logging.ERROR,
+        f"Request to {url} failed",
+        ctx=ctx,
+        extra_fields={"error": str(exc)},
+    )
```

> Do **not** change method signatures or exception types. Only wrap logging calls.

### 3.2 `src/api/healthcheck.py` and `src/api/webui_process_manager.py`

- Import `get_logger` and `log_with_ctx`.
- Ensure they log at:
  - `INFO` when WebUI is healthy / process starts successfully.
  - `WARNING` when retries or degraded states occur.
  - `ERROR` when definitive failures occur.

---

## 4. Pipeline & Controller Logging

### 4.1 `src/pipeline/pipeline_runner.py`

- Import helpers:

```diff
@@
-import logging
+import logging
@@
-from src.utils import ...
+from src.utils import get_logger, LogContext, log_with_ctx
```

- Use a `LogContext` that carries `run_id` and `stage`:

```diff
-logger = logging.getLogger(__name__)
+logger = get_logger(__name__)
@@ def run_pipeline(...):
-    logger.info("Starting pipeline run %s", run_id)
+    ctx = LogContext(run_id=run_id, subsystem="pipeline")
+    log_with_ctx(logger, logging.INFO, "Starting pipeline run", ctx=ctx)
@@ in stage loop:
-    logger.info("Running stage %s", stage.name)
+    stage_ctx = LogContext(run_id=run_id, stage=stage.name, subsystem="pipeline")
+    log_with_ctx(logger, logging.INFO, "Running stage", ctx=stage_ctx)
```

- On exceptions:

```diff
-    logger.error("Stage %s failed", stage.name, exc_info=True)
+    log_with_ctx(
+        logger,
+        logging.ERROR,
+        "Stage failed",
+        ctx=stage_ctx,
+        extra_fields={"error": str(exc)},
+    )
```

### 4.2 `src/pipeline/executor.py`

- Similar pattern: use `LogContext` with `run_id`, `stage`, and possibly `job_id` if available.
- Ensure at least:
  - One `INFO` at executor startup.
  - `ERROR` when a stage fails in executor.

### 4.3 `src/controller/pipeline_controller.py`

- Use `get_logger(__name__)`.
- Emit `INFO` logs for:
  - User-initiated “Run pipeline”.
  - User cancels a job.
- These will show up in the GUI’s detailed log panel later.

---

## 5. CLI / Entrypoint

If you have a CLI or entrypoint module (e.g., `src/cli.py`):

- Ensure it imports `get_logger`.
- Emit a couple of `INFO` lines:
  - Application start (`"StableNewV2 CLI start"`).
  - Pipeline run invoked (with basic run ID).

Keep changes minimal so as not to affect command-line behavior.

---

## 6. Validation

### 6.1 Unit / Integration Tests

- Run:

```bash
pytest tests/test_api_client.py -q
pytest tests/api/test_webui_healthcheck.py -q
pytest tests/controller/test_app_controller_pipeline_flow_pr0.py -q
pytest tests/pipeline/test_last_run_store_v2_5.py -q
```

All should pass.

### 6.2 Manual Log Inspection

- Launch the app (GUI or CLI) and trigger a simple pipeline run.
- Confirm logs now contain:
  - `Starting pipeline run` with `run_id`.
  - Per-stage `Running stage` messages.
  - API calls logged with method + endpoint and errors logged with context.

---

## 7. Definition of Done

This PR is complete when:

1. All targeted modules use `get_logger(__name__)` instead of ad-hoc loggers.
2. `LogContext` + `log_with_ctx` are available and used in:
   - `api.client`
   - `pipeline_runner`
   - `executor`
   - `pipeline_controller`
3. A pipeline run produces clearly contextual logs (run_id, stage, subsystem).
4. No tests are broken by these logging additions.
