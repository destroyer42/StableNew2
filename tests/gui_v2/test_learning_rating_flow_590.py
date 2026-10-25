"""PR-LEARN-UX-590: the review panel's rating flow and recommendation display (L16-L21, L24-L29)."""

from __future__ import annotations

from pathlib import Path
from tkinter import messagebox
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState, LearningVariant
from src.gui.theme_v2 import PRIMARY_BUTTON_STYLE
from src.gui.views.learning_review_panel import LearningReviewPanel
from src.learning.learning_record import LearningRecordWriter
from src.learning.recommendation_engine import (
    EVIDENCE_TIER_EXPERIMENT_STRONG,
    EVIDENCE_TIER_REVIEW_ONLY,
    ParameterRecommendation,
    RecommendationSet,
)
from tests.gui_v2.tk_test_utils import get_shared_tk_root


def _png(path: Path) -> str:
    Image.new("RGB", (16, 16)).save(path)
    return str(path)


def _records(controller: LearningController) -> list[str]:
    path = controller._learning_record_writer.records_path  # noqa: SLF001
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


@pytest.fixture
def flow(tmp_path: Path):
    root = get_shared_tk_root()
    if root is None:
        pytest.skip("No display available for Tkinter tests")
    state = LearningState()
    controller = LearningController(
        state, learning_record_writer=LearningRecordWriter(tmp_path / "learning_records.jsonl")
    )
    controller.update_experiment_design(
        {
            "name": "Rating flow",
            "description": "sweep",
            "prompt_source": "custom",
            "custom_prompt": "portrait",
            "stage": "txt2img",
            "variable_under_test": "CFG Scale",
            "start_value": 6.0,
            "end_value": 8.0,
            "step_value": 1.0,
            "images_per_value": 2,
        }
    )
    experiment = state.current_experiment
    assert experiment is not None
    images = [[_png(tmp_path / f"v{v}_{i}.png") for i in range(2)] for v in range(3)]
    plan = [
        LearningVariant(
            experiment_id=experiment.experiment_id,
            param_value=6.0 + v,
            status="completed",
            image_refs=images[v],
            job_id=f"job{v}",
        )
        for v in range(3)
    ]
    state.plan = plan
    state.selected_variant = plan[0]
    panel = LearningReviewPanel(root)
    panel.learning_controller = controller
    panel.display_variant_results(plan[0], experiment)
    yield SimpleNamespace(
        panel=panel, controller=controller, state=state, plan=plan, images=images, tmp=tmp_path
    )
    panel.destroy()


def _select(panel: LearningReviewPanel, index: int) -> None:
    panel.image_listbox.selection_clear(0, "end")
    panel.image_listbox.selection_set(index)
    panel._on_image_selected(None)  # noqa: SLF001


def _show(flow, variant_index: int, image_index: int = 0) -> None:
    flow.state.selected_variant = flow.plan[variant_index]
    flow.state.selected_image_index = image_index
    flow.panel._active_image_ref = None  # noqa: SLF001
    flow.panel.display_variant_results(flow.plan[variant_index], flow.state.current_experiment)


def _no_dialogs(monkeypatch, answer: bool = True) -> Mock:
    ask = Mock(return_value=answer)
    monkeypatch.setattr(messagebox, "askyesno", ask)
    monkeypatch.setattr(messagebox, "showinfo", Mock())
    return ask


# -- L16/L17: Save & Next is the primary route; details are optional ---------------------------------------------


def test_save_and_next_is_the_primary_rating_button_and_details_are_collapsed(flow) -> None:
    panel = flow.panel
    assert panel.save_next_button.cget("text") == "Save & Next"
    assert str(panel.save_next_button.cget("style")) == PRIMARY_BUTTON_STYLE
    # Optional fields sit inside the disclosure and start collapsed.
    assert panel.rating_details_section.is_expanded() is False


def test_a_star_rating_alone_saves_with_save_and_next(flow, monkeypatch) -> None:
    _no_dialogs(monkeypatch)
    panel = flow.panel
    _select(panel, 0)
    panel.rating_var.set(4)

    panel.save_and_next()

    assert flow.controller.get_rating_for_image(flow.images[0][0]) == 4
    assert len(_records(flow.controller)) == 1


def test_save_and_next_moves_to_the_next_unrated_image_in_stable_order(flow, monkeypatch) -> None:
    _no_dialogs(monkeypatch)
    panel = flow.panel
    _select(panel, 0)
    panel.rating_var.set(5)

    panel.save_and_next()

    assert panel._selected_image_ref() == flow.images[0][1]  # noqa: SLF001
    assert panel.rating_var.get() == 0  # nothing invented for the new image
    assert "Unrated" in panel.rating_status_var.get()


