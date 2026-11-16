"""PR-REVIEW-EVIDENCE-620: saving Review evidence never rewrites the image and is bound to its SHA-256.

Deterministic: temporary roots and synthetic images only; no GUI, network, WebUI, model or GPU.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState
from src.learning.learning_record import (
    LearningRecordWriter,
    current_rating_revisions,
    rating_revision_key,
)
from src.learning.recommendation_engine import RecommendationEngine
from src.review import review_evidence as evidence
from src.review.review_metadata_service import ReviewMetadataService
from src.utils.image_metadata import write_portable_review_metadata


def _controller(tmp_path: Path) -> LearningController:
    writer = LearningRecordWriter(tmp_path / "learning_records.jsonl")
    controller = LearningController(
        learning_state=LearningState(), pipeline_controller=object(), learning_record_writer=writer
    )
    controller.refresh_recommendations = Mock()  # type: ignore[method-assign]
    return controller


def _image(path: Path, fmt: str, color=(10, 20, 30)) -> Path:
    Image.new("RGB", (16, 16), color).save(path, format=fmt)
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pixels(path: Path) -> bytes:
    with Image.open(path) as image:
        return image.convert("RGB").tobytes()


def _rate(controller: LearningController, path: Path, rating: int = 4, **extra):
    return controller.save_review_feedback(
        {
            "image_path": str(path),
            "rating": rating,
            "quality_label": "good",
            "notes": f"note {rating}",
            "base_prompt": "p",
            "after_prompt": "p",
            **extra,
        }
    )


# --- J1: rate without mutation ----------------------------------------------------------------


@pytest.mark.parametrize(("name", "fmt"), [("a.png", "PNG"), ("a.jpg", "JPEG"), ("a.webp", "WEBP")])
def test_rating_never_changes_bytes_size_or_pixels(tmp_path, name, fmt):
    controller = _controller(tmp_path)
    path = _image(tmp_path / name, fmt)
    before = (path.read_bytes(), path.stat().st_size, _pixels(path))

    record = _rate(controller, path)

    assert (path.read_bytes(), path.stat().st_size, _pixels(path)) == before
    assert sorted(p.name for p in tmp_path.iterdir() if p.name != "learning_records.jsonl") == [name]
    assert record.metadata["artifact_sha256"] == hashlib.sha256(before[0]).hexdigest()


def test_saved_rating_is_read_back_by_digest_and_by_a_new_session(tmp_path):
    controller = _controller(tmp_path)
    path = _image(tmp_path / "a.png", "PNG")
    _rate(controller, path, 2)
    record = _rate(controller, path, 5)

    summary = controller.get_prior_review_summary(str(path))
    assert summary is not None
    assert summary["identity_status"] == evidence.IDENTITY_DIGEST
    assert summary["user_rating_raw"] == 5
    assert summary["review_record_id"] == record.run_id

    reopened = _controller(tmp_path)  # a new session over the same records file
    again = reopened.get_prior_review_summary(str(path))
    assert again is not None and again["user_rating_raw"] == 5


def test_rating_follows_the_bytes_when_the_file_is_moved(tmp_path):
    controller = _controller(tmp_path)
    path = _image(tmp_path / "a.png", "PNG")
    _rate(controller, path, 5)
    moved = tmp_path / "moved.png"
    moved.write_bytes(path.read_bytes())

    summary = controller.get_prior_review_summary(str(moved))
    assert summary is not None and summary["identity_status"] == evidence.IDENTITY_DIGEST


def test_view_supplied_digest_is_the_one_recorded(tmp_path):
    controller = _controller(tmp_path)
    path = _image(tmp_path / "a.png", "PNG")
    shown = _digest(path)
    path.write_bytes(_image(tmp_path / "other.png", "PNG", (200, 0, 0)).read_bytes())  # changed after display

    record = _rate(controller, path, 3, artifact_sha256=shown)

    assert record.metadata["artifact_sha256"] == shown
    summary = controller.get_prior_review_summary(str(path))
    assert summary is not None and summary["identity_status"] == evidence.IDENTITY_CHANGED


def test_unreadable_path_records_path_only_evidence(tmp_path):
    controller = _controller(tmp_path)
    missing = tmp_path / "gone.png"

    record = _rate(controller, missing)

    assert "artifact_sha256" not in record.metadata
    summary = controller.get_prior_review_summary(str(missing))
    assert summary is not None and summary["identity_status"] == evidence.IDENTITY_PATH


# --- J10: identity drift and legacy evidence --------------------------------------------------


def test_changed_bytes_are_reported_changed_not_silently_matched(tmp_path):
    controller = _controller(tmp_path)
    path = _image(tmp_path / "a.png", "PNG")
    _rate(controller, path, 5)
    _image(path, "PNG", (250, 5, 5))  # different bytes under the same path

    summary = controller.get_prior_review_summary(str(path))

    assert summary is not None
    assert summary["identity_status"] == "changed"
    # ... and the new bytes can be rated on their own, and restoring the old bytes finds the first rating again.
    _rate(controller, path, 1)
    latest = controller.get_prior_review_summary(str(path))
    assert latest is not None and latest["identity_status"] == "digest" and latest["user_rating_raw"] == 1


def _legacy_row(path: Path, rating: int) -> dict:
    return {
        "run_id": "legacy-1",
        "timestamp": "2026-01-01T00:00:00",
        "base_config": {},
        "variant_configs": [],
        "randomizer_mode": "review_feedback",
        "randomizer_plan_size": 1,
        "primary_model": "m",
        "primary_sampler": "",
        "primary_scheduler": "",
        "primary_steps": 0,
        "primary_cfg_scale": 0.0,
        "metadata": {
            "source": "review_tab",
            "record_kind": "review_tab_feedback",
            "image_path": str(path),
            "user_rating": rating,
            "user_rating_raw": rating,
            "quality_label": "good",
            "user_notes": "legacy",
        },
    }


def test_legacy_path_keyed_row_still_appears_as_the_prior_summary(tmp_path):
    controller = _controller(tmp_path)
    path = _image(tmp_path / "a.png", "PNG")
    controller._learning_record_writer.records_path.write_text(
        json.dumps(_legacy_row(path, 3)) + "\n", encoding="utf-8"
    )

    summary = controller.get_prior_review_summary(str(path))

    assert summary is not None
    assert summary["identity_status"] == evidence.IDENTITY_PATH
    assert summary["user_rating"] == 3 and summary["user_notes"] == "legacy"


@pytest.mark.parametrize(("name", "fmt", "source"), [
    ("s.png", "PNG", "embedded_review_metadata"),
    ("s.jpg", "JPEG", "sidecar_review_metadata"),
])
def test_legacy_embedded_or_sidecar_stamp_still_appears(tmp_path, name, fmt, source):
    controller = _controller(tmp_path)
    path = _image(tmp_path / name, fmt)
    payload = {"schema": "stablenew.review.v2.6", "user_rating": 4, "user_notes": "stamped"}
    if fmt == "PNG":
        assert write_portable_review_metadata(path, payload).storage == "embedded"
    else:
        from src.utils.image_metadata import write_review_sidecar

        assert write_review_sidecar(path, payload).success

    summary = controller.get_prior_review_summary(str(path))

    assert summary is not None and summary["source_type"] == source and summary["user_rating"] == 4


# --- the explicit export ----------------------------------------------------------------------


def test_export_embeds_png_and_says_the_identity_changes(tmp_path):
    controller = _controller(tmp_path)
    path = _image(tmp_path / "a.png", "PNG")
    record = _rate(controller, path, 4)
    before = _digest(path)

    result = controller.write_review_rating_into_file(path)

    assert result.success and result.storage == "embedded"
    assert _digest(path) != before  # the one place a rating changes the file, and only on request
    payload = ReviewMetadataService().read_review_metadata(path).payload
    assert payload is not None
    assert payload["run_id"] == record.run_id and payload["artifact_sha256"] == before
    # The exported file still reads back its rating (the evidence names the earlier bytes, so it is not "digest").
    summary = controller.get_prior_review_summary(str(path))
    assert summary is not None and summary["source_type"] == "embedded_review_metadata"


@pytest.mark.parametrize(("name", "fmt"), [("a.jpg", "JPEG"), ("a.webp", "WEBP")])
def test_export_writes_a_sidecar_and_never_re_encodes_jpeg_or_webp(tmp_path, name, fmt):
    controller = _controller(tmp_path)
    path = _image(tmp_path / name, fmt)
    _rate(controller, path, 4)
    before = path.read_bytes()

    result = controller.write_review_rating_into_file(path)

    assert result.success and result.storage == "sidecar"
    assert path.read_bytes() == before
    assert Path(str(result.sidecar_path)).exists()


def test_export_refuses_without_a_rating_for_the_current_bytes(tmp_path):
    controller = _controller(tmp_path)
    path = _image(tmp_path / "a.png", "PNG")
    with pytest.raises(ValueError):
        controller.write_review_rating_into_file(path)
    _rate(controller, path)
    _image(path, "PNG", (1, 2, 3))
    with pytest.raises(ValueError):
        controller.write_review_rating_into_file(path)


# --- records, keys, undo ----------------------------------------------------------------------


def test_revision_key_uses_the_digest_when_recorded_and_the_path_otherwise(tmp_path):
    controller = _controller(tmp_path)
    path = _image(tmp_path / "a.png", "PNG")
    copy = tmp_path / "copy.png"
    copy.write_bytes(path.read_bytes())
    first = _rate(controller, path, 2)
    second = _rate(controller, copy, 5)

    rows = [json.loads(line) for line in controller._learning_record_writer.records_path.read_text().splitlines()]
    assert rating_revision_key(rows[0]) == ("review_tab_feedback", "", f"sha256:{_digest(path)}")
    assert rating_revision_key(rows[0]) == rating_revision_key(rows[1])  # the same bytes are one sample
    assert [r["run_id"] for r in current_rating_revisions(rows)] == [second.run_id]
    assert first.run_id != second.run_id

    legacy = _legacy_row(path, 3)
    assert rating_revision_key(legacy) == ("review_tab_feedback", "", str(path))  # legacy rows unchanged


def test_undo_by_run_id_still_works_and_failed_append_is_not_saved(tmp_path, monkeypatch):
    controller = _controller(tmp_path)
    path = _image(tmp_path / "a.png", "PNG")
    record = _rate(controller, path)
    assert controller.undo_review_feedback(run_id=record.run_id, image_path=str(path)) is True
    assert controller.get_prior_review_summary(str(path)) is None

    monkeypatch.setattr(controller._learning_record_writer, "append_record", Mock(return_value=False))
    with pytest.raises(OSError, match="not confirmed saved"):
        _rate(controller, path)


def test_invalid_feedback_is_still_refused(tmp_path):
    controller = _controller(tmp_path)
    with pytest.raises(ValueError, match="image_path is required"):
        controller.save_review_feedback({"rating": 3})
    with pytest.raises(ValueError, match="between 1 and 5"):
        controller.save_review_feedback({"image_path": "x.png", "rating": 9})


# --- dispositions -----------------------------------------------------------------------------


def test_disposition_is_digest_bound_latest_wins_and_never_touches_the_file(tmp_path):
    writer = LearningRecordWriter(tmp_path / "learning_records.jsonl")
    path = _image(tmp_path / "a.png", "PNG")
    before = path.read_bytes()

    evidence.save_disposition(writer, image_path=path, disposition="retain", source_job_id="job-9")
    second = evidence.save_disposition(writer, image_path=path, disposition="rework")

    assert path.read_bytes() == before
    found = evidence.lookup_disposition(writer.records_path, path, _digest(path))
    assert (found.disposition, found.identity, found.run_id) == ("rework", "digest", second.run_id)
    assert second.metadata["artifact_sha256"] == _digest(path)
    # Moved copy: same bytes, found by digest. Changed bytes at the old path: reported changed, not applied.
    moved = tmp_path / "moved.png"
    moved.write_bytes(before)
    assert evidence.lookup_disposition(writer.records_path, moved, _digest(moved)).disposition == "rework"
    _image(path, "PNG", (9, 9, 9))
    drifted = evidence.lookup_disposition(writer.records_path, path, _digest(path))
    assert drifted.identity == "changed"


def test_disposition_validation_and_failed_append(tmp_path):
    writer = LearningRecordWriter(tmp_path / "learning_records.jsonl")
    path = _image(tmp_path / "a.png", "PNG")
    with pytest.raises(ValueError, match="disposition"):
        evidence.build_disposition_record(image_path=path, disposition="keep")
    with pytest.raises(ValueError, match="could not be read"):
        evidence.build_disposition_record(image_path=tmp_path / "missing.png", disposition="retain")
    writer.append_record = Mock(return_value=False)  # type: ignore[method-assign]
    with pytest.raises(OSError, match="not confirmed saved"):
        evidence.save_disposition(writer, image_path=path, disposition="discard")


def test_dispositions_are_not_ratings_for_listing_undo_or_the_recommendation_engine(tmp_path):
    controller = _controller(tmp_path)
    writer = controller._learning_record_writer
    path = _image(tmp_path / "a.png", "PNG")
    rated = _rate(controller, path, 5)
    disposition = evidence.save_disposition(writer, image_path=path, disposition="discard")

    assert [row["run_id"] for row in controller.list_recent_review_feedback(image_path=str(path))] == [
        rated.run_id
    ]
    assert writer.remove_latest_review_feedback(image_path=str(path)) is True  # removes the rating, not the decision
    rows = [json.loads(line) for line in writer.records_path.read_text().splitlines()]
    assert [row["run_id"] for row in rows] == [disposition.run_id]

    # Even a disposition that carries rating-shaped fields is not evidence for the engine (kind allow-list).
    poisoned = json.loads(json.dumps(rows[0]))
    poisoned["metadata"].update(user_rating=5, user_rating_raw=5, subscores={"anatomy": 5})
    poisoned["primary_model"], poisoned["primary_steps"], poisoned["primary_cfg_scale"] = "m", 20, 7.0
    rating_row = _legacy_row(path, 5)
    rating_row["metadata"]["record_kind"] = "review_tab_feedback"
    engine = RecommendationEngine(writer.records_path)
    scored = engine._score_records([rating_row, poisoned])  # noqa: SLF001
    assert evidence.DISPOSITION_KIND not in {row.get("record_kind") for row in scored}
    assert [row["record_kind"] for row in scored] == ["review_tab_feedback"]
    assert len(scored) == 1


def test_the_review_evidence_module_is_tk_free():
    source = Path(evidence.__file__).read_text(encoding="utf-8")
    assert "tkinter" not in source and "src.gui" not in source
