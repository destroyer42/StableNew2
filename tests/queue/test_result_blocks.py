"""KEEP-SPACE: a job result's repeated prompt-optimizer record is stored once by hash; callers see no difference."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from src.queue import result_blocks
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository, recent_integrity_errors
from tests.queue.test_job_repository_sqlite import _job


def _record(prompt: str = "a lighthouse") -> dict[str, Any]:
    return {"inputs": {"positive_original": prompt}, "policy": {"rationale": ["keep"] * 80}}


def _result(prompt: str = "a lighthouse") -> dict[str, Any]:
    """The shape a pipeline result has: the same record in four places."""

    return {
        "variants": [{"path": "output/a.png", "prompt_optimizer_v3": _record(prompt)}],
        "metadata": {
            "replay_descriptor": {"prompt_optimizer_v3": _record(prompt)},
            "diagnostics_descriptor": {
                "prompt_optimizer_v3": _record(prompt),
                "replay_descriptor": {"prompt_optimizer_v3": _record(prompt)},
            },
        },
    }


def _complete(queue: JobQueue, job_id: str, result: dict[str, Any]) -> None:
    queue.submit(_job(job_id))
    queue.mark_running(job_id)
    queue.mark_completed(job_id, result)


def _rows(path: Path, sql: str) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(path)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def test_each_record_is_stored_once_and_every_reader_gets_it_back(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    repository = JobRepository(path)
    queue = JobQueue(repository=repository)
    _complete(queue, "one", _result())
    _complete(queue, "two", _result())
    repository.close()

    stored = [text for (text,) in _rows(path, "SELECT result_json FROM jobs")]
    blocks = _rows(path, "SELECT sha256, block_json FROM result_blocks")
    assert len(blocks) == 1 and json.loads(blocks[0][1]) == _record()
    assert all("positive_original" not in text and blocks[0][0] in text for text in stored)
    with JobRepository(path) as restarted:
        assert restarted.get_job_model("one").result == _result()  # type: ignore[union-attr]
        assert restarted.get_job("two").result == _result()  # type: ignore[union-attr]
        assert [entry.result for entry in restarted.list_jobs(JobStatus.COMPLETED)] == [
            _result()
        ] * 2
        candidates = restarted.read_review_child_rows(parent_job_ids=["nothing"])
        assert candidates == ()
        assert restarted.get_artifact_references("one") == ["output/a.png"]


def test_the_returned_job_and_its_copies_are_independent_full_objects(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    _complete(queue, "one", _result())

    result = repository.get_job("one").result  # type: ignore[union-attr]
    result["variants"][0]["prompt_optimizer_v3"]["inputs"]["positive_original"] = "changed"

    assert result["metadata"]["replay_descriptor"]["prompt_optimizer_v3"] == _record()


def test_a_row_written_before_keeps_its_bytes_and_reads_as_stored(tmp_path: Path) -> None:
    """The migration only adds a table: an existing repository keeps every row byte for byte."""

    path = tmp_path / "jobs.sqlite3"
    repository = JobRepository(path)
    _complete(JobQueue(repository=repository), "old", {"variants": []})
    repository.close()
    legacy = json.dumps(_result(), sort_keys=True, separators=(",", ":"))
    connection = sqlite3.connect(path)
    with connection:
        connection.execute("DROP TABLE result_blocks")
        connection.execute("UPDATE jobs SET result_json = ?", (legacy,))
    connection.close()

    with JobRepository(path) as upgraded:
        assert upgraded.get_job("old").result == _result()  # type: ignore[union-attr]
        assert upgraded.schema_version == 1

    assert _rows(path, "SELECT result_json FROM jobs") == [(legacy,)]
    assert _rows(path, "SELECT COUNT(*) FROM result_blocks") == [(0,)]


def test_a_failed_transition_stores_neither_the_row_nor_its_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    queue.submit(_job("one"))
    queue.mark_running("one")

    def fail(_row: Any) -> Any:
        raise RuntimeError("after the update")

    monkeypatch.setattr(repository, "_row_to_job", fail)
    job = queue.get_job("one")
    assert job is not None
    with pytest.raises(RuntimeError):
        repository.transition_job(job, JobStatus.COMPLETED, result=_result())

    assert _rows(tmp_path / "jobs.sqlite3", "SELECT COUNT(*) FROM result_blocks") == [(0,)]


@pytest.mark.parametrize(
    ("damage", "reason"),
    [
        ("UPDATE result_blocks SET block_json = '{}'", "does not match"),
        ("DELETE FROM result_blocks", "is not stored"),
    ],
)
def test_a_damaged_or_missing_block_is_reported_and_never_stands_in(
    tmp_path: Path, damage: str, reason: str
) -> None:
    path = tmp_path / "jobs.sqlite3"
    repository = JobRepository(path)
    _complete(JobQueue(repository=repository), "one", _result())
    repository.close()
    connection = sqlite3.connect(path)
    with connection:
        connection.execute(damage)
    connection.close()

    with JobRepository(path) as restarted:
        entry = restarted.get_job("one")

    assert entry is not None and entry.status == JobStatus.COMPLETED
    block = entry.result["variants"][0]["prompt_optimizer_v3"]  # type: ignore[index]
    assert set(block) == {result_blocks.REFERENCE_KEY}
    assert any(reason in item["error"] for item in recent_integrity_errors())


def test_a_short_record_and_other_keys_stay_in_the_row() -> None:
    value = {"prompt_optimizer_v3": {"a": 1}, "other": _record()}

    compact, bodies = result_blocks.externalize(value)

    assert compact == value and bodies == {}
