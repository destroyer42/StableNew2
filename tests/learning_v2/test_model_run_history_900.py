"""MEC-900: per-checkpoint run history is read-only, path-free and observational."""

from __future__ import annotations

import json
from types import SimpleNamespace

from src.learning.model_run_history import (
    ModelRunSummary,
    RunRow,
    clean_error,
    read_run_history,
    summarize_runs,
)
from src.queue.job_repository import JobRepository


def snapshot(model: str, *, steps=30, cfg=7.0, sampler="DPM++ 2M", width=1024, height=1024):
    return json.dumps(
        {
            "normalized_job": {
                "stages": [
                    {
                        "stage_type": "txt2img",
                        "model": model,
                        "steps": steps,
                        "cfg_scale": cfg,
                        "sampler_name": sampler,
                        "scheduler": "Karras",
                    },
                    {"stage_type": "adetailer", "model": None, "steps": 14},
                ],
                "workload": {"config": {"width": width, "height": height}},
            }
        }
    )


def row(model, status="completed", error=None, **settings):
    return RunRow(
        status, "2026-10-01T10:00:00", "2026-10-02T10:00:00", snapshot(model, **settings), error
    )


def test_summary_groups_by_checkpoint_name_and_counts_only_completed_settings():
    rows = [
        row("sub/Turbo.safetensors [abc123]", steps=36, cfg=8.1),
        row("Turbo.safetensors", steps=36, cfg=8.1),
        row(
            "turbo.safetensors",
            status="failed",
            error=r"boom at C:\Users\me\models\Turbo.safetensors now",
        ),
        row("Turbo.safetensors", status="cancelled", steps=4, cfg=0.0),
        row("other.safetensors", status="queued"),
        RunRow("completed", None, None, "not json", None),
        RunRow("completed", None, None, json.dumps({"normalized_job": {"stages": []}}), None),
    ]
    summary = summarize_runs(rows)
    assert set(summary) == {"turbo", "other"}
    turbo = summary["turbo"]
    assert (turbo.completed, turbo.failed, turbo.cancelled, turbo.active) == (2, 1, 1, 0)
    settings = dict(turbo.settings)
    assert settings["steps"] == (("36", 2),)  # the cancelled run's 4 steps is not "used"
    assert settings["cfg_scale"] == (("8.1", 2),)
    assert turbo.resolution == (("1024x1024", 2),)
    assert turbo.last_run == "2026-10-02"
    message, count = turbo.errors[0]
    assert count == 1 and "Users" not in message and "<path>" in message
    assert summary["other"].active == 1 and summary["other"].runs_label() == "0 ok / 0 failed"


def test_verdicts_describe_history_without_claiming_quality():
    assert "Never completed" in ModelRunSummary(failed=3).verdict()
    assert "Unreliable" in ModelRunSummary(completed=1, failed=3).verdict()
    assert "without a failure" in ModelRunSummary(completed=5).verdict()
    assert ModelRunSummary().runs_label() == "none"
    text = "\n".join(ModelRunSummary(completed=2, failed=1, errors=(("x", 1),)).describe())
    assert "2 completed, 1 failed" in text and "failure x1: x" in text


def test_clean_error_is_one_bounded_line():
    cleaned = clean_error("first\nsecond /home/user/private/file.txt " + "y" * 400)
    assert "\n" not in cleaned and "private" not in cleaned and len(cleaned) <= 140


def test_paging_reads_every_window_and_honours_cancel():
    pages = [
        SimpleNamespace(rows=(row("a.safetensors"),), next_cursor=5, exhausted=False),
        SimpleNamespace(
            rows=(row("a.safetensors", status="failed"),), next_cursor=0, exhausted=True
        ),
    ]
    cursors = []

    class Repo:
        def read_run_evidence_page(self, *, before_cursor=None, window=2000):
            cursors.append(before_cursor)
            return pages[len(cursors) - 1]

    result = read_run_history(Repo())
    assert cursors == [None, 5] and (result["a"].completed, result["a"].failed) == (1, 1)
    try:
        read_run_history(Repo(), cancelled=lambda: True)
    except InterruptedError:
        pass
    else:  # pragma: no cover
        raise AssertionError("cancel must stop paging")


def test_repository_page_is_a_bounded_read_of_existing_rows(tmp_path):
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    columns = (
        "job_id, njr_snapshot, njr_fingerprint, priority, queue_order, status, created_at, queued_at, "
        "updated_at, run_mode, source, prompt_source, randomizer_metadata, execution_metadata, "
        "artifact_references, error_message, completed_at, payload_summary"
    )
    with repository._lock:
        for index in range(5):
            repository._connection.execute(
                f"INSERT INTO jobs ({columns}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"job-{index}",
                    snapshot("m.safetensors"),
                    "fp",
                    0,
                    index,
                    "failed" if index == 0 else "completed",
                    "2026-10-01T00:00:00",
                    "2026-10-01T00:00:00",
                    "2026-10-01T00:00:00",
                    "queue",
                    "test",
                    "manual",
                    "{}",
                    "{}",
                    "[]",
                    "bad" if index == 0 else None,
                    "2026-10-03T00:00:00",
                    "",
                ),
            )
        repository._connection.commit()
    first = repository.read_run_evidence_page(window=3)
    assert len(first.rows) == 3 and not first.exhausted
    rest = repository.read_run_evidence_page(before_cursor=first.next_cursor, window=3)
    assert len(rest.rows) == 2 and rest.exhausted
    summary = read_run_history(repository, window=2)["m"]
    assert (summary.completed, summary.failed) == (4, 1) and summary.errors == (("bad", 1),)
    repository.close()
