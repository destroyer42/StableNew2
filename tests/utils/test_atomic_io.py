"""Crash-safe state writes: a failure mid-write must leave the previous content intact, never a truncated file.

Regression for the audit finding that Learning/UI/LoRA stores used ``Path.write_text`` (truncate-then-write); a hard reset
left a real ``session.json`` as 100,884 NUL bytes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.learning.experiment_store import LearningExperimentStore
from src.learning.learning_record import LearningRecord, LearningRecordWriter
from src.utils import atomic_io
from src.utils.atomic_io import atomic_write_json, atomic_write_text


def _leftovers(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.name.endswith(".tmp"))


def test_atomic_write_text_publishes_complete_content_and_creates_parents(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "state.json"
    atomic_write_text(target, "hello")
    assert target.read_text(encoding="utf-8") == "hello"
    assert _leftovers(target.parent) == []


def test_a_crash_before_the_replace_keeps_the_previous_file_and_leaves_no_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "session.json"
    target.write_text('{"version": 1}', encoding="utf-8")

    def boom(*_: object, **__: object) -> None:
        raise OSError("simulated reset")

    monkeypatch.setattr(atomic_io.os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_text(target, '{"version": 2}')
    monkeypatch.undo()
    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 1}
    assert _leftovers(tmp_path) == []


def test_content_is_flushed_to_disk_before_the_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(atomic_io.os, "fsync", lambda fd: (order.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(atomic_io.os, "replace", lambda a, b: (order.append("replace"), real_replace(a, b))[1])
    atomic_write_text(tmp_path / "x.json", "{}")
    assert order == ["fsync", "replace"]


def test_a_transient_windows_sharing_denial_is_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_replace = os.replace
    attempts = {"n": 0}

    def flaky(source: str, target: Path) -> None:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise PermissionError(13, "sharing violation")
        real_replace(source, target)

    monkeypatch.setattr(atomic_io.os, "replace", flaky)
    monkeypatch.setattr(atomic_io.time, "sleep", lambda _s: None)
    atomic_write_text(tmp_path / "x.json", "ok")
    assert attempts["n"] == 3 and (tmp_path / "x.json").read_text(encoding="utf-8") == "ok"


def test_a_persistent_denial_is_raised_not_swallowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(atomic_io.os, "replace", lambda *_: (_ for _ in ()).throw(PermissionError(13, "locked")))
    monkeypatch.setattr(atomic_io.time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        atomic_write_text(tmp_path / "x.json", "ok")
    assert _leftovers(tmp_path) == []


def test_a_payload_that_cannot_be_serialized_never_touches_the_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "x.json"
    target.write_text('{"keep": true}', encoding="utf-8")
    with pytest.raises(TypeError):
        atomic_write_json(target, {"bad": object()})
    assert json.loads(target.read_text(encoding="utf-8")) == {"keep": True}


def test_the_learning_experiment_store_keeps_the_last_good_session_when_a_write_is_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LearningExperimentStore(tmp_path)
    handle = store.save_session(display_name="exp", payload={"revision": 1})
    session = handle.session_path

    def boom(*_: object, **__: object) -> None:
        raise OSError("simulated reset")

    monkeypatch.setattr(atomic_io.os, "replace", boom)
    with pytest.raises(OSError):
        store.save_session(display_name="exp", payload={"revision": 2}, experiment_id=handle.experiment_id)
    monkeypatch.undo()
    assert store.load_session(handle.experiment_id) == {"revision": 1}
    assert session.read_bytes() != b"\x00" * session.stat().st_size  # never a zero-filled file


def test_the_record_writer_reports_failure_instead_of_silently_dropping_a_record(tmp_path: Path) -> None:
    writer = LearningRecordWriter(tmp_path / "records.jsonl")
    record = LearningRecord.from_json(json.dumps({"run_id": "r1", "timestamp": "2026-10-16T00:00:00Z"}))
    assert writer.append_record(record) is True

    writer.records_path = tmp_path / "missing_dir" / "records.jsonl"  # unwritable destination
    assert writer.append_record(record) is False


def test_a_rating_that_cannot_be_stored_is_raised_to_the_ui_and_never_cached_as_saved(tmp_path: Path) -> None:
    """The review panel catches the exception and shows 'Error saving rating'; the cache must not claim a save."""

    from tests.learning_v2.test_ordinary_global_prompts_141 import ordinary_plan

    exp, controller, _ = ordinary_plan(tmp_path, positive=True)
    variant = controller.learning_state.plan[0]
    variant.image_refs = ["image.png"]

    class _FailingWriter:
        def append_record(self, _record: object) -> bool:
            return False

    controller._learning_record_writer = _FailingWriter()
    with pytest.raises(OSError, match="could not be written"):
        controller.record_rating("image.png", 5)
    assert "image.png" not in controller._rating_cache
