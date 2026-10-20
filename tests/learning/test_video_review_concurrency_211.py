"""PR-VID-QUALITY-211 repair: concurrent saves to one canonical evidence file.

Independent ``VideoReviewStore`` / ``LearningRecordWriter`` instances (as separate review windows would
have) must coordinate for the same path: no shared staging file, no lost or duplicated record, and a
well-defined revision order for one review target.  Threads are real; ordering is forced with events,
never with sleeps.
"""

from __future__ import annotations

import builtins
import json
import threading
from pathlib import Path

from src.learning.learning_record import LearningRecord, LearningRecordWriter
from src.learning.video_quality_review import (
    REVIEW_KEY,
    ClipReviewDraft,
    ReviewSaveError,
    ReviewTarget,
    VideoReviewStore,
)

SHA_A, SHA_B = "a" * 64, "b" * 64
EXPERIMENT = "exp-concurrent"


def _target(job: str = "job-a", sha: str = SHA_A) -> ReviewTarget:
    return ReviewTarget(
        experiment_id=EXPERIMENT,
        experiment_name="n",
        job_id=job,
        arm_index=0,
        arm_label="A",
        variable_name="pose_strength",
        tested_value=1.0,
        workflow_id="wf",
        workflow_version="1",
        backend_id="comfy",
        artifact_path="C:/out/a.mp4",
        artifact_sha256=sha,
    )


def _record(n: int) -> LearningRecord:
    return LearningRecord(
        run_id=f"run-{n}",
        timestamp="2026-10-20T00:00:00",
        base_config={},
        variant_configs=[],
        randomizer_mode="t",
        randomizer_plan_size=0,
        primary_model="",
        primary_sampler="",
        primary_scheduler="",
        primary_steps=0,
        primary_cfg_scale=0.0,
        metadata={"n": n, "pad": "x" * 2000},
    )


def _lines(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _run_threads(targets) -> list[BaseException]:
    errors: list[BaseException] = []

    def guard(fn):
        def run():
            try:
                fn()
            except BaseException as exc:  # noqa: BLE001 - collected for the assertion
                errors.append(exc)

        return run

    threads = [threading.Thread(target=guard(t)) for t in targets]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads), "a writer hung"
    return errors


# ------------------------------------------------------------------ the shared staging file


def test_each_append_stages_through_its_own_file_and_leaves_none_behind(tmp_path, monkeypatch):
    path = tmp_path / "learning_records.jsonl"
    staged: list[str] = []
    real_open = builtins.open

    def spy(file, mode="r", *args, **kwargs):
        if "w" in str(mode) and str(file).startswith(str(tmp_path)) and str(file) != str(path):
            staged.append(str(file))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy)
    first, second = LearningRecordWriter(path), LearningRecordWriter(path)
    assert first.append_record(_record(1)) and second.append_record(_record(2))
    monkeypatch.undo()

    assert len(staged) == 2 and len(set(staged)) == 2  # never one fixed pathname for every append
    assert str(path) + ".tmp" not in staged
    assert sorted(p.name for p in tmp_path.iterdir()) == ["learning_records.jsonl"]


def test_a_failed_append_removes_its_staging_file_and_reports_false(tmp_path, monkeypatch):
    path = tmp_path / "learning_records.jsonl"
    writer = LearningRecordWriter(path)

    def boom(fd):
        raise OSError("boom")

    monkeypatch.setattr("src.learning.learning_record.os.fsync", boom)
    assert writer.append_record(_record(1)) is False
    monkeypatch.undo()

    assert [p.name for p in tmp_path.iterdir() if p.name != "learning_records.jsonl"] == []
    assert not path.exists() or path.read_text() == ""


