"""PR-REFINE-160: the Review tab offers a before/after judgment only for an ADetailer output with a verified source."""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from src.gui.app_state_v2 import AppStateV2
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.review.adetailer_outcome import AdetailerPair
from src.utils.image_metadata import ReadPayloadResult

PROMPT = "nude portrait reference"
PAYLOAD = {"stage_manifest": {"final_prompt": PROMPT, "config": {"negative_prompt": "bad anatomy"}}}


def image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), (10, 20, 30)).save(path)
    return path


@pytest.fixture
def tab(tk_root: tk.Tk):
    widget = ReviewTabFrame(tk_root, app_state=AppStateV2())
    widget.preview.set_image_from_path = lambda _path: None  # type: ignore[method-assign]
    yield widget
    widget.destroy()


def show(tab, path: Path, pair: AdetailerPair | None):
    with (
        patch(
            "src.gui.views.review_tab_frame_v2.extract_embedded_metadata",
            return_value=ReadPayloadResult(payload=PAYLOAD, status="ok"),
        ),
        patch("src.gui.views.review_tab_frame_v2.resolve_adetailer_pair", return_value=pair),
    ):
        tab._show_image(path)


@pytest.mark.gui
def test_the_outcome_tools_are_enabled_only_for_a_verified_adetailer_output(tab, tmp_path):
    output, source, other = (
        image(tmp_path / "out.png"),
        image(tmp_path / "in.png"),
        image(tmp_path / "other.png"),
    )
    show(tab, other, None)
    assert str(tab._adetailer_compare_button.cget("state")) == "disabled"
    assert all(str(w.cget("state")) == "disabled" for w in tab._adetailer_outcome_widgets)
    show(tab, output, AdetailerPair(output=output, source=source))
    assert str(tab._adetailer_compare_button.cget("state")) == "normal"
    assert [str(w.cget("state")) for w in tab._adetailer_outcome_widgets] == [
        "readonly",
        "readonly",
        "normal",
    ]
    assert (
        tab.adetailer_face_outcome_var.get()
        == tab.adetailer_hands_outcome_var.get()
        == "Unreviewed"
    )


@pytest.mark.gui
def test_switching_images_resets_the_judgment_to_unreviewed(tab, tmp_path):
    output, source, other = (
        image(tmp_path / "out.png"),
        image(tmp_path / "in.png"),
        image(tmp_path / "other.png"),
    )
    show(tab, output, AdetailerPair(output=output, source=source))
    tab.adetailer_face_outcome_var.set("Improved")
    show(tab, other, None)
    assert tab.adetailer_face_outcome_var.get() == "Unreviewed"


@pytest.mark.gui
def test_the_feedback_payload_carries_the_judgment_only_when_one_was_made(tab, tmp_path):
    output, source = image(tmp_path / "out.png"), image(tmp_path / "in.png")
    pair = AdetailerPair(output=output, source=source)
    show(tab, output, pair)
    with patch(
        "src.gui.views.review_tab_frame_v2.extract_embedded_metadata",
        return_value=ReadPayloadResult(payload=PAYLOAD, status="ok"),
    ):
        assert "context" not in tab._build_feedback_payload(output)  # unreviewed stays unreviewed
        tab.adetailer_face_outcome_var.set("Improved")
        tab.adetailer_hands_outcome_var.set("Worsened")
        payload = tab._build_feedback_payload(output)
        review = payload["context"]["adetailer_outcome_review"]
        assert (review["face"], review["hands"]) == ("improved", "worsened")
        assert payload["rating"] == int(
            tab.rating_var.get()
        )  # the overall rating is untouched by the judgment
        assert "context" not in tab._build_feedback_payload(
            tmp_path / "unselected.png"
        )  # batch targets never inherit it


@pytest.mark.gui
def test_before_after_opens_the_existing_viewer_with_the_input_first(tab, tmp_path):
    output, source = image(tmp_path / "out.png"), image(tmp_path / "in.png")
    show(tab, output, AdetailerPair(output=output, source=source))
    calls: list[tuple] = []
    tab._render_compare_viewer = lambda path, **kw: calls.append((path, kw))  # type: ignore[method-assign]
    tab._open_adetailer_compare()
    assert calls == [
        (
            source,
            {
                "secondary_path": output,
                "title_prefix": "ADetailer Before / After",
                "labels": ("Before (sent to ADetailer)", "After (ADetailer output)"),
            },
        )
    ]


@pytest.mark.gui
def test_the_existing_content_visibility_policy_still_governs_prompts_and_the_judgment_holds_none(
    tab, tmp_path
):
    output, source = image(tmp_path / "out.png"), image(tmp_path / "in.png")
    show(tab, output, AdetailerPair(output=output, source=source))
    tab.on_content_visibility_mode_changed("sfw")
    tab.adetailer_face_outcome_var.set("Uncertain")
    with patch(
        "src.gui.views.review_tab_frame_v2.extract_embedded_metadata",
        return_value=ReadPayloadResult(payload=PAYLOAD, status="ok"),
    ):
        context = tab._build_feedback_payload(output)["context"]
    assert PROMPT not in json.dumps(context)
