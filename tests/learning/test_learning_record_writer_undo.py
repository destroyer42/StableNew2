"""ARCH-954: the learning-record store has one writer, and undo goes through it.

``LearningRecordWriter.remove_latest_review_feedback`` removes the latest matching review-tab record under the
store's evidence lock and replaces the file atomically, so a concurrent append is never lost and a failed
replace never leaves a truncated file.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from src.learning import learning_record
from src.learning.learning_record import LearningRecord, LearningRecordWriter, evidence_file_lock


def _record(run_id: str, *, source: str = "review_tab", image: str | None = None) -> LearningRecord:
    metadata: dict[str, object] = {"source": source}
    if image is not None:
        metadata["image_path"] = image
    return LearningRecord(
        run_id=run_id,
        timestamp="2026-11-10T00:00:00",
        base_config={},
        variant_configs=[],
        randomizer_mode="",
        randomizer_plan_size=0,
        primary_model="m",
        primary_sampler="Euler",
        primary_scheduler="Normal",
        primary_steps=20,
        primary_cfg_scale=7.0,
        metadata=metadata,
    )


def _run_ids(writer: LearningRecordWriter) -> list[str]:
    text = writer.records_path.read_text(encoding="utf-8")
    return [
        json.loads(line)["run_id"] for line in text.splitlines() if line.strip().startswith("{")
    ]


def test_removes_only_the_latest_matching_record(tmp_path: Path) -> None:
    writer = LearningRecordWriter(tmp_path)
    for run_id, image in (("r1", "a.png"), ("r2", "b.png"), ("r1", "a.png"), ("r3", "a.png")):
        assert writer.append_record(_record(run_id, image=image))

    assert writer.remove_latest_review_feedback(run_id="r1", image_path="a.png") is True

    # the later of the two r1/a.png records went; the earlier one and every other record stayed, in order
    assert _run_ids(writer) == ["r1", "r2", "r3"]


def test_without_filters_removes_the_latest_review_record_and_never_a_non_review_record(
    tmp_path: Path,
) -> None:
    writer = LearningRecordWriter(tmp_path)
    writer.append_record(_record("review-1"))
    writer.append_record(_record("review-2"))
    writer.append_record(_record("pipeline-run", source="pipeline"))

    assert writer.remove_latest_review_feedback() is True

    assert _run_ids(writer) == ["review-1", "pipeline-run"]


def test_no_match_returns_false_and_leaves_file_bytes_identical(tmp_path: Path) -> None:
    writer = LearningRecordWriter(tmp_path)
    writer.append_record(_record("r1", image="a.png"))
    writer.append_record(_record("p1", source="pipeline"))
    before = writer.records_path.read_bytes()

    assert writer.remove_latest_review_feedback(run_id="missing") is False
    assert writer.remove_latest_review_feedback(image_path="other.png") is False

    assert writer.records_path.read_bytes() == before


def test_empty_or_missing_file_returns_false(tmp_path: Path) -> None:
    writer = LearningRecordWriter(tmp_path)
    assert not writer.records_path.exists()
    assert writer.remove_latest_review_feedback() is False

    writer.records_path.write_text("", encoding="utf-8")
    assert writer.remove_latest_review_feedback() is False
    assert writer.records_path.read_text(encoding="utf-8") == ""


def test_malformed_and_blank_lines_do_not_crash_and_unselected_malformed_lines_are_kept(
    tmp_path: Path,
) -> None:
    writer = LearningRecordWriter(tmp_path)
    writer.append_record(_record("r1"))
    with open(writer.records_path, "a", encoding="utf-8") as handle:
        handle.write("this is not json\n\n")
    writer.append_record(_record("r2"))
    with open(writer.records_path, "a", encoding="utf-8") as handle:
        handle.write("{broken\n")

    assert writer.remove_latest_review_feedback() is True

    lines = [
        line
        for line in writer.records_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert "this is not json" in lines
    assert "{broken" in lines
    assert [json.loads(line)["run_id"] for line in lines if line.startswith('{"')] == ["r1"]


def test_pathologically_nested_line_is_unparseable_and_kept_not_an_error(tmp_path: Path) -> None:
    """``json.loads`` raises ``RecursionError`` (not ``ValueError``) on absurd nesting; it must be skipped, not raised."""

    writer = LearningRecordWriter(tmp_path)
    writer.append_record(_record("r1"))
    deep_line = "[" * 100_000 + "]" * 100_000
    with open(writer.records_path, "a", encoding="utf-8") as handle:
        handle.write(deep_line + "\n")

    # the valid review record before the unparseable line is still found and removed; the deep line is kept
    assert writer.remove_latest_review_feedback() is True
    assert writer.records_path.read_text(encoding="utf-8").splitlines() == [deep_line]

    # with only the unparseable line left there is no match: False, file unchanged
    before = writer.records_path.read_bytes()
    assert writer.remove_latest_review_feedback() is False
    assert writer.records_path.read_bytes() == before


def test_removing_the_last_record_leaves_an_empty_file(tmp_path: Path) -> None:
    writer = LearningRecordWriter(tmp_path)
    writer.append_record(_record("only"))

    assert writer.remove_latest_review_feedback(run_id="only") is True

    assert writer.records_path.read_text(encoding="utf-8") == ""


def test_undo_waits_for_the_evidence_lock(tmp_path: Path) -> None:
    writer = LearningRecordWriter(tmp_path)
    writer.append_record(_record("r1"))
    lock = evidence_file_lock(writer.records_path)
    holder_has_lock = threading.Event()
    release_lock = threading.Event()
    undo_finished = threading.Event()
    outcome: list[bool] = []

    def hold() -> None:
        with lock:
            holder_has_lock.set()
            release_lock.wait(timeout=10)

    def undo() -> None:
        outcome.append(writer.remove_latest_review_feedback())
        undo_finished.set()

    holder = threading.Thread(target=hold)
    holder.start()
    assert holder_has_lock.wait(timeout=5)
    worker = threading.Thread(target=undo)
    worker.start()
    try:
        assert not undo_finished.wait(timeout=0.5), (
            "undo ran while another writer held the evidence lock"
        )
    finally:
        release_lock.set()
        holder.join(timeout=5)
        worker.join(timeout=5)

    assert outcome == [True]
    assert _run_ids(writer) == []


def test_append_during_undo_is_not_lost(tmp_path: Path) -> None:
    writer = LearningRecordWriter(tmp_path)
    review_count = 25
    append_count = 50
    for index in range(review_count):
        writer.append_record(_record(f"review-{index}"))

    start = threading.Barrier(2)
    appended: list[bool] = []
    removed: list[bool] = []

    def append_loop() -> None:
        start.wait(timeout=10)
        for index in range(append_count):
            appended.append(writer.append_record(_record(f"pipeline-{index}", source="pipeline")))

    def undo_loop() -> None:
        start.wait(timeout=10)
        for _ in range(review_count):
            removed.append(writer.remove_latest_review_feedback())

    threads = [threading.Thread(target=append_loop), threading.Thread(target=undo_loop)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert all(appended) and len(appended) == append_count
    assert all(removed) and len(removed) == review_count
    run_ids = _run_ids(writer)
    assert sorted(run_ids) == sorted(f"pipeline-{index}" for index in range(append_count))


def test_failed_replace_leaves_the_original_file_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = LearningRecordWriter(tmp_path)
    writer.append_record(_record("r1"))
    writer.append_record(_record("r2"))
    before = writer.records_path.read_bytes()

    def failing_replace(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(learning_record, "atomic_write_text", failing_replace)

    assert writer.remove_latest_review_feedback() is False

    assert writer.records_path.read_bytes() == before
    assert [path.name for path in tmp_path.iterdir()] == [writer.records_path.name]