def test_save_and_next_crosses_variants_and_wraps_to_earlier_unrated(flow, monkeypatch) -> None:
    _no_dialogs(monkeypatch)
    panel = flow.panel
    # Rate everything but the very first image, then rate the last one: next must wrap to the first.
    for variant in (0, 1, 2):
        for image in (0, 1):
            ref = flow.images[variant][image]
            if (variant, image) != (0, 0):
                flow.controller.record_rating(ref, 3, "", {"context_flags": {}, "subscores": {}})
    _show(flow, 2, 1)
    # Already rated and unchanged: Save & Next is still safe and moves on.
    panel.rating_var.set(3)
    panel.save_and_next()

    assert panel._selected_image_ref() == flow.images[0][0]  # noqa: SLF001


def test_next_unrated_skips_unavailable_files_and_says_why(flow, monkeypatch) -> None:
    _no_dialogs(monkeypatch)
    panel = flow.panel
    Path(flow.images[0][1]).unlink()
    _select(panel, 0)
    panel.rating_var.set(2)

    panel.save_and_next()

    # The deleted file is not offered; the next ratable image is the first of the second variant.
    assert panel._selected_image_ref() == flow.images[1][0]  # noqa: SLF001
    assert "unavailable" in panel.workspace_status_var.get()


def test_nothing_ratable_left_explains_instead_of_claiming_completion(flow, monkeypatch) -> None:
    _no_dialogs(monkeypatch)
    panel = flow.panel
    for variant in (0, 1, 2):
        for image in (0, 1):
            if (variant, image) != (0, 0):
                flow.controller.record_rating(
                    flow.images[variant][image], 3, "", {"context_flags": {}, "subscores": {}}
                )
    Path(flow.images[0][0]).unlink()
    _show(flow, 0, 1)

    panel._on_next_unrated()  # noqa: SLF001

    text = panel.feedback_label.cget("text")
    assert "All completed samples are rated" not in text
    assert "unavailable" in text


# -- L18: no invented rating; unchanged saved rating is not re-appended ------------------------------------------


def test_save_without_a_chosen_rating_is_refused_and_writes_nothing(flow, monkeypatch) -> None:
    _no_dialogs(monkeypatch)
    panel = flow.panel
    _select(panel, 0)

    panel.save_and_next()

    assert _records(flow.controller) == []
    assert flow.controller.get_rating_for_image(flow.images[0][0]) is None
    assert "select a rating" in panel.feedback_label.cget("text").lower()


def test_saving_an_unchanged_saved_rating_appends_nothing(flow, monkeypatch) -> None:
    ask = _no_dialogs(monkeypatch)
    panel = flow.panel
    _select(panel, 0)
    panel.rating_var.set(4)
    panel._submit_rating()  # noqa: SLF001
    assert len(_records(flow.controller)) == 1

    _show(flow, 0, 0)
    assert panel.rating_var.get() == 4
    assert panel._submit_rating() is True  # noqa: SLF001

    assert len(_records(flow.controller)) == 1
    ask.assert_not_called()
    assert "Saved: 4" in panel.rating_status_var.get()


# -- L19: replacing a saved rating needs confirmation ------------------------------------------------------------


def test_replacing_a_saved_rating_asks_first_and_declining_keeps_it(flow, monkeypatch) -> None:
    ask = _no_dialogs(monkeypatch, answer=False)
    panel = flow.panel
    _select(panel, 0)
    panel.rating_var.set(2)
    panel._submit_rating()  # noqa: SLF001
    _show(flow, 0, 0)
    panel.rating_var.set(5)

    assert panel._submit_rating() is False  # noqa: SLF001

    ask.assert_called_once()
    assert flow.controller.get_rating_for_image(flow.images[0][0]) == 2
    assert len(_records(flow.controller)) == 1


def test_confirming_the_replacement_saves_the_new_rating(flow, monkeypatch) -> None:
    _no_dialogs(monkeypatch, answer=True)
    panel = flow.panel
    _select(panel, 0)
    panel.rating_var.set(2)
    panel._submit_rating()  # noqa: SLF001
    _show(flow, 0, 0)
    panel.rating_var.set(5)

    assert panel._submit_rating() is True  # noqa: SLF001

    assert flow.controller.get_rating_for_image(flow.images[0][0]) == 5


# -- L20: saved / draft / unrated / missing stay distinct --------------------------------------------------------


