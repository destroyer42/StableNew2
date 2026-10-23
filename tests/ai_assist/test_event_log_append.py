"""The event log is a true append-only log: concurrent writers (threads, objects, processes) never lose records (F5)."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from src.ai_assist.events import MAX_BYTES, EventLog

REPO_ROOT = Path(__file__).resolve().parents[2]


def _ids(log: EventLog, count: int = 100000) -> list[str]:
    return [str(record["request_id"]) for record in log.tail(count)]


def test_one_record_is_one_complete_line_and_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    assert EventLog(path).append({"request_id": "r1", "outcome": "suggestion"})
    assert EventLog(path).append({"request_id": "r2", "outcome": "refused_by_model"})
    lines = path.read_bytes().splitlines()
    assert len(lines) == 2 and all(json.loads(line)["request_id"] for line in lines)
    assert _ids(EventLog(path)) == ["r1", "r2"]


def test_many_log_objects_in_one_process_share_one_lock_and_lose_nothing(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    logs = [EventLog(path) for _ in range(4)]

    def work(index: int) -> None:
        for number in range(25):
            assert logs[index].append({"request_id": f"w{index}-{number}"})

    threads = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]
    ids = _ids(EventLog(path))
    assert len(ids) == 100 and len(set(ids)) == 100


_CHILD = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, {root!r})
    from src.ai_assist.events import EventLog
    log = EventLog({path!r})
    ok = all(log.append({{"request_id": "p{index}-" + str(n)}}) for n in range({count}))
    sys.exit(0 if ok else 3)
    """
)


def test_separate_processes_appending_to_the_same_log_lose_no_record(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                _CHILD.format(root=str(REPO_ROOT), path=str(path), index=index, count=60),
            ],
        )
        for index in range(4)
    ]
    assert [process.wait(timeout=120) for process in processes] == [0, 0, 0, 0]
    ids = _ids(EventLog(path))
    assert len(ids) == 240 and len(set(ids)) == 240
    for index in range(4):
        assert [n for n in range(60) if f"p{index}-{n}" in set(ids)] == list(range(60))
    for line in path.read_bytes().splitlines():
        json.loads(line)  # no interleaved or partial line anywhere


def test_a_torn_final_line_is_skipped_and_the_next_record_starts_a_fresh_line(
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.jsonl"
    path.write_bytes(b'{"request_id":"ok"}\n{"request_id":"to')
    log = EventLog(path)
    assert _ids(log) == ["ok"]
    assert log.append({"request_id": "after"})
    assert _ids(log) == ["ok", "after"]
    assert (
        path.read_bytes().endswith(b'{"request_id":"after"}\n') or b'"after"' in path.read_bytes()
    )
    assert log.tail(1)[0]["request_id"] == "after"


def test_a_reader_racing_a_writer_never_raises_and_never_sees_a_partial_record(
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.jsonl"
    log = EventLog(path)
    stop = threading.Event()
    problems: list[BaseException] = []

    def read() -> None:
        reader = EventLog(path)
        try:
            while not stop.is_set():
                for record in reader.tail(50):
                    assert set(record) <= {"utc", "request_id"}
        except BaseException as exc:  # noqa: BLE001 - recorded and asserted below
            problems.append(exc)

    thread = threading.Thread(target=read)
    thread.start()
    for index in range(300):
        assert log.append({"request_id": f"r{index}"})
    stop.set()
    thread.join(20)
    assert not problems
    assert len(_ids(log)) == 300


def test_the_log_rotates_by_size_keeps_one_generation_and_loses_nothing_it_keeps(
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.jsonl"
    log = EventLog(path, max_bytes=2048)
    for index in range(200):
        assert log.append({"request_id": f"r{index:04d}", "reason": "x" * 40})
    rotated = path.with_name(path.name + ".1")
    assert rotated.exists() and path.stat().st_size <= 2048 + 300
    ids = _ids(log)
    assert ids == sorted(ids) and ids[-1] == "r0199"
    assert len(ids) == len(set(ids))
    assert MAX_BYTES > 100 * 1024


def test_a_write_failure_returns_false_and_never_raises(tmp_path: Path) -> None:
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    assert EventLog(blocked).append({"request_id": "x"}) is False


def test_oversized_or_foreign_fields_are_refused_before_anything_is_written(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    log = EventLog(path)
    for bad in ({"prompt": "text"}, {"reason": "x" * 200}, {"request_id": ["a"]}):
        with pytest.raises(ValueError):
            log.append(bad)
    assert not path.exists()
