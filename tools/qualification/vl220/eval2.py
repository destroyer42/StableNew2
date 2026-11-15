"""The real-image evaluation contract ``stablenew.vl220.eval/2`` (PR-AI-VL-242): cases, human labels, closed answers, evidence.

``eval/1`` (``contract.py``) stays exactly as it was; it is the synthetic wiring contract. ``eval/2`` is for the owner's own
generated images, labelled by a person in Review and exported by AI-VL-240. It differs from ``eval/1`` in four ways:

* the defect vocabulary is Review's own finding taxonomy, imported from ``src.review.findings`` (read-only), so the evaluation
  measures what the product would show; ``Prompt adherence`` is left out because a real case carries no prompt;
* every answer field is required and every value is a closed enum (no free text anywhere, not even in a refusal), the
  image-level verdict is explicit and the schema ties it to the findings list (``clean`` has none, ``defective`` has 1..6);
* cases and labels are built from a ``stablenew.vl240.review_export/1`` document (``review_export.py``) and labels are refused
  unless the labeler is human;
* the only per-case record a real run may persist is :func:`evidence_record`: status, reason code, time, memory and the closed
  structured answer. It never carries answer text, prompts, paths or image bytes, and :func:`validate_evidence` refuses any
  evidence file that does.

The gate values a run is judged by are data here (:data:`GATES`), fixed before any run; changing one needs a new contract
version. This module runs nothing and starts no process.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.review.findings import Category
from tools.qualification.vl220.contract import ContractViolation, canonical_json, digest

CONTRACT_ID = "stablenew.vl220.eval/2"
CASES_SCHEMA = "stablenew.vl220.cases/2"
LABELS_SCHEMA = "stablenew.vl220.labels/2"
RESPONSE_SCHEMA = "stablenew.vl220.response/2"
EVIDENCE_SCHEMA = "stablenew.vl220.evidence/2"
EXPORT_SCHEMA = "stablenew.vl240.review_export/1"
GATE_SET_ID = "stablenew.vl242.gates/1"
GATE_STATUS = "proposed_pending_owner_approval"

KIND_IMAGE = "image_review"
KIND_PAIR = "pair_review"
KINDS: tuple[str, ...] = (KIND_IMAGE, KIND_PAIR)

TIER_FAST = "fast"
TIER_DEEP = "deep"
TIERS: tuple[str, ...] = (TIER_FAST, TIER_DEEP)

# ----------------------------------------------------------------------------------------------------- vocabularies

#: Review's categories a model can judge from pixels alone. ``Prompt adherence`` needs the prompt, which a real case does not
#: carry (the owner's prompts stay private), so it is excluded here and from the labels, never guessed.
EXCLUDED_CATEGORIES: tuple[str, ...] = (Category.PROMPT.value,)
CATEGORIES: tuple[str, ...] = tuple(
    item.value for item in Category if item.value not in EXCLUDED_CATEGORIES
)

#: A 3 x 3 grid over the image, row-major, plus the whole image. A model cannot reliably answer pixel boxes; a coarse closed
#: zone can be decoded by grammar and compared with the human rectangle (:func:`zones_of_box`).
ZONES: tuple[str, ...] = (
    "top_left", "top", "top_right", "left", "center", "right", "bottom_left", "bottom", "bottom_right",
)  # fmt: skip
WHOLE_IMAGE = "whole_image"
REGIONS: tuple[str, ...] = (*ZONES, WHOLE_IMAGE)
#: A human box occupies a zone when the zone holds at least this share of the box's area (the centre zone always counts).
ZONE_MIN_SHARE = 0.10
#: ``whole_image`` matches a human finding with no recorded region, or one whose box occupies at least this many zones.
WHOLE_IMAGE_MIN_ZONES = 6

VERDICT_CLEAN = "clean"
VERDICT_DEFECTIVE = "defective"
VERDICTS: tuple[str, ...] = (VERDICT_CLEAN, VERDICT_DEFECTIVE)

SUBJECT_COUNTS: tuple[str, ...] = ("0", "1", "2", "3", "4", "5_or_more")

PAIR_FIRST = "first_better"
PAIR_NONE = "no_clear_difference"
PAIR_SECOND = "second_better"
PAIR_ANSWERS: tuple[str, ...] = (PAIR_FIRST, PAIR_NONE, PAIR_SECOND)

JUDGMENT_HELPED = "helped"
JUDGMENT_NO_BENEFIT = "no_benefit"
JUDGMENT_WORSE = "worse"
JUDGMENT_INCONCLUSIVE = "inconclusive"
JUDGMENTS: tuple[str, ...] = (
    JUDGMENT_HELPED,
    JUDGMENT_NO_BENEFIT,
    JUDGMENT_WORSE,
    JUDGMENT_INCONCLUSIVE,
)

REFUSALS: tuple[str, ...] = ("image_unreadable", "declined")

MAX_ANSWER_FINDINGS = 6
MAX_LABEL_FINDINGS = 24
MAX_CASES = 512
MAX_RESPONSE_BYTES = 4 * 1024

LABELER_HUMAN = "human"

# Per-case run status, the same tokens ``driver.py`` uses for ``evidence/1``.
STATUS_VALID = "valid"
STATUS_MODEL_REFUSED = "model_refused"
STATUS_INVALID = "invalid"
RUN_STATUSES: tuple[str, ...] = (
    STATUS_VALID, STATUS_MODEL_REFUSED, STATUS_INVALID, "not_run", "timeout", "cancelled", "output_too_large",
    "child_exit_nonzero", "launch_failed",
)  # fmt: skip

_ID = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_CODE = re.compile(r"[a-z0-9_]{0,64}")


def _fail(code: str, detail: str = "") -> ContractViolation:
    return ContractViolation(code, detail)


def _exact(document: Any, allowed: frozenset[str], what: str) -> Mapping[str, Any]:
    if not isinstance(document, dict):
        raise _fail("not_an_object", what)
    unknown = set(document) - allowed
    if unknown:
        raise _fail("unknown_keys", f"{what}: {sorted(unknown)}")
    missing = allowed - set(document)
    if missing:
        raise _fail("missing_keys", f"{what}: {sorted(missing)}")
    return document


def _list(value: Any, what: str, low: int, high: int) -> list[Any]:
    if not isinstance(value, list) or not low <= len(value) <= high:
        raise _fail("bad_list", what)
    return value


def _identifier(value: Any, what: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise _fail("bad_identifier", what)
    return value


def _positive_int(value: Any, what: str) -> int:
    if type(value) is not int or value <= 0:
        raise _fail("bad_integer", what)
    return value


# ------------------------------------------------------------------------------------------------------------- zones


def zones_of_box(box: Sequence[int], width: int, height: int) -> tuple[str, ...]:
    """The grid zones a half-open pixel box ``(left, top, right, bottom)`` occupies, in :data:`ZONES` order.

    A zone counts when it holds at least :data:`ZONE_MIN_SHARE` of the box's area; the zone holding the box's centre always
    counts, so a tiny box has exactly one zone."""

    left, top, right, bottom = box
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise _fail("bad_region", "box outside the image or empty")
    area = (right - left) * (bottom - top)
    xs = (0.0, width / 3, 2 * width / 3, float(width))
    ys = (0.0, height / 3, 2 * height / 3, float(height))
    cx, cy = (left + right) / 2, (top + bottom) / 2
    found: list[str] = []
    for row in range(3):
        for col in range(3):
            dx = max(0.0, min(right, xs[col + 1]) - max(left, xs[col]))
            dy = max(0.0, min(bottom, ys[row + 1]) - max(top, ys[row]))
            holds_centre = (xs[col] <= cx < xs[col + 1] or (col == 2 and cx == xs[3])) and (
                ys[row] <= cy < ys[row + 1] or (row == 2 and cy == ys[3])
            )
            if holds_centre or dx * dy >= ZONE_MIN_SHARE * area:
                found.append(ZONES[row * 3 + col])
    return tuple(found)


def region_matches(answer_region: str, human_zones: Sequence[str] | None) -> bool:
    """Whether a model's region is compatible with a human finding's zones (``None``: the human recorded no region)."""

    if human_zones is None:
        return True
    if answer_region == WHOLE_IMAGE:
        return len(human_zones) >= WHOLE_IMAGE_MIN_ZONES
    return answer_region in human_zones


# ------------------------------------------------------------------------------------------------------------- cases


@dataclass(frozen=True, slots=True)
class Asset:
    asset_id: str
    sha256: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class Case:
    case_id: str
    kind: str
    #: Presentation order. A pair case does not say which image is the corrected one; the labels do.
    asset_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CaseSet:
    set_id: str
    export_sha256: str
    assets: tuple[Asset, ...]
    cases: tuple[Case, ...]

    def case(self, case_id: str) -> Case:
        for item in self.cases:
            if item.case_id == case_id:
                return item
        raise KeyError(case_id)

    def asset(self, asset_id: str) -> Asset:
        for item in self.assets:
            if item.asset_id == asset_id:
                return item
        raise KeyError(asset_id)


def validate_case_set(document: Any) -> CaseSet:
    """Parse a ``cases/2`` document. Cases carry ids, kinds and pinned assets only: no prompt, no label, no text."""

    data = _exact(
        document,
        frozenset({"schema", "set_id", "contract_id", "export_sha256", "assets", "cases"}),
        "case set",
    )
    if data["schema"] != CASES_SCHEMA or data["contract_id"] != CONTRACT_ID:
        raise _fail("bad_schema", "case set")
    if (
        not isinstance(data["export_sha256"], str)
        or _HEX64.fullmatch(data["export_sha256"]) is None
    ):
        raise _fail("bad_export_digest")
    assets: list[Asset] = []
    for raw in _list(data["assets"], "assets", 1, 2 * MAX_CASES):
        item = _exact(raw, frozenset({"asset_id", "sha256", "width", "height"}), "asset")
        if not isinstance(item["sha256"], str) or _HEX64.fullmatch(item["sha256"]) is None:
            raise _fail("bad_asset_digest")
        assets.append(
            Asset(
                _identifier(item["asset_id"], "asset_id"), item["sha256"],
                _positive_int(item["width"], "width"), _positive_int(item["height"], "height"),
            )
        )  # fmt: skip
    if len({asset.asset_id for asset in assets}) != len(assets) or len(
        {a.sha256 for a in assets}
    ) != len(assets):
        raise _fail("duplicate_asset")
    known = {asset.asset_id for asset in assets}
    cases: list[Case] = []
    for raw in _list(data["cases"], "cases", 1, MAX_CASES):
        item = _exact(raw, frozenset({"case_id", "kind", "asset_ids"}), "case")
        kind = item["kind"]
        if kind not in KINDS:
            raise _fail("bad_kind", str(kind))
        ids = tuple(
            _identifier(value, "asset_ids[]")
            for value in _list(item["asset_ids"], "asset_ids", 1, 2)
        )
        if len(ids) != (2 if kind == KIND_PAIR else 1) or len(set(ids)) != len(ids):
            raise _fail("bad_asset_count", str(item["case_id"]))
        if not set(ids) <= known:
            raise _fail("unknown_asset", str(item["case_id"]))
        cases.append(Case(_identifier(item["case_id"], "case_id"), kind, ids))
    if len({case.case_id for case in cases}) != len(cases):
        raise _fail("duplicate_case")
    return CaseSet(
        _identifier(data["set_id"], "set_id"), data["export_sha256"], tuple(assets), tuple(cases)
    )


# ------------------------------------------------------------------------------------------------------------ labels


@dataclass(frozen=True, slots=True)
class HumanFinding:
    category: str
    #: ``None`` when the operator recorded no region; otherwise the zones the confirmed box occupies.
    zones: tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class ImageReference:
    verdict: str
    findings: tuple[HumanFinding, ...]
    subject_count: int | None


@dataclass(frozen=True, slots=True)
class PairReference:
    judgment: str
    after_asset_id: str


@dataclass(frozen=True, slots=True)
class LabelSet:
    set_id: str
    labeler: str
    references: Mapping[str, ImageReference | PairReference]

    def image(self, case_id: str) -> ImageReference:
        reference = self.references[case_id]
        assert isinstance(reference, ImageReference)
        return reference

    def pair(self, case_id: str) -> PairReference:
        reference = self.references[case_id]
        assert isinstance(reference, PairReference)
        return reference


def _image_reference(raw: Any, case_id: str) -> ImageReference:
    item = _exact(raw, frozenset({"verdict", "findings", "subject_count"}), "image reference")
    if item["verdict"] not in VERDICTS:
        raise _fail("bad_verdict", case_id)
    findings: list[HumanFinding] = []
    for entry in _list(item["findings"], "findings", 0, MAX_LABEL_FINDINGS):
        finding = _exact(entry, frozenset({"category", "zones"}), "human finding")
        if finding["category"] not in CATEGORIES:
            raise _fail("bad_category", case_id)
        zones = finding["zones"]
        if zones is not None:
            listed = _list(zones, "zones", 1, len(ZONES))
            if any(zone not in ZONES for zone in listed) or len(set(listed)) != len(listed):
                raise _fail("bad_zones", case_id)
            zones = tuple(zone for zone in ZONES if zone in listed)
        findings.append(HumanFinding(finding["category"], zones))
    if (item["verdict"] == VERDICT_CLEAN) != (not findings):
        raise _fail("verdict_does_not_match_findings", case_id)
    count = item["subject_count"]
    if count is not None and (type(count) is not int or count < 0):
        raise _fail("bad_subject_count", case_id)
    return ImageReference(item["verdict"], tuple(findings), count)


def validate_label_set(document: Any, case_set: CaseSet) -> LabelSet:
    """Labels cover exactly the cases and were written by a person; anything else is refused."""

    data = _exact(
        document,
        frozenset({"schema", "set_id", "contract_id", "labeler", "export_sha256", "labels"}),
        "labels",
    )
    if data["schema"] != LABELS_SCHEMA or data["contract_id"] != CONTRACT_ID:
        raise _fail("bad_schema", "label set")
    if data["labeler"] != LABELER_HUMAN:
        raise _fail("labels_need_human_labeler")
    if data["set_id"] != case_set.set_id or data["export_sha256"] != case_set.export_sha256:
        raise _fail("label_set_mismatch")
    references: dict[str, ImageReference | PairReference] = {}
    for raw in _list(data["labels"], "labels", 1, MAX_CASES):
        item = _exact(raw, frozenset({"case_id", "reference"}), "label")
        case_id = _identifier(item["case_id"], "label case_id")
        if case_id in references:
            raise _fail("duplicate_label", case_id)
        try:
            case = case_set.case(case_id)
        except KeyError as exc:
            raise _fail("label_for_unknown_case", case_id) from exc
        if case.kind == KIND_IMAGE:
            references[case_id] = _image_reference(item["reference"], case_id)
        else:
            ref = _exact(
                item["reference"], frozenset({"judgment", "after_asset_id"}), "pair reference"
            )
            if ref["judgment"] not in JUDGMENTS:
                raise _fail("bad_judgment", case_id)
            if ref["after_asset_id"] not in case.asset_ids:
                raise _fail("bad_after_asset", case_id)
            references[case_id] = PairReference(ref["judgment"], ref["after_asset_id"])
    if set(references) != {case.case_id for case in case_set.cases}:
        raise _fail("labels_do_not_cover_cases")
    return LabelSet(case_set.set_id, LABELER_HUMAN, references)


# --------------------------------------------------------------------------------------------------------- questions

IMAGE_PROMPT = (
    "You are reviewing one generated image for visible defects. Answer only with the JSON object the schema allows.\n"
    'Set "verdict" to "clean" when you see no defect, with an empty "findings" list; otherwise set it to "defective" and '
    "list each defect you can see (at most 6), each with one category and one region.\n"
    "Categories: Face (facial features), Hands (fingers, hand shape), Anatomy (limbs, body proportions, joints), "
    "Composition (framing, cropping, layout), Rendering artifact (noise, smearing, seams, broken textures), "
    "General / local issue (any other local problem).\n"
    "Regions: the image is divided into a 3 by 3 grid: top_left, top, top_right, left, center, right, bottom_left, "
    "bottom, bottom_right; use whole_image only for a problem that covers most of the image.\n"
    'Set "subject_count" to the number of people or characters you can see ("5_or_more" for five or more).\n'
    "Report only what is visible. Do not describe the image."
)
PAIR_PROMPT = (
    "You are comparing two versions of one generated image, shown first and second. Answer only with the JSON object the "
    "schema allows.\n"
    'Set "answer" to "first_better" or "second_better" when that version shows clearly fewer or less severe visible '
    'defects, or "no_clear_difference" when neither is clearly better.\n'
    "Judge visible defects only (faces, hands, anatomy, composition, rendering artifacts), not taste or style."
)


def prompt_for(kind: str) -> str:
    if kind == KIND_IMAGE:
        return IMAGE_PROMPT
    if kind == KIND_PAIR:
        return PAIR_PROMPT
    raise _fail("bad_kind", kind)


# --------------------------------------------------------------------------------------------------------- responses


def build_response_schema(kind: str) -> dict[str, Any]:
    """The JSON Schema a constrained decoder receives for ``kind``. Every object is closed, every field required, every value
    an enum; the only free length is a list, and it is bounded. ``image_review`` has two ``ok`` branches so the grammar ties
    the verdict to the findings list. Keywords are the ones the AI Assist grammar proof covers."""

    head = {
        "schema": {"const": RESPONSE_SCHEMA},
        "status": {"const": "ok"},
        "kind": {"const": kind},
    }
    refused = {
        "type": "object", "additionalProperties": False, "required": ["schema", "status", "refusal"],
        "properties": {
            "schema": {"const": RESPONSE_SCHEMA}, "status": {"const": "refused"}, "refusal": {"enum": list(REFUSALS)},
        },
    }  # fmt: skip
    if kind == KIND_IMAGE:
        finding = {
            "type": "object", "additionalProperties": False, "required": ["category", "region"],
            "properties": {"category": {"enum": list(CATEGORIES)}, "region": {"enum": list(REGIONS)}},
        }  # fmt: skip
        branches = []
        for verdict, low, high in (
            (VERDICT_CLEAN, 0, 0),
            (VERDICT_DEFECTIVE, 1, MAX_ANSWER_FINDINGS),
        ):
            properties = {
                **head,
                "verdict": {"const": verdict},
                "findings": {"type": "array", "minItems": low, "maxItems": high, "items": finding},
                "subject_count": {"enum": list(SUBJECT_COUNTS)},
            }
            branches.append(
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": list(properties),
                    "properties": properties,
                }
            )
        return {"oneOf": [*branches, refused]}
    if kind == KIND_PAIR:
        properties = {**head, "answer": {"enum": list(PAIR_ANSWERS)}}
        ok = {
            "type": "object",
            "additionalProperties": False,
            "required": list(properties),
            "properties": properties,
        }
        return {"oneOf": [ok, refused]}
    raise _fail("bad_kind", kind)


@dataclass(frozen=True, slots=True)
class ResponseCheck:
    """``valid`` with a closed ``answer``, ``refused`` with a closed refusal code, or ``invalid`` with a reason code."""

    status: str
    reason: str
    answer: Mapping[str, Any] | None


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key")
        out[key] = value
    return out


def _reject_constant(name: str) -> Any:
    raise ValueError(name)


def _answer(kind: str, document: Mapping[str, Any]) -> dict[str, Any]:
    """The closed structured answer of a valid response, normalized (duplicate findings collapsed, kept in order)."""

    if kind == KIND_PAIR:
        _exact(document, frozenset({"schema", "status", "kind", "answer"}), "response")
        if document["answer"] not in PAIR_ANSWERS:
            raise _fail("bad_pair_answer")
        return {"answer": document["answer"]}
    _exact(
        document,
        frozenset({"schema", "status", "kind", "verdict", "findings", "subject_count"}),
        "response",
    )
    if document["verdict"] not in VERDICTS:
        raise _fail("bad_verdict")
    if document["subject_count"] not in SUBJECT_COUNTS:
        raise _fail("bad_subject_count")
    high = 0 if document["verdict"] == VERDICT_CLEAN else MAX_ANSWER_FINDINGS
    low = 0 if document["verdict"] == VERDICT_CLEAN else 1
    findings: list[dict[str, str]] = []
    for raw in _list(document["findings"], "findings", low, high):
        item = _exact(raw, frozenset({"category", "region"}), "finding")
        if item["category"] not in CATEGORIES or item["region"] not in REGIONS:
            raise _fail("bad_finding")
        entry = {"category": item["category"], "region": item["region"]}
        if entry not in findings:
            findings.append(entry)
    return {
        "verdict": document["verdict"],
        "findings": findings,
        "subject_count": document["subject_count"],
    }


def validate_response(case: Case, text: str) -> ResponseCheck:
    """Strict check of one raw answer. Never raises and never keeps any of the text: the result holds enum values only."""

    if (
        not isinstance(text, str)
        or len(text.encode("utf-8", errors="replace")) > MAX_RESPONSE_BYTES
    ):
        return ResponseCheck(STATUS_INVALID, "response_too_large", None)
    try:
        document = json.loads(
            text, object_pairs_hook=_strict_pairs, parse_constant=_reject_constant
        )
    except ValueError:
        return ResponseCheck(STATUS_INVALID, "not_json", None)
    if not isinstance(document, dict):
        return ResponseCheck(STATUS_INVALID, "not_an_object", None)
    if document.get("schema") != RESPONSE_SCHEMA:
        return ResponseCheck(STATUS_INVALID, "bad_schema", None)
    if document.get("status") == "refused":
        if set(document) != {"schema", "status", "refusal"} or document["refusal"] not in REFUSALS:
            return ResponseCheck(STATUS_INVALID, "bad_refusal", None)
        return ResponseCheck(STATUS_MODEL_REFUSED, str(document["refusal"]), None)
    if document.get("status") != "ok" or document.get("kind") != case.kind:
        return ResponseCheck(STATUS_INVALID, "kind_mismatch", None)
    try:
        return ResponseCheck(STATUS_VALID, "", _answer(case.kind, document))
    except ContractViolation as exc:
        return ResponseCheck(STATUS_INVALID, exc.code, None)


# ----------------------------------------------------------------------------------------------------------- evidence

_RECORD_KEYS = frozenset(
    {"case_id", "status", "reason", "wall_seconds", "peak_working_set_bytes", "answer"}
)


def evidence_record(
    case: Case,
    check: ResponseCheck | None,
    *,
    wall_seconds: float,
    peak_working_set_bytes: int,
    run_status: str | None = None,
    reason: str = "",
) -> dict[str, Any]:
    """The one record a real run may persist for a case: closed values only.

    ``check`` is the validated answer (``None`` when the child produced none, with ``run_status`` saying why, e.g.
    ``timeout``). The raw text is never an argument, so it cannot be written."""

    status = run_status if check is None else check.status
    code = reason if check is None else check.reason
    if status not in RUN_STATUSES or _CODE.fullmatch(code) is None:
        raise _fail("bad_run_status", str(status))
    if check is None and status == STATUS_VALID:
        raise _fail("valid_needs_answer")
    record = {
        "case_id": case.case_id,
        "status": status,
        "reason": code,
        "wall_seconds": round(float(wall_seconds), 3),
        "peak_working_set_bytes": int(peak_working_set_bytes),
        "answer": None if check is None or check.answer is None else dict(check.answer),
    }
    _record(record, case)
    return record


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    status: str
    reason: str
    wall_seconds: float
    peak_working_set_bytes: int
    answer: Mapping[str, Any] | None

    @property
    def answered(self) -> bool:
        return self.status == STATUS_VALID and self.answer is not None


@dataclass(frozen=True, slots=True)
class Evidence:
    tier: str
    candidate_id: str
    plan_sha256: str
    case_set_sha256: str
    complete: bool
    results: Mapping[str, CaseResult]


def _record(raw: Any, case: Case) -> CaseResult:
    item = _exact(raw, _RECORD_KEYS, "case record")
    if item["status"] not in RUN_STATUSES:
        raise _fail("bad_run_status", case.case_id)
    if not isinstance(item["reason"], str) or _CODE.fullmatch(item["reason"]) is None:
        raise _fail("reason_is_not_a_code", case.case_id)
    if item["status"] == STATUS_MODEL_REFUSED and item["reason"] not in REFUSALS:
        raise _fail("bad_refusal", case.case_id)
    seconds = item["wall_seconds"]
    if (
        isinstance(seconds, bool)
        or not isinstance(seconds, (int, float))
        or not math.isfinite(seconds)
        or seconds < 0
    ):
        raise _fail("bad_wall_seconds", case.case_id)
    peak = item["peak_working_set_bytes"]
    if type(peak) is not int or peak < 0:
        raise _fail("bad_peak_bytes", case.case_id)
    answer = item["answer"]
    if (answer is None) != (item["status"] != STATUS_VALID):
        raise _fail("answer_only_for_valid", case.case_id)
    if answer is not None:
        # Re-validate through the response path: the stored answer must be exactly a normalized closed answer.
        document = {
            "schema": RESPONSE_SCHEMA,
            "status": "ok",
            "kind": case.kind,
            **_exact_answer(answer, case.kind),
        }
        check = validate_response(case, canonical_json(document))
        if check.status != STATUS_VALID or check.answer != answer:
            raise _fail("answer_not_closed", case.case_id)
    return CaseResult(case.case_id, item["status"], item["reason"], float(seconds), peak, answer)


def _exact_answer(answer: Any, kind: str) -> Mapping[str, Any]:
    keys = (
        frozenset({"answer"})
        if kind == KIND_PAIR
        else frozenset({"verdict", "findings", "subject_count"})
    )
    return _exact(answer, keys, "answer")


def validate_evidence(document: Any, case_set: CaseSet) -> Evidence:
    """Parse an ``evidence/2`` file: one record per case, closed values only. Anything shaped like free text is refused."""

    data = _exact(
        document,
        frozenset(
            {
                "schema",
                "contract_id",
                "plan_sha256",
                "case_set_sha256",
                "candidate_id",
                "tier",
                "complete",
                "cases",
            }
        ),
        "evidence",
    )
    if data["schema"] != EVIDENCE_SCHEMA or data["contract_id"] != CONTRACT_ID:
        raise _fail("bad_schema", "evidence")
    if data["tier"] not in TIERS:
        raise _fail("bad_tier")
    for key in ("plan_sha256", "case_set_sha256"):
        if not isinstance(data[key], str) or _HEX64.fullmatch(data[key]) is None:
            raise _fail("bad_digest", key)
    if not isinstance(data["candidate_id"], str) or _ID.fullmatch(data["candidate_id"]) is None:
        raise _fail("bad_identifier", "candidate_id")
    if not isinstance(data["complete"], bool):
        raise _fail("bad_complete")
    results: dict[str, CaseResult] = {}
    for raw in _list(data["cases"], "cases", 1, MAX_CASES):
        case_id = raw.get("case_id") if isinstance(raw, dict) else None
        try:
            case = case_set.case(str(case_id))
        except KeyError as exc:
            raise _fail("record_for_unknown_case", str(case_id)[:64]) from exc
        if case.case_id in results:
            raise _fail("duplicate_record", case.case_id)
        results[case.case_id] = _record(raw, case)
    if set(results) != {case.case_id for case in case_set.cases}:
        raise _fail("evidence_does_not_cover_cases")
    return Evidence(
        data["tier"],
        data["candidate_id"],
        data["plan_sha256"],
        data["case_set_sha256"],
        data["complete"],
        results,
    )


def evidence_document(
    records: Sequence[Mapping[str, Any]],
    *,
    tier: str,
    candidate_id: str,
    plan_sha256: str,
    case_set_sha256: str,
    complete: bool,
) -> dict[str, Any]:
    """The whole ``evidence/2`` file for one tier and case set, built from :func:`evidence_record` rows."""

    return {
        "schema": EVIDENCE_SCHEMA,
        "contract_id": CONTRACT_ID,
        "plan_sha256": plan_sha256,
        "case_set_sha256": case_set_sha256,
        "candidate_id": candidate_id,
        "tier": tier,
        "complete": complete,
        "cases": [dict(row) for row in records],
    }


# --------------------------------------------------------------------------------------------------------------- gates


@dataclass(frozen=True, slots=True)
class Gate:
    """One pass/fail rule fixed before any run. ``metric`` names a value the analysis computes; ``op`` is ``>=`` or ``<=``.

    ``min_n`` is the sample a full-run PASS needs (fewer: ``insufficient_sample``); ``basis`` says whether the verdict reads the
    point estimate or a one-sided 95 % bound, and ``support`` names an extra statistical condition."""

    gate_id: str
    tier: str
    question: str
    metric: str
    op: str
    threshold: float
    min_n: Mapping[str, int]
    basis: str
    support: str = ""


#: Proposed, pending owner approval (``GATE_STATUS``). Reasoning per value: PR-AI-VL-242 contract, section 6.
GATES: tuple[Gate, ...] = (
    Gate("F1", TIER_FAST, "structured validity", "valid_rate", ">=", 0.95, {"cases": 50}, "point"),
    Gate("F2", TIER_FAST, "clean false alarm", "false_alarm_rate", "<=", 0.25, {"clean": 20}, "point"),
    Gate("F3", TIER_FAST, "image-level defect recall", "recall", ">=", 0.50, {"defective": 30}, "point"),
    Gate("F4", TIER_FAST, "above every deterministic floor", "balanced_accuracy_lower", ">", 0.50,
         {"clean": 20, "defective": 30}, "one_sided_lower_95", "best_floor"),
    Gate("F5", TIER_FAST, "memory and time", "resource_violations", "<=", 0.0, {"cases": 50}, "count"),
    Gate("D1", TIER_DEEP, "structured validity", "valid_rate", ">=", 0.95, {"cases": 50}, "point"),
    Gate("D2", TIER_DEEP, "clean false alarm", "false_alarm_rate", "<=", 0.15, {"clean": 20}, "point"),
    Gate("D3", TIER_DEEP, "finding-level precision", "finding_precision", ">=", 0.60, {"defective": 30}, "point",
         "above_best_floor"),
    Gate("D4", TIER_DEEP, "image-level F1 over the fast tier", "f1_gain", ">=", 0.15,
         {"clean": 20, "defective": 30}, "point", "mcnemar_one_sided_p<=0.05"),
    Gate("D5", TIER_DEEP, "above every deterministic floor", "balanced_accuracy_lower", ">", 0.50,
         {"clean": 20, "defective": 30}, "one_sided_lower_95", "best_floor"),
    Gate("D6", TIER_DEEP, "memory and time", "resource_violations", "<=", 0.0, {"cases": 50}, "count"),
    Gate("T1", "two_tier", "a conditional rule reaches deep detection at half its time", "recall_shortfall", "<=", 0.05,
         {"clean": 20, "defective": 30}, "point", "false_alarm<=0.15;seconds<=0.5*deep;deep_gates_pass"),
)  # fmt: skip

#: Bootstrap settings every interval in the report uses (fixed so the report is reproducible).
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 242
CONFIDENCE = 0.95


def gate_table() -> list[dict[str, Any]]:
    return [
        {
            "gate_id": gate.gate_id, "tier": gate.tier, "question": gate.question, "metric": gate.metric, "op": gate.op,
            "threshold": gate.threshold, "min_n": dict(gate.min_n), "basis": gate.basis, "support": gate.support,
        }
        for gate in GATES
    ]  # fmt: skip


def contract_section() -> dict[str, Any]:
    """Everything the ``eval/2`` plan binds about the contract itself: vocabularies, schemas, question texts and gates."""

    return {
        "contract_id": CONTRACT_ID,
        "schemas": [CASES_SCHEMA, LABELS_SCHEMA, RESPONSE_SCHEMA, EVIDENCE_SCHEMA],
        "export_schema": EXPORT_SCHEMA,
        "categories": list(CATEGORIES),
        "excluded_categories": list(EXCLUDED_CATEGORIES),
        "regions": list(REGIONS),
        "zone_min_share": ZONE_MIN_SHARE,
        "whole_image_min_zones": WHOLE_IMAGE_MIN_ZONES,
        "subject_counts": list(SUBJECT_COUNTS),
        "pair_answers": list(PAIR_ANSWERS),
        "judgments": list(JUDGMENTS),
        "refusals": list(REFUSALS),
        "max_answer_findings": MAX_ANSWER_FINDINGS,
        "response_schema_sha256": {kind: digest(build_response_schema(kind)) for kind in KINDS},
        "prompt_sha256": {kind: digest(prompt_for(kind)) for kind in KINDS},
        "gate_set": {"gate_set_id": GATE_SET_ID, "status": GATE_STATUS, "gates": gate_table()},
        "intervals": {
            "proportions": "wilson_score",
            "composites": "stratified_percentile_bootstrap",
            "paired_binary": "exact_mcnemar",
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED,
            "confidence": CONFIDENCE,
        },
        "persistence": "per case: status, reason code, seconds, peak bytes, closed answer; never text",
    }


__all__ = [
    "CASES_SCHEMA",
    "CATEGORIES",
    "CONTRACT_ID",
    "EVIDENCE_SCHEMA",
    "EXPORT_SCHEMA",
    "GATES",
    "KINDS",
    "LABELS_SCHEMA",
    "REGIONS",
    "RESPONSE_SCHEMA",
    "Case",
    "CaseResult",
    "CaseSet",
    "Evidence",
    "Gate",
    "LabelSet",
    "ResponseCheck",
    "build_response_schema",
    "contract_section",
    "evidence_document",
    "evidence_record",
    "gate_table",
    "region_matches",
    "validate_case_set",
    "validate_evidence",
    "validate_label_set",
    "validate_response",
    "zones_of_box",
]
