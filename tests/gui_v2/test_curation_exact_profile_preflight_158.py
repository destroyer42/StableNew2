"""PR-IMG-MODELS-158: staged-curation advancement shares the one reprocess admission boundary."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState
from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1 as ZP
from src.image_backends.operation_compatibility import OperationNotSupportedError
from src.learning.discovered_review_models import DiscoveredReviewExperiment, DiscoveredReviewItem
from src.learning.discovered_review_store import DiscoveredReviewStore
from src.utils.image_metadata import ReadPayloadResult

ZIMAGE = ZP.transformer.filename


def _advance(tmp_path, model: str, target: str = "face_triage"):
    job_service = MagicMock()
    job_service.submit_njrs = MagicMock(return_value=["job-queued-1"])
    pipeline_controller = MagicMock()
    pipeline_controller._job_service = job_service
    pipeline_controller._config_manager = None
    pipeline_controller._app_state = AppStateV2()
    ctrl = LearningController(learning_state=LearningState(), pipeline_controller=pipeline_controller)
    store = DiscoveredReviewStore(tmp_path / "discovered")
    ctrl._discovered_review_store = store
    image = tmp_path / "candidate.png"
    image.write_text("placeholder", encoding="utf-8")
    store.save_group(
        DiscoveredReviewExperiment(
            group_id="disc",
            display_name="Group",
            stage="txt2img",
            prompt_hash="hash",
            items=[
                DiscoveredReviewItem(
                    item_id="cand-1", artifact_path=str(image), stage="txt2img", model=model,
                    sampler="Euler", scheduler="Beta", steps=9, cfg_scale=1.0,
                    positive_prompt="prompt text", negative_prompt="",
                    extra_fields={"face_triage_tier": "heavy"},
                )
            ],
            varying_fields=["cfg_scale"],
        )
    )
    ctrl.record_staged_curation_selection(
        "disc", "cand-1", "advanced_to_face_triage", reason_tags=["bad_face"], notes="rescue"
    )
    payload = {"stage_manifest": {"stage": "txt2img", "config": {"steps": 9, "cfg_scale": 1.0}}}
    with (
        patch("src.gui.controllers.learning_controller.extract_embedded_metadata",
              return_value=ReadPayloadResult(payload=payload, status="ok")),
        patch("src.gui.controllers.learning_controller.resolve_prompt_fields", return_value=("prompt text", "")),
        patch("src.gui.controllers.learning_controller.resolve_model_vae_fields", return_value=(model, "Automatic")),
        patch("src.gui.controllers.learning_controller.ConfigManager.get_setting", return_value="output"),
    ):
        return ctrl, job_service, lambda: ctrl.submit_staged_curation_advancement("disc", target)


def test_a_zimage_candidate_cannot_be_advanced_to_a_postprocess_stage(tmp_path):
    _ctrl, job_service, advance = _advance(tmp_path, ZIMAGE)
    with pytest.raises(OperationNotSupportedError, match="Z-Image.*Nothing was queued"):
        advance()
    job_service.submit_njrs.assert_not_called()


def test_an_ordinary_candidate_is_still_advanced_through_the_same_single_submission(tmp_path):
    _ctrl, job_service, advance = _advance(tmp_path, "juggernautXL")
    assert advance() == 1
    records, policy = job_service.submit_njrs.call_args[0]
    assert len(records) == 1 and records[0].start_stage == "adetailer"
    assert policy.start_when_idle is False
