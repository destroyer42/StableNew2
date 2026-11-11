"""ARCH-954: ``LearningController.undo_review_feedback`` delegates to the record writer.

The controller no longer touches the records file itself; it asks the writer to remove the record and refreshes
recommendations only when something was actually removed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState
from src.learning.learning_record import LearningRecordWriter


class _StubPipelineController:
    def set_learning_enabled(self, _enabled: bool) -> None:
        return


class _RecordingWriter(LearningRecordWriter):
    def __init__(self, path: Path, result: bool) -> None:
        super().__init__(path)
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def remove_latest_review_feedback(
        self, *, run_id: str | None = None, image_path: str | None = None
    ) -> bool:
        self.calls.append({"run_id": run_id, "image_path": image_path})
        return self.result


def _controller(writer: LearningRecordWriter | None) -> tuple[LearningController, list[int]]:
    controller = LearningController(
        learning_state=LearningState(),
        pipeline_controller=_StubPipelineController(),
        learning_record_writer=writer,
    )
    refreshes: list[int] = []
    controller.refresh_recommendations = lambda *a, **k: refreshes.append(1)  # type: ignore[method-assign]
    return controller, refreshes


def test_undo_delegates_to_the_writer_and_refreshes_on_success(tmp_path: Path) -> None:
    writer = _RecordingWriter(tmp_path, result=True)
    controller, refreshes = _controller(writer)

    assert controller.undo_review_feedback(run_id="r1", image_path="a.png") is True

    assert writer.calls == [{"run_id": "r1", "image_path": "a.png"}]
    assert refreshes == [1]


def test_undo_does_not_refresh_when_nothing_was_removed(tmp_path: Path) -> None:
    writer = _RecordingWriter(tmp_path, result=False)
    controller, refreshes = _controller(writer)

    assert controller.undo_review_feedback(run_id="r1") is False

    assert writer.calls == [{"run_id": "r1", "image_path": None}]
    assert refreshes == []


def test_undo_without_a_writer_returns_false() -> None:
    controller, refreshes = _controller(None)

    assert controller.undo_review_feedback() is False
    assert refreshes == []
