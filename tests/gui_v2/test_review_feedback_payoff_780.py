"""Real Tk status binding over the existing Review save callback; no backend traffic."""

import json
from unittest.mock import Mock

import pytest

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.learning.learning_record import LearningRecordWriter
from tests.gui_v2.tk_test_utils import get_shared_tk_root


@pytest.fixture
def review(tmp_path, monkeypatch):
    root = get_shared_tk_root()
    if root is None:
        pytest.skip("No display available for Tkinter tests")
    frame = ReviewTabFrame(root)
    writer = LearningRecordWriter(tmp_path / "records.jsonl")
    controller = LearningController(LearningState(), learning_record_writer=writer)
    monkeypatch.setattr(controller, "refresh_recommendations", Mock())
    monkeypatch.setattr(frame, "_resolve_learning_controller", lambda: controller)
    monkeypatch.setattr(frame, "_refresh_prior_review_summary", Mock())
    monkeypatch.setattr(
        frame, "_build_feedback_payload", lambda path: {"image_path": str(path), "rating": 4}
    )
    paths = [tmp_path / f"image-{i}.png" for i in range(3)]
    frame._image_index_by_row = paths
    frame._selected_image_path = paths[0]
    for path in paths:
        frame.images_list.insert("end", path.name)
    yield frame, controller, writer, paths
    frame.destroy()


@pytest.mark.parametrize("outcome", [False, OSError("disk failed")])
def test_single_failed_write_has_inline_refusal_and_no_undo(review, monkeypatch, outcome):
    frame, controller, writer, _ = review
    monkeypatch.setattr(
        writer,
        "append_record",
        Mock(
            return_value=outcome if outcome is False else None,
            side_effect=outcome if isinstance(outcome, Exception) else None,
        ),
    )
    frame._save_feedback()
    assert "Save not confirmed" in frame._feedback_status_var.get()
    assert frame._feedback_undo_stack == []
    assert not writer.records_path.exists()
    controller.refresh_recommendations.assert_not_called()


def test_partial_batch_tokens_and_undo_match_persisted_identities(review, monkeypatch):
    frame, controller, writer, paths = review
    append = writer.append_record

    def mixed(record):
        return False if record.metadata["image_path"] == str(paths[1]) else append(record)

    monkeypatch.setattr(writer, "append_record", mixed)
    frame.images_list.selection_set(0, 2)
    frame._save_feedback_batch()
    rows = [json.loads(line) for line in writer.records_path.read_text().splitlines()]
    assert len(rows) == 2
    tokens = frame._feedback_undo_stack[-1]
    assert {t["run_id"] for t in tokens} == {row["run_id"] for row in rows}
    assert {t["image_path"] for t in tokens} == {str(paths[0]), str(paths[2])}
    status = frame._feedback_status_var.get()
    assert "Saved 2 feedback record(s); not confirmed 1" in status
    assert str(paths[1]) in status
    assert controller.refresh_recommendations.call_count == 2
    # Undo uses only the two identities confirmed by the append owner.
    monkeypatch.setattr("src.gui.views.review_tab_frame_v2.messagebox.showinfo", Mock())
    frame._undo_last_feedback_save()
    assert not writer.records_path.read_text().strip()
    assert frame._feedback_undo_stack == []


def test_annotation_failure_is_saved_evidence_and_keeps_undo(review, monkeypatch):
    frame, controller, writer, _ = review
    monkeypatch.setattr(
        controller._review_metadata_service,
        "stamp_review_metadata",
        Mock(side_effect=OSError("image read-only")),
    )
    frame._save_feedback()
    assert len(writer.records_path.read_text().splitlines()) == 1
    assert len(frame._feedback_undo_stack[-1]) == 1
    assert "Learning record is saved" in frame._feedback_status_var.get()
    assert "annotation failed" in frame._feedback_status_var.get()


@pytest.mark.parametrize("batch", [False, True])
def test_post_append_refresh_failure_preserves_saved_outcome_and_undo(review, monkeypatch, batch):
    frame, controller, writer, _ = review
    monkeypatch.setattr(
        controller, "refresh_recommendations", Mock(side_effect=ValueError("refresh failed"))
    )
    monkeypatch.setattr(
        frame, "_refresh_prior_review_summary", Mock(side_effect=ValueError("summary failed"))
    )
    if batch:
        frame.images_list.selection_set(0, 2)
        frame._save_feedback_batch()
    else:
        frame._save_feedback()
    rows = [json.loads(line) for line in writer.records_path.read_text().splitlines()]
    assert len(rows) == (3 if batch else 1)
    assert {token["run_id"] for token in frame._feedback_undo_stack[-1]} == {
        row["run_id"] for row in rows
    }
    assert "Evidence is saved; refresh" in frame._feedback_status_var.get()
    assert "Save not confirmed:" not in frame._feedback_status_var.get()
    if batch:
        assert "not confirmed 0" in frame._feedback_status_var.get()


def test_batch_payload_failure_preserves_prior_success_tokens(review, monkeypatch):
    frame, _, writer, paths = review

    def build(path):
        if path == paths[1]:
            raise ValueError("metadata unavailable")
        return {"image_path": str(path), "rating": 4}

    monkeypatch.setattr(frame, "_build_feedback_payload", build)
    frame.images_list.selection_set(0, 2)
    frame._save_feedback_batch()
    assert len(writer.records_path.read_text().splitlines()) == 2
    assert len(frame._feedback_undo_stack[-1]) == 2
    assert "Saved 2 feedback record(s); not confirmed 1" in frame._feedback_status_var.get()
