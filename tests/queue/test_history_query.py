"""History search: filters, keyset paging, the examination budget, and that it never writes."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from src.pipeline.cli_njr_builder import build_cli_njr
from src.queue.history_query import HistoryPage, HistoryQuery
from src.queue.job_model import Job, JobStatus
from src.queue.job_repository import JobRepository


def _job(job_id: str, prompt: str, model: str = "m.safetensors") -> Job:
    record = build_cli_njr(
        prompt=prompt,
        batch_size=1,
        run_name=job_id,
        config={
            "txt2img": {"model": model, "steps": 4, "cfg_scale": 5.0, "width": 64, "height": 64}
        },
    )
    record = replace(record, job_id=job_id)
    job = Job(job_id=job_id, snapshot={"normalized_job": record.to_dict()})
    job._normalized_record = record  # type: ignore[attr-defined]
    return job


def _seed(repository: JobRepository, rows: list[tuple[str, str, str, str, str | None]]) -> None:
    """Insert ``(job_id, created_at, status, prompt, pack_id)`` rows."""

    for job_id, created_at, status, prompt, pack_id in rows:
        repository.record_job_submission(_job(job_id, prompt))
        with repository.transaction() as connection:
            connection.execute(
                "UPDATE jobs SET created_at = ?, status = ?, prompt_pack_id = ? WHERE job_id = ?",
                (created_at, status, pack_id, job_id),
            )


ROWS = [
    ("j1", "2026-10-01T10:00:00", "completed", "a red Dragon over hills", "pack-a"),
    ("j2", "2026-10-02T10:00:00", "failed", "a blue dragon", "pack-b"),
    ("j3", "2026-10-03T10:00:00", "completed", "a quiet harbor at dawn", "pack-a"),
    ("j4", "2026-10-04T10:00:00", "queued", "a red fox", None),
    ("j5", "2026-10-05T10:00:00", "completed", "a red dragon and a fox", "pack-b"),
    ("j6", "2026-10-06T10:00:00", "cancelled", "snowy harbor", None),
]


def _repository(tmp_path: Path) -> JobRepository:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    _seed(repository, ROWS)
    return repository


def _ids(page: HistoryPage) -> list[str]:
    return [entry.job_id for entry in page.entries]


def test_default_query_returns_everything_newest_first(tmp_path: Path) -> None:
    page = _repository(tmp_path).query_history(HistoryQuery())

    assert _ids(page) == ["j6", "j5", "j4", "j3", "j2", "j1"]
    assert page.exhausted is True


def test_paging_with_the_cursor_visits_every_job_once(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    seen: list[str] = []
    cursor = None
    for _ in range(10):
        page = repository.query_history(HistoryQuery(limit=2, cursor=cursor))
        seen.extend(_ids(page))
        if page.exhausted:
            break
        cursor = page.next_cursor

    assert seen == ["j6", "j5", "j4", "j3", "j2", "j1"]


def test_jobs_sharing_a_creation_time_page_without_gaps_or_repeats(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    _seed(
        repository,
        [(f"t{i}", "2026-10-01T10:00:00", "completed", f"tie {i}", None) for i in range(5)],
    )
    seen: list[str] = []
    cursor = None
    while True:
        page = repository.query_history(HistoryQuery(limit=2, cursor=cursor))
        seen.extend(_ids(page))
        if page.exhausted:
            break
        cursor = page.next_cursor

    assert sorted(seen) == [f"t{i}" for i in range(5)]
    assert len(seen) == len(set(seen))


def test_status_filter(tmp_path: Path) -> None:
    page = _repository(tmp_path).query_history(
        HistoryQuery(statuses=frozenset({JobStatus.COMPLETED, JobStatus.FAILED}))
    )

    assert _ids(page) == ["j5", "j3", "j2", "j1"]


def test_date_range_is_inclusive_of_the_start_and_exclusive_of_the_end(tmp_path: Path) -> None:
    page = _repository(tmp_path).query_history(
        HistoryQuery(
            created_from=datetime(2026, 10, 2, 10), created_before=datetime(2026, 10, 5, 10)
        )
    )

    assert _ids(page) == ["j4", "j3", "j2"]


def test_pack_filter_is_exact(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    assert _ids(repository.query_history(HistoryQuery(pack_id="pack-a"))) == ["j3", "j1"]
    assert _ids(repository.query_history(HistoryQuery(pack_id="pack"))) == []


def test_text_terms_are_all_required_and_case_insensitive(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    assert _ids(repository.query_history(HistoryQuery(text="DRAGON"))) == ["j5", "j2", "j1"]
    assert _ids(repository.query_history(HistoryQuery(text="red dragon"))) == ["j5", "j1"]
    assert _ids(repository.query_history(HistoryQuery(text="m.safetensors harbor"))) == ["j6", "j3"]


def test_filters_combine(tmp_path: Path) -> None:
    page = _repository(tmp_path).query_history(
        HistoryQuery(text="dragon", pack_id="pack-b", statuses=frozenset({JobStatus.COMPLETED}))
    )

    assert _ids(page) == ["j5"]


def test_text_with_sql_wildcards_matches_literally(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    assert _ids(repository.query_history(HistoryQuery(text="%"))) == []
    assert _ids(repository.query_history(HistoryQuery(text="_"))) == []


def test_budget_bounds_a_rare_search_and_the_cursor_continues_it(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    rows = [
        (f"n{i:02d}", f"2026-10-{i + 1:02d}T10:00:00", "completed", f"noise {i}", None)
        for i in range(20)
    ]
    rows[0] = ("n00", "2026-10-01T10:00:00", "completed", "needle", None)
    _seed(repository, rows)

    first = repository.query_history(HistoryQuery(text="needle", max_examined=5, limit=1))

    assert _ids(first) == []
    assert first.exhausted is False
    assert first.examined == 5

    cursor = first.next_cursor
    found: list[str] = []
    for _ in range(10):
        page = repository.query_history(
            HistoryQuery(text="needle", max_examined=5, limit=1, cursor=cursor)
        )
        found.extend(_ids(page))
        if page.exhausted or found:
            break
        cursor = page.next_cursor

    assert found == ["n00"]


def test_reaching_the_limit_on_the_last_row_still_reports_exhausted(tmp_path: Path) -> None:
    page = _repository(tmp_path).query_history(HistoryQuery(limit=6))

    assert len(page.entries) == 6
    assert page.exhausted is True


def test_a_query_changes_nothing(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    def fingerprint() -> tuple[object, ...]:
        with repository.transaction() as connection:
            schema = connection.execute(
                "SELECT type, name, sql FROM sqlite_master ORDER BY name"
            ).fetchall()
            rows = connection.execute(
                "SELECT job_id, status, updated_at, njr_fingerprint FROM jobs ORDER BY job_id"
            ).fetchall()
        return (tuple(tuple(row) for row in schema), tuple(tuple(row) for row in rows))

    before = fingerprint()
    repository.query_history(HistoryQuery(text="dragon", limit=2))
    repository.query_history(HistoryQuery(statuses=frozenset({JobStatus.FAILED})))

    assert fingerprint() == before
