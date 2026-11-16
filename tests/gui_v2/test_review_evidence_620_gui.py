"""PR-REVIEW-EVIDENCE-620: Review loads the saved rating of the image shown and exports it only on request.

Real Tk Review tab, real ``LearningController`` over a temporary records file; synthetic images only.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.learning.learning_record import LearningRecordWriter
from src.utils.image_metadata import build_contract_kv, write_image_metadata


def _image(path: Path, color, *, job_id: str = "job-620") -> Path:
    Image.new("RGB", (24, 24), color).save(path)
    payload = {
        "generation": {"model": "sdxlBase.safetensors"},
        "stage_manifest": {"stage": "txt2img", "final_prompt": "a fox", "config": {"steps": 20}},
    }
    assert write_image_metadata(
        path, build_contract_kv(payload, job_id=job_id, run_id="synthetic", stage="txt2img")
    )
    return path


@pytest.fixture
def review(tk_root, tmp_path, monkeypatch):
    frame = ReviewTabFrame(tk_root)
    writer = LearningRecordWriter(tmp_path / "records.jsonl")
    controller = LearningController(LearningState(), learning_record_writer=writer)
    monkeypatch.setattr(controller, "refresh_recommendations", Mock())
    monkeypatch.setattr(frame, "_resolve_learning_controller", lambda: controller)
    monkeypatch.setattr("src.gui.views.review_tab_frame_v2.messagebox.showwarning", Mock())
    first = _image(tmp_path / "first.png", (10, 20, 30))
    second = _image(tmp_path / "second.png", (200, 20, 30))
    yield frame, controller, first, second
    frame.destroy()


def _rate(frame, rating: int, quality: str, notes: str) -> None:
    frame.rating_var.set(rating)
    frame.anatomy_rating_var.set(rating)
    frame.composition_rating_var.set(rating)
    frame.prompt_adherence_rating_var.set(rating)
    frame.quality_var.set(quality)
    frame.feedback_notes.delete("1.0", "end")
    frame.feedback_notes.insert("1.0", notes)
    frame._save_feedback()


def _controls(frame):
    return (
        frame.rating_var.get(),
        frame.anatomy_rating_var.get(),
        frame.quality_var.get(),
        frame.feedback_notes.get("1.0", "end").strip(),
    )


def test_saved_rating_reloads_and_an_unrated_image_shows_the_unrated_state(review):
    frame, _controller, first, second = review
    before = first.read_bytes()

    frame._show_image(first)
    assert frame._selected_image_sha256 == hashlib.sha256(before).hexdigest()
    _rate(frame, 5, "excellent", "keeper")
    assert first.read_bytes() == before
    assert "The image file was not changed" in frame._feedback_status_var.get()

    frame._show_image(second)  # unrated: never the previous image's values
    assert _controls(frame) == (3, 3, "okay", "")
    assert "none" in frame._prior_review_summary_var.get().lower()

    frame._show_image(first)  # reselecting loads the saved rating
    assert _controls(frame) == (5, 5, "excellent", "keeper")
    assert "Rating: 5" in frame._prior_review_summary_var.get()


def test_edits_made_before_the_context_arrives_are_not_overwritten(review):
    frame, _controller, first, _second = review
    frame._show_image(first)
    frame.rating_var.set(2)  # operator touched the control before the saved rating was applied
    frame._load_saved_rating({"identity_status": "digest", "user_rating_raw": 5, "subscores": {}})
    assert frame.rating_var.get() == 2


def test_a_changed_file_is_reported_changed_and_its_controls_stay_unrated(review):
    frame, _controller, first, _second = review
    frame._show_image(first)
    _rate(frame, 5, "excellent", "keeper")
    _image(first, (1, 2, 3))  # different bytes under the same path

    frame._show_image(first)

    assert _controls(frame) == (3, 3, "okay", "")
    assert "changed since it was reviewed" in frame._prior_review_summary_var.get()


def test_write_rating_into_file_confirms_then_embeds_png_only_on_request(review):
    frame, _controller, first, _second = review
    frame._show_image(first)
    _rate(frame, 4, "good", "")
    before = first.read_bytes()
    asked: list[tuple[str, str]] = []
    frame._confirm_replace_hook = lambda title, message: asked.append((title, message)) or False

    frame._write_rating_into_file()
    assert first.read_bytes() == before and "identity" in asked[0][1]  # declined: nothing written

    frame._confirm_replace_hook = lambda *_: True
    frame._write_rating_into_file()
    assert first.read_bytes() != before
    assert "Rating written" in frame._feedback_status_var.get()


def test_write_rating_into_file_never_re_encodes_jpeg(review, tmp_path):
    frame, controller, _first, _second = review
    jpeg = tmp_path / "photo.jpg"
    Image.new("RGB", (24, 24), (9, 9, 9)).save(jpeg, format="JPEG")
    controller.save_review_feedback({"image_path": str(jpeg), "rating": 3, "base_prompt": "p"})
    frame._selected_image_path = jpeg
    before = jpeg.read_bytes()
    frame._confirm_replace_hook = lambda title, message: "not re-encoded" in message

    frame._write_rating_into_file()

    assert jpeg.read_bytes() == before
    assert Path(f"{jpeg}.review.json").exists()
