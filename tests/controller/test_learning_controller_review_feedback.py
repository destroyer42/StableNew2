from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState
from src.learning.learning_record import LearningRecordWriter
from src.review.review_metadata_service import REVIEW_METADATA_SCHEMA, ReviewMetadataService


def _build_controller(tmp_path):
    writer = LearningRecordWriter(tmp_path / "learning_records.jsonl")
    return LearningController(
        learning_state=LearningState(),
        pipeline_controller=object(),
        learning_record_writer=writer,
    )


def _write_png(path: Path) -> None:
    image = Image.new("RGB", (8, 8), color=(10, 20, 30))
    image.save(path)


def test_save_review_feedback_persists_record(tmp_path) -> None:
    controller = _build_controller(tmp_path)

    record = controller.save_review_feedback(
        {
            "image_path": "C:/images/test.png",
            "rating": 4,
            "quality_label": "good",
            "notes": "hands improved",
            "base_prompt": "portrait",
            "base_negative_prompt": "blurry",
            "after_prompt": "portrait, bending forward",
            "after_negative_prompt": "blurry, extra hand",
            "prompt_delta": "bending forward",
            "negative_prompt_delta": "extra hand",
            "prompt_mode": "append",
            "negative_prompt_mode": "append",
            "stages": ["adetailer"],
            "model": "modelA.safetensors",
        }
    )

    assert record.metadata["source"] == "review_tab"
    assert record.metadata["image_path"] == "C:/images/test.png"
    assert record.metadata["user_rating"] == 4
    assert record.metadata["prompt_after"] == "portrait, bending forward"


def test_list_recent_review_feedback_returns_newest_first(tmp_path) -> None:
    controller = _build_controller(tmp_path)
    controller.save_review_feedback(
        {
            "image_path": "img_a.png",
            "rating": 2,
            "quality_label": "poor",
            "base_prompt": "a",
            "after_prompt": "a",
        }
    )
    controller.save_review_feedback(
        {
            "image_path": "img_a.png",
            "rating": 5,
            "quality_label": "excellent",
            "base_prompt": "a",
            "after_prompt": "a, better",
        }
    )

    rows = controller.list_recent_review_feedback(limit=5, image_path="img_a.png")
    assert len(rows) == 2
    assert rows[0]["rating"] == 5
    assert rows[1]["rating"] == 2


def test_save_review_feedback_stamps_embedded_review_metadata(tmp_path: Path) -> None:
    controller = _build_controller(tmp_path)
    image_path = tmp_path / "reviewed.png"
    _write_png(image_path)

    record = controller.save_review_feedback(
        {
            "image_path": str(image_path),
            "rating": 4,
            "quality_label": "good",
            "notes": "hands improved",
            "base_prompt": "portrait",
            "base_negative_prompt": "blurry",
            "after_prompt": "portrait, detailed hands",
            "after_negative_prompt": "blurry, extra fingers",
            "prompt_delta": "detailed hands",
            "negative_prompt_delta": "extra fingers",
            "prompt_mode": "append",
            "negative_prompt_mode": "append",
            "stages": ["adetailer"],
            "model": "modelA.safetensors",
            "context": {"actor": "user", "panel": "review"},
            "subscores": {
                "anatomy": 5,
                "composition": 4,
                "prompt_adherence": 3,
            },
        }
    )

    stamp_state = record.metadata.get("artifact_review_metadata") or {}
    read_result = ReviewMetadataService().read_review_metadata(image_path)

    assert stamp_state["success"] is True
    assert stamp_state["storage"] == "embedded"
    assert read_result.payload is not None
    assert read_result.payload["schema"] == REVIEW_METADATA_SCHEMA
    assert read_result.payload["run_id"] == record.run_id
    assert read_result.payload["user_rating"] == 4


def test_save_review_feedback_falls_back_to_sidecar_when_embedding_is_unsupported(tmp_path: Path) -> None:
    controller = _build_controller(tmp_path)
    image_path = tmp_path / "reviewed.bmp"
    image_path.write_bytes(b"not-a-real-bmp")

    record = controller.save_review_feedback(
        {
            "image_path": str(image_path),
            "rating": 3,
            "quality_label": "mixed",
            "base_prompt": "portrait",
            "after_prompt": "portrait, refined",
        }
    )

    stamp_state = record.metadata.get("artifact_review_metadata") or {}
    read_result = ReviewMetadataService().read_review_metadata(image_path)

    assert stamp_state["success"] is True
    assert stamp_state["storage"] == "sidecar"
    assert stamp_state["sidecar_path"]
    assert Path(str(stamp_state["sidecar_path"])).exists()
    assert read_result.source == "sidecar"
    assert read_result.payload is not None
    assert read_result.payload["run_id"] == record.run_id


def test_get_prior_review_summary_prefers_internal_learning_record(tmp_path: Path) -> None:
    controller = _build_controller(tmp_path)
    image_path = tmp_path / "prior.png"
    _write_png(image_path)

    controller.save_review_feedback(
        {
            "image_path": str(image_path),
            "rating": 2,
            "quality_label": "poor",
            "notes": "older review",
            "base_prompt": "portrait",
            "after_prompt": "portrait",
        }
    )
    record = controller.save_review_feedback(
        {
            "image_path": str(image_path),
            "rating": 5,
            "quality_label": "excellent",
            "notes": "latest review",
            "base_prompt": "portrait",
            "after_prompt": "portrait, refined",
            "prompt_delta": "refined",
            "prompt_mode": "append",
        }
    )

    summary = controller.get_prior_review_summary(str(image_path))

    assert summary is not None
    assert summary["source_type"] == "internal_learning_record"
    assert summary["user_rating"] == 5
    assert summary["quality_label"] == "excellent"
    assert summary["user_notes"] == "latest review"
    assert summary["review_record_id"] == record.run_id


def test_import_review_images_to_staged_curation_carries_portable_review_summary(tmp_path: Path) -> None:
    controller = _build_controller(tmp_path)
    image_path = tmp_path / "imported.png"
    _write_png(image_path)

    controller.save_review_feedback(
        {
            "image_path": str(image_path),
            "rating": 4,
            "quality_label": "good",
            "notes": "portable review",
            "base_prompt": "portrait",
            "after_prompt": "portrait, refined",
        }
    )

    group_id = controller.import_review_images_to_staged_curation([str(image_path)], display_name="Import Test")
    store = controller._get_discovered_store()  # noqa: SLF001
    experiment = store.load_group(group_id)

    assert experiment is not None
    portable_review = experiment.items[0].extra_fields.get("portable_review_summary")
    assert isinstance(portable_review, dict)
    assert portable_review["user_rating"] == 4
    assert portable_review["quality_label"] == "good"