def test_many_independent_writers_append_without_loss_corruption_or_duplication(tmp_path):
    path = tmp_path / "learning_records.jsonl"
    writers = [LearningRecordWriter(path) for _ in range(4)]
    barrier = threading.Barrier(8)
    results: list[bool] = []
    lock = threading.Lock()

    def worker(index: int):
        def run():
            barrier.wait()
            for step in range(25):
                ok = writers[index % 4].append_record(_record(index * 1000 + step))
                with lock:
                    results.append(ok)

        return run

    assert _run_threads([worker(i) for i in range(8)]) == []

    assert results.count(True) == 200
    rows = _lines(path)  # every line parses: nothing was interleaved or truncated
    assert len(rows) == 200
    expected = {f"run-{i * 1000 + s}" for i in range(8) for s in range(25)}
    assert {row["run_id"] for row in rows} == expected
    assert all(len(row["metadata"]["pad"]) == 2000 for row in rows)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["learning_records.jsonl"]


def test_the_image_writer_contract_is_unchanged(tmp_path):
    path = tmp_path / "learning_records.jsonl"
    writer = LearningRecordWriter(path)

    assert writer.append_record(_record(1)) is True
    writer.write(_record(2))  # the backward-compatible alias still appends

    assert [row["run_id"] for row in _lines(path)] == ["run-1", "run-2"]
    assert (
        LearningRecordWriter(tmp_path).records_path == path
    )  # a directory still resolves to the file


def test_the_lock_is_shared_by_path_not_by_instance(tmp_path):
    from src.learning.learning_record import evidence_file_lock

    path = tmp_path / "learning_records.jsonl"
    assert evidence_file_lock(path) is evidence_file_lock(tmp_path / "." / "learning_records.jsonl")
    assert evidence_file_lock(path) is not evidence_file_lock(tmp_path / "other.jsonl")


# ------------------------------------------------------------------ read-modify-append ordering


def test_concurrent_saves_of_one_review_target_get_distinct_ordered_revisions(tmp_path):
    path = tmp_path / "learning_records.jsonl"
    stores = [VideoReviewStore(path) for _ in range(6)]  # six independently instantiated windows
    barrier = threading.Barrier(6)

    def saver(index: int):
        def run():
            barrier.wait()
            draft = ClipReviewDraft(1 + index % 5, "achieved", {}, f"edit {index}")
            stores[index].save_clip(_target(), draft)

        return run

    assert _run_threads([saver(i) for i in range(6)]) == []

    rows = _lines(path)
    revisions = [row["metadata"][REVIEW_KEY]["revision"] for row in rows]
    assert revisions == [
        1,
        2,
        3,
        4,
        5,
        6,
    ]  # file order is revision order: serialized, no duplicates
    latest = VideoReviewStore(path).load(EXPERIMENT).clip_for("job-a", SHA_A)
    assert latest.revision == 6 and latest.draft.notes == rows[-1]["metadata"][REVIEW_KEY]["notes"]


def test_a_second_save_waits_for_the_first_instead_of_reusing_its_revision(tmp_path, monkeypatch):
    """Deterministic: the first save is parked inside its append; the second must not read until it ends."""

    path = tmp_path / "learning_records.jsonl"
    first_store, second_store = VideoReviewStore(path), VideoReviewStore(path)
    in_append, release, second_read = threading.Event(), threading.Event(), threading.Event()
    real_append = LearningRecordWriter.append_record
    real_load = VideoReviewStore.load

    def gated_append(self, record):
        in_append.set()
        assert release.wait(30)
        return real_append(self, record)

    def watched_load(self, experiment_id):
        if self is second_store:
            second_read.set()
        return real_load(self, experiment_id)

    monkeypatch.setattr(LearningRecordWriter, "append_record", gated_append)
    monkeypatch.setattr(VideoReviewStore, "load", watched_load)
    outcomes: dict[str, object] = {}

    def save(key, store, rating):
        def run():
            outcomes[key] = store.save_clip(_target(), ClipReviewDraft(rating, "achieved"))

        return run

    t1 = threading.Thread(target=save("a", first_store, 2))
    t1.start()
    assert in_append.wait(30)
    t2 = threading.Thread(target=save("b", second_store, 4))
    t2.start()
    blocked = not second_read.wait(0.5)
    release.set()
    t1.join(30)
    t2.join(30)

    assert blocked, "the second save read the file while the first was still writing"
    assert (outcomes["a"].revision, outcomes["b"].revision) == (1, 2)
    assert [row["metadata"][REVIEW_KEY]["overall_rating"] for row in _lines(path)] == [2, 4]


