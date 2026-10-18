"""Provenance is never lost silently (audit B9, P3-5)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from src.pipeline.cli_njr_builder import build_cli_njr
from src.queue import job_repository as job_repository_module
from src.queue.job_model import Job
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository, recent_integrity_errors
from src.utils.njr_identity import snapshot_envelope, snapshot_fingerprint, snapshot_json


def _job(job_id: str, prompt: str) -> Job:
    record = build_cli_njr(
        prompt=prompt,
        batch_size=1,
        run_name=job_id,
        config={
            "txt2img": {
                "model": "test.safetensors",
                "steps": 4,
                "cfg_scale": 5.0,
                "width": 64,
                "height": 64,
            }
        },
    )
    job = Job(job_id=record.job_id, snapshot={"normalized_job": record.to_dict()})
    job._normalized_record = record  # type: ignore[attr-defined]
    return job


@pytest.mark.parametrize("prompt", ["plain ascii", "café 山 \U0001f600 prompt"])
def test_the_runner_identity_equals_the_repository_fingerprint(tmp_path: Path, prompt: str) -> None:
    """One hash identity: embedded provenance must match the SQLite row, ASCII or not."""

    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    job = _job("hash-identity", prompt)
    queue.submit(job)
    stored = repository._connection.execute(  # noqa: SLF001 - persistence contract evidence
        "SELECT njr_fingerprint FROM jobs WHERE job_id = ?", (job.job_id,)
    ).fetchone()["njr_fingerprint"]
    record = job._normalized_record  # type: ignore[attr-defined]
    runner_identity = snapshot_fingerprint(
        snapshot_envelope(record.job_id, record.to_queue_snapshot())
    )
    assert runner_identity == stored
    repository.close()


def test_snapshot_json_is_ascii_canonical() -> None:
    text = snapshot_json(snapshot_envelope("j", {"b": "café", "a": 1}))
    assert text.isascii()
    assert text.index('"normalized_job"') < len(text)
    assert text == (
        '{"job_id":"j","normalized_job":{"a":1,"b":"caf\\u00e9"},"schema_version":"2.6"}'
    )


def test_a_corrupt_stored_column_is_logged_and_recorded_not_silently_defaulted(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    queue.submit(_job("corrupt-me", "a prompt"))
    repository._connection.execute(  # noqa: SLF001
        "UPDATE jobs SET result_json = ? WHERE job_id = ?", ("{not json", "corrupt-me")
    )
    repository._connection.commit()  # noqa: SLF001
    before = len(recent_integrity_errors())
    with caplog.at_level(logging.ERROR, logger=job_repository_module.logger.name):
        job = repository.get_job("corrupt-me")
    assert job is not None and job.result is None  # a bad row cannot take the history down
    assert "corrupt" in caplog.text and "corrupt-me" in caplog.text
    errors = recent_integrity_errors()
    assert len(errors) == before + 1
    assert errors[-1]["job_id"] == "corrupt-me" and errors[-1]["column"] == "result_json"
    repository.close()


def test_an_empty_column_is_not_corruption() -> None:
    before = len(recent_integrity_errors())
    assert job_repository_module._json_loads(None, {"d": 1}) == {"d": 1}  # noqa: SLF001
    assert job_repository_module._json_loads("", []) == []  # noqa: SLF001
    assert len(recent_integrity_errors()) == before


def test_a_raising_history_listener_is_logged_and_does_not_stop_the_others(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    seen: list[str] = []

    def _bad(entry) -> None:
        raise RuntimeError("listener bug")

    repository.register_callback(_bad)
    repository.register_callback(lambda entry: seen.append(entry.job_id))
    with caplog.at_level(logging.WARNING, logger=job_repository_module.logger.name):
        queue.submit(_job("listener-job", "a prompt"))
    assert "listener-job" in seen
    assert "listener bug" in caplog.text
    repository.close()


def test_a_raising_queue_status_listener_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    from src.queue import job_queue as job_queue_module

    queue = JobQueue()
    queue._status_callbacks.append(
        lambda job, status: (_ for _ in ()).throw(RuntimeError("cb bug"))
    )  # noqa: SLF001
    job = Job(job_id="q1")
    with caplog.at_level(logging.WARNING, logger=job_queue_module.logger.name):
        queue._notify_status(job, job.status)  # noqa: SLF001
    assert "cb bug" in caplog.text
