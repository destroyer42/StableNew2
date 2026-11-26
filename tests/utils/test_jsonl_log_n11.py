"""N11: every JSONL record is a timestamped, single-line JSON object, and rotation never fails silently."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import pytest

from src.utils.logger import (
    JsonlFileHandler,
    JsonlFileLogConfig,
    attach_jsonl_log_handler,
    log_with_ctx,
)


def _records(*paths: Path) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        if path.exists():
            rows.extend(
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
    return rows


@pytest.fixture
def jsonl_logger():
    created: list[tuple[logging.Logger, logging.Handler]] = []

    def make(path: Path, **kwargs) -> tuple[logging.Logger, JsonlFileHandler]:
        handler = JsonlFileHandler(path, **kwargs)
        log = logging.getLogger(f"tests.n11.jsonl.{len(created)}")
        log.setLevel(logging.DEBUG)
        log.propagate = False
        log.addHandler(handler)
        created.append((log, handler))
        return log, handler

    yield make
    for log, handler in created:
        log.removeHandler(handler)
        handler.close()


def test_every_record_has_timestamp_level_and_logger(tmp_path, jsonl_logger):
    path = tmp_path / "stablenew.log.jsonl"
    log, handler = jsonl_logger(path)

    log.info("plain %s", "message")
    log_with_ctx(log, logging.WARNING, "structured", extra_fields={"job_id": "j1"})
    handler.flush()

    plain, structured = _records(path)
    for record in (plain, structured):
        assert datetime.fromisoformat(record["ts"]).tzinfo is not None
        assert record["logger"] == log.name
    assert plain["level"] == "INFO" and plain["message"] == "plain message"
    assert structured["level"] == "WARNING" and structured["job_id"] == "j1"


def test_payload_keys_are_kept_and_not_overwritten(tmp_path, jsonl_logger):
    path = tmp_path / "stablenew.log.jsonl"
    log, handler = jsonl_logger(path)

    log.info("x", extra={"json_payload": {"message": "x", "event": "e", "outcome": "ok"}})
    handler.flush()

    (record,) = _records(path)
    assert record["event"] == "e" and record["outcome"] == "ok" and record["message"] == "x"


def test_exception_stays_inside_one_json_line(tmp_path, jsonl_logger):
    path = tmp_path / "stablenew.log.jsonl"
    log, handler = jsonl_logger(path)

    try:
        raise ValueError("boom")
    except ValueError:
        log.exception("it failed")
    handler.flush()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["level"] == "ERROR"
    assert "ValueError: boom" in record["exc_text"]
    assert "Traceback" in record["exc_text"]


def _fill(log: logging.Logger, count: int) -> None:
    for index in range(count):
        log.info("record %04d %s", index, "x" * 80)


@pytest.mark.skipif(os.name != "nt", reason="a second open handle only blocks rename on Windows")
def test_rotation_succeeds_while_another_handle_holds_the_file(tmp_path, jsonl_logger):
    path = tmp_path / "stablenew.log.jsonl"
    log, handler = jsonl_logger(path, max_bytes=4_000, backup_count=3)
    log.info("first")
    handler.flush()

    with open(path, encoding="utf-8") as reader:  # a log viewer, a bundle or a second handler
        _fill(log, 200)
        handler.flush()
        assert reader.readline()  # still usable

    files = [path] + [path.with_name(f"{path.name}.{i}") for i in (1, 2, 3)]
    assert path.stat().st_size < 3 * 4_000, "the live file kept growing: rotation failed"
    assert path.with_name(path.name + ".1").exists()
    messages = [r["message"] for r in _records(*files)]
    assert not any(m.startswith("Log rotation failed") for m in messages)


def test_a_refused_rotation_keeps_backups_reports_once_and_backs_off(
    tmp_path, jsonl_logger, monkeypatch, capsys
):
    path = tmp_path / "stablenew.log.jsonl"
    backup1 = path.with_name(path.name + ".1")
    backup2 = path.with_name(path.name + ".2")
    backup1.write_text('{"message": "old 1"}\n', encoding="utf-8")
    backup2.write_text('{"message": "old 2"}\n', encoding="utf-8")
    log, handler = jsonl_logger(path, max_bytes=1_000, backup_count=3)

    attempts: list[str] = []

    def refuse(source, dest):
        attempts.append(str(dest))
        raise PermissionError(
            32, "The process cannot access the file because it is being used by another process"
        )

    monkeypatch.setattr(handler, "_rename", refuse)
    monkeypatch.setattr(handler, "_copy", refuse)
    _fill(log, 100)
    handler.flush()

    assert backup1.read_text(encoding="utf-8") == '{"message": "old 1"}\n'
    assert backup2.read_text(encoding="utf-8") == '{"message": "old 2"}\n'
    failures = [r for r in _records(path) if r.get("event") == "log_rotation_failed"]
    assert len(failures) == 1
    assert failures[0]["level"] == "WARNING" and "PermissionError" in failures[0]["error"]
    assert failures[0]["size_bytes"] > 500 and failures[0]["max_bytes"] == 1_000
    assert "Log rotation failed" in capsys.readouterr().err
    assert len(attempts) <= 2, "rotation was retried on every record"


def test_rotation_preserves_every_record(tmp_path, jsonl_logger):
    path = tmp_path / "stablenew.log.jsonl"
    log, handler = jsonl_logger(path, max_bytes=3_000, backup_count=50)

    _fill(log, 150)
    handler.flush()

    files = [path] + sorted(path.parent.glob(path.name + ".*"))
    messages = {r["message"] for r in _records(*files)}
    assert {f"record {i:04d} {'x' * 80}" for i in range(150)} <= messages
    assert not list(path.parent.glob("*.rotating"))


def test_attaching_twice_for_one_file_returns_the_same_handler(tmp_path):
    config = JsonlFileLogConfig(path=tmp_path / "logs" / "stablenew.log.jsonl")
    root = logging.getLogger()
    first = attach_jsonl_log_handler(config)
    try:
        second = attach_jsonl_log_handler(config)
        assert second is first
        assert sum(1 for h in root.handlers if isinstance(h, JsonlFileHandler)) == 1
    finally:
        for handler in [h for h in root.handlers if isinstance(h, JsonlFileHandler)]:
            root.removeHandler(handler)
            handler.close()
