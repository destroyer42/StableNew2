from __future__ import annotations

import json
from pathlib import Path

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState
from src.learning.learning_record import LearningRecordWriter


class _StubPipelineController:
    def set_learning_enabled(self, _enabled: bool) -> None:
        return


def test_review_feedback_advanced_rating_and_undo(tmp_path: Path) -> None:
    records_path = tmp_path / "learning_records.jsonl"
    writer = LearningRecordWriter(records_path)
    controller = LearningController(
        learning_state=LearningState(),
        pipeline_controller=_StubPipelineController(),
        learning_record_writer=writer,
    )

    record = controller.save_review_feedback(
        {
            "image_path": "output/a.png",
            "rating": 2,
            "quality_label": "poor",
            "notes": "hands are wrong",
            "base_prompt": "portrait",
            "base_negative_prompt": "bad hands",
            "after_prompt": "portrait, detailed hands",
            "after_negative_prompt": "bad hands, malformed fingers",
            "subscores": {
                "anatomy": 5,
                "composition": 4,
                "prompt_adherence": 3,
            },
        }
    )

    lines = records_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    metadata = payload["metadata"]
    assert metadata["advanced_rating_enabled"] is True
    assert metadata["subscores"]["anatomy"] == 5
    assert metadata["user_rating_raw"] == 2
    assert metadata["user_rating"] == 3

    undone = controller.undo_review_feedback(run_id=record.run_id, image_path="output/a.png")
    assert undone is True
    assert records_path.read_text(encoding="utf-8").strip() == ""
