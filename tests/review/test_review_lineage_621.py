"""PR-REVIEW-LIFECYCLE-621: read-only lineage lookup, original-prompt baseline and prompt provenance.

Temporary SQLite and synthetic images; nothing is queued for real and no backend, model or GPU is touched.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from src.controller.content_visibility_resolver import REDACTED_TEXT, ContentVisibilityResolver
from src.queue.job_model import JobStatus
from src.review.effective_prompt import (
    BASELINE_NONE,
    NOT_RECORDED,
    format_provenance,
    project_effective_prompts,
    redact_view,
)
from src.review.review_lineage import (
    UNVERIFIED,
    VERIFIED,
    LineageSource,
    find_review_children,
    repository_of,
)
from src.utils.image_metadata import (
    BASELINE_AS_SENT,
    BASELINE_ORIGINAL,
    resolve_rework_baseline,
)
from tests.helpers.batch_ops_201 import admit, image_file, make_stack, review_njr, settle_fifo


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _child(job_id, batch_id, *, source=None, digest=None, parent_job=None):
    record = review_njr(job_id, batch_id, source=source, artifact_sha256=digest, source_count=1)
    if parent_job:
        record = replace(record, source=replace(record.source, parent_job_id=parent_job))
    return record


def _result(output: Path) -> dict:
    return {
        "success": True,
        "artifact": {
            "stage": "img2img",
            "artifact_type": "image",
            "primary_path": str(output),
            "output_paths": [str(output)],
        },
        "variants": [],
        "metadata": {},
    }


@pytest.fixture
def stack(tmp_path):
    return make_stack(tmp_path)


def test_verified_children_are_found_by_digest_with_outputs_and_batch(stack, tmp_path):
    source = image_file(tmp_path / "source.png", 1)
    output = image_file(tmp_path / "out" / "child.png", 2)
    admit(stack, [_child("child-1", "batch-a", source=source, digest=_digest(source))])
    settle_fifo(stack, result=_result(output))

    found = find_review_children(stack.repository, [LineageSource("k1", _digest(source), "")])

    (child,) = found.children_of("k1")
    assert child.relation == VERIFIED and child.verified
    assert child.status is JobStatus.COMPLETED
    assert child.batch_id == "batch-a"
    assert child.outputs == (str(output),)
    assert child.parent_artifact_id == f"sha256:{_digest(source)}"
    assert [c.job_id for c in found.of_batch("batch-a")] == ["child-1"]
    assert found.of_batch("other") == ()


def test_a_job_only_claim_is_labelled_unverified_and_a_foreign_digest_is_not_a_child(
    stack, tmp_path
):
    source = image_file(tmp_path / "source.png", 1)
    other = image_file(tmp_path / "other.png", 9)
    admit(
        stack,
        [
            _child("job-only", "b1", source=source, parent_job="parent-job"),
            _child("sibling", "b2", source=source, digest=_digest(other), parent_job="parent-job"),
        ],
    )

    found = find_review_children(
        stack.repository, [LineageSource("k1", _digest(source), "parent-job")]
    )

    assert [(c.job_id, c.relation) for c in found.children_of("k1")] == [("job-only", UNVERIFIED)]
    assert found.children_of("k1")[0].outputs == ()  # not finished: no outputs, and never guessed


def test_failed_and_queued_children_are_derived_from_the_repository_each_time(stack, tmp_path):
    source = image_file(tmp_path / "source.png", 1)
    digest = _digest(source)
    admit(stack, [_child("queued-1", "b1", source=source, digest=digest)])
    source_key = LineageSource("k1", digest, "")

    assert find_review_children(stack.repository, [source_key]).children_of("k1")[0].active

    settle_fifo(stack, {0: "failed"}, error="backend refused")
    (child,) = find_review_children(stack.repository, [source_key]).children_of("k1")
    assert child.status is JobStatus.FAILED and child.failure and not child.outputs

    # A restart is a new view of the same file: the same answer without any remembered state.
    reopened = stack.reopen()
    (again,) = find_review_children(reopened.repository, [source_key]).children_of("k1")
    assert (again.job_id, again.status) == ("queued-1", JobStatus.FAILED)


def test_missing_output_file_is_not_offered_and_no_repository_is_harmless(stack, tmp_path):
    source = image_file(tmp_path / "source.png", 1)
    admit(stack, [_child("c1", "b1", source=source, digest=_digest(source))])
    settle_fifo(stack, result=_result(tmp_path / "gone.png"))

    (child,) = find_review_children(
        stack.repository, [LineageSource("k", _digest(source), "")]
    ).children_of("k")
    assert child.outputs == ()
    assert find_review_children(None, [LineageSource("k", "ab" * 32, "")]).by_source == {}
    assert repository_of(object()) is None


def test_the_lineage_read_is_bounded_and_reports_truncation(stack, tmp_path):
    source = image_file(tmp_path / "source.png", 1)
    digest = _digest(source)
    admit(stack, [_child(f"c{i}", f"b{i}", source=source, digest=digest) for i in range(5)])

    found = find_review_children(stack.repository, [LineageSource("k", digest, "")], limit=3)

    assert len(found.children_of("k")) == 3 and found.truncated
    # A cut drops the OLDEST rows: the latest child decides a source's state, so it must survive.
    assert [child.job_id for child in found.children_of("k")] == ["c2", "c3", "c4"]
    rows = stack.repository.read_review_child_rows(
        parent_artifact_ids=[f"sha256:{digest}"], limit=2
    )
    assert [row.job_id for row in rows] == ["c3", "c4"]


# --- original-prompt baseline ---------------------------------------------------------------------------------------


def _payload(**stage):
    return {
        "generation": {"final_prompt": "gen final"},
        "stage_manifest": {"stage": "txt2img", **stage},
    }


def test_baseline_is_the_recorded_original_not_the_optimized_prompt():
    payload = _payload(prompt="optimized", final_prompt="optimized", original_prompt="authored")

    baseline = resolve_rework_baseline(payload)

    assert (baseline.prompt, baseline.prompt_basis) == ("authored", BASELINE_ORIGINAL)


def test_baseline_without_an_original_is_the_prompt_as_sent_and_says_so():
    baseline = resolve_rework_baseline(_payload(prompt="as sent", final_prompt="as sent"))

    assert (baseline.prompt, baseline.prompt_basis) == ("as sent", BASELINE_AS_SENT)
    assert resolve_rework_baseline(None).prompt == ""


def test_stage_original_wins_over_the_generation_original_and_negatives_resolve_alike():
    payload = {
        "generation": {
            "original_prompt": "generation original",
            "original_negative_prompt": "gen neg",
        },
        "stage_manifest": {
            "original_prompt": "stage original",
            "final_prompt": "optimized",
            "negative_prompt": "optimized neg",
        },
    }

    baseline = resolve_rework_baseline(payload)

    assert baseline.prompt == "stage original"
    assert (baseline.negative_prompt, baseline.negative_basis) == ("gen neg", BASELINE_ORIGINAL)


# --- prompt provenance ------------------------------------------------------------------------------------------------


def test_provenance_shows_each_stage_marks_missing_values_and_names_the_baseline():
    payload = {
        "stage": "adetailer",
        "stage_history": [
            {"stage": "txt2img", "original_prompt": "fox", "final_prompt": "fox, masterpiece"},
        ],
        "stage_manifest": {
            "stage": "adetailer",
            "original_prompt": "face",
            "final_prompt": "face, detailed",
        },
    }

    view = project_effective_prompts(payload)
    text = format_provenance(view)

    assert [stage.stage for stage in view.stages] == ["txt2img", "adetailer"]
    assert view.adetailer is not None and view.adetailer.final == "face, detailed"
    assert view.baseline_basis == BASELINE_ORIGINAL and "original prompt" in text
    assert "final:    fox, masterpiece" in text
    assert (
        NOT_RECORDED in text
    )  # the txt2img entry recorded no negative prompts... and the missing ones say so


def test_provenance_marks_adetailer_and_everything_else_not_recorded_when_absent():
    view = project_effective_prompts({"stage_manifest": {"stage": "txt2img"}})

    assert view.adetailer is None and view.baseline_basis == BASELINE_NONE
    text = format_provenance(view)
    assert "ADetailer: not recorded" in text and "no prompt was recorded" in text
    assert format_provenance(project_effective_prompts(None)).count("not recorded") >= 2


def test_provenance_is_redacted_in_sfw_mode_including_adetailer():
    payload = {
        "stage_manifest": {
            "stage": "adetailer",
            "original_prompt": "explicit nude scene",
            "final_prompt": "explicit nude scene, detailed",
        }
    }
    view = project_effective_prompts(payload)
    subject = {"positive_prompt": "explicit nude scene", "name": "x.png"}

    hidden = redact_view(view, ContentVisibilityResolver("sfw"), subject)
    shown = redact_view(view, ContentVisibilityResolver("nsfw"), subject)

    text = format_provenance(hidden)
    assert "nude" not in text and REDACTED_TEXT in text
    assert hidden.adetailer is not None and hidden.adetailer.final == REDACTED_TEXT
    assert "nude" in format_provenance(shown)
