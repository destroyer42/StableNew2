"""AI-VL-240: turn operator-confirmed Review evidence into one hash-manifested real-image evaluation export.

Only facts a person confirmed in Review are exported. An AI suggestion, an unconfirmed or rejected finding, a pixel-difference
measure and a rating are never labels. A record is used only when every image it names can be bound to the SHA-256 it
recorded; otherwise it is refused with a code. Prompt text, notes and file names are not exported: the export folder holds
images under their hash names and one JSON document.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.review.review_evidence import (
    INSPECTION_CLEARED,
    VERDICT_DEFECTS,
    VERDICT_NO_DEFECT,
    EvidenceIndex,
    InspectionRecord,
    InspectionRecordError,
    parse_inspection_row,
)
from tools.qualification.vl240 import contract
from tools.qualification.vl240.contract import Refused
from tools.qualification.vl240.sources import (
    ImageBinder,
    ImageFacts,
    JobFacts,
    JudgmentRecord,
    Region,
    claim_digest,
    guided_correction_jobs,
    job_with_paths,
    latest_per_job,
    open_repository,
    parse_region,
    read_judgment_records,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(slots=True)
class Finding:
    category: str
    region: Region | None
    record_id: str
    severity: str | None = None


@dataclass(slots=True)
class ImageEntry:
    sha256: str
    path: Path
    facts: ImageFacts
    findings: list[Finding] = field(default_factory=list)
    roles: set[str] = field(default_factory=set)
    records: set[str] = field(default_factory=set)
    #: True only from a saved ``no_defect_seen`` inspection of exactly these bytes.
    clean: bool = False
    subject_count: int | None = None
    #: Set when a clean mark and a confirmed finding exist for the same bytes: neither label is exported.
    conflict: bool = False


@dataclass(slots=True)
class PairEntry:
    before: str
    after: str
    judgment: str
    region_judgments: tuple[Any, ...]
    overall_preference: str | None
    intervention: dict[str, Any]
    learning_record_id: str
    job_id: str


@dataclass(slots=True)
class Collected:
    visibility_mode: str
    images: dict[str, ImageEntry] = field(default_factory=dict)
    pairs: list[PairEntry] = field(default_factory=list)
    refused: list[Refused] = field(default_factory=list)
    withheld: Counter[str] = field(default_factory=Counter)
    unparseable_lines: int = 0
    judgment_records: int = 0
    correction_jobs: int = 0
    #: Latest inspection row per image digest, by verdict (``cleared`` counts rows Undo wrote).
    inspections: Counter[str] = field(default_factory=Counter)


def _visible(facts: ImageFacts, mode: str) -> bool:
    from src.controller.content_visibility_resolver import ContentVisibilityResolver

    return bool(ContentVisibilityResolver(mode).decide(facts.subject).visible)


def _correction_finding(job: JobFacts, size: tuple[int, int] | None) -> tuple[str, Region | None]:
    correction = job.correction or {}
    category = correction.get("category")
    if category not in contract.CATEGORIES or correction.get("action") not in contract.ACTIONS:
        raise Refused("malformed_correction", job.job_id)
    try:
        region = parse_region(correction.get("region"), size)
    except Refused:
        raise Refused("malformed_correction", job.job_id) from None
    return str(category), region


def _intervention(job: JobFacts) -> dict[str, Any]:
    base: dict[str, Any] = {"kind": job.source_kind or "unrecorded", "stages": list(job.stages)}
    if job.correction is not None:
        base.update(
            kind="guided_correction",
            action=job.correction.get("action"),
            category=job.correction.get("category"),
            region=job.correction.get("region"),
        )
    return base


def _add_image(collected: Collected, digest: str, path: Any, facts: ImageFacts) -> ImageEntry:
    entry = collected.images.get(digest)
    if entry is None:
        entry = collected.images[digest] = ImageEntry(digest, path, facts)
    return entry


def collect(learning_records: Path, job_repository: Path, *, visibility_mode: str) -> Collected:
    """Read Review's records and the images they name. Opens everything read-only; writes nothing."""

    if visibility_mode not in contract.VISIBILITY_MODES:
        raise Refused("unknown_visibility_mode")
    collected = Collected(visibility_mode)
    with open_repository(job_repository) as connection:
        records, refused, bad = read_judgment_records(learning_records)
        collected.refused.extend(refused)
        collected.unparseable_lines = bad
        binder = ImageBinder()
        _findings_from_corrections(collected, connection, binder)
        _pairs_from_judgments(collected, connection, binder, latest_per_job(records))
        collected.judgment_records = len(records)
        _from_inspections(collected, EvidenceIndex.read(learning_records), binder)
        _flag_conflicts(collected)
    return collected


