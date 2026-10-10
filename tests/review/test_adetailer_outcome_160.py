"""PR-REFINE-160: operator before/after judgments of an ADetailer output ride the existing Review feedback record."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState
from src.learning.learning_record import LearningRecordWriter
from src.pipeline.adetailer_effectiveness import VISUAL_OUTCOMES
from src.review import adetailer_outcome
from src.review.adetailer_outcome import (
    ATTRIBUTION,
    SCHEMA,
    build_review_context,
    load_effectiveness,
    normalize_outcome,
    resolve_adetailer_pair,
)
from src.review.review_metadata_service import ReviewMetadataService


def image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), (10, 20, 30)).save(path)
    return path


def with_metadata(monkeypatch, payload, status="ok"):
    monkeypatch.setattr(
        adetailer_outcome,
        "extract_embedded_metadata",
        lambda _p: SimpleNamespace(status=status, payload=payload),
    )


def adetailer_payload(source: Path, stage="adetailer"):
    return {"stage_manifest": {"stage": stage}, "artifact": {"input_image_path": str(source)}}


# ------------------------------------------------------------------------------------------------ source verification


def test_a_verified_adetailer_output_resolves_its_source(tmp_path, monkeypatch):
    source, output = image(tmp_path / "in.png"), image(tmp_path / "out.png")
    with_metadata(monkeypatch, adetailer_payload(source))
    pair = resolve_adetailer_pair(output)
    assert pair is not None and pair.source == source and pair.output == output


@pytest.mark.parametrize(
    "case", ["wrong_stage", "no_artifact", "missing_source", "same_file", "no_metadata", "none"]
)
def test_nothing_is_resolved_unless_the_source_is_verified(tmp_path, monkeypatch, case):
    source, output = image(tmp_path / "in.png"), image(tmp_path / "out.png")
    payload = adetailer_payload(source)
    status = "ok"
    target: Path | None = output
    if case == "wrong_stage":
        payload = adetailer_payload(source, stage="upscale")
    elif case == "no_artifact":
        payload = {"stage_manifest": {"stage": "adetailer"}}
    elif case == "missing_source":
        payload = adetailer_payload(tmp_path / "gone.png")
    elif case == "same_file":
        payload = adetailer_payload(output)
    elif case == "no_metadata":
        status = "missing"
    elif case == "none":
        target = None
    with_metadata(monkeypatch, payload, status)
    assert resolve_adetailer_pair(target) is None


# ------------------------------------------------------------------------------------------------ judgments


def pair_of(tmp_path, monkeypatch):
    source, output = image(tmp_path / "in.png"), image(tmp_path / "out.png")
    with_metadata(monkeypatch, adetailer_payload(source))
    return resolve_adetailer_pair(output)


def test_the_default_is_unreviewed_and_records_nothing(tmp_path, monkeypatch):
    pair = pair_of(tmp_path, monkeypatch)
    assert build_review_context(pair, face="Unreviewed", hands="unreviewed") is None
    assert (
        normalize_outcome("something else") == "unreviewed"
        and normalize_outcome(None) == "unreviewed"
    )
    assert VISUAL_OUTCOMES[0] == "unreviewed"


@pytest.mark.parametrize(
    ("face", "hands"),
    [("Improved", "Unchanged"), ("Worsened", "Uncertain"), ("Unreviewed", "Improved")],
)
def test_explicit_judgments_carry_region_attribution_and_provenance(
    tmp_path, monkeypatch, face, hands
):
    pair = pair_of(tmp_path, monkeypatch)
    context = build_review_context(pair, face=face, hands=hands, note="  checked at 200%  ")[
        "adetailer_outcome_review"
    ]
    assert (context["face"], context["hands"]) == (face.lower(), hands.lower())
    assert context["schema"] == SCHEMA and context["source"] == "operator_review"
    assert (
        context["attribution"] == ATTRIBUTION
        and "not a causal attribution" in context["attribution"]
    )
    assert context["reviewed_pair"] == {
        "input_image": str(pair.source),
        "output_image": str(pair.output),
    }
    assert context["note"] == "checked at 200%"
    assert not {"rating", "score", "weighted_score"} & set(context)  # no invented numeric quality


def test_a_judgment_is_never_attached_without_a_verified_pair():
    assert build_review_context(None, face="Improved", hands="Improved") is None


def test_missing_comparison_content_is_not_treated_as_unchanged(tmp_path, monkeypatch):
    source, output = image(tmp_path / "in.png"), image(tmp_path / "out.png")
    with_metadata(monkeypatch, adetailer_payload(source))
    source.unlink()
    assert resolve_adetailer_pair(output) is None  # no pair means no judgment, not "unchanged"


# ------------------------------------------------------------------------------------------------ persistence reuse


def controller(tmp_path):
    return LearningController(
        learning_state=LearningState(),
        pipeline_controller=object(),
        learning_record_writer=LearningRecordWriter(tmp_path / "learning_records.jsonl"),
    )


@pytest.mark.parametrize(
    ("face", "hands", "expected"),
    [("Improved", "Improved", "improved"), ("Worsened", "Unchanged", "worsened")],
)
def test_judgments_persist_through_the_existing_feedback_record_and_stamp(
    tmp_path, monkeypatch, face, hands, expected
):
    pair = pair_of(tmp_path, monkeypatch)
    context = build_review_context(pair, face=face, hands=hands)
    feedback = {
        "image_path": str(pair.output),
        "rating": 3,
        "quality_label": "okay",
        "notes": "",
        "base_prompt": "p",
        "after_prompt": "p",
        "context": context,
        "subscores": {"anatomy": 3, "composition": 3, "prompt_adherence": 3},
    }
    record = controller(tmp_path).save_review_feedback(feedback)
    assert (
        record.metadata["user_rating"] == 3
    )  # the overall rating is the operator's own, separate input
    saved = record.metadata["review_context"]["adetailer_outcome_review"]
    assert saved["face"] == expected
    assert saved["source"] == "operator_review"
    stamped = ReviewMetadataService().read_review_summary(pair.output)
    assert stamped is not None
    assert stamped.review_context["adetailer_outcome_review"]["reviewed_pair"][
        "input_image"
    ] == str(pair.source)


def test_a_review_without_a_judgment_keeps_the_existing_record_shape(tmp_path, monkeypatch):
    pair = pair_of(tmp_path, monkeypatch)
    record = controller(tmp_path).save_review_feedback(
        {
            "image_path": str(pair.output),
            "rating": 4,
            "quality_label": "good",
            "base_prompt": "p",
            "after_prompt": "p",
            "subscores": {"anatomy": 4, "composition": 4, "prompt_adherence": 4},
        }
    )
    assert "adetailer_outcome_review" not in record.metadata["review_context"]


def test_the_stage_effectiveness_record_is_found_beside_the_output_when_present(tmp_path):
    output = image(tmp_path / "run" / "adetailer_out.png")
    assert load_effectiveness(output) is None
    manifests = output.parent / "manifests"
    manifests.mkdir()
    (manifests / "adetailer_out.json").write_text(
        '{"adetailer_effectiveness": {"schema": "x"}}', encoding="utf-8"
    )
    assert load_effectiveness(output) == {"schema": "x"}
