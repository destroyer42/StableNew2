"""Deterministic scoring for the visual evaluation contract (PR-AI-VL-220). Pure functions; no model, file or clock access.

``score_run`` takes the case set, the separate label set, the raw text each system answered with and its measurements, and
returns plain numbers per dimension. A system that returns nothing, something invalid or a refusal is scored as such, never
skipped, so a harness cannot look better by failing quietly.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tools.qualification.vl220 import contract
from tools.qualification.vl220.contract import CaseSet, LabelSet, Measurement, ResourceLimits


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else round(numerator / denominator, 6)


_ARTICLES = frozenset({"a", "an", "the"})


def _singular(token: str) -> str:
    if len(token) > 3 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _normal(text: str) -> str:
    """Lower case, separators and punctuation as spaces, leading articles dropped, plural ``s`` dropped.

    ``"A red square."``, ``"red-square"``, ``"RED_SQUARES"`` and ``"red square"`` are the same name. Anything that is a
    different word (``"rectangle"``) or a different property (``"blue square"``) is not."""

    cleaned = "".join(ch if ch.isalnum() else " " for ch in text.lower())
    tokens = [_singular(token) for token in cleaned.split()]
    while tokens and tokens[0] in _ARTICLES:
        tokens.pop(0)
    return " ".join(tokens)


def score_answers(
    reference: Mapping[str, Any], payload: Mapping[str, Any] | None
) -> tuple[int, int]:
    """Correct element answers and the total, for adherence and consistency cases."""

    expected: Mapping[str, bool] = reference["answers"]
    given: Mapping[str, bool] = payload["answers"] if payload else {}
    return sum(1 for key, value in expected.items() if given.get(key) is value), len(expected)


def score_findings(
    reference: Mapping[str, Any], payload: Mapping[str, Any] | None
) -> tuple[int, int, int]:
    """True positives, false positives, false negatives of ``(region, category)`` findings."""

    expected = {(item["region"], item["category"]) for item in reference["findings"]}
    given = (
        {(item["region"], item["category"]) for item in payload["findings"]} if payload else set()
    )
    return len(expected & given), len(given - expected), len(expected - given)


def _accepted(reference: Mapping[str, Any]) -> dict[str, str]:
    accepted: dict[str, str] = {}
    for name in reference["objects"]:
        accepted[_normal(name)] = name
        for alias in reference["synonyms"].get(name, []):
            accepted[_normal(alias)] = name
    return accepted


def _is_generic(mention: str, accepted: Mapping[str, str]) -> bool:
    """A bare head word of a reference name (``"square"`` for ``"red square"``): true but less specific than asked."""

    words = mention.split()
    return bool(words) and any(
        len(words) < len(name.split()) and name.split()[-len(words) :] == words for name in accepted
    )


def score_objects(
    reference: Mapping[str, Any], payload: Mapping[str, Any] | None
) -> tuple[int, int, int]:
    """Supported mentions, unsupported mentions (hallucinations), and reference objects found.

    A generic mention (just the kind, ``"square"``, where the reference says ``"red square"``) is not a hallucination, so it
    counts as supported; it does not count as finding the object, because the question asked for the color too. How many
    mentions were generic is reported apart (:func:`generic_mentions`)."""

    accepted = _accepted(reference)
    mentions = [_normal(item) for item in payload["objects"]] if payload else []
    exact = [item for item in mentions if item in accepted]
    generic = [item for item in mentions if item not in accepted and _is_generic(item, accepted)]
    found = {accepted[item] for item in exact}
    supported = len(exact) + len(generic)
    return supported, len(mentions) - supported, len(found)


def generic_mentions(reference: Mapping[str, Any], payload: Mapping[str, Any] | None) -> int:
    accepted = _accepted(reference)
    mentions = [_normal(item) for item in payload["objects"]] if payload else []
    return sum(1 for item in mentions if item not in accepted and _is_generic(item, accepted))


def score_run(
    case_set: CaseSet,
    labels: LabelSet,
    responses: Mapping[str, str],
    measurements: Mapping[str, Measurement] | None = None,
    limits: ResourceLimits | None = None,
) -> dict[str, Any]:
    """Score one system over a whole case set. ``responses`` maps case id to the system's raw text ("" if it gave none)."""

    tp = fp = fn = clean_total = clean_alarms = 0
    ba_hit = ba_total = 0
    mention_ok = mention_bad = object_found = object_total = generic = 0
    valid = refused = invalid = 0
    reasons: dict[str, int] = {}
    per_kind: dict[str, int] = {}
    for case in case_set.cases:
        per_kind[case.kind] = per_kind.get(case.kind, 0) + 1
        check = contract.validate_response(case, responses.get(case.case_id, ""))
        if check.status == "valid":
            valid += 1
        elif check.status == "refused":
            refused += 1
        else:
            invalid += 1
            reasons[check.reason] = reasons.get(check.reason, 0) + 1
        payload = check.payload if check.valid else None
        reference = labels.references[case.case_id]
        if case.kind == contract.KIND_DEFECT:
            a, b, c = score_findings(reference, payload)
            tp, fp, fn = tp + a, fp + b, fn + c
            if not reference["findings"]:
                clean_total += 1
                clean_alarms += 1 if payload and payload["findings"] else 0
        elif case.kind == contract.KIND_BEFORE_AFTER:
            ba_total += 1
            ba_hit += 1 if payload and payload["preferred"] == reference["preferred"] else 0
        elif case.kind == contract.KIND_DESCRIBE:
            ok, bad, found = score_objects(reference, payload)
            mention_ok, mention_bad = mention_ok + ok, mention_bad + bad
            object_found += found
            object_total += len(reference["objects"])
            generic += generic_mentions(reference, payload)
    adherence_hit, adherence_total = _split(case_set, labels, responses, contract.KIND_ADHERENCE)
    consistency_hit, consistency_total = _split(
        case_set, labels, responses, contract.KIND_CONSISTENCY
    )
    report: dict[str, Any] = {
        "cases": len(case_set.cases),
        "cases_by_kind": dict(sorted(per_kind.items())),
        contract.DIM_ADHERENCE: _ratio(adherence_hit, adherence_total),
        contract.DIM_CONSISTENCY: _ratio(consistency_hit, consistency_total),
        contract.DIM_DEFECT: {
            "precision": _ratio(tp, tp + fp),
            "recall": _ratio(tp, tp + fn),
            "false_alarm_rate_on_clean_cases": _ratio(clean_alarms, clean_total),
        },
        contract.DIM_BEFORE_AFTER: _ratio(ba_hit, ba_total),
        contract.DIM_HALLUCINATION: {
            "unsupported_mention_rate": _ratio(mention_bad, mention_ok + mention_bad),
            "object_recall": _ratio(object_found, object_total),
        },
        # Detail the hallucination score does not carry (kept apart so that score's shape stays what it was).
        "describe_detail": {"generic_mentions": generic},
        contract.DIM_STRUCTURED: {
            "valid_rate": _ratio(valid, len(case_set.cases)),
            "refused_rate": _ratio(refused, len(case_set.cases)),
            "invalid_rate": _ratio(invalid, len(case_set.cases)),
            "invalid_reasons": dict(sorted(reasons.items())),
        },
    }
    report[contract.DIM_RESOURCES] = _resources(case_set, measurements, limits or ResourceLimits())
    return report


