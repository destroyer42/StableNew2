from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.controller.app_controller import AppController
from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningExperiment, LearningState
from src.learning.learning_record import LearningRecordWriter


class _DummyVar:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


def _build_reprocess_controller() -> AppController:
    with patch("src.controller.app_controller.AppController.__init__", return_value=None):
        controller = AppController.__new__(AppController)
    controller.job_service = Mock()
    controller._append_log = Mock()
    controller._api_client = Mock()
    controller.cancel_token = None
    controller._build_reprocess_config = Mock(
        return_value={
            "steps": 20,
            "cfg_scale": 7.0,
            "img2img": {"denoising_strength": 0.2},
        }
    )
    return controller


def test_review_reprocess_feedback_to_recommendation_apply(tmp_path: Path) -> None:
    app_controller = _build_reprocess_controller()
    image = tmp_path / "img_a.png"
    image.write_bytes(b"")
    app_controller._extract_reprocess_baseline_from_image = Mock(
        return_value={
            "prompt": "portrait photo",
            "negative_prompt": "blurry",
            "model": "modelA.safetensors",
            "vae": "vaeA",
            "config": {"steps": 30, "cfg_scale": 7.5},
        }
    )

    submitted = app_controller.on_reprocess_images_with_prompt_delta(
        image_paths=[str(image)],
        stages=["adetailer"],
        prompt_delta="bending forward",
        negative_prompt_delta="extra hand",
        prompt_mode="append",
        negative_prompt_mode="append",
    )
    assert submitted == 1

    writer = LearningRecordWriter(tmp_path / "data" / "learning" / "learning_records.jsonl")
    stage_cards = SimpleNamespace(txt2img_card=SimpleNamespace(cfg_var=_DummyVar(6.0)))
    pipeline_controller = Mock()
    pipeline_controller.stage_cards_panel = stage_cards
    pipeline_controller.can_enqueue_learning_jobs.return_value = (True, "")
    pipeline_controller.get_preview_jobs.return_value = [object()]

    learning_state = LearningState()
    learning_state.current_experiment = LearningExperiment(
        name="review-e2e",
        stage="txt2img",
        variable_under_test="CFG Scale",
        prompt_text="portrait photo",
    )
    learning_controller = LearningController(
        learning_state=learning_state,
        pipeline_controller=pipeline_controller,
        learning_record_writer=writer,
    )

    learning_controller.save_review_feedback(
        {
            "image_path": str(image),
            "rating": 5,
            "quality_label": "excellent",
            "notes": "great",
            "base_prompt": "portrait photo",
            "base_negative_prompt": "blurry",
            "after_prompt": "portrait photo, bending forward",
            "after_negative_prompt": "blurry, extra hand",
            "prompt_delta": "bending forward",
            "negative_prompt_delta": "extra hand",
            "prompt_mode": "append",
            "negative_prompt_mode": "append",
            "stage": "txt2img",
            "model": "modelA.safetensors",
            "sampler": "Euler a",
            "scheduler": "karras",
            "steps": 30,
            "cfg_scale": 8.5,
            "stages": ["adetailer"],
        }
    )

    recommendations = learning_controller.get_recommendations_for_current_prompt()
    assert recommendations is not None
    best_cfg = recommendations.get_best_for_parameter("cfg_scale")
    assert best_cfg is not None
    assert best_cfg.recommended_value == 8.5

    learning_controller.set_automation_mode("apply_with_confirm")
    applied = learning_controller.apply_recommendations_to_pipeline(recommendations)
    assert applied is True
    assert stage_cards.txt2img_card.cfg_var.get() == 8.5

    lines = writer.records_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 1
    assert "review_tab" in lines[-1]


