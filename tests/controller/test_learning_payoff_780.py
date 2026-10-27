"""Durable-write outcomes, reproduced before changing the Review feedback path."""

import json
from unittest.mock import Mock

import pytest

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState
from src.learning.learning_record import LearningRecordWriter


@pytest.mark.parametrize("failure", [False, OSError("append failed")])
def test_review_append_failure_cannot_stamp_or_refresh(tmp_path, monkeypatch, failure):
    writer = LearningRecordWriter(tmp_path / "records.jsonl")
    controller = LearningController(LearningState(), learning_record_writer=writer)
    append = Mock(
        return_value=failure if failure is False else None,
        side_effect=failure if isinstance(failure, Exception) else None,
    )
    monkeypatch.setattr(writer, "append_record", append)
    stamp = Mock()
    monkeypatch.setattr(controller._review_metadata_service, "stamp_review_metadata", stamp)
    refresh = Mock()
    monkeypatch.setattr(controller, "refresh_recommendations", refresh)
    with pytest.raises(OSError):
        controller.save_review_feedback({"image_path": str(tmp_path / "image.png"), "rating": 4})
    stamp.assert_not_called()
    refresh.assert_not_called()
    assert not writer.records_path.exists()


def test_writer_fsync_failure_and_operator_repetition_preserve_ratings(tmp_path, monkeypatch):
    writer = LearningRecordWriter(tmp_path / "records.jsonl")
    controller = LearningController(LearningState(), learning_record_writer=writer)
    monkeypatch.setattr(controller, "refresh_recommendations", Mock())
    payload = {
        "image_path": str(tmp_path / "image.png"),
        "rating": 2,
        "subscores": {"anatomy": 5, "composition": 4, "prompt_adherence": 3},
    }
    with monkeypatch.context() as patch:
        patch.setattr(
            "src.learning.learning_record.os.fsync", Mock(side_effect=OSError("disk failed"))
        )
        with pytest.raises(OSError, match="not confirmed"):
            controller.save_review_feedback(payload)
    assert not writer.records_path.exists()
    first = controller.save_review_feedback(payload)
    first_line = writer.records_path.read_bytes()
    second = controller.save_review_feedback({**payload, "rating": 5})
    assert second.run_id != first.run_id
    assert writer.records_path.read_bytes().startswith(first_line)
    rows = [json.loads(line) for line in writer.records_path.read_text().splitlines()]
    assert [row["metadata"]["user_rating_raw"] for row in rows] == [2, 5]
    assert rows[0]["metadata"]["user_rating"] == 3
    assert (
        LearningRecordWriter(writer.records_path).records_path.read_bytes()
        == writer.records_path.read_bytes()
    )
