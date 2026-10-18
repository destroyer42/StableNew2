"""The hygiene report: classification, protections, duplicate-snapshot accounting, and that it never writes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from src.pipeline.cli_njr_builder import build_cli_njr
from src.queue.job_hygiene_report import (
    ReportOptions,
    build_report,
    candidates_csv,
    format_report,
    open_read_only,
)
from src.queue.job_model import Job
from src.queue.job_repository import JobRepository

NOW = datetime(2026, 10, 18, 12, 0, 0)
OLD = "2026-08-01T10:00:00"
RECENT = "2026-10-17T10:00:00"


def _job(job_id: str) -> Job:
    record = build_cli_njr(
        prompt=f"prompt {job_id}",
        batch_size=1,
        run_name=job_id,
        config={
            "txt2img": {
                "model": "m.safetensors",
                "steps": 4,
                "cfg_scale": 5.0,
                "width": 64,
                "height": 64,
            }
        },
    )
    record = replace(record, job_id=job_id)
    job = Job(job_id=job_id, snapshot={"normalized_job": record.to_dict()})
    job._normalized_record = record  # type: ignore[attr-defined]
    return job


def _add(
    repo: JobRepository,
    job_id: str,
    *,
    created: str = OLD,
    status: str = "completed",
    refs=(),
    parent=None,
) -> None:
    repo.record_job_submission(_job(job_id))
    with repo.transaction() as connection:
        connection.execute(
            "UPDATE jobs SET created_at = ?, status = ?, artifact_references = ?, parent_job_id = ? WHERE job_id = ?",
            (created, status, json.dumps(list(refs)), parent, job_id),
        )


def _report(repo: JobRepository, tmp_path: Path, **kwargs):
    connection = open_read_only(repo.path)  # type: ignore[arg-type]
    try:
        options = ReportOptions(
            now=NOW, output_root=tmp_path / "out", learning_root=tmp_path / "learning", **kwargs
        )
        return build_report(connection, options, path=repo.path)
    finally:
        connection.close()


@pytest.fixture
def repo(tmp_path: Path) -> JobRepository:
    return JobRepository(tmp_path / "jobs.sqlite3")


def _classes(report) -> dict[str, int]:
    return {name: info["jobs"] for name, info in report["prune"]["classes"].items()}


def test_classification_and_protections(repo: JobRepository, tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "present.png").write_bytes(b"x")
    _add(repo, "present", refs=[str(out / "present.png")])
    _add(repo, "partly", refs=[str(out / "present.png"), str(out / "gone.png")])
    _add(repo, "gone", refs=[str(out / "gone.png"), str(out / "gone.json")])
    _add(repo, "gone-with-child", refs=[str(out / "gone2.png")])
    _add(repo, "child", refs=[str(out / "present.png")], parent="gone-with-child")
    _add(repo, "gone-in-learning", refs=[str(out / "gone3.png")])
    _add(repo, "no-outputs", status="failed", refs=[])
    _add(repo, "relative-gone", refs=["rel/gone.png"])
    _add(repo, "too-recent", created=RECENT, refs=[str(out / "gone4.png")])
    _add(repo, "queued", status="queued", refs=[str(out / "gone5.png")])
    learning = tmp_path / "learning"
    learning.mkdir()
    (learning / "learning_records.jsonl").write_text(
        '{"metadata": {"job_id": "gone-in-learning"}}\n', encoding="utf-8"
    )

    report = _report(repo, tmp_path)

    classes = _classes(report)
    assert (
        classes["candidate"] == 2
    )  # gone and relative-gone (the relative path resolves under the output root)
    assert classes["all_present"] == 2  # present, child
    assert classes["partly_missing"] == 1
    assert classes["no_outputs"] == 1
    assert classes["protected_has_replay_children"] == 1
    assert classes["protected_in_learning_files"] == 1
    assert report["prune"]["terminal_jobs_older_than_cutoff"] == 8  # not too-recent, not queued
    assert sorted(report["prune"]["candidate_job_ids"]) == ["gone", "relative-gone"]
    assert candidates_csv(report).splitlines()[0] == "job_id"


def test_relative_paths_without_an_output_root_are_never_candidates(
    repo: JobRepository, tmp_path: Path
) -> None:
    _add(repo, "relative-gone", refs=["rel/gone.png"])
    connection = open_read_only(repo.path)  # type: ignore[arg-type]
    report = build_report(connection, ReportOptions(now=NOW), path=repo.path)
    connection.close()

    assert _classes(report) == {"unresolvable": 1}
    assert report["prune"]["candidates"]["jobs"] == 0
    assert "unresolvable" in format_report(report)


def test_age_threshold_is_respected(repo: JobRepository, tmp_path: Path) -> None:
    _add(repo, "gone", created="2026-10-10T10:00:00", refs=[str(tmp_path / "gone.png")])

    assert _report(repo, tmp_path, older_than_days=30)["prune"]["candidates"]["jobs"] == 0
    assert _report(repo, tmp_path, older_than_days=5)["prune"]["candidates"]["jobs"] == 1


def _frozen(digest: str, experiment: str, padding: int) -> dict:
    return {
        "frozen_experiment": {
            "experiment_id": experiment,
            "snapshot_sha256": digest,
            "snapshot": {"arms": ["x" * padding]},
        }
    }


def test_duplicated_snapshots_are_counted_per_copy_and_estimated_once(
    repo: JobRepository, tmp_path: Path
) -> None:
    digest = hashlib.sha256(b"s").hexdigest()
    for job_id in ("a", "b", "c"):
        _add(repo, job_id)
        with repo.transaction() as connection:
            row = connection.execute(
                "SELECT njr_snapshot FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            snapshot = json.loads(row["njr_snapshot"])
            snapshot["normalized_job"]["workload"] = {"metadata": _frozen(digest, "exp-1", 1000)}
            snapshot["normalized_job"]["provenance"] = {"metadata": _frozen(digest, "exp-1", 1000)}
            connection.execute(
                "UPDATE jobs SET njr_snapshot = ? WHERE job_id = ?", (json.dumps(snapshot), job_id)
            )
    _add(repo, "plain")

    dup = _report(repo, tmp_path)["duplicated_snapshots"]

    assert dup["jobs_with_frozen_snapshot"] == 3
    assert dup["distinct_snapshots"] == 1
    assert dup["copies"] == 6
    one = dup["bytes_if_stored_once"]
    assert one > 1000
    assert dup["bytes_all_copies"] == 6 * one
    assert dup["estimated_saving_bytes"] == 5 * one
    assert dup["largest"][0]["jobs"] == 3
    assert dup["largest"][0]["experiment_id"] == "exp-1"


def test_totals_and_the_text_report(repo: JobRepository, tmp_path: Path) -> None:
    _add(repo, "a")
    _add(repo, "b", status="failed")

    report = _report(repo, tmp_path)
    text = format_report(report)

    assert report["jobs"]["total"] == 2
    assert report["jobs"]["by_status"] == {"completed": 1, "failed": 1}
    assert report["column_bytes"]["njr_snapshot"] > 0
    assert report["database"]["file_bytes"] > 0
    assert "nothing was changed" in text
    assert "Bytes by column" in text
    json.dumps(report)  # serializable


def test_the_report_cannot_write_and_leaves_the_database_untouched(
    repo: JobRepository, tmp_path: Path
) -> None:
    _add(repo, "a")
    before = repo.path.read_bytes()  # type: ignore[union-attr]
    _report(repo, tmp_path)

    connection = open_read_only(repo.path)  # type: ignore[arg-type]
    with pytest.raises(Exception, match="readonly|read-only|query_only"):
        connection.execute("DELETE FROM jobs")
    connection.close()
    assert repo.path.read_bytes() == before  # type: ignore[union-attr]
    assert repo.count() == 1


def test_the_command_line_prints_json_and_writes_the_candidate_list(
    repo: JobRepository, tmp_path: Path, capsys
) -> None:
    from tools.job_repository_report import main

    _add(repo, "gone", refs=[str(tmp_path / "gone.png")])
    csv_path = tmp_path / "candidates.csv"

    code = main(
        [
            "--database",
            str(repo.path),
            "--learning-root",
            str(tmp_path / "learning"),
            "--candidates-csv",
            str(csv_path),
            "--json",
            "--older-than-days",
            "1",
        ]
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["prune"]["candidates"]["jobs"] == 1
    assert csv_path.read_text(encoding="utf-8").split() == ["job_id", "gone"]
    assert main(["--database", str(tmp_path / "missing.sqlite3")]) == 2


def test_a_missing_learning_folder_is_called_out(repo: JobRepository, tmp_path: Path) -> None:
    _add(repo, "gone", refs=[str(tmp_path / "gone.png")])

    report = _report(repo, tmp_path)  # tmp_path / "learning" does not exist

    assert report["prune"]["criteria"]["learning_root_found"] is False
    assert "Learning folder not found" in format_report(report)


def test_the_command_line_runs_without_importing_the_application(
    repo: JobRepository, tmp_path: Path
) -> None:
    """A machine without the project's dependencies (no ``requests``) must still be able to run the report."""

    import subprocess
    import sys

    _add(repo, "gone", refs=[str(tmp_path / "gone.png")])
    tool = Path(__file__).resolve().parents[2] / "tools" / "job_repository_report.py"
    code = (
        "import runpy, sys\n"
        f"ns = runpy.run_path({str(tool)!r}, run_name='report_tool')\n"
        f"rc = ns['main'](['--database', {str(repo.path)!r}, '--learning-root', {str(tmp_path / 'learning')!r}])\n"
        "assert not any(name == 'src' or name.startswith('src.') for name in sys.modules), 'imported the application'\n"
        "assert 'requests' not in sys.modules\n"
        "raise SystemExit(rc)\n"
    )

    result = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=120
    )

    assert result.returncode == 0, result.stderr
    assert "Job repository hygiene report" in result.stdout
