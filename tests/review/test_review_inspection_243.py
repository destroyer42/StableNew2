"""AI-VL-243: the ``review_inspection`` evidence record, its readers and the severity on ``Finding``.

Deterministic: temporary roots and synthetic images only; no GUI, network, WebUI, model or GPU.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState
from src.gui.view_contracts.review_workspace_contract import (
    ItemFacts,
    ItemState,
    collect_facts,
    derive_state,
    item_key,
)
from src.learning.learning_record import LearningRecordWriter
from src.review import review_evidence as evidence
from src.review.assist.contracts import SourceIdentity
from src.review.findings import (
    Category,
    Certainty,
    Confirmation,
    Finding,
    FindingSource,
    Origin,
    Region,
    Severity,
    correction_context,
)

OBSERVATION = "zz private observation words zz"
SIZE = (32, 24)


def _image(path: Path, color=(10, 20, 30)) -> Path:
    Image.new("RGB", SIZE, color).save(path)
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(path: Path) -> FindingSource:
    identity = SourceIdentity(_digest(path), path.stat().st_size, SIZE[0], SIZE[1], 1, "PNG")
    return FindingSource(path, identity, (1, 1))


def _finding(
    path: Path,
    category=Category.HANDS,
    region: Region | None = Region(2, 2, 10, 10),
    *,
    confirmation=Confirmation.CONFIRMED,
    severity: Severity | None = None,
    origin=Origin.OPERATOR,
    certainty=Certainty.CLEAR,
) -> Finding:
    return Finding(
        _source(path),
        region,
        category,
        origin,
        OBSERVATION,
        certainty,
        confirmation,
        suggestion_label="Some model · Unqualified suggestion",
        severity=severity,
    )


@pytest.fixture
def writer(tmp_path: Path) -> LearningRecordWriter:
    return LearningRecordWriter(tmp_path / "records.jsonl")


@pytest.fixture
def image(tmp_path: Path) -> Path:
    return _image(tmp_path / "a.png")


def _rows(writer: LearningRecordWriter) -> list[dict]:
    return [json.loads(line) for line in writer.records_path.read_text("utf-8").splitlines()]


# -------------------------------------------------------------------------------------------------- record and vocabulary


def test_defects_record_is_closed_vocabulary_bound_to_the_bytes(writer, image):
    findings = [
        _finding(image, Category.HANDS, Region(2, 2, 10, 10), severity=Severity.MAJOR),
        _finding(image, Category.FACE, None, certainty=Certainty.TENTATIVE),
    ]
    record = evidence.save_inspection(
        writer,
        image_path=image,
        verdict=evidence.VERDICT_DEFECTS,
        findings=findings,
        subject_count=3,
        image_size=SIZE,
    )
    (row,) = _rows(writer)
    metadata = row["metadata"]
    assert metadata["source"] == "review_tab_inspection" == evidence.INSPECTION_SOURCE
    assert metadata["record_kind"] == "review_inspection"
    assert metadata["artifact_sha256"] == _digest(image)
    assert metadata["inspection_schema"] == "stablenew.review-inspection"
    assert metadata["inspection_schema_version"] == 1
    assert metadata["verdict"] == "defects_confirmed"
    assert metadata["subject_count"] == 3
    assert metadata["reviewed_at"]
    assert metadata["findings"] == [
        {
            "category": "Hands",
            "region": [2, 2, 10, 10],
            "certainty": "Clear to the operator",
            "severity": "major",
        },
        {"category": "Face", "region": None, "certainty": "Tentative", "severity": None},
    ]
    # no observation text, origin or suggestion label anywhere in the stored row
    text = writer.records_path.read_text("utf-8")
    assert OBSERVATION not in text and "Unqualified" not in text and "Some model" not in text
    assert "Operator observation" not in text
    assert record.metadata == metadata


def test_clean_record_and_subject_count_not_recorded(writer, image):
    evidence.save_inspection(writer, image_path=image, verdict=evidence.VERDICT_NO_DEFECT)
    metadata = _rows(writer)[0]["metadata"]
    assert metadata["verdict"] == "no_defect_seen"
    assert metadata["findings"] == [] and metadata["subject_count"] is None


@pytest.mark.parametrize(
    ("verdict", "findings", "count", "message"),
    [
        ("no_defect_seen", "one", None, "cannot carry findings"),
        ("defects_confirmed", "none", None, "at least one finding"),
        ("defects_confirmed", "unreviewed", None, "you confirmed"),
        ("defects_confirmed", "uncertain", None, "you confirmed"),
        ("defects_confirmed", "rejected", None, "you confirmed"),
        ("defects_confirmed", "one", 0, "whole number"),
        ("defects_confirmed", "one", 13, "whole number"),
        ("defects_confirmed", "one", True, "whole number"),
        ("defects_confirmed", "one", "3", "whole number"),
        ("cleared", "none", None, "verdict must be one of"),
        ("", "none", None, "verdict must be one of"),
    ],
)
def test_invalid_requests_are_refused_and_nothing_is_written(
    writer, image, verdict, findings, count, message
):
    given = {
        "none": [],
        "one": [_finding(image)],
        "unreviewed": [_finding(image, confirmation=Confirmation.UNREVIEWED)],
        "uncertain": [_finding(image, confirmation=Confirmation.UNCERTAIN)],
        "rejected": [_finding(image, confirmation=Confirmation.REJECTED)],
    }[findings]
    with pytest.raises(ValueError, match=message):
        evidence.save_inspection(
            writer, image_path=image, verdict=verdict, findings=given, subject_count=count
        )
    assert not writer.records_path.exists()


def test_subject_count_bounds_are_one_to_twelve(writer, image):
    for count in (1, 12):
        evidence.save_inspection(
            writer, image_path=image, verdict="no_defect_seen", subject_count=count
        )
    assert [row["metadata"]["subject_count"] for row in _rows(writer)] == [1, 12]


def test_confirmed_suggestion_origin_is_stored_without_its_label(writer, image):
    suggested = _finding(image, Category.GENERAL, None, origin=Origin.MODEL)
    evidence.save_inspection(
        writer, image_path=image, verdict="defects_confirmed", findings=[suggested]
    )
    assert "Unqualified" not in writer.records_path.read_text("utf-8")
    assert "External model suggestion" not in writer.records_path.read_text("utf-8")


def test_region_outside_the_image_is_refused_and_duplicates_collapse(writer, image):
    outside = _finding(image, region=Region(2, 2, 10, 10))
    with pytest.raises(ValueError):
        evidence.build_inspection_record(
            image_path=image, verdict="defects_confirmed", findings=[outside], image_size=(8, 8)
        )
    twice = [_finding(image), _finding(image, certainty=Certainty.UNKNOWN)]
    record = evidence.build_inspection_record(
        image_path=image, verdict="defects_confirmed", findings=twice, image_size=SIZE
    )
    assert len(record.metadata["findings"]) == 1


def test_unreadable_image_without_a_digest_is_refused(writer, tmp_path):
    with pytest.raises(ValueError, match="could not be read"):
        evidence.build_inspection_record(
            image_path=tmp_path / "missing.png", verdict="no_defect_seen"
        )


# -------------------------------------------------------------------------------------------------- reading and identity


def test_parse_refuses_free_text_and_unknown_vocabulary(writer, image):
    evidence.save_inspection(
        writer, image_path=image, verdict="defects_confirmed", findings=[_finding(image)]
    )
    good = _rows(writer)[0]
    assert evidence.parse_inspection_row(good).findings[0].category == "Hands"

    def mutated(mutate):
        row = json.loads(json.dumps(good))
        mutate(row["metadata"])
        return row

    cases = [
        lambda m: m["findings"][0].update(observation=OBSERVATION),
        lambda m: m["findings"][0].update(category="Eyebrows"),
        lambda m: m["findings"][0].update(certainty="Sure"),
        lambda m: m["findings"][0].update(severity="critical"),
        lambda m: m["findings"][0].update(region=[0, 0, 5]),
        lambda m: m["findings"][0].update(region=[4, 0, 2, 5]),
        lambda m: m.update(verdict="no_defect_seen"),
        lambda m: m.update(findings=[]),
        lambda m: m.update(verdict="looks_fine"),
        lambda m: m.update(subject_count=40),
        lambda m: m.update(artifact_sha256="nope"),
        lambda m: m.update(inspection_schema_version=2),
    ]
    for mutate in cases:
        with pytest.raises(evidence.InspectionRecordError):
            evidence.parse_inspection_row(mutated(mutate))


def test_latest_wins_and_undo_writes_a_cleared_row(writer, image):
    evidence.save_inspection(writer, image_path=image, verdict="no_defect_seen", subject_count=2)
    first = evidence.lookup_inspection(writer.records_path, image, _digest(image))
    assert first.verdict == "no_defect_seen" and first.identity == "digest"
    assert first.record is not None and first.record.subject_count == 2
    evidence.save_inspection(
        writer, image_path=image, verdict="defects_confirmed", findings=[_finding(image)]
    )
    second = evidence.lookup_inspection(writer.records_path, image, _digest(image))
    assert second.verdict == "defects_confirmed" and second.record.subject_count is None
    evidence.clear_inspection(writer, image_path=image, artifact_sha256=_digest(image))
    cleared = evidence.lookup_inspection(writer.records_path, image, _digest(image))
    assert cleared.record is None and cleared.verdict == "" and not cleared.malformed
    rows = _rows(writer)
    assert [row["metadata"]["verdict"] for row in rows] == [
        "no_defect_seen",
        "defects_confirmed",
        "cleared",
    ]  # nothing was deleted or rewritten
    assert (
        evidence.EvidenceIndex.read(writer.records_path).inspection(image, _digest(image)).verdict
        == ""
    )


def test_changed_bytes_are_reported_changed_and_never_applied(writer, image):
    evidence.save_inspection(writer, image_path=image, verdict="no_defect_seen")
    old = _digest(image)
    _image(image, (200, 1, 1))  # the file at the same path now has different bytes
    new = _digest(image)
    assert new != old
    by_path = evidence.lookup_inspection(writer.records_path, image, new)
    assert by_path.identity == "changed" and by_path.record is None and by_path.verdict == ""
    index = evidence.EvidenceIndex.read(writer.records_path)
    assert index.inspection(image, new).identity == "changed"
    assert index.inspection(image, new).verdict == ""
    # the same old bytes under another name still match by digest
    copy = image.with_name("copy.png")
    copy.write_bytes(b"")
    assert evidence.lookup_inspection(writer.records_path, copy, old).verdict == "no_defect_seen"


def test_a_malformed_latest_row_is_not_replaced_by_an_earlier_one(writer, image):
    evidence.save_inspection(writer, image_path=image, verdict="no_defect_seen")
    row = _rows(writer)[0]
    row["run_id"] = "bad"
    row["metadata"]["verdict"] = "maybe"
    with writer.records_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")
    found = evidence.lookup_inspection(writer.records_path, image, _digest(image))
    assert found.malformed and found.record is None


# -------------------------------------------------------------------------- existing behavior is untouched


def test_rating_disposition_and_undo_never_see_an_inspection(writer, image, tmp_path):
    controller = LearningController(
        LearningState(), pipeline_controller=object(), learning_record_writer=writer
    )
    controller.refresh_recommendations = Mock()  # type: ignore[method-assign]
    controller.save_review_feedback(
        {"image_path": str(image), "rating": 4, "base_prompt": "p", "after_prompt": "p"}
    )
    evidence.save_disposition(writer, image_path=image, disposition="retain")
    evidence.save_inspection(writer, image_path=image, verdict="no_defect_seen")
    digest = _digest(image)
    assert (
        evidence.lookup_rating(writer.records_path, image, digest).row["metadata"][
            "user_rating_raw"
        ]
        == 4
    )
    assert evidence.lookup_disposition(writer.records_path, image, digest).disposition == "retain"
    assert [row["image_path"] for row in controller.list_recent_review_feedback()] == [str(image)]
    # "Undo Last Save" for a rating removes the rating row and leaves the inspection and disposition
    assert controller.undo_review_feedback(image_path=str(image)) is True
    assert controller.undo_review_feedback(image_path=str(image)) is False
    assert [row["metadata"]["source"] for row in _rows(writer)] == [
        "review_tab_disposition",
        "review_tab_inspection",
    ]
    assert (
        evidence.lookup_inspection(writer.records_path, image, digest).verdict == "no_defect_seen"
    )
    # an inspection is neither a rating nor a disposition
    index = evidence.EvidenceIndex.read(writer.records_path)
    assert index.rating(image, digest).row is None
    assert index.disposition(image, digest).disposition == "retain"


def test_workspace_state_ignores_the_inspection_and_the_row_shows_the_verdict_only(writer, image):
    evidence.save_inspection(
        writer, image_path=image, verdict="defects_confirmed", findings=[_finding(image)]
    )
    facts = collect_facts([image], records_path=writer.records_path, repository=None)
    item = facts.items[item_key(image)]
    assert item.inspection == "defects_confirmed"
    assert derive_state(item) is ItemState.TO_REVIEW  # an inspection is not a decision
    assert derive_state(replace(item, inspection="")) is ItemState.TO_REVIEW
    assert ItemFacts().inspection == ""
    _image(image, (9, 9, 9))
    changed = collect_facts([image], records_path=writer.records_path, repository=None)
    assert changed.items[item_key(image)].inspection == ""  # changed bytes: never applied


# ------------------------------------------------------------------------------------------------------ severity


def test_finding_without_severity_is_unchanged(image):
    plain = _finding(image)
    assert plain.severity is None
    positional = Finding(
        _source(image),
        Region(2, 2, 10, 10),
        Category.HANDS,
        Origin.OPERATOR,
        OBSERVATION,
        Certainty.CLEAR,
        Confirmation.CONFIRMED,
        suggestion_label="Some model · Unqualified suggestion",
    )
    assert positional == plain
    # the provenance a queued correction freezes does not mention severity
    context = correction_context(plain.source, plain.category, plain.region, _action())
    assert set(context) == {"schema", "action", "category", "region", "source_size"}
    assert replace(plain, severity=Severity.MINOR).severity is Severity.MINOR


def _action():
    from src.review.findings import Action

    return Action.MASK


def test_severity_is_closed_and_optional(image):
    assert [item.value for item in Severity] == ["minor", "major"]
    with pytest.raises(ValueError):
        Finding(
            _source(image),
            None,
            Category.FACE,
            Origin.OPERATOR,
            "x",
            severity="severe",  # type: ignore[arg-type]
        )