def _findings_from_corrections(collected: Collected, connection: Any, binder: ImageBinder) -> None:
    for job, own_paths in guided_correction_jobs(connection):
        collected.correction_jobs += 1
        try:
            digest = claim_digest(job.parent_artifact_id)
            parent = (
                job_with_paths(connection, job.parent_job_id, include_snapshot=False)
                if job.parent_job_id
                else None
            )
            path, facts = binder.bind(digest, [*own_paths, *(parent[1] if parent else [])])
            category, region = _correction_finding(job, (facts.width, facts.height))
        except Refused as exc:
            collected.refused.append(Refused(exc.code, exc.record_id or job.job_id))
            continue
        if not _visible(facts, collected.visibility_mode):
            collected.withheld["finding_image"] += 1
            continue
        entry = _add_image(collected, digest, path, facts)
        entry.records.add(job.job_id)
        _add_finding(entry, category, region, job.job_id, None)


def _add_finding(
    entry: ImageEntry, category: str, region: Region | None, record_id: str, severity: str | None
) -> None:
    """One finding per category and region; a severity the operator saved fills in one a correction did not carry."""

    for existing in entry.findings:
        if existing.category == category and existing.region == region:
            if existing.severity is None:
                existing.severity = severity
            return
    entry.findings.append(Finding(category, region, record_id, severity))


def _from_inspections(collected: Collected, index: EvidenceIndex, binder: ImageBinder) -> None:
    """The operator's saved inspections (the latest per digest): the only source of a clean mark, severity and count.

    A cleared row means "no inspection". A row whose bytes changed (or whose file is gone) is excluded and counted
    under its own code. Nothing here reads a prompt, a note or an observation: the record does not hold one.
    """

    for digest, payload in index.inspection_rows():
        record_id = str(payload.get("run_id") or "")[:80]
        try:
            record = parse_inspection_row(payload)
        except InspectionRecordError:
            collected.refused.append(Refused("malformed_inspection", record_id))
            continue
        if record.verdict == INSPECTION_CLEARED:
            collected.inspections[INSPECTION_CLEARED] += 1
            continue
        try:
            entry = collected.images.get(digest)
            if entry is None:
                path, facts = binder.bind(digest, [record.image_path])
            else:
                path, facts = entry.path, entry.facts
            findings = [
                (
                    item.category,
                    parse_region(
                        list(item.region) if item.region else None, (facts.width, facts.height)
                    ),
                    item.severity,
                )
                for item in record.findings
            ]
        except Refused as exc:
            code = {
                "image_changed_since_review": "inspection_image_changed_since_review",
                "image_unavailable": "inspection_image_unavailable",
            }.get(exc.code, "malformed_inspection")
            collected.refused.append(Refused(code, record_id))
            continue
        if not _visible(facts, collected.visibility_mode):
            collected.withheld["inspection_image"] += 1
            continue
        collected.inspections[record.verdict] += 1
        _apply_inspection(collected, digest, path, facts, record, findings)


def _apply_inspection(
    collected: Collected,
    digest: str,
    path: Path,
    facts: ImageFacts,
    record: InspectionRecord,
    findings: list[tuple[str, Region | None, str | None]],
) -> None:
    entry = _add_image(collected, digest, path, facts)
    entry.records.add(record.run_id)
    if record.verdict == VERDICT_NO_DEFECT:
        entry.clean = True
    elif record.verdict == VERDICT_DEFECTS:
        for category, region, severity in findings:
            _add_finding(entry, category, region, record.run_id, severity)
    if record.subject_count is not None:
        entry.subject_count = record.subject_count


