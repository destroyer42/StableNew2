"""Unit tests for the Phase 8 logging helpers."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from src.utils import (
    InMemoryLogHandler,
    JsonlFileHandler,
    LogContext,
    get_logger,
    log_with_ctx,
)


def test_log_with_ctx_attaches_json_payload() -> None:
    handler = InMemoryLogHandler(max_entries=2)
    handler.setLevel(logging.INFO)
    logger = get_logger("tests.utils.test_logger_v2")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    log_with_ctx(
        logger,
        logging.INFO,
        "payload test",
        ctx=LogContext(subsystem="api", job_id="job-123"),
        extra_fields={"custom": "value"},
    )

    entries = handler.get_entries()
    assert entries, "Expected at least one log entry"
    payload = entries[-1].get("payload")
    assert payload is not None
    assert payload.get("custom") == "value"
    assert payload.get("job_id") == "job-123"
    logger.removeHandler(handler)


def test_jsonl_file_handler_writes_jsonl(tmp_path: Path) -> None:
    log_path = tmp_path / "stablenew.log.jsonl"
    handler = JsonlFileHandler(log_path, max_bytes=1024, backup_count=1)
    logger = get_logger("tests.utils.test_logger_v2.jsonl")
    logger.addHandler(handler)

    log_with_ctx(
        logger,
        logging.WARNING,
        "jsonl sink",
        ctx=LogContext(subsystem="api", job_id="job-jsonl"),
        extra_fields={"detail": "test"},
    )

    handler.flush()
    logger.removeHandler(handler)
    handler.close()

    assert log_path.exists()
    lines = [
        line.strip() for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["job_id"] == "job-jsonl"
    assert data["detail"] == "test"
