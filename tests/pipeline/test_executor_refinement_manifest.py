from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from src.pipeline.executor import Pipeline


def test_adetailer_manifest_carries_canonical_adaptive_refinement_block() -> None:
    pipeline = Pipeline(Mock(), Mock())
    pipeline.client.get_current_model = Mock(return_value="model.safetensors")
    pipeline.client.get_current_vae = Mock(return_value="vae.pt")

    adaptive_refinement = {
        "intent": {
            "schema": "stablenew.adaptive-refinement.v1",
            "enabled": True,
            "mode": "adetailer",
            "profile_id": "auto_v1",
            "detector_preference": "null",
            "record_decisions": True,
            "algorithm_version": "v1",
        },
        "prompt_intent": {
            "intent_band": "portrait",
            "requested_pose": "profile",
            "wants_face_detail": True,
        },
        "decision_bundle": {
            "schema": "stablenew.refinement-decision.v1",
            "algorithm_version": "v1",
            "mode": "adetailer",
            "policy_id": "adetailer_micro_face_v1",
            "detector_id": "null",
            "observation": {
                "subject_assessment": {
                    "detector_id": "null",
                    "scale_band": "micro",
                }
            },
            "applied_overrides": {
                "ad_confidence": 0.22,
                "ad_mask_min_ratio": 0.003,
                "ad_inpaint_only_masked_padding": 48,
            },
            "prompt_patch": {},
            "notes": ["small_subject_recovery"],
        },
        "detector_notes": [],
    }

    with patch.object(pipeline, "_load_image_base64", return_value="fake_b64"), \
         patch.object(pipeline, "_generate_images_with_progress", return_value={"images": ["result_b64"]}), \
         patch("src.pipeline.executor.save_image_from_base64", return_value=Path("output/test.png")), \
         patch.object(pipeline, "_write_manifest_file") as write_manifest_mock, \
         patch("builtins.open", MagicMock()):
        config = {
            "adetailer_enabled": True,
            "adetailer_model": "face_yolov8n.pt",
            "adetailer_steps": 28,
            "adetailer_confidence": 0.22,
            "ad_mask_min_ratio": 0.003,
            "adetailer_padding": 48,
            "adaptive_refinement": adaptive_refinement,
        }

        result = pipeline.run_adetailer(
            input_image_path=Path("input.png"),
            prompt="test prompt",
            negative_prompt="test negative",
            config=config,
            run_dir=Path("output"),
            image_name="test",
        )

    assert result is not None
    assert result["adaptive_refinement"]["decision_bundle"]["policy_id"] == "adetailer_micro_face_v1"
    assert result["adaptive_refinement"]["decision_bundle"]["applied_overrides"] == {
        "ad_confidence": 0.22,
        "ad_mask_min_ratio": 0.003,
        "ad_inpaint_only_masked_padding": 48,
    }
    manifest_metadata = write_manifest_mock.call_args.kwargs["metadata"]
    assert manifest_metadata["adaptive_refinement"]["intent"]["mode"] == "adetailer"
    assert manifest_metadata["adaptive_refinement"]["decision_bundle"]["policy_id"] == "adetailer_micro_face_v1"