def _split(
    case_set: CaseSet, labels: LabelSet, responses: Mapping[str, str], kind: str
) -> tuple[int, int]:
    hit = total = 0
    for case in case_set.cases:
        if case.kind != kind:
            continue
        check = contract.validate_response(case, responses.get(case.case_id, ""))
        a, b = score_answers(
            labels.references[case.case_id], check.payload if check.valid else None
        )
        hit, total = hit + a, total + b
    return hit, total


def _resources(
    case_set: CaseSet, measurements: Mapping[str, Measurement] | None, limits: ResourceLimits
) -> dict[str, Any]:
    if not measurements:
        return {"measured_cases": 0, "unmeasured_cases": len(case_set.cases), "violations": {}}
    violations: dict[str, int] = {}
    walls: list[float] = []
    peak = 0
    for case in case_set.cases:
        measurement = measurements.get(case.case_id)
        if measurement is None:
            violations["unmeasured"] = violations.get("unmeasured", 0) + 1
            continue
        walls.append(measurement.wall_seconds)
        peak = max(peak, measurement.peak_working_set_bytes)
        for code in contract.limit_violations(measurement, limits):
            violations[code] = violations.get(code, 0) + 1
    walls.sort()
    median = walls[len(walls) // 2] if walls else None
    return {
        "measured_cases": len(walls),
        "unmeasured_cases": len(case_set.cases) - len(walls),
        "median_wall_seconds": median,
        "max_wall_seconds": walls[-1] if walls else None,
        "peak_working_set_bytes": peak,
        "violations": dict(sorted(violations.items())),
    }


class _Lcg:
    """A tiny fixed generator so seeded baselines are identical on every Python version."""

    def __init__(self, seed: int) -> None:
        self._state = seed & 0xFFFFFFFF

    def below(self, bound: int) -> int:
        self._state = (self._state * 1664525 + 1013904223) & 0xFFFFFFFF
        return (self._state >> 8) % bound


def baseline_responses(case_set: CaseSet, mode: str, seed: int = 220) -> dict[str, str]:
    """Contract-valid answers from a system that looks at nothing: ``all_yes``, ``all_no`` or ``seeded_random``."""

    if mode not in ("all_yes", "all_no", "seeded_random"):
        raise ValueError(mode)
    rng = _Lcg(seed)
    out: dict[str, str] = {}
    for case in case_set.cases:
        head: dict[str, Any] = {
            "schema": contract.RESPONSE_SCHEMA,
            "status": "ok",
            "kind": case.kind,
        }
        if case.kind in (contract.KIND_ADHERENCE, contract.KIND_CONSISTENCY):
            head["answers"] = [
                {
                    "id": key,
                    "value": True
                    if mode == "all_yes"
                    else False
                    if mode == "all_no"
                    else bool(rng.below(2)),
                }
                for key, _ in case.elements
            ]
        elif case.kind == contract.KIND_DEFECT:
            flag = mode == "all_yes" or (mode == "seeded_random" and rng.below(2) == 1)
            head["findings"] = (
                [{"region": "other", "category": "other", "severity": "minor"}] if flag else []
            )
        elif case.kind == contract.KIND_BEFORE_AFTER:
            choice = (
                "a"
                if mode == "all_yes"
                else "tie"
                if mode == "all_no"
                else contract.PREFERENCES[rng.below(3)]
            )
            head.update({"preferred": choice, "reason": "no_difference"})
        else:
            head["objects"] = ["red square"] if mode == "all_yes" else []
        out[case.case_id] = contract.canonical_json(head)
    return out


__all__ = [
    "baseline_responses",
    "generic_mentions",
    "score_answers",
    "score_findings",
    "score_objects",
    "score_run",
]