def test_workspace_counts_keep_saved_draft_unrated_and_missing_apart(flow) -> None:
    flow.controller.record_rating(flow.images[0][0], 4, "", {"context_flags": {}, "subscores": {}})
    flow.controller.save_review_draft(
        flow.images[0][1], {"overall_rating": 3, "notes": "", "subscores": {}, "context_flags": {}}
    )
    Path(flow.images[2][1]).unlink()

    flow.panel._refresh_experiment_workspace(flow.state.current_experiment)  # noqa: SLF001

    text = flow.panel.workspace_status_var.get()
    assert "1 saved / 1 draft / 3 unrated" in text
    assert "1 unavailable" in text


def test_a_draft_is_not_presented_as_a_saved_rating(flow) -> None:
    flow.controller.save_review_draft(
        flow.images[0][0], {"overall_rating": 3, "notes": "", "subscores": {}, "context_flags": {}}
    )
    _show(flow, 0, 0)

    status = flow.panel.rating_status_var.get()
    assert "Saved:" not in status
    assert "not saved" in status.lower() or "draft" in status.lower()
    assert flow.controller.get_rating_for_image(flow.images[0][0]) is None


def test_an_unavailable_image_is_marked_and_stays_unrated(flow) -> None:
    Path(flow.images[0][0]).unlink()
    _show(flow, 0, 0)

    assert "[file unavailable]" in flow.panel.image_listbox.get(0)
    assert "unavailable" in flow.panel.rating_status_var.get()
    assert flow.controller.get_rating_for_image(flow.images[0][0]) is None


# -- L21: the plan-table average-rating mismatch -----------------------------------------------------------------


def test_plan_table_average_rating_uses_the_experiment_id_not_the_name(flow) -> None:
    flow.controller.record_rating(flow.images[0][0], 4, "", {"context_flags": {}, "subscores": {}})
    flow.controller.record_rating(flow.images[0][1], 2, "", {"context_flags": {}, "subscores": {}})
    table = Mock()
    flow.controller._plan_table = table  # noqa: SLF001

    flow.controller._update_variant_ratings()  # noqa: SLF001

    assert flow.state.current_experiment.name != flow.state.current_experiment.experiment_id
    table.update_row_rating.assert_any_call(0, 3.0)
    table.update_row_rating.assert_any_call(1, None)


# -- recommendations: what, where, on what evidence, and what Apply would change ---------------------------------


class _Var:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


def _stage_cards(cfg: float = 7.0) -> SimpleNamespace:
    return SimpleNamespace(
        txt2img_card=SimpleNamespace(
            cfg_var=_Var(cfg),
            steps_var=_Var(20),
            sampler_var=_Var("Euler a"),
            scheduler_var=_Var("normal"),
            model_var=_Var("modelA.safetensors"),
            vae_var=_Var(""),
        )
    )


def _controlled_recommendations(flow, *, tier: str = EVIDENCE_TIER_EXPERIMENT_STRONG):
    return RecommendationSet(
        prompt_text="portrait",
        stage="txt2img",
        timestamp=0.0,
        recommendations=[
            ParameterRecommendation(
                parameter_name="cfg_scale",
                recommended_value=7.5,
                confidence_score=0.8,
                sample_count=5,
                mean_rating=4.5,
                rating_stddev=0.4,
                confidence_rationale="rated higher across two tested values",
                context_key="txt2img",
            )
        ],
        evidence_tier=tier,
        automation_eligible=tier == EVIDENCE_TIER_EXPERIMENT_STRONG,
    )


def _with_pipeline(flow, cards) -> None:
    flow.controller.pipeline_controller = SimpleNamespace(
        stage_cards_panel=cards,
        can_enqueue_learning_jobs=lambda: (True, ""),
        get_preview_jobs=lambda: [object()],
        _app_state=SimpleNamespace(
            current_config=SimpleNamespace(model_name="modelA.safetensors", vae_name="")
        ),
    )


def test_without_evidence_the_panel_explains_and_apply_is_unavailable(flow) -> None:
    flow.panel.update_recommendations(None)

    assert flow.panel.recommendation_summary_var.get().startswith("No recommendation yet.")
    assert str(flow.panel.apply_button.cget("state")) == "disabled"
    assert "nothing to apply" in flow.panel.apply_note_var.get().lower()


def test_controlled_evidence_names_the_setting_value_stage_and_tier(flow) -> None:
    recs = _controlled_recommendations(flow)
    flow.panel.update_recommendations(recs)

    headline = flow.panel.recommendation_summary_var.get()
    assert headline == "Suggested: cfg_scale: 7.5"
    assert "Controlled experiment evidence" in flow.panel.recommendation_scope_var.get()
    assert "txt2img stage" in flow.panel.recommendation_scope_var.get()


