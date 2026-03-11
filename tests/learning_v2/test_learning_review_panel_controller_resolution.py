from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import ANY
from unittest.mock import MagicMock


def test_get_learning_controller_prefers_panel_reference() -> None:
    from src.gui.views.learning_review_panel import LearningReviewPanel

    controller = object()
    panel = LearningReviewPanel.__new__(LearningReviewPanel)
    panel.learning_controller = controller
    panel.master = SimpleNamespace()

    assert panel._get_learning_controller() is controller


def test_submit_rating_uses_panel_learning_controller() -> None:
    from src.gui.views.learning_review_panel import LearningReviewPanel

    controller = MagicMock()
    panel = LearningReviewPanel.__new__(LearningReviewPanel)
    panel.learning_controller = controller
    panel.master = SimpleNamespace()
    panel.current_variant = object()
    panel.current_experiment = None
    panel.rating_var = SimpleNamespace(get=lambda: 4, set=lambda value: None)
    panel.notes_text = SimpleNamespace(get=lambda *_: "good", delete=lambda *_: None)
    panel.image_listbox = SimpleNamespace(curselection=lambda: (0,))
    panel.feedback_label = MagicMock()
    panel._image_full_paths = ["out/test.png"]
    panel._get_rating_for_image = lambda _path: None
    panel.display_variant_results = MagicMock()

    panel._submit_rating()

    controller.record_rating.assert_called_once_with("out/test.png", 4, "good", ANY)
    panel.feedback_label.config.assert_called()