def test_auto_micro_experiment_submits_one_validation_job_when_allowed(tmp_path: Path) -> None:
    writer = LearningRecordWriter(tmp_path / "data" / "learning" / "learning_records.jsonl")
    stage_cards = SimpleNamespace(txt2img_card=SimpleNamespace(cfg_var=_DummyVar(7.0)))
    pipeline_controller = Mock()
    pipeline_controller.stage_cards_panel = stage_cards
    pipeline_controller.can_enqueue_learning_jobs.return_value = (True, "")
    pipeline_controller.get_preview_jobs.return_value = [object(), object()]

    learning_state = LearningState()
    learning_state.current_experiment = LearningExperiment(
        name="auto-micro",
        stage="txt2img",
        variable_under_test="CFG Scale",
        prompt_text="portrait photo",
    )
    learning_controller = LearningController(
        learning_state=learning_state,
        pipeline_controller=pipeline_controller,
        learning_record_writer=writer,
    )
    learning_controller.set_automation_mode("auto_micro_experiment")

    success = learning_controller.apply_recommendations_to_pipeline(
        [{"parameter": "cfg_scale", "value": 9.0}]
    )

    assert success is True
    assert stage_cards.txt2img_card.cfg_var.get() == 9.0
    pipeline_controller.submit_preview_jobs_to_queue.assert_called_once()
    call_kwargs = pipeline_controller.submit_preview_jobs_to_queue.call_args.kwargs
    assert call_kwargs["source"] == "learning_auto_micro"
    assert len(call_kwargs["records"]) == 1


def test_apply_with_confirm_supports_manual_rollback(tmp_path: Path) -> None:
    writer = LearningRecordWriter(tmp_path / "data" / "learning" / "learning_records.jsonl")
    stage_cards = SimpleNamespace(txt2img_card=SimpleNamespace(cfg_var=_DummyVar(7.0)))
    pipeline_controller = Mock()
    pipeline_controller.stage_cards_panel = stage_cards
    pipeline_controller.can_enqueue_learning_jobs.return_value = (True, "")
    pipeline_controller.get_preview_jobs.return_value = [object()]

    learning_state = LearningState()
    learning_state.current_experiment = LearningExperiment(
        name="rollback",
        stage="txt2img",
        variable_under_test="CFG Scale",
        prompt_text="portrait photo",
    )
    learning_controller = LearningController(
        learning_state=learning_state,
        pipeline_controller=pipeline_controller,
        learning_record_writer=writer,
    )
    learning_controller.set_automation_mode("apply_with_confirm")

    applied = learning_controller.apply_recommendations_to_pipeline(
        [{"parameter": "cfg_scale", "value": 8.2}]
    )
    assert applied is True
    assert stage_cards.txt2img_card.cfg_var.get() == 8.2

    rolled_back = learning_controller.rollback_last_recommendation_apply()
    assert rolled_back is True
    assert stage_cards.txt2img_card.cfg_var.get() == 7.0


def test_auto_micro_experiment_rolls_back_when_queue_cap_blocks(tmp_path: Path) -> None:
    writer = LearningRecordWriter(tmp_path / "data" / "learning" / "learning_records.jsonl")
    stage_cards = SimpleNamespace(txt2img_card=SimpleNamespace(cfg_var=_DummyVar(7.0)))
    pipeline_controller = Mock()
    pipeline_controller.stage_cards_panel = stage_cards
    pipeline_controller.can_enqueue_learning_jobs.return_value = (False, "queue cap exceeded")
    pipeline_controller.get_preview_jobs.return_value = [object()]

    learning_state = LearningState()
    learning_state.current_experiment = LearningExperiment(
        name="cap-block",
        stage="txt2img",
        variable_under_test="CFG Scale",
        prompt_text="portrait photo",
    )
    learning_controller = LearningController(
        learning_state=learning_state,
        pipeline_controller=pipeline_controller,
        learning_record_writer=writer,
    )
    learning_controller.set_automation_mode("auto_micro_experiment")

    success = learning_controller.apply_recommendations_to_pipeline(
        [{"parameter": "cfg_scale", "value": 9.0}]
    )
    assert success is False
    assert stage_cards.txt2img_card.cfg_var.get() == 7.0
    pipeline_controller.submit_preview_jobs_to_queue.assert_not_called()

