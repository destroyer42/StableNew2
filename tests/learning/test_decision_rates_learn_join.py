"""LEARN-JOIN: decisions joined to job NJRs, rates by recipe, and the data threshold."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

from src.app.review_gateway_store import SyncLedger, read_published_image_digests
from src.controller.app_controller_services.pack_model_batch_service import (
    BATCH_SCHEMA,
    batch_identity,
)
from src.gui.controllers.keep_rates_loader import load_keep_rates
from src.learning.decision_rates import (
    FACTOR_CFG,
    FACTOR_EMBEDDING,
    FACTOR_LORA,
    FACTOR_PACK,
    FACTOR_SAMPLER,
    FACTOR_STEPS,
    NOT_ENOUGH,
    Decision,
    JobFacts,
    build_report,
    current_decisions,
    difference_interval,
    job_facts,
    summary_lines,
)
from src.pipeline.job_models_v2 import LoRATag
from src.queue.job_model import Job
from src.queue.job_repository import JobRepository
from src.review.review_evidence import REVIEW_BATCH, save_disposition
from src.review.review_lineage import batch_of_job_reader
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config

BATCH = {"schema": BATCH_SCHEMA, "batch_id": "b-1", "name": "Night run"}


def _record(job_id: str):
    return make_pipeline_njr(
        job_id=job_id,
        stage_chain=[
            make_stage_config(
                model="Folder\\Alpha.safetensors [abc123]",
                sampler_name="DPM++ 2M",
                scheduler="Karras",
                steps=30,
                cfg_scale=7.0,
            )
        ],
        prompt_pack_id="pack-a",
        prompt_pack_name="Pack A",
        lora_tags=(LoRATag("detail", 0.8),),
        positive_embeddings=("good",),
        negative_embeddings=("bad",),
    )


def _snapshot(job_id: str = "job-1") -> dict:
    record = _record(job_id).to_dict()
    record["provenance"]["matrix_slot_values"] = {"pose": "standing  up"}
    record["provenance"]["txt2img_prompt_info"] = {
        "final_prompt": "(good:1.2), a cat",
        "final_negative_prompt": "bad, blurry",
    }
    record["provenance"]["metadata"] = {"batch": BATCH}
    return {"normalized_job": record}


def _row(digest: str, disposition: str, *, job_id: str = "job-1", **metadata) -> dict:
    return {
        "primary_model": "alpha",
        "metadata": {
            "record_kind": "review_disposition",
            "artifact_sha256": digest,
            "review_disposition": disposition,
            "image_path": f"C:/out/{digest}.png",
            "source_job_id": job_id,
            **metadata,
        },
    }


def test_job_facts_reads_every_factor_from_the_stored_snapshot() -> None:
    facts = job_facts(_snapshot())

    assert facts.model == "alpha"
    assert facts.model_name == "Alpha"
    assert facts.factors["Slot: pose"] == ("standing up",)
    assert facts.factors[FACTOR_LORA] == ("detail @ 0.8",)
    assert facts.factors[FACTOR_EMBEDDING] == ("good @ 1.2", "bad @ 1 (negative)")
    assert facts.factors[FACTOR_SAMPLER] == ("DPM++ 2M / Karras",)
    assert facts.factors[FACTOR_STEPS] == ("30",)
    assert facts.factors[FACTOR_CFG] == ("7",)
    assert facts.factors[FACTOR_PACK] == ("Pack A",)
    assert (facts.batch_id, facts.batch_name) == ("b-1", "Night run")


def test_the_latest_row_decides_and_undo_and_rework_remove_the_image() -> None:
    rows = [
        _row("a", "retain", review_favorite=True, review_tags=["face"]),
        _row("b", "retain"),
        _row("b", "discard", job_id=""),  # the earlier row's job id is carried forward
        _row("c", "retain"),
        _row("c", "cleared"),
        _row("d", "rework"),
        {"metadata": {"record_kind": "review_tab_feedback", "artifact_sha256": "e"}},
    ]

    found = {decision.digest: decision for decision in current_decisions(rows)}

    assert set(found) == {"a", "b"}
    assert found["a"].favorite and found["a"].tags == ("face",)
    assert found["b"].disposition == "discard" and found["b"].job_id == "job-1"


def _decisions(prefix: str, job_id: str, kept: int, deleted: int) -> list[Decision]:
    return [
        Decision(f"{prefix}{index}", "retain" if index < kept else "discard", job_id=job_id)
        for index in range(kept + deleted)
    ]


def _facts(steps: str) -> JobFacts:
    return JobFacts(model="alpha", model_name="Alpha", factors={FACTOR_STEPS: (steps,)})


def test_a_difference_is_shown_only_when_the_interval_excludes_zero() -> None:
    facts = {"low": _facts("20"), "high": _facts("30")}

    big = build_report(_decisions("a", "low", 50, 50) + _decisions("b", "high", 90, 10), facts)
    rows = {row.option: row for row in big.by_model["Alpha"][FACTOR_STEPS]}
    assert rows["30"].difference.startswith("kept +40 pts (+")
    assert rows["20"].difference.startswith("kept -40 pts")

    # 85% against 80% with 200 each is not enough, and 29 images is never enough.
    close = build_report(_decisions("a", "low", 160, 40) + _decisions("b", "high", 170, 30), facts)
    assert {row.difference for row in close.by_model["Alpha"][FACTOR_STEPS]} == {NOT_ENOUGH}
    thin = build_report(_decisions("a", "low", 0, 29) + _decisions("b", "high", 90, 10), facts)
    assert {row.difference for row in thin.by_model["Alpha"][FACTOR_STEPS]} == {NOT_ENOUGH}


def test_telling_85_from_80_percent_takes_about_900_images_each() -> None:
    low, _high = difference_interval((765, 900), (720, 900), z=1.959964)
    assert low > 0
    low, _high = difference_interval((255, 300), (240, 300), z=1.959964)
    assert low < 0


def test_report_counts_unjoined_videos_undecided_favourites_and_batches() -> None:
    decisions = [
        Decision("a", "retain", favorite=True, tags=("face",), job_id="job-1"),
        Decision("b", "discard", job_id="gone", model="alpha"),
        Decision("v", "retain", job_id="job-1", video=True),
        Decision("c", "retain", job_id="", batch={"batch_id": "b-2", "name": "Stamped"}),
    ]

    report = build_report(decisions, {"job-1": job_facts(_snapshot())}, published={"a", "z"})

    assert (report.overall.decided, report.joined, report.unjoined, report.videos) == (3, 1, 2, 1)
    assert report.undecided == 1
    assert report.models[0].counts.favorites == 1
    assert {row.option for row in report.batches} == {"Night run", "Stamped"}
    assert "Joined to a job: 1 of 3." in " ".join(summary_lines(report))


def _repository(path: Path, job_id: str = "job-1") -> JobRepository:
    record = replace(_record(job_id), job_id=job_id)
    metadata = dict(record.extra_metadata or {})
    metadata["batch"] = BATCH
    from src.pipeline.policy_warnings import with_provenance_metadata

    record = with_provenance_metadata(record, metadata)
    job = Job(job_id=job_id, snapshot={"normalized_job": record.to_dict()})
    job._normalized_record = record  # type: ignore[attr-defined]
    repository = JobRepository(path)
    repository.record_job_submission(job)
    return repository


def test_the_database_is_only_read_and_unknown_ids_are_absent(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    _repository(path).close()
    before = path.read_bytes()

    found = JobRepository.read_snapshots_for_jobs(path, ["job-1", "missing", "job-1"])

    assert list(found) == ["job-1"]
    assert path.read_bytes() == before
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    plan = connection.execute(
        "EXPLAIN QUERY PLAN SELECT job_id, njr_snapshot FROM jobs WHERE job_id IN (?, ?)",
        ("a", "b"),
    ).fetchall()
    connection.close()
    assert "SEARCH" in str(plan)


def test_a_decision_row_is_stamped_with_its_batch_and_loads_into_the_report(tmp_path: Path) -> None:
    from src.learning.learning_record import LearningRecordWriter

    repository = _repository(tmp_path / "jobs.sqlite3")
    image = tmp_path / "one.png"
    image.write_bytes(b"not really a png")
    writer = LearningRecordWriter(tmp_path / "learning_records.jsonl")

    record = save_disposition(
        writer,
        image_path=image,
        disposition="retain",
        source_job_id="job-1",
        batch_of_job=batch_of_job_reader(repository, batch_identity),
    )
    repository.close()
    assert record.metadata[REVIEW_BATCH] == {"batch_id": "b-1", "name": "Night run"}

    report = load_keep_rates(
        writer.records_path, tmp_path / "jobs.sqlite3", ledger_path=tmp_path / "no-ledger.sqlite3"
    )
    assert (report.overall.kept, report.joined, report.undecided) == (1, 1, None)
    assert report.batches[0].option == "Night run"
    assert not (tmp_path / "no-ledger.sqlite3").exists()


def test_a_failing_batch_lookup_never_blocks_the_decision(tmp_path: Path) -> None:
    from src.learning.learning_record import LearningRecordWriter

    image = tmp_path / "one.png"
    image.write_bytes(b"x")
    writer = LearningRecordWriter(tmp_path / "records.jsonl")

    def broken(_job_id: str):
        raise RuntimeError("database is locked")

    record = save_disposition(
        writer, image_path=image, disposition="discard", source_job_id="job-1", batch_of_job=broken
    )

    assert REVIEW_BATCH not in record.metadata
    assert json.loads(writer.records_path.read_text(encoding="utf-8"))["metadata"]["source_job_id"]


def test_published_digests_are_read_from_an_existing_ledger(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    ledger = SyncLedger(path)
    ledger.mark_published("one", "v", "a.png", "AA", "image", "published", "now")
    ledger.mark_published("two", "v", "b.png", "bb", "image", "skipped", "now")
    ledger.mark_published("three", "v", "c.mp4", "cc", "video", "published", "now")

    assert read_published_image_digests(path) == {"aa"}
    assert read_published_image_digests(tmp_path / "none.sqlite3") is None
