from __future__ import annotations

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState
from src.learning.learning_record import LearningRecordWriter


def _build_controller(tmp_path):
    writer = LearningRecordWriter(tmp_path / "learning_records.jsonl")
    return LearningController(
        learning_state=LearningState(),
        pipeline_controller=object(),
        learning_record_writer=writer,
    )


def test_save_review_feedback_persists_record(tmp_path) -> None:
    controller = _build_controller(tmp_path)

    record = controller.save_review_feedback(
        {
            "image_path": "C:/images/test.png",
            "rating": 4,
            "quality_label": "good",
            "notes": "hands improved",
            "base_prompt": "portrait",
            "base_negative_prompt": "blurry",
            "after_prompt": "portrait, bending forward",
            "after_negative_prompt": "blurry, extra hand",
            "prompt_delta": "bending forward",
            "negative_prompt_delta": "extra hand",
            "prompt_mode": "append",
            "negative_prompt_mode": "append",
            "stages": ["adetailer"],
            "model": "modelA.safetensors",
        }
    )

    assert record.metadata["source"] == "review_tab"
    assert record.metadata["image_path"] == "C:/images/test.png"
    assert record.metadata["user_rating"] == 4
    assert record.metadata["prompt_after"] == "portrait, bending forward"


def test_list_recent_review_feedback_returns_newest_first(tmp_path) -> None:
    controller = _build_controller(tmp_path)
    controller.save_review_feedback(
        {
            "image_path": "img_a.png",
            "rating": 2,
            "quality_label": "poor",
            "base_prompt": "a",
            "after_prompt": "a",
        }
    )
    controller.save_review_feedback(
        {
            "image_path": "img_a.png",
            "rating": 5,
            "quality_label": "excellent",
            "base_prompt": "a",
            "after_prompt": "a, better",
        }
    )

    rows = controller.list_recent_review_feedback(limit=5, image_path="img_a.png")
    assert len(rows) == 2
    assert rows[0]["rating"] == 5
    assert rows[1]["rating"] == 2

