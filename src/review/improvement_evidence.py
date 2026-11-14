"""Verify Review comparison evidence and prepare bounded judgments for the existing feedback writer."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.gui.controllers.history_compare_service import HistoryCompareService
from src.gui.view_contracts.history_comparison_artifact import verify_image
from src.gui_v2.history_compare_model import ComparisonRefused, recorded_job
from src.pipeline.adetailer_effectiveness import SCHEMA as EFFECTIVENESS_SCHEMA
from src.pipeline.adetailer_effectiveness import compare_images
from src.pipeline.image_edit_inputs import KEY as MASK_EDIT_KEY
from src.review.adetailer_outcome import normalize_outcome, resolve_adetailer_pair
from src.review.assist.identity import current_file_sha256
from src.review.findings import CORRECTION_KEY, MAX_FINDINGS, Category, FindingSource, Region
from src.review.inspection import inspect_source
from src.utils.image_metadata import ImageMetadataContractV26, read_image_metadata

OVERALL_PREFERENCES = (
    "unreviewed",
    "prefer original",
    "prefer result",
    "no preference",
    "uncertain",
)


@dataclass(frozen=True, slots=True)
class ImprovementPair:
    before: Path
    before_sha256: str
    after: FindingSource
    job_id: str
    verified: bool
    before_subject: Mapping[str, Any]
    after_subject: Mapping[str, Any]
    correction: Mapping[str, Any]
    summary: tuple[str, ...]
    before_bytes_subject: Mapping[str, Any]

    def require_current(self) -> None:
        if (
            current_file_sha256(self.before) != self.before_sha256
            or current_file_sha256(self.after.path) != self.after.identity.file_sha256
        ):
            raise ValueError("The comparison images changed. Reopen inspection before saving.")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _effectiveness(result: Mapping[str, Any]) -> Mapping[str, Any]:
    # Use the completed repository result. A neighboring file alone cannot attest to this job.
    for item in (result, *_variants(result)):
        record = _mapping(item.get("adetailer_effectiveness"))
        if record.get("schema") == EFFECTIVENESS_SCHEMA:
            return record
    return {}


def _variants(result: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    items = result.get("variants")
    return (_mapping(items[0]),) if isinstance(items, (list, tuple)) and len(items) == 1 else ()


def summarize(
    effectiveness: Mapping[str, Any],
    changed: Mapping[str, Any],
    *,
    requested: bool,
    experiment: bool,
) -> tuple[str, ...]:
    lines = [
        "Correction request recorded." if requested else "Guided correction request unavailable."
    ]
    if effectiveness:
        execution = _mapping(effectiveness.get("execution"))
        for key, label in (("face", "Face"), ("hands", "Hand")):
            row = _mapping(execution.get(key))
            requested_pass = row.get("requested_enabled")
            ack = row.get("acknowledged_by_extension")
            if requested_pass is True:
                outcome = (
                    "acknowledged by the backend"
                    if ack is True
                    else "acknowledgement unavailable"
                    if ack is None
                    else "no backend acknowledgement recorded"
                )
                lines.append(f"{label} pass requested · {outcome}.")
            elif requested_pass is False:
                lines.append(f"{label} pass off.")
        lines.append("Forge detection counts unknown. Individual pass effects were not measured.")
    else:
        lines.append("Backend settings acknowledgement unavailable.")
    if changed.get("status") == "measured" and type(changed.get("identical")) is bool:
        lines.append(
            "Observable pixels match." if changed["identical"] else "Observable pixels changed."
        )
    else:
        lines.append("Pixel comparison unavailable.")
    lines.append(
        "Learning experiment association recorded."
        if experiment
        else "Controlled experiment evidence unavailable."
    )
    return tuple(lines)


def resolve_improvement(repository: Any, after: FindingSource) -> ImprovementPair:
    """Resolve one completed result. Legacy ADetailer metadata can offer inspection with unverified lineage."""

    embedded = read_image_metadata(after.path).get(ImageMetadataContractV26.KEY_JOB_ID)
    if repository is None or not embedded:
        raise ComparisonRefused("A completed result with verifiable History identity is required.")
    job_id = str(embedded)
    entry = repository.get_job(job_id)
    job = recorded_job(entry, role="selected")
    result_image = verify_image(entry)
    if (
        job.job_id != job_id
        or Path(result_image.path).resolve() != after.path.resolve()
        or result_image.sha256 != after.identity.file_sha256
    ):
        raise ComparisonRefused("The selected image differs from the completed History result.")
    stages = job.njr.stage_chain_labels
    meta = job.njr.provenance.metadata
    correction = _mapping(meta.get(CORRECTION_KEY))
    if correction.get("schema") != "stablenew.guided-correction.v1":
        correction = {}
    result = _mapping(entry.result)
    before_subject: Mapping[str, Any] = {}
    after_subject = {
        "positive_prompt": job.njr.positive_prompt,
        "negative_prompt": job.njr.negative_prompt,
        "name": after.path.name,
    }
    verified = False
    before_sha = ""
    if job.njr.source.parent_job_id:
        pair = HistoryCompareService(repository).prepare(job_id)
        before = Path(pair.parent.image.path)
        before_sha = pair.parent.image.sha256
        before_subject, after_subject = (
            pair.parent.visibility_subject,
            pair.child.visibility_subject,
        )
        if pair.child.image.sha256 != after.identity.file_sha256:
            raise ComparisonRefused("The selected result changed during comparison.")
        verified = pair.parent_artifact_verified
    elif correction:
        # A guided edit of a local file has an artifact claim but no parent History job.
        frozen = _mapping(meta.get(MASK_EDIT_KEY))
        reprocess = _mapping(meta.get("reprocess"))
        items = reprocess.get("source_items")
        source_meta = (
            _mapping(_mapping(items[0]).get("metadata"))
            if isinstance(items, (tuple, list)) and len(items) == 1
            else {}
        )
        path = frozen.get("original_path") or source_meta.get("source_path")
        claim = job.njr.source.parent_artifact_id
        if not isinstance(path, str) or not path or not claim:
            raise ComparisonRefused("The correction did not record an exact source artifact.")
        before = Path(str(path))
        before_sha = current_file_sha256(before)
        if claim != f"sha256:{before_sha}":
            raise ComparisonRefused(
                "The source image bytes differ from the recorded correction input."
            )
        verified = True
    else:
        adetailer = resolve_adetailer_pair(after.path)
        recorded_inputs = {
            str(_mapping(item.get("artifact")).get("input_image_path") or "")
            for item in (result, *_variants(result))
        }
        if (
            adetailer is None
            or "adetailer" not in stages
            or str(adetailer.source) not in recorded_inputs
        ):
            raise ComparisonRefused("No direct before image was recorded for this result.")
        before = adetailer.source
        before_sha = current_file_sha256(before)

    if before.resolve() == after.path.resolve():
        raise ComparisonRefused("The before and after images refer to the same file.")
    loaded_before = inspect_source(before, after.revision)
    if loaded_before.source.identity.file_sha256 != before_sha:
        raise ComparisonRefused("The source changed during comparison.")
    if not before_subject:
        before_subject = loaded_before.subject
    effectiveness = _effectiveness(result) if "adetailer" in stages and verified else {}
    changed = compare_images(before, after.path) if verified else {}
    learning = job.njr.learning_context
    summary = summarize(
        effectiveness,
        changed,
        requested=bool(correction or effectiveness),
        experiment=bool(learning and learning.experiment_id),
    )
    if not result_image.historical_hash:
        summary += (
            "Result bytes were checked for this viewing. History has no original output digest.",
        )
    proof = ImprovementPair(
        before,
        before_sha,
        after,
        job_id,
        verified,
        before_subject,
        after_subject,
        correction,
        summary,
        loaded_before.subject,
    )
    proof.require_current()
    return proof


def build_improvement_context(
    pair: ImprovementPair,
    observations: tuple[tuple[Category, Region | None, str], ...],
    preference: str = "unreviewed",
) -> dict[str, Any]:
    if not pair.verified:
        raise ValueError("A verified before/after source is required for region feedback.")
    if preference not in OVERALL_PREFERENCES:
        raise ValueError("Choose a supported overall preference.")
    if len(observations) > MAX_FINDINGS:
        raise ValueError("Too many region judgments.")
    rows = []
    for category, region, judgment in observations:
        if not isinstance(category, Category):
            raise ValueError("Choose a supported region category.")
        if region is not None:
            region.validate(pair.after.identity.size)
        outcome = normalize_outcome(judgment)
        if outcome != "unreviewed":
            rows.append(
                {
                    "category": category.value,
                    "after_region": list(region.box) if region else None,
                    "outcome": outcome,
                }
            )
    if not rows:
        raise ValueError("Choose a region judgment before saving.")
    return {
        "guided_improvement_review": {
            "schema": "stablenew.guided-improvement-review.v1",
            "source": "operator_review",
            "source_sha256": pair.before_sha256,
            "result_sha256": pair.after.identity.file_sha256,
            "result_job_id": pair.job_id,
            "region_coordinate_space": "stored result pixels",
            "result_size": list(pair.after.identity.size),
            "judgments": rows,
            "overall_preference": preference,
        }
    }
