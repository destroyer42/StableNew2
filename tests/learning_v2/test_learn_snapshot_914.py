"""LEARN-SNAPSHOT-914: a Learning job carries its frozen experiment snapshot by hash, stored once by JobRepository.

Every test runs the real ``JobService`` over a temporary SQLite repository (no runner, no network, no GPU). The owner's
real repository is not touched; its saving is reported by the read-only ``tools/job_repository_report.py``.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from src.controller.submission_policy_v26 import SubmissionPolicy
from src.learning.execution_controller import (
    LearningExecutionController,
    experiment_snapshot_bodies,
)
from src.learning.experiment_execution import snapshot_digest, thaw_snapshot
from src.learning.experiment_reconciliation import read_job_evidence
from src.learning.intelligence_sources import read_rating_log
from src.learning.learning_record import LearningRecordWriter
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.queue.job_hygiene_report import build_report, format_report, open_read_only
from src.queue.job_repository import JobRepository, JobRepositoryError
from src.utils.experiment_snapshot_ref import (
    ExperimentSnapshotIntegrityError,
    ExperimentSnapshotUnavailable,
    resolve_experiment_snapshot,
)
from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot
from tests.golden.route_records import real_job_service
from tests.learning_v2.test_model_comparison_140 import (
    KLEIN,
    SDXL,
    baseline,
    controller_for,
    experiment,
)

THREE_ARMS = [SDXL, "peer.safetensors", KLEIN]


def _run(tmp_path: Path, service: Any, models: list[str] = THREE_ARMS) -> tuple[Any, Any]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    exp = experiment(tmp_path, models=models)
    controller = controller_for(exp, baseline())
    controller.pipeline_controller = object()
    controller.execution_controller = LearningExecutionController(
        controller.learning_state, service
    )
    controller.run_plan()
    return controller, exp


def _stored_rows(path: Path) -> list[sqlite3.Row]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(
            "SELECT job_id, njr_snapshot, njr_fingerprint FROM jobs"
        ).fetchall()
    finally:
        connection.close()


def test_three_arm_comparison_stores_the_snapshot_once_and_each_njr_only_its_hash(
    tmp_path: Path,
) -> None:
    with real_job_service(tmp_path / "queue") as service:
        controller, exp = _run(tmp_path, service)
        repository = service.history_store
        body = exp.execution_snapshot_json
        digest = snapshot_digest(body)
        rows = _stored_rows(tmp_path / "queue" / "state" / "jobs.sqlite3")
        assert len(rows) == 3
        for row in rows:
            text = row["njr_snapshot"]
            assert body not in text
            assert json.dumps(thaw_snapshot(body)["model_comparison"], sort_keys=True) not in text
            assert text.count(digest) <= 2
            stored = json.loads(text)["normalized_job"]
            for metadata in (stored["workload"]["metadata"], stored["provenance"]["metadata"]):
                frozen = metadata["frozen_experiment"]
                assert "snapshot" not in frozen
                assert frozen["snapshot_storage"] == "job_repository"
                assert frozen["schema_version"] == 2
                assert frozen["snapshot_sha256"] == digest
        assert repository.count_experiment_snapshots() == 1
        assert repository.get_experiment_snapshot(digest) == body
        for variant in controller.learning_state.plan:
            evidence = read_job_evidence(repository, exp, variant)
            assert not evidence.error, evidence.error
            assert resolve_experiment_snapshot(
                evidence.job._normalized_record.extra_metadata, repository.get_experiment_snapshot
            ) == thaw_snapshot(body)


def test_a_second_experiment_adds_one_row_and_a_restart_still_resolves(tmp_path: Path) -> None:
    with real_job_service(tmp_path / "queue") as service:
        _run(tmp_path / "a", service)
        _, second = _run(tmp_path / "b", service, models=[SDXL, "peer.safetensors"])
        assert service.history_store.count_experiment_snapshots() == 2
    reopened = JobRepository(tmp_path / "queue" / "state" / "jobs.sqlite3")
    try:
        job = next(
            job
            for job in reopened.list_job_models()
            if job._normalized_record.extra_metadata["frozen_experiment"]["snapshot_sha256"]
            == snapshot_digest(second.execution_snapshot_json)
        )
        assert resolve_experiment_snapshot(
            job._normalized_record.extra_metadata, reopened.get_experiment_snapshot
        ) == thaw_snapshot(second.execution_snapshot_json)
    finally:
        reopened.close()


def test_a_replay_of_a_new_job_resolves_the_stored_snapshot_without_supplying_it(
    tmp_path: Path,
) -> None:
    with real_job_service(tmp_path / "queue") as service:
        _, exp = _run(tmp_path, service)
        repository = service.history_store
        parent = repository.list_job_models()[0]._normalized_record
        replay = compile_replay_intent(ReplayIntent(parent), id_fn=lambda: "replay-914")
        assert service.submit_njrs([replay], SubmissionPolicy()) == ["replay-914"]
        stored = repository.get_job_model("replay-914")._normalized_record
        assert resolve_experiment_snapshot(
            stored.extra_metadata, repository.get_experiment_snapshot
        ) == thaw_snapshot(exp.execution_snapshot_json)
        assert repository.count_experiment_snapshots() == 1


def test_a_job_referring_to_an_unstored_snapshot_is_refused_all_or_none(tmp_path: Path) -> None:
    exp = experiment(tmp_path, models=THREE_ARMS)
    controller = controller_for(exp, baseline())
    records = [controller._build_variant_njr(v, exp) for v in controller.learning_state.plan]
    with real_job_service(tmp_path / "queue") as service:
        with pytest.raises(JobRepositoryError, match="not stored; nothing was admitted"):
            service.submit_njrs(records, SubmissionPolicy())
        assert service.history_store.count() == 0
        assert service.history_store.count_experiment_snapshots() == 0
        with pytest.raises(ExperimentSnapshotIntegrityError):
            service.submit_njrs(
                records,
                SubmissionPolicy(),
                experiment_snapshots={snapshot_digest(exp.execution_snapshot_json): "{}"},
            )
        assert service.history_store.count() == 0
        bodies = experiment_snapshot_bodies(records, exp)
        assert service.submit_njrs(records, SubmissionPolicy(), experiment_snapshots=bodies)
        assert service.history_store.count_experiment_snapshots() == 1


def test_a_tampered_stored_body_fails_hash_verification_loudly(tmp_path: Path) -> None:
    with real_job_service(tmp_path / "queue") as service:
        controller, exp = _run(tmp_path, service)
        repository = service.history_store
        digest = snapshot_digest(exp.execution_snapshot_json)
        tampered = exp.execution_snapshot_json.replace('"study"', '"other"', 1)
        assert tampered != exp.execution_snapshot_json
        with repository.transaction() as connection:
            connection.execute(
                "UPDATE experiment_snapshots SET snapshot_json = ? WHERE sha256 = ?",
                (tampered, digest),
            )
        job = repository.list_job_models()[0]
        with pytest.raises(ExperimentSnapshotIntegrityError, match="altered after admission"):
            resolve_experiment_snapshot(
                job._normalized_record.extra_metadata, repository.get_experiment_snapshot
            )
        evidence = read_job_evidence(repository, exp, controller.learning_state.plan[0])
        assert evidence.error and "altered after admission" in evidence.error
    with pytest.raises(ExperimentSnapshotUnavailable):
        resolve_experiment_snapshot(job._normalized_record.extra_metadata, None)


def _legacy_record(record: Any, snapshot_json: str) -> Any:
    """``record`` as the pre-914 builder wrote it: schema 1 with the body embedded in both metadata blocks."""

    payload = record.to_dict()
    for section in ("workload", "provenance"):
        frozen = payload[section]["metadata"]["frozen_experiment"]
        frozen.pop("snapshot_storage")
        frozen["schema_version"] = 1
        frozen["snapshot"] = thaw_snapshot(snapshot_json)
    payload["job_id"] = f"legacy-{record.job_id}"
    return normalized_job_from_snapshot(
        {"schema_version": "2.6", "job_id": payload["job_id"], "normalized_job": payload}
    )


def test_migration_is_additive_and_idempotent_on_a_copy_of_a_legacy_db(tmp_path: Path) -> None:
    exp = experiment(tmp_path, models=THREE_ARMS)
    controller = controller_for(exp, baseline())
    records = [
        _legacy_record(controller._build_variant_njr(v, exp), exp.execution_snapshot_json)
        for v in controller.learning_state.plan
    ]
    fixture = tmp_path / "legacy" / "jobs.sqlite3"
    from src.queue.job_model import Job

    legacy = JobRepository(fixture)
    legacy.record_job_submissions([Job(r.job_id, _normalized_record=r) for r in records])
    with legacy.transaction() as connection:  # the pre-914 schema had no snapshot table
        connection.execute("DROP TABLE experiment_snapshots")
    legacy.close()
    copy = tmp_path / "copy" / "jobs.sqlite3"
    copy.parent.mkdir()
    shutil.copy2(fixture, copy)
    before = [tuple(row) for row in _stored_rows(copy)]
    for _ in range(2):  # opening twice: the migration runs once and then changes nothing
        repository = JobRepository(copy)
        try:
            assert repository.count_experiment_snapshots() == 0
            for job in repository.list_job_models():
                assert resolve_experiment_snapshot(
                    job._normalized_record.extra_metadata, repository.get_experiment_snapshot
                ) == thaw_snapshot(exp.execution_snapshot_json)
        finally:
            repository.close()
    assert [
        tuple(row) for row in _stored_rows(copy)
    ] == before  # NJR text and fingerprints unchanged
    connection = sqlite3.connect(fixture)
    try:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'experiment_snapshots'"
            ).fetchone()
            is None
        )  # the original fixture was not opened again
    finally:
        connection.close()


def test_legacy_rating_resolves_identically_and_a_new_rating_stores_only_the_hash(
    tmp_path: Path,
) -> None:
    with real_job_service(tmp_path / "queue") as service:
        controller, exp = _run(tmp_path, service)
        repository = service.history_store
        controller._learning_record_writer = LearningRecordWriter(tmp_path / "ratings.jsonl")
        for index, variant in enumerate(controller.learning_state.plan):
            variant.image_refs = [f"image-{index}.png"]
            controller.record_rating(variant.image_refs[0], 5 - index)
        rows = [json.loads(line) for line in (tmp_path / "ratings.jsonl").read_text().splitlines()]
        digest = snapshot_digest(exp.execution_snapshot_json)
        for row in rows:
            frozen = row["metadata"]["frozen_experiment"]
            assert "snapshot" not in frozen
            assert frozen["schema_version"] == 3
            assert frozen["snapshot_storage"] == "job_repository"
            assert frozen["snapshot_sha256"] == digest
            assert exp.execution_snapshot_json not in json.dumps(row)
            assert resolve_experiment_snapshot(
                row["metadata"], repository.get_experiment_snapshot
            ) == thaw_snapshot(exp.execution_snapshot_json)

        legacy = json.loads(json.dumps(rows[0]))
        legacy["metadata"]["frozen_experiment"].pop("snapshot_storage")
        legacy["metadata"]["frozen_experiment"]["schema_version"] = 2
        legacy["metadata"]["frozen_experiment"]["snapshot"] = thaw_snapshot(
            exp.execution_snapshot_json
        )
        assert resolve_experiment_snapshot(legacy["metadata"]) == resolve_experiment_snapshot(
            rows[0]["metadata"], repository.get_experiment_snapshot
        )


def test_a_rating_of_an_experiment_admitted_before_914_keeps_its_embedded_body(
    tmp_path: Path,
) -> None:
    exp = experiment(tmp_path)
    controller = controller_for(exp, baseline())  # no repository holds this experiment's body
    controller._learning_record_writer = LearningRecordWriter(tmp_path / "ratings.jsonl")
    variant = controller.learning_state.plan[0]
    controller._build_variant_njr(variant, exp)
    variant.image_refs = ["image-0.png"]
    controller.record_rating("image-0.png", 4)
    row = json.loads((tmp_path / "ratings.jsonl").read_text().splitlines()[0])
    frozen = row["metadata"]["frozen_experiment"]
    assert frozen["schema_version"] == 2
    assert "snapshot_storage" not in frozen
    assert frozen["snapshot"] == thaw_snapshot(exp.execution_snapshot_json)


def test_rating_log_resolves_by_hash_and_reports_missing_or_altered_bodies(tmp_path: Path) -> None:
    rows_path = tmp_path / "ratings.jsonl"
    body = json.dumps(
        {"experiment_id": "e1", "study_type": "ordinary"}, sort_keys=True, separators=(",", ":")
    )
    digest = snapshot_digest(body)
    row = {
        "metadata": {
            "record_kind": "learning_experiment_rating",
            "experiment_id": "e1",
            "job_id": "j1",
            "image_path": "a.png",
            "user_rating": 4,
            "learning_context": {"experiment_id": "e1", "variant_id": "e1:0"},
            "frozen_experiment": {
                "schema_version": 3,
                "snapshot_sha256": digest,
                "snapshot_storage": "job_repository",
            },
        }
    }
    rows_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    resolved = read_rating_log(rows_path, {digest: body}.get)
    assert not resolved.problems
    assert resolve_experiment_snapshot(resolved.rows[0]["metadata"]) == json.loads(body)
    assert (
        "snapshot" not in json.loads(rows_path.read_text())["metadata"]["frozen_experiment"]
    )  # never rewritten
    missing = read_rating_log(rows_path, None)
    assert any("does not hold" in problem for problem in missing.problems)
    with pytest.raises(ExperimentSnapshotUnavailable):
        resolve_experiment_snapshot(missing.rows[0]["metadata"])
    altered = read_rating_log(rows_path, {digest: body.replace("ordinary", "tampered")}.get)
    assert any("fails hash verification" in problem for problem in altered.problems)


def test_job_repository_report_shows_the_saving_on_a_synthetic_db(tmp_path: Path) -> None:
    exp = experiment(tmp_path, models=THREE_ARMS)
    controller = controller_for(exp, baseline())
    new = [controller._build_variant_njr(v, exp) for v in controller.learning_state.plan]
    legacy = [_legacy_record(record, exp.execution_snapshot_json) for record in new]
    from src.queue.job_model import Job

    paths = {}
    for name, records, bodies in (
        ("legacy", legacy, None),
        ("by_hash", new, experiment_snapshot_bodies(new, exp)),
    ):
        path = tmp_path / name / "jobs.sqlite3"
        repository = JobRepository(path)
        repository.record_job_submissions(
            [Job(r.job_id, _normalized_record=r) for r in records], experiment_snapshots=bodies
        )
        repository.close()
        paths[name] = path
    reports = {}
    for name, path in paths.items():
        connection = open_read_only(path)
        try:
            reports[name] = build_report(connection, path=path)
        finally:
            connection.close()
    before, after = reports["legacy"], reports["by_hash"]
    legacy_bytes = before["column_bytes"]["njr_snapshot"]
    stored_bytes = after["column_bytes"]["njr_snapshot"] + after["experiment_snapshots"]["bytes"]
    print(
        f"njr_snapshot bytes legacy={legacy_bytes} by_hash={stored_bytes} (includes the one stored body)"
    )
    assert before["duplicated_snapshots"]["copies"] == 6  # three jobs x two embedded copies
    assert after["duplicated_snapshots"]["copies"] == 0
    assert after["experiment_snapshots"] == {
        "rows": 1,
        "bytes": len(exp.execution_snapshot_json.encode("utf-8")),
        "jobs_by_reference": 3,
    }
    assert stored_bytes < legacy_bytes
    assert "stored once by hash (LEARN-SNAPSHOT-914): 1 snapshot(s)" in format_report(after)


def test_the_report_marker_copy_matches_the_resolver_rule() -> None:
    # The report is loaded by path without the application, so it copies the marker; the copy must not drift.
    import src.queue.job_hygiene_report as report
    import src.utils.experiment_snapshot_ref as ref

    assert (report.STORAGE_KEY, report.STORAGE_JOB_REPOSITORY) == (
        ref.STORAGE_KEY,
        ref.STORAGE_JOB_REPOSITORY,
    )


def test_a_row_resolved_at_the_load_boundary_still_serializes_and_cannot_be_forged_on_disk() -> (
    None
):
    from src.utils.experiment_snapshot_ref import (
        resolve_experiment_snapshot,
        resolve_rows,
        snapshot_sha256,
    )

    body = json.dumps({"model_identity": "m"}, sort_keys=True, separators=(",", ":"))
    digest = snapshot_sha256(body)
    frozen = {"snapshot_sha256": digest, "snapshot_storage": "job_repository", "schema_version": 3}
    rows, unavailable, altered = resolve_rows(
        [{"metadata": {"frozen_experiment": frozen}}], {digest: body}.get
    )
    assert (unavailable, altered) == (0, 0)
    text = json.dumps(rows[0], sort_keys=True)  # readers hash and serialize resolved rows
    assert resolve_experiment_snapshot(rows[0]["metadata"]) == {"model_identity": "m"}
    # The same row read back from JSON carries no in-memory mark, so a forged embedded body is verified and refused.
    forged = json.loads(text)
    forged["metadata"]["frozen_experiment"]["snapshot"] = {"model_identity": "other"}
    with pytest.raises(ExperimentSnapshotIntegrityError):
        resolve_experiment_snapshot(forged["metadata"])
