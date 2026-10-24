"""PR-HISTORY-610A: eligibility of a persisted record for the two Iterate choices (pure; no Tk, no GPU)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from src.gui_v2.history_iterate_model import assess_history_iterate
from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import JobStatus
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config
from tests.pipeline.test_history_variation_compiler_610a import _source

SECRET = "super private prompt words"


def _entry(njr, *, result=None, status=JobStatus.COMPLETED, snapshot="auto") -> JobHistoryEntry:
    return JobHistoryEntry(
        job_id=njr.job_id,
        created_at=datetime(2026, 10, 24),
        status=status,
        result=result,
        snapshot={"normalized_job": njr.to_dict()} if snapshot == "auto" else snapshot,
    )


def _image(tmp_path: Path, name: str = "out.png") -> str:
    path = tmp_path / name
    path.write_bytes(b"\x89PNG\r\n")
    return str(path)


def _result(path: str) -> dict:
    return {"artifact": {"artifact_type": "image", "primary_path": path, "output_paths": [path]}}


def test_a_single_image_txt2img_job_offers_both_choices(tmp_path):
    njr, image = _source(), _image(tmp_path)
    assessment = assess_history_iterate(_entry(njr, result=_result(image)))
    assert assessment.review.supported and assessment.pipeline.supported
    assert assessment.image_path == image and assessment.njr.job_id == njr.job_id
    assert assessment.any_supported


def test_variant_recipe_blocks_pipeline_but_still_allows_editing_the_pixels(tmp_path):
    njr = _source(matrix_slot_values={"hair": "red"})
    assessment = assess_history_iterate(_entry(njr, result=_result(_image(tmp_path))))
    assert assessment.review.supported
    assert not assessment.pipeline.supported and "Matrix" in assessment.pipeline.reason


@pytest.mark.parametrize(
    ("make", "fragment"),
    [
        (
            lambda tmp: (make_pipeline_njr(stage_chain=(make_stage_config("svd_native"),)), None),
            "still-image",
        ),
        (
            lambda tmp: (
                make_pipeline_njr(stage_chain=(make_stage_config(), make_stage_config("img2img"))),
                None,
            ),
            "single-stage",
        ),
        (lambda tmp: (make_pipeline_njr(input_image_paths=("in.png",)), None), "source image"),
        (lambda tmp: (make_pipeline_njr(images_per_prompt=2), None), "Multi-image"),
        (lambda tmp: (make_pipeline_njr(variant_total=3), None), "multi-variant"),
        (
            lambda tmp: (make_pipeline_njr(extra_metadata={"batch_id": "b-1"}), None),
            "grouped batch",
        ),
    ],
)
def test_unsupported_shapes_block_both_choices_with_a_reason(tmp_path, make, fragment):
    njr, _ = make(tmp_path)
    assessment = assess_history_iterate(_entry(njr, result=_result(_image(tmp_path))))
    assert not assessment.any_supported
    assert (
        fragment in assessment.review.reason
        and assessment.review.reason == assessment.pipeline.reason
    )


def test_artifact_problems_block_both_choices(tmp_path):
    njr, image = _source(), _image(tmp_path)
    second = _image(tmp_path, "second.png")
    cases = {
        "video poster": {
            "video_bundle": {"primary_path": str(tmp_path / "clip.mp4")},
            "artifact": {"thumbnail_path": image},
        },
        "thumbnail only": {"artifact": {"artifact_type": "image", "thumbnail_path": image}},
        "multi image": {"artifact": {"artifact_type": "image", "output_paths": [image, second]}},
        "multi variant": {
            "artifact": {"primary_path": image},
            "variants": [{"artifact": {"primary_path": second}}],
        },
        "image count": {"artifact": {"primary_path": image}, "image_count": 4},
        "missing file": _result(str(tmp_path / "gone.png")),
        "no artifact": {"artifact": {}},
        "none": None,
    }
    for label, result in cases.items():
        assessment = assess_history_iterate(_entry(njr, result=result))
        assert not assessment.any_supported, label
        assert assessment.review.reason, label


def test_record_problems_are_visible_refusals_not_crashes(tmp_path):
    njr, image = _source(), _image(tmp_path)
    assert assess_history_iterate(None).review.reason
    assert (
        "completed"
        in assess_history_iterate(
            _entry(njr, result=_result(image), status=JobStatus.FAILED)
        ).review.reason
    )
    assert (
        "snapshot"
        in assess_history_iterate(_entry(njr, result=_result(image), snapshot=None)).review.reason
    )
    assert (
        "cannot be read"
        in assess_history_iterate(
            _entry(njr, result=_result(image), snapshot={"normalized_job": {"garbage": True}})
        ).review.reason
    )
    other = make_pipeline_njr(job_id="someone-else")
    mismatched = JobHistoryEntry(
        job_id=njr.job_id,
        created_at=datetime(2026, 10, 24),
        status=JobStatus.COMPLETED,
        result=_result(image),
        snapshot={"normalized_job": other.to_dict()},
    )
    assert "different job" in assess_history_iterate(mismatched).review.reason


def test_reasons_never_contain_prompt_text(tmp_path):
    njr = make_pipeline_njr(positive_prompt=SECRET, input_image_paths=("in.png",))
    assessment = assess_history_iterate(_entry(njr, result=_result(_image(tmp_path))))
    blob = " ".join(
        [assessment.review.reason, assessment.pipeline.reason, assessment.review.summary]
    )
    assert SECRET not in blob
