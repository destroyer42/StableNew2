"""The visual evaluation contract (PR-AI-VL-220): closed vocabularies, case and label schemas, response validation.

This module is a specification made executable. It defines what a visual evaluation case, its separate human reference label
and a model's structured answer must look like, and rejects everything else. It runs no model and starts no process: the
image invocation a real run would need is a separate, unapproved contract
(``docs/Subsystems/AiAssist/PR-AI-VL-220_Image_Invocation_Contract.md``).

Cases carry no reference data. Labels live in a separate document, keyed by case id, and for any asset that is not synthetic
they must be written by a person. :func:`validate_case_set` and :func:`validate_label_set` enforce both rules.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

CONTRACT_ID = "stablenew.vl220.eval/1"
CASES_SCHEMA = "stablenew.vl220.cases/1"
LABELS_SCHEMA = "stablenew.vl220.labels/1"
RESPONSE_SCHEMA = "stablenew.vl220.response/1"

#: This package specifies the invocation but does not approve it; an owner decision flips this, in a later change.
INVOCATION_APPROVED = False

KIND_ADHERENCE = "adherence"
KIND_DEFECT = "defect_triage"
KIND_CONSISTENCY = "consistency"
KIND_BEFORE_AFTER = "before_after"
KIND_DESCRIBE = "describe"
KINDS: tuple[str, ...] = (
    KIND_ADHERENCE,
    KIND_DEFECT,
    KIND_CONSISTENCY,
    KIND_BEFORE_AFTER,
    KIND_DESCRIBE,
)

DIM_ADHERENCE = "prompt_adherence"
DIM_DEFECT = "anatomical_defect_triage"
DIM_CONSISTENCY = "multi_subject_consistency"
DIM_BEFORE_AFTER = "before_after_usefulness"
DIM_HALLUCINATION = "hallucination"
DIM_STRUCTURED = "structured_output"
DIM_RESOURCES = "memory_runtime_limits"
DIMENSIONS: tuple[str, ...] = (
    DIM_ADHERENCE, DIM_DEFECT, DIM_CONSISTENCY, DIM_BEFORE_AFTER, DIM_HALLUCINATION, DIM_STRUCTURED, DIM_RESOURCES,
)  # fmt: skip
DIMENSION_OF_KIND: Mapping[str, str] = {
    KIND_ADHERENCE: DIM_ADHERENCE,
    KIND_DEFECT: DIM_DEFECT,
    KIND_CONSISTENCY: DIM_CONSISTENCY,
    KIND_BEFORE_AFTER: DIM_BEFORE_AFTER,
    KIND_DESCRIBE: DIM_HALLUCINATION,
}

REGIONS: tuple[str, ...] = ("face", "hands", "arms", "legs", "torso", "background", "other")
DEFECT_CATEGORIES: tuple[str, ...] = (
    "extra_limb",
    "missing_limb",
    "fused_limb",
    "distorted",
    "wrong_count",
    "other",
)
SEVERITIES: tuple[str, ...] = ("minor", "major")
PREFERENCES: tuple[str, ...] = ("a", "b", "tie")
PREFERENCE_REASONS: tuple[str, ...] = (
    "more_complete",
    "fewer_defects",
    "closer_to_prompt",
    "no_difference",
)

MAX_ELEMENTS = 12
MAX_FINDINGS = 8
MAX_OBJECTS = 16
MAX_OBJECT_CHARS = 40
MAX_REFUSAL_CHARS = 400
MAX_PROMPT_CHARS = 1000
MAX_RESPONSE_BYTES = 16 * 1024

#: Anything shaped like reference data is refused inside a case, at any depth.
FORBIDDEN_CASE_KEYS: frozenset[str] = frozenset(
    {
        "reference",
        "label",
        "labels",
        "expected",
        "answer",
        "answers",
        "solution",
        "ground_truth",
        "preferred",
        "truth",
    }
)

ORIGIN_SYNTHETIC = "synthetic"
ORIGIN_EXISTING = "existing"
LABELER_HUMAN = "human"
LABELER_SYNTHETIC = "synthetic_by_construction"

_ID = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")
_HEX64 = re.compile(r"[0-9a-f]{64}")


class ContractViolation(ValueError):
    """A case, label or response document does not satisfy the contract. ``code`` is a stable token."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def _fail(code: str, detail: str = "") -> ContractViolation:
    return ContractViolation(code, detail)


