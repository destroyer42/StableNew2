"""PR-HISTORY-610A: an edited variation keeps truthful parent lineage and is never projected as an exact retry."""

from __future__ import annotations

from src.pipeline.history_variation_compiler import HistoryVariationDraft, compile_history_variation
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.queue.batch_projection import retry_children_from_rows
from src.queue.job_model import Job, JobPriority
from src.queue.job_repository import JobRepository
from tests.helpers.njr_factory import make_pipeline_njr


def _job(njr) -> Job:
    job = Job(job_id=njr.job_id, priority=JobPriority.NORMAL)
    job._normalized_record = njr
    job.snapshot = {"normalized_job": njr.to_dict()}
    return job


def test_variation_has_lineage_but_is_not_listed_as_a_replay_child(tmp_path):
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    parent = make_pipeline_njr(
        job_id="parent", config={"prompt": "p", "model": "sdxl", "steps": 20}
    )
    replay = compile_replay_intent(ReplayIntent(parent), id_fn=lambda: "replay-1")
    variation = compile_history_variation(
        HistoryVariationDraft.from_source(parent).with_edits(steps=33), id_fn=lambda: "variation-1"
    )
    repository.record_job_submissions([_job(parent), _job(replay), _job(variation)])

    children = repository.list_replay_child_rows(["parent"])
    assert [row.job_id for row in children] == ["replay-1"]
    assert set(retry_children_from_rows(children)) == {"parent"}

    # lineage is still persisted for the variation: the parent link is queryable and truthful
    assert (
        repository.get_job("variation-1").snapshot["normalized_job"]["source"]["parent_job_id"]
        == "parent"
    )
    row = repository._connection.execute(  # noqa: SLF001 - read-only projection check
        "SELECT parent_job_id FROM jobs WHERE job_id = ?", ("variation-1",)
    ).fetchone()
    assert row["parent_job_id"] == "parent"


def test_variation_is_distinguishable_from_unchanged_replay_in_the_snapshot(tmp_path):
    parent = make_pipeline_njr(
        job_id="parent", config={"prompt": "p", "model": "sdxl", "steps": 20}
    )
    replay = compile_replay_intent(ReplayIntent(parent), id_fn=lambda: "r")
    variation = compile_history_variation(
        HistoryVariationDraft.from_source(parent), id_fn=lambda: "v"
    )
    assert "history_variation" not in replay.source.to_dict()["metadata"]
    assert "history_variation" in variation.source.to_dict()["metadata"]
    assert replay.extra_metadata.get("replay") is True
    assert "replay" not in variation.extra_metadata
