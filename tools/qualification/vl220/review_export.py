"""Build ``eval/2`` cases and human labels from a Review export (``stablenew.vl240.review_export/1``, AI-VL-240).

The converter reads only the fields the contract needs and copies no other value: operator observation text, prompts, file
names, paths and interventions never reach the case or label document. Case and asset ids are derived from SHA-256 digests,
so they carry no name either. Both documents belong outside Git, next to the export (``__main__`` in ``vl242`` refuses a
destination inside the repository).

Rules, each with a stable refusal code (``ContractViolation.code``):

* ``provenance.labeler`` must be ``human`` (``labels_need_human_labeler``);
* a confirmed-clean image with findings is a contradiction (``clean_image_has_findings``);
* an image neither confirmed clean nor carrying a confirmed finding was not reviewed and is excluded (counted);
* ``Prompt adherence`` findings are dropped (a real case carries no prompt) and an image left with none is excluded (counted);
* a finding with a ``confirmation`` field counts only when it is ``Confirmed``;
* a pair's images must be listed in ``images`` and differ; its judgment is ``helped``, ``no_benefit``, ``worse`` or
  ``inconclusive``. Pairs are shown in alternating order (sorted by case id: before first, then after first, ...), so a model
  that always prefers one position scores at chance, and the labels, not the case, say which image is the corrected one.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.review.findings import Category
from tools.qualification.vl220 import eval2
from tools.qualification.vl220.contract import ContractViolation, digest

_EXPORT_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_CATEGORY_VALUES = frozenset(item.value for item in Category)
CONFIRMED = "Confirmed"
MAX_IMAGES = 1024
MAX_PAIRS = 256


def _fail(code: str, detail: str = "") -> ContractViolation:
    return ContractViolation(code, detail)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _mapping(value: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise _fail("not_an_object", what)
    return value


def _export_id(value: Any, what: str) -> str:
    if not isinstance(value, str) or _EXPORT_ID.fullmatch(value) is None:
        raise _fail("bad_export_identifier", what)
    return value


def _size(value: Any, what: str) -> int:
    if type(value) is not int or value <= 0:
        raise _fail("bad_image_size", what)
    return value


@dataclass(frozen=True, slots=True)
class _Image:
    image_id: str
    sha256: str
    width: int
    height: int
    clean_confirmed: bool
    findings: tuple[tuple[str, tuple[int, int, int, int] | None], ...]
    subject_count: int | None


def _region(value: Any, width: int, height: int) -> tuple[int, int, int, int] | None:
    if value is None:
        return None
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(type(edge) is not int for edge in value)
    ):
        raise _fail("bad_region")
    left, top, right, bottom = value
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise _fail("bad_region", "outside the image or empty")
    return left, top, right, bottom


def _image(raw: Any) -> _Image:
    item = _mapping(raw, "image")
    for key in ("image_id", "sha256", "width", "height", "clean_confirmed", "findings"):
        if key not in item:
            raise _fail("missing_keys", f"image: {key}")
    image_id = _export_id(item["image_id"], "image_id")
    if not isinstance(item["sha256"], str) or _HEX64.fullmatch(item["sha256"]) is None:
        raise _fail("bad_image_digest")
    width, height = _size(item["width"], "width"), _size(item["height"], "height")
    if not isinstance(item["clean_confirmed"], bool):
        raise _fail("bad_clean_confirmed")
    if not isinstance(item["findings"], list) or len(item["findings"]) > eval2.MAX_LABEL_FINDINGS:
        raise _fail("bad_findings")
    findings: list[tuple[str, tuple[int, int, int, int] | None]] = []
    for entry in item["findings"]:
        finding = _mapping(entry, "finding")
        if "confirmation" in finding and finding["confirmation"] != CONFIRMED:
            if not isinstance(finding["confirmation"], str):
                raise _fail("bad_confirmation")
            continue
        category = finding.get("category")
        if category not in _CATEGORY_VALUES:
            raise _fail("bad_category")
        findings.append((str(category), _region(finding.get("region"), width, height)))
    if item["clean_confirmed"] and findings:
        raise _fail("clean_image_has_findings")
    count = item.get("subject_count")
    if count is not None and (type(count) is not int or count < 0):
        raise _fail("bad_subject_count")
    return _Image(
        image_id, item["sha256"], width, height, item["clean_confirmed"], tuple(findings), count
    )


@dataclass(frozen=True, slots=True)
class Conversion:
    """The case document, the label document and content-free counts of what was kept and excluded."""

    cases: dict[str, Any]
    labels: dict[str, Any]
    summary: dict[str, Any]


def convert(export: Any) -> Conversion:
    """Validate a Review export and build the ``cases/2`` and ``labels/2`` documents. Pure; reads and writes no file."""

    data = _mapping(export, "export")
    for key in ("schema", "images", "pairs", "provenance"):
        if key not in data:
            raise _fail("missing_keys", f"export: {key}")
    if data["schema"] != eval2.EXPORT_SCHEMA:
        raise _fail("bad_schema", "export")
    if _mapping(data["provenance"], "provenance").get("labeler") != eval2.LABELER_HUMAN:
        raise _fail("labels_need_human_labeler")
    if not isinstance(data["images"], list) or not 1 <= len(data["images"]) <= MAX_IMAGES:
        raise _fail("bad_list", "images")
    if not isinstance(data["pairs"], list) or len(data["pairs"]) > MAX_PAIRS:
        raise _fail("bad_list", "pairs")
    images = [_image(raw) for raw in data["images"]]
    if len({image.image_id for image in images}) != len(images):
        raise _fail("duplicate_image")
    if len({image.sha256 for image in images}) != len(images):
        raise _fail("duplicate_image_digest")
    by_id = {image.image_id: image for image in images}
    export_sha256 = digest(data)
    set_id = f"vl242-{export_sha256[:12]}"

    assets: dict[str, dict[str, Any]] = {}

    def asset(image: _Image) -> str:
        asset_id = f"a.{image.sha256[:20]}"
        assets.setdefault(
            asset_id,
            {
                "asset_id": asset_id,
                "sha256": image.sha256,
                "width": image.width,
                "height": image.height,
            },
        )
        return asset_id

    cases: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "images_in_export": len(images), "image_cases": 0, "clean": 0, "defective": 0, "excluded_unreviewed": 0,
        "excluded_prompt_only": 0, "prompt_findings_dropped": 0, "unconfirmed_findings_ignored": 0,
        "findings": 0, "findings_without_region": 0, "subject_count_recorded": 0, "multi_subject": 0,
        "pairs_in_export": len(data["pairs"]), "pair_cases": 0, "judgments": dict.fromkeys(eval2.JUDGMENTS, 0),
    }  # fmt: skip
    summary["unconfirmed_findings_ignored"] = sum(
        1
        for raw in data["images"]
        for entry in raw["findings"]
        if isinstance(entry, dict)
        and "confirmation" in entry
        and entry["confirmation"] != CONFIRMED
    )
    for image in sorted(images, key=lambda item: item.sha256):
        visual = [
            (category, box)
            for category, box in image.findings
            if category not in eval2.EXCLUDED_CATEGORIES
        ]
        summary["prompt_findings_dropped"] += len(image.findings) - len(visual)
        if not image.clean_confirmed and not image.findings:
            summary["excluded_unreviewed"] += 1
            continue
        if not image.clean_confirmed and not visual:
            summary["excluded_prompt_only"] += 1
            continue
        case_id = f"img.{image.sha256[:20]}"
        cases.append({"case_id": case_id, "kind": eval2.KIND_IMAGE, "asset_ids": [asset(image)]})
        findings = [
            {
                "category": category,
                "zones": None
                if box is None
                else list(eval2.zones_of_box(box, image.width, image.height)),
            }
            for category, box in visual
        ]
        verdict = eval2.VERDICT_CLEAN if image.clean_confirmed else eval2.VERDICT_DEFECTIVE
        labels.append(
            {
                "case_id": case_id,
                "reference": {
                    "verdict": verdict,
                    "findings": findings,
                    "subject_count": image.subject_count,
                },
            }
        )
        summary["image_cases"] += 1
        summary[verdict] += 1
        summary["findings"] += len(findings)
        summary["findings_without_region"] += sum(1 for item in findings if item["zones"] is None)
        if image.subject_count is not None:
            summary["subject_count_recorded"] += 1
            summary["multi_subject"] += 1 if image.subject_count >= 2 else 0

    pair_rows: list[tuple[str, _Image, _Image, str]] = []
    seen_pairs: set[str] = set()
    for raw in data["pairs"]:
        item = _mapping(raw, "pair")
        for key in ("pair_id", "before_image_id", "after_image_id", "judgment"):
            if key not in item:
                raise _fail("missing_keys", f"pair: {key}")
        pair_id = _export_id(item["pair_id"], "pair_id")
        if pair_id in seen_pairs:
            raise _fail("duplicate_pair")
        seen_pairs.add(pair_id)
        before = by_id.get(_export_id(item["before_image_id"], "before_image_id"))
        after = by_id.get(_export_id(item["after_image_id"], "after_image_id"))
        if before is None or after is None:
            raise _fail("pair_image_not_exported")
        if before.sha256 == after.sha256:
            raise _fail("pair_images_identical")
        if item["judgment"] not in eval2.JUDGMENTS:
            raise _fail("bad_judgment")
        pair_rows.append((f"pair.{_sha(pair_id)[:20]}", before, after, str(item["judgment"])))
    for index, (case_id, before, after, judgment) in enumerate(
        sorted(pair_rows, key=lambda row: row[0])
    ):
        before_id, after_id = asset(before), asset(after)
        order = [before_id, after_id] if index % 2 == 0 else [after_id, before_id]
        cases.append({"case_id": case_id, "kind": eval2.KIND_PAIR, "asset_ids": order})
        labels.append(
            {"case_id": case_id, "reference": {"judgment": judgment, "after_asset_id": after_id}}
        )
        summary["pair_cases"] += 1
        summary["judgments"][judgment] += 1

    if not cases:
        raise _fail("nothing_to_evaluate")
    case_doc = {
        "schema": eval2.CASES_SCHEMA,
        "contract_id": eval2.CONTRACT_ID,
        "set_id": set_id,
        "export_sha256": export_sha256,
        "assets": sorted(assets.values(), key=lambda row: row["asset_id"]),
        "cases": cases,
    }
    label_doc = {
        "schema": eval2.LABELS_SCHEMA,
        "contract_id": eval2.CONTRACT_ID,
        "set_id": set_id,
        "labeler": eval2.LABELER_HUMAN,
        "export_sha256": export_sha256,
        "labels": labels,
    }
    # The output must satisfy the contract it was built for.
    case_set = eval2.validate_case_set(case_doc)
    eval2.validate_label_set(label_doc, case_set)
    summary["case_set_sha256"] = digest(case_doc)
    summary["label_set_sha256"] = digest(label_doc)
    summary["export_sha256"] = export_sha256
    return Conversion(case_doc, label_doc, summary)


__all__ = ["CONFIRMED", "Conversion", "convert"]
