# Logging Strategy – StableNewV2 (Phase 1)

This document describes how logging works in StableNewV2 after the Phase-1 logging PRs.

---

## 1. Goals

- Provide enough information to diagnose failures without overwhelming the user.
- Maintain a clear separation between:
  - High-level status (StatusBarV2).
  - Detailed traces (LogTracePanelV2 + log files).
- Ensure logs include context (run ID, stage, subsystem) when relevant.

---

## 2. Logger Helpers

- `src/utils/logger.py` defines:
  - `get_logger(name: str)` – wrapper around `logging.getLogger`.
  - `LogContext` – carries `run_id`, `job_id`, `stage`, and `subsystem`.
  - `log_with_ctx(logger, level, message, ctx=..., extra_fields=...)` – appends a JSON context blob to the log line.
  - `InMemoryLogHandler` – stores recent log entries for GUI use.
  - `attach_gui_log_handler(max_entries=500)` – attaches an in-memory handler to the root logger and returns it.

New code should use `get_logger(__name__)` and `log_with_ctx` for pipeline/API logs where context matters.

---

## 3. Backend Sinks

- The standard logging configuration still sends logs to:
  - Console (stdout/stderr) for CLI/dev.
  - Optional file handler (e.g., `logs/stablenew_v2.log`) if configured.
- Logs are plain text with optional JSON context appended when `log_with_ctx` is used, for example:

  ```text
  INFO stage started | {"run_id": "run-123", "stage": "txt2img", "subsystem": "pipeline"}
  ```

---

## 4. GUI Sinks

### 4.1 StatusBarV2 (Status/Health lane)

- Shows:
  - Current status text (idle, starting, running stage, completed, error).
  - Progress bar for the current run.
  - ETA for the current run (if available).
  - WebUI connection state.
- Driven by controller/pipeline events, not raw log messages.

### 4.2 LogTracePanelV2 (Detailed trace lane)

- Collapsible panel, hidden by default.
- Backed by `InMemoryLogHandler` attached during GUI boot.
- Shows:
  - Recent log entries (level + message).
  - Filter options: ALL / WARN+ / ERROR.
- Intended for developers/power users troubleshooting issues.

---

## 5. Context Model

When using `log_with_ctx`, recommended fields:

- `run_id` – per pipeline run.
- `job_id` – per queue job (future).
- `stage` – e.g., `txt2img`, `adetailer`, `img2img`, `upscale`.
- `subsystem` – `pipeline`, `api`, `controller`, `gui`, etc.

Examples:

- Pipeline start:

  ```python
  ctx = LogContext(run_id=run_id, subsystem="pipeline")
  log_with_ctx(logger, logging.INFO, "Starting pipeline run", ctx=ctx)
  ```

- Stage failure:

  ```python
  ctx = LogContext(run_id=run_id, stage=stage.name, subsystem="pipeline")
  log_with_ctx(
      logger,
      logging.ERROR,
      "Stage failed",
      ctx=ctx,
      extra_fields={"error": str(exc)},
  )
  ```

---

## 6. How to Use Logs for Troubleshooting

1. **Check StatusBarV2**
   - Look for: running/idle state, ETA/progress, WebUI state.

2. **Expand LogTracePanelV2**
   - Click “Details ▼” to expand.
   - Filter to WARN+ or ERROR.
   - Review recent error/context messages.

3. **Inspect log files (if configured)**
   - Tail `logs/stablenew_v2.log` or per-run logs.
   - Search for the problematic `run_id`.

4. **Share logs**
   - Include StatusBarV2 & LogTracePanel snapshots and relevant log snippets.

---

## 7. Future Work (Beyond Phase 1)

- Add structured JSONL logging for:
  - Learning subsystem.
  - Queue & cluster jobs.
  - Metrics (latency, throughput).
- Enhance LogTracePanelV2 filters by subsystem/run_id.
- Surface key log events as clickable elements pointing to relevant UI sections.