def _flag_conflicts(collected: Collected) -> None:
    """A clean mark with a confirmed finding on the same bytes is a contradiction: reported, never resolved.

    The image keeps no label from either side. When it belongs to no judged pair there is nothing left to say
    about it, so it leaves the export.
    """

    for digest in sorted(collected.images):
        entry = collected.images[digest]
        if entry.clean and entry.findings:
            entry.conflict = True
            collected.refused.append(
                Refused("clean_contradicts_confirmed_finding", sorted(entry.records)[0])
            )
            if not entry.roles:
                del collected.images[digest]


def _pairs_from_judgments(
    collected: Collected, connection: Any, binder: ImageBinder, records: list[JudgmentRecord]
) -> None:
    for record in sorted(
        records, key=lambda item: (item.source_sha256, item.result_sha256, item.job_id)
    ):
        try:
            found = job_with_paths(connection, record.job_id, include_snapshot=True)
            if found is None:
                raise Refused("job_not_found", record.record_id)
            job, paths = found
            if job.correction is not None and job.parent_artifact_id:
                if claim_digest(job.parent_artifact_id) != record.source_sha256:
                    raise Refused("judgment_source_mismatch", record.record_id)
            parent = (
                job_with_paths(connection, job.parent_job_id, include_snapshot=False)
                if job.parent_job_id
                else None
            )
            before_path, before = binder.bind(
                record.source_sha256, [*paths, *(parent[1] if parent else [])]
            )
            after_path, after = binder.bind(record.result_sha256, paths)
            if before.sha256 == after.sha256:
                raise Refused("pair_is_one_image", record.record_id)
        except Refused as exc:
            collected.refused.append(Refused(exc.code, exc.record_id or record.record_id))
            continue
        if not (
            _visible(before, collected.visibility_mode)
            and _visible(after, collected.visibility_mode)
        ):
            collected.withheld["pair"] += 1
            continue
        outcomes = {item.judgment for item in record.judgments}
        for digest, path, facts, role in (
            (before.sha256, before_path, before, "before"),
            (after.sha256, after_path, after, "after"),
        ):
            entry = _add_image(collected, digest, path, facts)
            entry.roles.add(role)
            entry.records.add(record.record_id)
        collected.pairs.append(
            PairEntry(
                before.sha256,
                after.sha256,
                outcomes.pop() if len(outcomes) == 1 else "mixed",
                record.judgments,
                record.overall_preference,
                _intervention(job),
                record.record_id,
                record.job_id,
            )
        )


# --------------------------------------------------------------------------------------------------------- document


def _region(region: Region | None) -> list[int] | None:
    """``[left, top, right, bottom]``, half-open stored pixels (``Region.box``), or ``None`` for the whole image."""

    return None if region is None else list(region.box)