def test_suggest_only_shows_but_never_offers_apply(flow) -> None:
    recs = _controlled_recommendations(flow)
    flow.controller.set_automation_mode("suggest_only")
    flow.panel.update_recommendations(recs)

    assert str(flow.panel.apply_button.cget("state")) == "disabled"
    assert "Suggest only" in flow.panel.apply_note_var.get()


def test_apply_with_confirm_shows_the_exact_before_and_after_values(flow) -> None:
    recs = _controlled_recommendations(flow)
    _with_pipeline(flow, _stage_cards(cfg=4.0))
    flow.controller.set_automation_mode("apply_with_confirm")
    flow.panel.update_recommendations(recs)

    assert str(flow.panel.apply_button.cget("state")) == "normal"
    assert "Would change cfg_scale: 4.0 -> 7.5" in flow.panel.apply_note_var.get()


def test_declining_the_confirmation_leaves_pipeline_settings_untouched(flow, monkeypatch) -> None:
    recs = _controlled_recommendations(flow)
    cards = _stage_cards(cfg=4.0)
    _with_pipeline(flow, cards)
    flow.controller.set_automation_mode("apply_with_confirm")
    flow.panel.update_recommendations(recs)
    monkeypatch.setattr(flow.controller, "get_recommendations_for_current_prompt", lambda: recs)
    ask = _no_dialogs(monkeypatch, answer=False)

    flow.panel._on_apply_recommendations()  # noqa: SLF001

    assert cards.txt2img_card.cfg_var.get() == 4.0
    ask.assert_called_once()
    message = ask.call_args.args[1]
    assert "cfg_scale: 4.0 → 7.5" in message
    assert "Past jobs, prompts and results are not changed." in message


def test_confirming_applies_all_changes_to_pipeline_settings_only(flow, monkeypatch) -> None:
    recs = _controlled_recommendations(flow)
    cards = _stage_cards(cfg=4.0)
    _with_pipeline(flow, cards)
    flow.controller.set_automation_mode("apply_with_confirm")
    flow.panel.update_recommendations(recs)
    monkeypatch.setattr(flow.controller, "get_recommendations_for_current_prompt", lambda: recs)
    _no_dialogs(monkeypatch, answer=True)

    flow.panel._on_apply_recommendations()  # noqa: SLF001

    assert cards.txt2img_card.cfg_var.get() == 7.5
    assert _records(flow.controller) == []  # applying never writes ratings or history


def test_manual_only_evidence_explains_why_auto_mode_cannot_apply(flow) -> None:
    recs = _controlled_recommendations(flow, tier=EVIDENCE_TIER_REVIEW_ONLY)
    flow.controller.set_automation_mode("auto_micro_experiment")
    flow.panel.update_recommendations(recs)

    assert str(flow.panel.apply_button.cget("state")) == "disabled"
    assert "Review feedback only (manual only)" in flow.panel.recommendation_scope_var.get()
    assert "2 distinct tested values and 3 controlled ratings" in flow.panel.apply_note_var.get()


def test_apply_refusal_is_explained_not_silent(flow, monkeypatch) -> None:
    recs = _controlled_recommendations(flow)
    flow.controller.set_automation_mode("apply_with_confirm")
    flow.panel.update_recommendations(recs)
    monkeypatch.setattr(flow.controller, "get_recommendations_for_current_prompt", lambda: recs)
    monkeypatch.setattr(flow.panel, "_confirm_apply", lambda _recs: True)
    monkeypatch.setattr(flow.controller, "apply_recommendations_to_pipeline", lambda _recs: False)
    _no_dialogs(monkeypatch)

    flow.panel._on_apply_recommendations()  # noqa: SLF001

    assert "Nothing was changed" in flow.panel.feedback_label.cget("text")


# -- model comparison / grid ratings never become recommendations; Learning never calls the runner directly ------


def test_recommendation_and_rating_paths_never_touch_the_runner_or_profile_store(
    flow, monkeypatch
) -> None:
    import src.learning.guided_workflow as guided
    import src.learning.recommendation_summary as summary_module

    for module in (guided, summary_module):
        source = Path(module.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "PipelineRunner",
            "run_njr",
            "JobService",
            "profile_store",
            "write_profile",
        ):
            assert forbidden not in source, (
                f"{module.__name__} must stay a presentation module ({forbidden})"
            )
