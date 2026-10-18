"""Review panel: leaving an image saves its rated draft, unchanged saved ratings make no draft, Save All Drafts."""

from __future__ import annotations

from pathlib import Path
from tkinter import messagebox

import pytest

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState, LearningVariant
from src.gui.views.learning_review_panel import LearningReviewPanel
from src.learning.learning_record import LearningRecordWriter
from tests.gui_v2.tk_test_utils import get_shared_tk_root


@pytest.fixture
def review(tmp_path: Path):
    root = get_shared_tk_root()
    if root is None:
        pytest.skip("No display available for Tkinter tests")
    state = LearningState()
    controller = LearningController(
        state, learning_record_writer=LearningRecordWriter(tmp_path / "learning_records.jsonl")
    )
    controller.update_experiment_design(
        {
            "name": "Panel flow",
            "description": "sweep",
            "prompt_source": "custom",
            "custom_prompt": "portrait",
            "stage": "txt2img",
            "variable_under_test": "CFG Scale",
            "start_value": 6.0,
            "end_value": 7.0,
            "step_value": 1.0,
            "images_per_value": 2,
        }
    )
    experiment = state.current_experiment
    assert experiment is not None
    variant = LearningVariant(
        experiment_id=experiment.experiment_id,
        param_value=6.0,
        status="completed",
        image_refs=["a.png", "b.png", "c.png"],
        job_id="j1",
    )
    state.plan = [variant]
    state.selected_variant = variant
    panel = LearningReviewPanel(root)
    panel.learning_controller = controller
    panel.display_variant_results(variant, experiment)
    yield panel, controller
    panel.destroy()


def _select(panel: LearningReviewPanel, index: int) -> None:
    panel.image_listbox.selection_clear(0, "end")
    panel.image_listbox.selection_set(index)
    panel._on_image_selected(None)  # noqa: SLF001


def test_leaving_an_image_saves_its_rated_draft(review) -> None:
    panel, controller = review
    _select(panel, 0)
    panel.rating_var.set(4)

    _select(panel, 1)

    assert controller.get_rating_for_image("a.png") == 4
    assert controller.get_review_draft("a.png") is None
    assert "saved as a rating" in panel.feedback_label.cget("text")


def test_leaving_an_image_with_only_notes_keeps_a_draft(review) -> None:
    panel, controller = review
    _select(panel, 0)
    panel.notes_text.insert("1.0", "undecided")

    _select(panel, 1)

    assert controller.is_image_rated("a.png") is False
    assert controller.get_review_draft("a.png")["notes"] == "undecided"  # type: ignore[index]


def test_revisiting_a_saved_image_unchanged_creates_no_draft(review) -> None:
    panel, controller = review
    _select(panel, 0)
    panel.rating_var.set(3)
    _select(panel, 1)
    assert controller.is_image_rated("a.png")

    _select(panel, 0)
    _select(panel, 1)

    assert controller.get_review_draft("a.png") is None
    assert (
        len(
            controller._learning_record_writer.records_path.read_text(encoding="utf-8").splitlines()
        )
        == 1
    )  # noqa: SLF001


def test_changing_a_saved_rating_stays_a_draft_until_saved_explicitly(review) -> None:
    panel, controller = review
    _select(panel, 0)
    panel.rating_var.set(3)
    _select(panel, 1)
    _select(panel, 0)
    panel.rating_var.set(5)

    _select(panel, 1)

    assert controller.get_rating_for_image("a.png") == 3
    assert controller.get_review_draft("a.png")["overall_rating"] == 5  # type: ignore[index]


def test_save_all_drafts_saves_them_and_reports(review, monkeypatch) -> None:
    panel, controller = review
    # The image shown in the controls is captured as it appears, so draft the other two.
    controller.save_review_draft(
        "b.png", {"overall_rating": 2, "notes": "", "subscores": {}, "context_flags": {}}
    )
    controller.save_review_draft(
        "c.png", {"overall_rating": 5, "notes": "", "subscores": {}, "context_flags": {}}
    )
    monkeypatch.setattr(messagebox, "askyesno", lambda *args, **kwargs: True)

    panel._save_all_drafts()  # noqa: SLF001

    assert controller.get_rating_for_image("b.png") == 2
    assert controller.get_rating_for_image("c.png") == 5
    assert panel.feedback_label.cget("text") == "2 saved."


def test_declining_the_save_all_prompt_changes_nothing(review, monkeypatch) -> None:
    panel, controller = review
    controller.save_review_draft(
        "b.png", {"overall_rating": 2, "notes": "", "subscores": {}, "context_flags": {}}
    )
    monkeypatch.setattr(messagebox, "askyesno", lambda *args, **kwargs: False)

    panel._save_all_drafts()  # noqa: SLF001

    assert controller.is_image_rated("b.png") is False
    assert controller.get_review_draft("b.png") is not None


def test_the_status_line_says_how_many_more_ratings_are_needed(review) -> None:
    panel, controller = review

    panel._refresh_experiment_workspace(panel.current_experiment)  # noqa: SLF001

    assert (
        "Need 3 more ratings across at least 2 more tested values"
        in panel.workspace_status_var.get()
    )


def test_merely_viewing_images_leaves_no_drafts(review) -> None:
    panel, controller = review

    _select(panel, 0)
    _select(panel, 1)
    _select(panel, 2)

    assert controller.learning_state.review_drafts == {}


def test_changing_a_context_flag_counts_as_a_draft(review) -> None:
    panel, controller = review
    _select(panel, 0)
    panel._context_flag_vars["animals"].set(True)  # noqa: SLF001

    _select(panel, 1)

    assert controller.get_review_draft("a.png")["context_flags"]["animals"] is True  # type: ignore[index]