def test_identical_concurrent_saves_append_once(tmp_path):
    path = tmp_path / "learning_records.jsonl"
    stores = [VideoReviewStore(path) for _ in range(5)]
    barrier = threading.Barrier(5)
    statuses: list[str] = []
    lock = threading.Lock()

    def saver(store):
        def run():
            barrier.wait()
            outcome = store.save_clip(_target(), ClipReviewDraft(4, "achieved", {}, "same"))
            with lock:
                statuses.append(outcome.status)

        return run

    assert _run_threads([saver(s) for s in stores]) == []

    assert sorted(statuses) == ["saved", "unchanged", "unchanged", "unchanged", "unchanged"]
    assert len(_lines(path)) == 1


def test_two_clips_and_a_preference_saved_together_keep_three_distinct_valid_records(tmp_path):
    path = tmp_path / "learning_records.jsonl"
    stores = [VideoReviewStore(path) for _ in range(3)]
    barrier = threading.Barrier(3)

    def clip(store, job, sha, rating):
        def run():
            barrier.wait()
            store.save_clip(_target(job, sha), ClipReviewDraft(rating, "achieved", {}, job))

        return run

    def preference():
        barrier.wait()
        stores[2].save_preference(
            experiment_id=EXPERIMENT,
            preferred_job_id="job-b",
            preferred_arm_label="B",
            preferred_artifact_sha256=SHA_B,
            reason="best",
        )

    errors = _run_threads(
        [clip(stores[0], "job-a", SHA_A, 2), clip(stores[1], "job-b", SHA_B, 5), preference]
    )

    assert errors == []
    rows = [row["metadata"][REVIEW_KEY] for row in _lines(path)]
    assert len(rows) == 3 and len({row["review_id"] for row in rows}) == 3
    stored = VideoReviewStore(path).load(EXPERIMENT)
    assert stored.clip_for("job-a", SHA_A).draft.overall_rating == 2
    assert stored.clip_for("job-b", SHA_B).draft.overall_rating == 5
    assert stored.preference.preferred_job_id == "job-b" and stored.preference.reason == "best"


def test_a_failed_write_under_concurrency_never_reports_success_and_does_not_block_others(
    tmp_path, monkeypatch
):
    path = tmp_path / "learning_records.jsonl"
    stores = [VideoReviewStore(path) for _ in range(3)]
    real_append = LearningRecordWriter.append_record

    def flaky(self, record):
        if record.metadata[REVIEW_KEY].get("job_id") == "job-bad":
            return False
        return real_append(self, record)

    monkeypatch.setattr(LearningRecordWriter, "append_record", flaky)
    barrier = threading.Barrier(3)
    results: dict[str, object] = {}

    def save(store, job, sha):
        def run():
            barrier.wait()
            try:
                results[job] = store.save_clip(_target(job, sha), ClipReviewDraft(3, "achieved"))
            except ReviewSaveError as exc:
                results[job] = exc

        return run

    errors = _run_threads(
        [
            save(stores[0], "job-a", SHA_A),
            save(stores[1], "job-bad", SHA_B),
            save(stores[2], "job-c", "c" * 64),
        ]
    )

    assert errors == []
    assert isinstance(results["job-bad"], ReviewSaveError)
    assert results["job-a"].status == "saved" and results["job-c"].status == "saved"
    assert {row["metadata"][REVIEW_KEY]["job_id"] for row in _lines(path)} == {"job-a", "job-c"}
