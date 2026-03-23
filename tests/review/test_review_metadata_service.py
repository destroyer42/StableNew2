from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.learning.learning_record import LearningRecord
from src.review.review_metadata_service import REVIEW_METADATA_SCHEMA, ReviewMetadataService
from src.utils.image_metadata import PORTABLE_REVIEW_KEY, read_image_metadata


def _write_png(path: Path) -> None:
    image = Image.new("RGB", (8, 8), color=(10, 20, 30))
    image.save(path)


def _build_record(metadata: dict[str, object] | None = None) -> LearningRecord:
    return LearningRecord(
        run_id="run-review-1",
        timestamp="2026-03-10T12:00:00",
        base_config={"stage": "img2img", "prompt": "base prompt"},
        variant_configs=[{"prompt": "after prompt"}],
        randomizer_mode="review_feedback",
        randomizer_plan_size=1,
        primary_model="modelA.safetensors",
        primary_sampler="DPM++ 2M",
        primary_scheduler="Karras",
        primary_steps=24,
        primary_cfg_scale=6.5,
        metadata=dict(metadata or {}),
    )


def test_review_metadata_service_embeds_review_payload_without_removing_existing_metadata(tmp_path: Path) -> None:
    image_path = tmp_path / "sample.png"
    _write_png(image_path)
    assert read_image_metadata(image_path) == {}

    service = ReviewMetadataService()
    record = _build_record(
        {
            "source": "review_tab",
            "user_rating": 4,
            "user_rating_raw": 4,
            "quality_label": "good",
            "user_notes": "hands improved",
            "prompt_before": "portrait",
            "prompt_after": "portrait, detailed hands",
            "negative_prompt_before": "blurry",
            "negative_prompt_after": "blurry, extra fingers",
            "prompt_delta": "detailed hands",
            "negative_prompt_delta": "extra fingers",
            "prompt_mode": "append",
            "negative_prompt_mode": "append",
            "stages": ["adetailer"],
            "review_context": {"actor": "user", "panel": "review"},
            "subscores": {"anatomy": 5, "composition": 4, "prompt_adherence": 3},
            "weighted_score": 4.0,
            "model": "modelA.safetensors",
        }
    )

    result = service.stamp_review_metadata(
        image_path=image_path,
        feedback={"sampler": "Euler", "scheduler": "Karras"},
        record=record,
    )

    stored = read_image_metadata(image_path)
    read_result = service.read_review_metadata(image_path)

    assert result.success is True
    assert result.storage == "embedded"
    assert PORTABLE_REVIEW_KEY in stored
    assert read_result.source == "embedded"
    assert read_result.payload is not None
    assert read_result.payload["schema"] == REVIEW_METADATA_SCHEMA
    assert read_result.payload["run_id"] == record.run_id
    assert read_result.payload["review_context"]["panel"] == "review"
    assert read_result.payload["subscores"]["anatomy"] == 5


def test_review_metadata_service_falls_back_to_sidecar_for_unsupported_extension(tmp_path: Path) -> None:
    image_path = tmp_path / "sample.bmp"
    image_path.write_bytes(b"not-a-real-bmp")

    service = ReviewMetadataService()
    record = _build_record(
        {
            "source": "review_tab",
            "user_rating": 3,
            "prompt_before": "base",
            "prompt_after": "after",
        }
    )

    result = service.stamp_review_metadata(
        image_path=image_path,
        feedback={},
        record=record,
    )
    read_result = service.read_review_metadata(image_path)

    assert result.success is True
    assert result.storage == "sidecar"
    assert result.sidecar_path is not None
    assert Path(result.sidecar_path).exists()
    assert read_result.source == "sidecar"
    assert read_result.payload is not None
    assert read_result.payload["run_id"] == record.run_id


def test_review_metadata_service_normalizes_portable_review_summary(tmp_path: Path) -> None:
    image_path = tmp_path / "summary.png"
    _write_png(image_path)

    service = ReviewMetadataService()
    record = _build_record(
        {
            "source": "review_tab",
            "user_rating": 5,
            "user_rating_raw": 4,
            "quality_label": "excellent",
            "user_notes": "best version",
            "prompt_before": "base",
            "prompt_after": "base, refined",
            "prompt_delta": "refined",
            "prompt_mode": "append",
            "review_context": {"actor": "user"},
        }
    )

    stamp_result = service.stamp_review_metadata(image_path=image_path, feedback={}, record=record)
    summary = service.read_review_summary(image_path)

    assert stamp_result.success is True
    assert summary is not None
    assert summary.source_type == "embedded_review_metadata"
    assert summary.schema == REVIEW_METADATA_SCHEMA
    assert summary.user_rating == 5
    assert summary.user_rating_raw == 4
    assert summary.quality_label == "excellent"
    assert summary.user_notes == "best version"
    assert summary.prompt_delta == "refined"
    assert summary.prompt_mode == "append"