from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.review.artifact_metadata_inspector import ArtifactMetadataInspector
from src.review.review_metadata_service import ReviewMetadataService
from src.utils.image_metadata import build_contract_kv, write_image_metadata


def _write_png(path: Path) -> None:
    image = Image.new("RGB", (8, 8), color=(10, 20, 30))
    image.save(path)


def test_artifact_metadata_inspector_reports_generation_and_internal_review_precedence(tmp_path: Path) -> None:
    image_path = tmp_path / "artifact.png"
    _write_png(image_path)
    generation_payload = {
        "job_id": "job-1",
        "run_id": "run-1",
        "stage": "txt2img",
        "generation": {
            "prompt": "portrait",
            "negative_prompt": "blurry",
            "steps": 24,
            "cfg_scale": 6.5,
            "width": 1024,
            "height": 1024,
            "sampler_name": "DPM++ 2M",
            "scheduler": "Karras",
            "model": "modelA",
            "vae": "Automatic",
            "seed": 123,
        },
        "stage_manifest": {
            "stage": "txt2img",
            "config": {
                "steps": 24,
                "cfg_scale": 6.5,
                "sampler_name": "DPM++ 2M",
                "scheduler": "Karras",
                "width": 1024,
                "height": 1024,
                "seed": 123,
                "model": "modelA",
                "sd_vae": "Automatic",
            },
        },
    }
    kv = build_contract_kv(generation_payload, job_id="job-1", run_id="run-1", stage="txt2img")
    assert write_image_metadata(image_path, kv) is True

    review_service = ReviewMetadataService()
    stamp_result = review_service.write_portable_review_metadata if False else None
    del stamp_result
    from src.learning.learning_record import LearningRecord

    record = LearningRecord(
        run_id="review-run-1",
        timestamp="2026-03-23T12:00:00",
        base_config={},
        variant_configs=[],
        randomizer_mode="review_feedback",
        randomizer_plan_size=1,
        primary_model="modelA",
        primary_sampler="DPM++ 2M",
        primary_scheduler="Karras",
        primary_steps=24,
        primary_cfg_scale=6.5,
        metadata={
            "source": "review_tab",
            "user_rating": 3,
            "quality_label": "good",
            "user_notes": "portable review",
        },
    )
    assert review_service.stamp_review_metadata(image_path=image_path, feedback={}, record=record).success is True

    inspector = ArtifactMetadataInspector(review_service)
    inspection = inspector.inspect_artifact(
        image_path,
        internal_review_summary={
            "source_type": "internal_learning_record",
            "schema": "stablenew.internal-review-summary.v2.6",
            "review_timestamp": "2026-03-23T12:30:00",
            "user_rating": 5,
            "quality_label": "excellent",
        },
    )

    payload = inspection.to_dict()
    assert payload["normalized_generation_summary"]["present"] is True
    assert payload["normalized_generation_summary"]["stage"] == "txt2img"
    assert payload["normalized_generation_summary"]["sampler"] == "DPM++ 2M"
    assert payload["source_diagnostics"]["embedded_generation_present"] is True
    assert payload["source_diagnostics"]["embedded_review_present"] is True
    assert payload["source_diagnostics"]["internal_review_present"] is True
    assert payload["source_diagnostics"]["active_review_precedence"] == "internal_learning_record"
    assert payload["normalized_review_summary"]["user_rating"] == 5
    assert payload["raw_embedded_review_payload"]["quality_label"] == "good"


def test_artifact_metadata_inspector_reports_sidecar_review_metadata(tmp_path: Path) -> None:
    image_path = tmp_path / "artifact.bmp"
    image_path.write_bytes(b"fake-bmp")

    from src.learning.learning_record import LearningRecord

    review_service = ReviewMetadataService()
    record = LearningRecord(
        run_id="review-run-2",
        timestamp="2026-03-23T13:00:00",
        base_config={},
        variant_configs=[],
        randomizer_mode="review_feedback",
        randomizer_plan_size=1,
        primary_model="",
        primary_sampler="",
        primary_scheduler="",
        primary_steps=0,
        primary_cfg_scale=0.0,
        metadata={
            "source": "review_tab",
            "user_rating": 4,
            "quality_label": "good",
            "user_notes": "sidecar review",
        },
    )
    result = review_service.stamp_review_metadata(image_path=image_path, feedback={}, record=record)
    assert result.storage == "sidecar"

    inspector = ArtifactMetadataInspector(review_service)
    payload = inspector.inspect_artifact(image_path).to_dict()

    assert payload["source_diagnostics"]["embedded_generation_present"] is False
    assert payload["source_diagnostics"]["embedded_review_present"] is False
    assert payload["source_diagnostics"]["sidecar_review_present"] is True
    assert payload["source_diagnostics"]["active_review_precedence"] == "sidecar_review_metadata"
    assert payload["normalized_review_summary"]["user_notes"] == "sidecar review"