from __future__ import annotations

from pathlib import Path

from src.gui.controllers.review_workflow_adapter import ReviewWorkflowAdapter
from src.gui.view_contracts.feedback_panel_contract import update_feedback_state
from src.gui.view_contracts.form_section_contract import update_form_section
from src.gui.view_contracts.selection_list_contract import update_selection_list


def test_review_adapter_prompt_diff_contract() -> None:
    adapter = ReviewWorkflowAdapter()
    diff = adapter.build_prompt_diff(
        base_prompt="portrait",
        base_negative_prompt="bad hands",
        prompt_delta="dramatic lighting",
        negative_prompt_delta="extra fingers",
        prompt_mode="append",
        negative_prompt_mode="append",
    )
    assert "Before +: portrait" in diff.before_text
    assert "After +: portrait, dramatic lighting" in diff.after_text
    assert diff.after_negative_prompt == "bad hands, extra fingers"


def test_review_feedback_payload_contract() -> None:
    adapter = ReviewWorkflowAdapter()
    payload = adapter.build_feedback_payload(
        image_path=Path("output/a.png"),
        metadata_payload={
            "stage_manifest": {
                "prompt": "a portrait",
                "negative_prompt": "bad hands",
                "model": "modelA",
            }
        },
        rating=4,
        quality_label="good",
        notes="clean result",
        prompt_delta="cinematic",
        negative_prompt_delta="extra fingers",
        prompt_mode="append",
        negative_prompt_mode="append",
        stages=["adetailer"],
        anatomy_rating=5,
        composition_rating=4,
        prompt_adherence_rating=4,
    )
    assert str(payload["image_path"]).endswith("output\\a.png") or str(payload["image_path"]).endswith("output/a.png")
    assert payload["after_prompt"] == "a portrait, cinematic"
    assert payload["subscores"]["anatomy"] == 5


def test_review_feedback_payload_uses_resolved_prompt_fallbacks() -> None:
    adapter = ReviewWorkflowAdapter()
    payload = adapter.build_feedback_payload(
        image_path=Path("output/b.png"),
        metadata_payload={
            "stage_manifest": {
                "final_prompt": "final portrait prompt",
                "config": {"negative_prompt": "washed out"},
                "model": "modelB",
            }
        },
        rating=4,
        quality_label="good",
        notes="clean result",
        prompt_delta="cinematic",
        negative_prompt_delta="extra fingers",
        prompt_mode="append",
        negative_prompt_mode="append",
        stages=["img2img"],
        anatomy_rating=5,
        composition_rating=4,
        prompt_adherence_rating=4,
    )

    assert payload["base_prompt"] == "final portrait prompt"
    assert payload["base_negative_prompt"] == "washed out"
    assert payload["after_prompt"] == "final portrait prompt, cinematic"
    assert payload["after_negative_prompt"] == "washed out, extra fingers"


def test_view_contract_state_helpers() -> None:
    sel = update_selection_list(["a", "b", "c"], [0, 2, 9])
    assert sel.selected_indices == (0, 2)
    assert sel.selected_count == 2

    form_state, edits = update_form_section(
        previous_mode="append",
        next_mode="modify",
        edits_by_mode={"append": "x"},
        readonly_text="base prompt",
    )
    assert form_state.mode == "modify"
    assert edits["modify"] == "base prompt"

    feedback = update_feedback_state(selected_count=2, undo_depth=1)
    assert feedback.can_save is True
    assert feedback.can_batch_save is True
    assert feedback.can_undo is True