def build_document(collected: Collected, *, exported_at: datetime | None = None) -> dict[str, Any]:
    """The export document. Opaque ids are assigned in hash order, so the same evidence gives the same ids."""

    ids = {
        digest: f"img-{index:04d}" for index, digest in enumerate(sorted(collected.images), start=1)
    }
    images = []
    for digest in sorted(collected.images):
        entry = collected.images[digest]
        images.append(
            {
                "image_id": ids[digest],
                "sha256": digest,
                "file": f"{contract.IMAGE_DIR}/{digest}.{entry.facts.extension}",
                "width": entry.facts.width,
                "height": entry.facts.height,
                "model_family": None,
                "clean_confirmed": entry.clean and not entry.conflict,
                "findings": []
                if entry.conflict
                else [
                    {
                        "category": finding.category,
                        "region": _region(finding.region),
                        "severity": finding.severity,
                        "record_id": finding.record_id,
                    }
                    for finding in sorted(
                        entry.findings, key=lambda f: (f.category, f.region.box if f.region else ())
                    )
                ],
                "subject_count": entry.subject_count,
                "roles": sorted(entry.roles),
                "record_ids": sorted(entry.records),
            }
        )
    pairs: list[dict[str, Any]] = []
    mixed_pairs: list[dict[str, Any]] = []
    ordered = sorted(collected.pairs, key=lambda p: (p.before, p.after, p.job_id))
    for index, pair in enumerate(ordered, start=1):
        # ``pairs`` holds only a single human judgment; a pair whose regions disagree is kept apart, never forced into one.
        (mixed_pairs if pair.judgment == "mixed" else pairs).append(
            {
                "pair_id": f"pair-{index:04d}",
                "before_image_id": ids[pair.before],
                "after_image_id": ids[pair.after],
                "intervention": pair.intervention,
                "judgment": pair.judgment,
                "region_judgments": [
                    {
                        "category": item.category,
                        "region": _region(item.region),
                        "judgment": item.judgment,
                    }
                    for item in pair.region_judgments
                ],
                "overall_preference": pair.overall_preference,
                "record_ids": {"learning_record": pair.learning_record_id, "job": pair.job_id},
            }
        )
    when = (exported_at or datetime.now(UTC)).astimezone(UTC)
    return {
        "schema": contract.SCHEMA,
        "images": images,
        "pairs": pairs,
        "mixed_pairs": mixed_pairs,
        "provenance": {
            "labeler": "human",
            "basis": "operator-confirmed Review records only",
            "sources": ["learning_records", "job_repository"],
            "exported_at": when.isoformat(timespec="seconds"),
            "exporter_version": contract.EXPORTER_VERSION,
            "content_visibility_mode": collected.visibility_mode,
            "contains_prompt_text": False,
            "availability": dict(contract.AVAILABILITY),
        },
    }


def describe(collected: Collected, *, targets: str = "full") -> dict[str, Any]:
    """Counts by stratum and progress against the targets. No ids, paths or text."""

    document = build_document(collected)
    images = document["images"]
    defect = [item for item in images if item["findings"]]
    by_category = Counter(
        category
        for item in defect
        for category in {finding["category"] for finding in item["findings"]}
    )
    have: dict[str, int] = {
        "clean_confirmed_images": sum(1 for item in images if item["clean_confirmed"]),
        "defect_images": len(defect),
        "multi_subject_images": sum(1 for item in images if (item["subject_count"] or 0) >= 2),
        "judged_pairs": len(document["pairs"]),
    }
    for category, name in contract.CATEGORY_TARGET.items():
        have[name] = by_category.get(category, 0)
    progress = {}
    for name, spec in contract.TARGETS[targets].items():
        target = int(spec["target"])
        progress[name] = {
            "have": have[name],
            "target": target,
            "remaining": max(0, target - have[name]),
            "met": have[name] >= target,
            "recordable_in_review": bool(spec["recordable"]),
        }
    buckets = Counter(
        "5_or_more" if item["subject_count"] >= 5 else str(item["subject_count"])
        for item in images
        if item["subject_count"] is not None
    )
    return {
        "schema": contract.SCHEMA,
        "targets": targets,
        "content_visibility_mode": collected.visibility_mode,
        "counts": {
            "images": len(images),
            "clean_confirmed_images": have["clean_confirmed_images"],
            "inspections_by_verdict": {
                verdict: collected.inspections.get(verdict, 0)
                for verdict in (VERDICT_NO_DEFECT, VERDICT_DEFECTS, INSPECTION_CLEARED)
            },
            "images_with_subject_count": sum(buckets.values()),
            "subject_counts": {
                name: buckets.get(name, 0) for name in contract.SUBJECT_COUNT_BUCKETS
            },
            "findings_with_severity": sum(
                1 for item in images for finding in item["findings"] if finding["severity"]
            ),
            "pairs": len(document["pairs"]),
            "mixed_pairs": len(document["mixed_pairs"]),
            "defect_images_by_category": {c: by_category.get(c, 0) for c in contract.CATEGORIES},
            "pairs_by_judgment": {
                j: sum(
                    1 for p in (*document["pairs"], *document["mixed_pairs"]) if p["judgment"] == j
                )
                for j in contract.JUDGMENTS
            },
            "pairs_by_intervention": dict(
                sorted(
                    Counter(
                        str(p["intervention"].get("action") or p["intervention"]["kind"])
                        for p in (*document["pairs"], *document["mixed_pairs"])
                    ).items()
                )
            ),
            "corrected_jobs_seen": collected.correction_jobs,
            "judgment_records_seen": collected.judgment_records,
            "unparseable_judgment_lines": collected.unparseable_lines,
            "withheld_by_visibility": dict(sorted(collected.withheld.items())),
            "refused_by_reason": dict(
                sorted(Counter(item.code for item in collected.refused).items())
            ),
        },
        "progress": progress,
        "availability": dict(contract.AVAILABILITY),
    }