def canonical_json(document: Any) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(document: Any) -> str:
    return hashlib.sha256(canonical_json(document).encode("ascii")).hexdigest()


def _keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            found.add(str(key))
            found |= _keys(item)
    elif isinstance(value, list):
        for item in value:
            found |= _keys(item)
    return found


def _identifier(value: Any, what: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise _fail("bad_identifier", what)
    return value


def _exact(
    document: Any, allowed: frozenset[str], what: str, required: frozenset[str] | None = None
) -> Mapping[str, Any]:
    if not isinstance(document, dict):
        raise _fail("not_an_object", what)
    unknown = set(document) - allowed
    if unknown:
        raise _fail("unknown_keys", f"{what}: {sorted(unknown)}")
    missing = (required if required is not None else allowed) - set(document)
    if missing:
        raise _fail("missing_keys", f"{what}: {sorted(missing)}")
    return document


# --------------------------------------------------------------------------------------------------------------- cases


@dataclass(frozen=True, slots=True)
class Asset:
    asset_id: str
    sha256: str
    bytes: int
    origin: str
    media_type: str


@dataclass(frozen=True, slots=True)
class Case:
    case_id: str
    kind: str
    asset_ids: tuple[str, ...]
    prompt: str
    elements: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class CaseSet:
    set_id: str
    assets: tuple[Asset, ...]
    cases: tuple[Case, ...]

    def case(self, case_id: str) -> Case:
        for item in self.cases:
            if item.case_id == case_id:
                return item
        raise KeyError(case_id)


_ELEMENT_KINDS = frozenset({KIND_ADHERENCE, KIND_CONSISTENCY})


def validate_case_set(document: Any) -> CaseSet:
    """Parse and check a case document; reject reference-shaped keys, unknown keys and unpinned assets."""

    data = _exact(document, frozenset({"schema", "set_id", "assets", "cases"}), "case set")
    if data["schema"] != CASES_SCHEMA:
        raise _fail("bad_schema", "case set")
    if FORBIDDEN_CASE_KEYS & {key.lower() for key in _keys(data)}:
        raise _fail("case_carries_reference_data")
    assets: list[Asset] = []
    for raw in _list(data["assets"], "assets", 1, 512):
        item = _exact(
            raw, frozenset({"asset_id", "sha256", "bytes", "origin", "media_type"}), "asset"
        )
        if item["origin"] not in (ORIGIN_SYNTHETIC, ORIGIN_EXISTING):
            raise _fail("bad_origin", str(item["origin"]))
        if not isinstance(item["sha256"], str) or _HEX64.fullmatch(item["sha256"]) is None:
            raise _fail("bad_asset_digest")
        if (
            not isinstance(item["bytes"], int)
            or isinstance(item["bytes"], bool)
            or item["bytes"] <= 0
        ):
            raise _fail("bad_asset_size")
        if item["media_type"] not in ("image/png", "image/jpeg"):
            raise _fail("bad_media_type")
        assets.append(
            Asset(
                _identifier(item["asset_id"], "asset_id"),
                item["sha256"],
                item["bytes"],
                item["origin"],
                item["media_type"],
            )
        )
    known = {asset.asset_id for asset in assets}
    if len(known) != len(assets):
        raise _fail("duplicate_asset")
    cases: list[Case] = []
    for raw in _list(data["cases"], "cases", 1, 512):
        item = _exact(
            raw, frozenset({"case_id", "kind", "asset_ids", "prompt", "elements"}), "case",
            required=frozenset({"case_id", "kind", "asset_ids", "prompt"}),
        )  # fmt: skip
        kind = item["kind"]
        if kind not in KINDS:
            raise _fail("bad_kind", str(kind))
        asset_ids = tuple(
            _identifier(value, "asset_ids[]")
            for value in _list(item["asset_ids"], "asset_ids", 1, 2)
        )
        if len(asset_ids) != (2 if kind == KIND_BEFORE_AFTER else 1):
            raise _fail("bad_asset_count", str(item["case_id"]))
        if not set(asset_ids) <= known:
            raise _fail("unknown_asset", str(item["case_id"]))
        prompt = item["prompt"]
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
            raise _fail("bad_prompt", str(item["case_id"]))
        elements: list[tuple[str, str]] = []
        if kind in _ELEMENT_KINDS:
            for entry in _list(item.get("elements"), "elements", 1, MAX_ELEMENTS):
                parsed = _exact(entry, frozenset({"id", "text"}), "element")
                if (
                    not isinstance(parsed["text"], str)
                    or not parsed["text"].strip()
                    or len(parsed["text"]) > 120
                ):
                    raise _fail("bad_element_text")
                elements.append((_identifier(parsed["id"], "element id"), parsed["text"]))
            if len({key for key, _ in elements}) != len(elements):
                raise _fail("duplicate_element")
        elif "elements" in item:
            raise _fail("unexpected_elements", str(item["case_id"]))
        cases.append(
            Case(_identifier(item["case_id"], "case_id"), kind, asset_ids, prompt, tuple(elements))
        )
    if len({case.case_id for case in cases}) != len(cases):
        raise _fail("duplicate_case")
    return CaseSet(_identifier(data["set_id"], "set_id"), tuple(assets), tuple(cases))


def _list(value: Any, what: str, low: int, high: int) -> list[Any]:
    if not isinstance(value, list) or not low <= len(value) <= high:
        raise _fail("bad_list", what)
    return value


# -------------------------------------------------------------------------------------------------------------- labels


@dataclass(frozen=True, slots=True)
class LabelSet:
    set_id: str
    labeler: str
    references: Mapping[str, Mapping[str, Any]]


def _finding(raw: Any) -> dict[str, str]:
    item = _exact(raw, frozenset({"region", "category", "severity"}), "finding")
    if (
        item["region"] not in REGIONS
        or item["category"] not in DEFECT_CATEGORIES
        or item["severity"] not in SEVERITIES
    ):
        raise _fail("bad_finding")
    return {"region": item["region"], "category": item["category"], "severity": item["severity"]}


def _object_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_OBJECT_CHARS:
        raise _fail("bad_object_name")
    return value


def _reference(case: Case, raw: Any) -> dict[str, Any]:
    if case.kind in _ELEMENT_KINDS:
        item = _exact(raw, frozenset({"answers"}), "reference")
        answers = item["answers"]
        if not isinstance(answers, dict) or set(answers) != {key for key, _ in case.elements}:
            raise _fail("answers_do_not_match_elements", case.case_id)
        if not all(isinstance(value, bool) for value in answers.values()):
            raise _fail("bad_answer", case.case_id)
        return {"answers": dict(answers)}
    if case.kind == KIND_DEFECT:
        item = _exact(raw, frozenset({"findings"}), "reference")
        return {
            "findings": [
                _finding(entry) for entry in _list(item["findings"], "findings", 0, MAX_FINDINGS)
            ]
        }
    if case.kind == KIND_BEFORE_AFTER:
        item = _exact(raw, frozenset({"preferred"}), "reference")
        if item["preferred"] not in PREFERENCES:
            raise _fail("bad_preference", case.case_id)
        return {"preferred": item["preferred"]}
    item = _exact(raw, frozenset({"objects", "synonyms"}), "reference")
    objects = [_object_name(value) for value in _list(item["objects"], "objects", 0, MAX_OBJECTS)]
    synonyms = item["synonyms"]
    if not isinstance(synonyms, dict) or not set(synonyms) <= set(objects):
        raise _fail("bad_synonyms", case.case_id)
    return {
        "objects": objects,
        "synonyms": {
            key: [_object_name(value) for value in _list(values, "synonyms", 0, 8)]
            for key, values in synonyms.items()
        },
    }


def validate_label_set(document: Any, case_set: CaseSet) -> LabelSet:
    """Labels must cover exactly the cases, and a person must have written them for any non-synthetic asset."""

    data = _exact(document, frozenset({"schema", "set_id", "labeler", "labels"}), "label set")
    if data["schema"] != LABELS_SCHEMA:
        raise _fail("bad_schema", "label set")
    if data["set_id"] != case_set.set_id:
        raise _fail("label_set_mismatch")
    if data["labeler"] not in (LABELER_HUMAN, LABELER_SYNTHETIC):
        raise _fail("bad_labeler")
    uses_existing = any(asset.origin == ORIGIN_EXISTING for asset in case_set.assets)
    if uses_existing and data["labeler"] != LABELER_HUMAN:
        raise _fail("existing_assets_need_human_labels")
    references: dict[str, Mapping[str, Any]] = {}
    for raw in _list(data["labels"], "labels", 1, 512):
        item = _exact(raw, frozenset({"case_id", "reference"}), "label")
        case_id = _identifier(item["case_id"], "label case_id")
        if case_id in references:
            raise _fail("duplicate_label", case_id)
        try:
            case = case_set.case(case_id)
        except KeyError as exc:
            raise _fail("label_for_unknown_case", case_id) from exc
        references[case_id] = _reference(case, item["reference"])
    if set(references) != {case.case_id for case in case_set.cases}:
        raise _fail("labels_do_not_cover_cases")
    return LabelSet(str(data["set_id"]), str(data["labeler"]), references)


# ----------------------------------------------------------------------------------------------------------- responses


@dataclass(frozen=True, slots=True)
class ResponseCheck:
    """``status`` is ``valid`` (payload usable), ``refused`` (a schema-valid refusal) or ``invalid`` (``reason`` says why)."""

    status: str
    reason: str
    payload: Mapping[str, Any]

    @property
    def valid(self) -> bool:
        return self.status == "valid"


def _invalid(reason: str) -> ResponseCheck:
    return ResponseCheck("invalid", reason, {})


def validate_response(case: Case, text: str) -> ResponseCheck:
    """Strict check of one structured answer against the contract. Never raises."""

    if (
        not isinstance(text, str)
        or len(text.encode("utf-8", errors="replace")) > MAX_RESPONSE_BYTES
    ):
        return _invalid("response_too_large")
    try:
        document = json.loads(text)
    except ValueError:
        return _invalid("not_json")
    if not isinstance(document, dict):
        return _invalid("not_an_object")
    if document.get("schema") != RESPONSE_SCHEMA:
        return _invalid("bad_schema")
    status = document.get("status")
    if status == "refused":
        reason = document.get("refusal_reason")
        if (
            set(document) != {"schema", "status", "refusal_reason"}
            or not isinstance(reason, str)
            or len(reason) > MAX_REFUSAL_CHARS
        ):
            return _invalid("bad_refusal")
        return ResponseCheck("refused", "", {})
    if status != "ok" or document.get("kind") != case.kind:
        return _invalid("kind_mismatch")
    try:
        payload = _payload(case, document)
    except ContractViolation as exc:
        return _invalid(exc.code)
    return ResponseCheck("valid", "", payload)


def _payload(case: Case, document: Mapping[str, Any]) -> dict[str, Any]:
    if case.kind in _ELEMENT_KINDS:
        _exact(document, frozenset({"schema", "status", "kind", "answers"}), "response")
        answers: dict[str, bool] = {}
        for raw in _list(document["answers"], "answers", 1, MAX_ELEMENTS):
            item = _exact(raw, frozenset({"id", "value"}), "answer")
            if not isinstance(item["value"], bool) or not isinstance(item["id"], str):
                raise _fail("bad_answer")
            if item["id"] in answers:
                raise _fail("duplicate_answer")
            answers[item["id"]] = item["value"]
        if set(answers) != {key for key, _ in case.elements}:
            raise _fail("answers_do_not_match_elements")
        return {"answers": answers}
    if case.kind == KIND_DEFECT:
        _exact(document, frozenset({"schema", "status", "kind", "findings"}), "response")
        return {
            "findings": [
                _finding(entry)
                for entry in _list(document["findings"], "findings", 0, MAX_FINDINGS)
            ]
        }
    if case.kind == KIND_BEFORE_AFTER:
        _exact(document, frozenset({"schema", "status", "kind", "preferred", "reason"}), "response")
        if document["preferred"] not in PREFERENCES or document["reason"] not in PREFERENCE_REASONS:
            raise _fail("bad_preference")
        return {"preferred": document["preferred"], "reason": document["reason"]}
    _exact(document, frozenset({"schema", "status", "kind", "objects"}), "response")
    return {
        "objects": [
            _object_name(value) for value in _list(document["objects"], "objects", 0, MAX_OBJECTS)
        ]
    }


def build_response_schema(kind: str) -> dict[str, Any]:
    """The JSON Schema a constrained decoder would be given for ``kind``: two branches, ok and refused, closed objects.

    It uses only keywords the AI Assist grammar proof already covers (``oneOf``, ``const``, ``enum``, ``required``,
    ``additionalProperties: false``, ``minItems``/``maxItems``, ``maxLength``). :func:`validate_response` is the authority; the
    schema is deliberately no looser than it."""

    if kind not in KINDS:
        raise _fail("bad_kind", kind)
    head: dict[str, Any] = {
        "schema": {"const": RESPONSE_SCHEMA},
        "status": {"const": "ok"},
        "kind": {"const": kind},
    }
    if kind in _ELEMENT_KINDS:
        payload = {
            "answers": {
                "type": "array", "minItems": 1, "maxItems": MAX_ELEMENTS,
                "items": {
                    "type": "object", "additionalProperties": False, "required": ["id", "value"],
                    "properties": {"id": {"type": "string", "maxLength": 64}, "value": {"type": "boolean"}},
                },
            }
        }  # fmt: skip
    elif kind == KIND_DEFECT:
        payload = {
            "findings": {
                "type": "array", "minItems": 0, "maxItems": MAX_FINDINGS,
                "items": {
                    "type": "object", "additionalProperties": False, "required": ["region", "category", "severity"],
                    "properties": {
                        "region": {"enum": list(REGIONS)},
                        "category": {"enum": list(DEFECT_CATEGORIES)},
                        "severity": {"enum": list(SEVERITIES)},
                    },
                },
            }
        }  # fmt: skip
    elif kind == KIND_BEFORE_AFTER:
        payload = {
            "preferred": {"enum": list(PREFERENCES)},
            "reason": {"enum": list(PREFERENCE_REASONS)},
        }
    else:
        payload = {
            "objects": {
                "type": "array", "minItems": 0, "maxItems": MAX_OBJECTS,
                "items": {"type": "string", "maxLength": MAX_OBJECT_CHARS},
            }
        }  # fmt: skip
    ok_branch = {
        "type": "object",
        "additionalProperties": False,
        "required": [*head, *payload],
        "properties": {**head, **payload},
    }
    refused_branch = {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema", "status", "refusal_reason"],
        "properties": {
            "schema": {"const": RESPONSE_SCHEMA},
            "status": {"const": "refused"},
            "refusal_reason": {"type": "string", "maxLength": MAX_REFUSAL_CHARS},
        },
    }
    return {"oneOf": [ok_branch, refused_branch]}


# ------------------------------------------------------------------------------------------------- resource limits


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    """Proposed per-case ceilings (owner-tunable): CPU only, bounded time and memory."""

    max_wall_seconds: float = 180.0
    max_peak_working_set_bytes: int = 6 * 1024**3
    max_context_tokens: int = 4096
    require_cpu_only: bool = True


@dataclass(frozen=True, slots=True)
class Measurement:
    wall_seconds: float
    peak_working_set_bytes: int
    context_tokens: int
    cpu_only: bool


def limit_violations(measurement: Measurement, limits: ResourceLimits) -> tuple[str, ...]:
    found: list[str] = []
    if measurement.wall_seconds > limits.max_wall_seconds:
        found.append("wall_time")
    if measurement.peak_working_set_bytes > limits.max_peak_working_set_bytes:
        found.append("memory")
    if measurement.context_tokens > limits.max_context_tokens:
        found.append("context")
    if limits.require_cpu_only and not measurement.cpu_only:
        found.append("not_cpu_only")
    return tuple(found)


# ---------------------------------------------------------------------------------------------------------- comparators


@dataclass(frozen=True, slots=True)
class Comparator:
    comparator_id: str
    display_name: str
    eligible: bool
    dimensions: tuple[str, ...]
    reasons: tuple[str, ...]


def comparators() -> tuple[Comparator, ...]:
    """Who the candidate can be compared with today, and exactly why anyone else cannot be."""

    return (
        Comparator(
            "deterministic-floor",
            "Deterministic floors (all-yes, all-no, seeded random)",
            True,
            (
                DIM_ADHERENCE,
                DIM_DEFECT,
                DIM_CONSISTENCY,
                DIM_BEFORE_AFTER,
                DIM_HALLUCINATION,
                DIM_STRUCTURED,
            ),
            (),
        ),
        Comparator(
            "florence2-caption",
            "Smart Review caption adapter (Florence-2, existing PR-IMG-REVIEW-320)",
            True,
            (DIM_HALLUCINATION,),
            (
                "free_text_captions_only",
                "no_structured_output",
                "no_defect_triage",
                "needs_verified_catalog_resource",
            ),
        ),
        Comparator(
            "sam2-segmentation",
            "Smart Review segmentation adapter (SAM2, existing)",
            False,
            (),
            ("no_text_output",),
        ),
        Comparator(
            "qwen3.5-text-gguf",
            "Registered Qwen3.5 GGUF text models",
            False,
            (),
            ("text_only_registration", "no_projector_registered", "mmproj_flag_is_forbidden"),
        ),
        Comparator(
            "lfm3-1.7b-text-gguf",
            "Registered LFM3-1.7B GGUF text models",
            False,
            (),
            ("text_only_registration", "language_model_has_no_vision_encoder"),
        ),
        Comparator(
            "lfm3-vl-2b-q4_k_m-liquidai",
            "LFM3-VL-2B Q4_K_M with F16 projector (this candidate)",
            False,
            (
                DIM_ADHERENCE,
                DIM_DEFECT,
                DIM_CONSISTENCY,
                DIM_BEFORE_AFTER,
                DIM_HALLUCINATION,
                DIM_STRUCTURED,
                DIM_RESOURCES,
            ),
            (
                "image_invocation_not_approved",
                "license_not_acknowledged",
                "not_imported_into_an_evaluation_root",
            ),
        ),
    )


def comparator_table() -> list[dict[str, Any]]:
    return [
        {
            "comparator_id": item.comparator_id, "eligible": item.eligible,
            "dimensions": list(item.dimensions), "reasons": list(item.reasons),
        }
        for item in comparators()
    ]  # fmt: skip


__all__ = [
    "CASES_SCHEMA",
    "CONTRACT_ID",
    "DIMENSIONS",
    "DIMENSION_OF_KIND",
    "INVOCATION_APPROVED",
    "KINDS",
    "LABELS_SCHEMA",
    "RESPONSE_SCHEMA",
    "Case",
    "CaseSet",
    "ContractViolation",
    "LabelSet",
    "Measurement",
    "ResourceLimits",
    "ResponseCheck",
    "build_response_schema",
    "canonical_json",
    "comparator_table",
    "comparators",
    "digest",
    "limit_violations",
    "validate_case_set",
    "validate_label_set",
    "validate_response",
]