# ------------------------------------------------------------------------------------------------------------ write


def _inside_git(path: Path) -> bool:
    resolved = path.resolve()
    if resolved == _REPO_ROOT or _REPO_ROOT in resolved.parents:
        return True
    return any((parent / ".git").exists() for parent in (resolved, *resolved.parents))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_bytes((json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def write_export(
    collected: Collected, out_root: Path, *, link: bool = False, exported_at: datetime | None = None
) -> Path:
    """Write ``<out_root>/vl240-<UTC stamp>/`` with hash-named images, the document and the manifest."""

    if not collected.images:
        raise Refused("nothing_to_export")
    if _inside_git(out_root):
        raise Refused("output_inside_git")
    when = (exported_at or datetime.now(UTC)).astimezone(UTC)
    target = out_root / f"vl240-{when.strftime('%Y%m%dT%H%M%SZ')}"
    try:
        target.mkdir(parents=True, exist_ok=False)
        (target / contract.IMAGE_DIR).mkdir()
        files = []
        for digest in sorted(collected.images):
            entry = collected.images[digest]
            name = f"{digest}.{entry.facts.extension}"
            destination = target / contract.IMAGE_DIR / name
            linked = False
            if link:
                try:
                    os.link(entry.path, destination)
                    linked = True
                except OSError:
                    linked = False
            if not linked:
                shutil.copyfile(entry.path, destination)
            if _sha256_file(destination) != digest:
                destination.unlink()
                raise Refused("image_changed_during_export")
            files.append(
                {
                    "path": f"{contract.IMAGE_DIR}/{name}",
                    "sha256": digest,
                    "bytes": entry.facts.size_bytes,
                }
            )
        document_path = target / contract.DOCUMENT_NAME
        _write_json(document_path, build_document(collected, exported_at=when))
        _write_json(
            target / contract.MANIFEST_NAME,
            {
                "schema": contract.MANIFEST_SCHEMA,
                "document": {"path": contract.DOCUMENT_NAME, "sha256": _sha256_file(document_path)},
                "files": files,
            },
        )
    except OSError:
        raise Refused("output_unwritable") from None
    return target


def verify_export(folder: Path) -> dict[str, Any]:
    """Re-hash an export against its manifest. Reads only. Returns codes and counts, never names."""

    problems: Counter[str] = Counter()
    try:
        manifest = json.loads((folder / contract.MANIFEST_NAME).read_bytes())
        document = json.loads((folder / contract.DOCUMENT_NAME).read_bytes())
    except (OSError, ValueError):
        raise Refused("export_unreadable") from None
    if (
        manifest.get("schema") != contract.MANIFEST_SCHEMA
        or document.get("schema") != contract.SCHEMA
    ):
        raise Refused("export_schema_mismatch")
    declared = {item["path"]: item["sha256"] for item in manifest.get("files", [])}
    for path, digest in declared.items():
        try:
            if _sha256_file(folder / path) != digest or Path(path).stem != digest:
                problems["file_hash_mismatch"] += 1
        except OSError:
            problems["file_missing"] += 1
    try:
        if _sha256_file(folder / contract.DOCUMENT_NAME) != manifest["document"]["sha256"]:
            problems["document_hash_mismatch"] += 1
    except (OSError, KeyError, TypeError):
        problems["document_hash_mismatch"] += 1
    referenced = {image["file"]: image["sha256"] for image in document.get("images", [])}
    if referenced != declared:
        problems["manifest_does_not_match_document"] += 1
    return {"ok": not problems, "problems": dict(problems), "images": len(declared)}
