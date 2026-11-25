"""Case set and scorer for AI Assist slot suggestions (AI-230f).

Pure and offline: nothing here starts a process, uses the network or reads a model. ``run_cases`` takes any callable that turns
a request into the model's raw text (a fake in tests; the operator CLI in ``__main__`` supplies a loopback Ollama call), then
scores every answer with the production validator and the production judges (``judge_variety`` / ``judge_proposals``), so a
result means exactly what the dialog would have shown the operator.

The cases are synthetic. They are modeled on the goals an operator actually types (lighting for a photographic look, a
companion or pet, interesting environments, camera angle, atmosphere) but contain no pack content. A result records case ids,
outcome codes, counts and judge reason codes only; no goal, sentence, slot name or suggested value is ever stored (AI Assist
invariant: nothing derived from prompts is persisted beyond digests, counts and codes).
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from src.ai_assist.contracts import AssistRequest, OutcomeCode
from src.ai_assist.framing import build_json_schema
from src.ai_assist.remote import _wire_problem
from src.ai_assist.validators import validate_output
from src.gui_v2.ai_slot_proposal import (
    build_context,
    build_proposal_request,
    compute_insertion_points,
    judge_proposals,
)
from src.gui_v2.ai_slot_variety import (
    build_variety_request,
    judge_variety,
    matrix_state,
)

KIND_VARIETY = "variety"
KIND_PROPOSAL = "proposal"
RESULT_SCHEMA = "stablenew.ai230.slot_cases.v1"

Slots = tuple[tuple[str, tuple[str, ...]], ...]

_KNIGHT = "a knight in a forest, wearing armor, at dusk"
_PORTRAIT = "portrait of a woman in a cafe, soft expression, shallow depth of field"
_CITY = "a lone traveler walking through an old city, cinematic composition"
_ROOM = "a cozy reading room with a large window and a worn armchair"


@dataclass(frozen=True, slots=True)
class SlotCase:
    case_id: str
    kind: str
    goal: str
    sentence: str = ""
    slots: Slots = ()
    select: tuple[str, ...] = ()
    per_slot: int = 3
    focus: str = "direct"


CASES: tuple[SlotCase, ...] = (
    SlotCase(
        "var-lighting-photo",
        KIND_VARIETY,
        "lighting that looks like real photography",
        slots=(("lighting", ("soft light", "golden hour")), ("location", ("cafe", "street"))),
        select=("lighting",),
    ),
    SlotCase(
        "var-environment-unique",
        KIND_VARIETY,
        "unique and visually interesting environments",
        slots=(("environment", ("forest", "desert")), ("character", ("knight", "ranger"))),
        select=("environment",),
        per_slot=5,
    ),
    SlotCase(
        "var-hair-explore",
        KIND_VARIETY,
        "bolder hair options",
        slots=(("hair_color", ("black", "brown")), ("hair_type", ("straight", "wavy"))),
        select=("hair_color", "hair_type"),
        focus="explore",
    ),
    SlotCase(
        "var-clothing-formal",
        KIND_VARIETY,
        "formal evening wear",
        slots=(("clothes", ("gown", "tuxedo")), ("activity", ("dancing", "reading"))),
        select=("clothes",),
    ),
    SlotCase(
        "var-two-slots",
        KIND_VARIETY,
        "more variety in the camera work and the setting",
        slots=(("perspective", ("close-up", "wide shot")), ("location", ("harbor", "market"))),
        select=("perspective", "location"),
        per_slot=2,
    ),
    SlotCase(
        "prop-lighting-hyperreal",
        KIND_PROPOSAL,
        "better lighting for hyperrealism",
        sentence=_KNIGHT,
        slots=(("location", ("forest", "harbor")),),
    ),
    SlotCase(
        "prop-companion",
        KIND_PROPOSAL,
        "with a companion or pet",
        sentence=_KNIGHT,
        slots=(("location", ("forest", "harbor")),),
    ),
    SlotCase(
        "prop-camera",
        KIND_PROPOSAL,
        "different camera angles",
        sentence=_PORTRAIT,
        slots=(("mood", ("calm", "wistful")),),
    ),
    SlotCase(
        "prop-atmosphere",
        KIND_PROPOSAL,
        "more atmosphere and weather",
        sentence=_CITY,
        slots=(("era", ("medieval", "victorian")),),
    ),
    SlotCase(
        "prop-time-of-day",
        KIND_PROPOSAL,
        "different times of day",
        sentence=_ROOM,
        slots=(("furniture", ("armchair", "sofa")),),
    ),
)


def _slot_objects(slots: Slots) -> list[Any]:
    return [SimpleNamespace(name=name, values=list(values)) for name, values in slots]


def build_case_request(case: SlotCase, request_id: str = "a" * 32) -> AssistRequest:
    """The production request for ``case``, built by the production constructors."""

    states = matrix_state(_slot_objects(case.slots))
    if case.kind == KIND_VARIETY:
        return build_variety_request(
            request_id,
            case.goal,
            states,
            content_class="standard",
            selected=case.select,
            per_slot=case.per_slot,
            focus=case.focus,
        )
    return build_proposal_request(
        request_id, case.goal, case.sentence, states, content_class="standard"
    )[0]


@dataclass(frozen=True, slots=True)
class CaseResult:
    """Counts and codes for one case. Holds no authored or model text."""

    case_id: str
    kind: str
    code: str
    reason: str = ""
    returned: int = 0
    offered: int = 0
    rejected: int = 0
    reject_reasons: tuple[tuple[str, int], ...] = field(default=(), repr=False)
    seconds: float = 0.0


def score_case(case: SlotCase, raw_text: str, *, seconds: float = 0.0) -> CaseResult:
    """Validate ``raw_text`` for ``case`` and judge it exactly as the dialog would."""

    request = build_case_request(case)
    # The same envelope check Remote Preview applies before the shared validator (field set, string types, duplicate keys).
    wire = _wire_problem(raw_text, build_json_schema(request))
    if wire:
        return CaseResult(case.case_id, case.kind, OutcomeCode.MALFORMED.value, wire, seconds=seconds)
    validated = validate_output(raw_text, request)
    if validated.suggestion is None:
        return CaseResult(
            case.case_id, case.kind, validated.code.value, validated.reason, seconds=seconds
        )
    suggestion = validated.suggestion
    visible: Callable[[str], bool] = lambda _text: True  # noqa: E731 - the cases hold no hidden content
    if case.kind == KIND_VARIETY:
        rows = judge_variety(suggestion, matrix_state(_slot_objects(case.slots)), is_visible=visible)
        reasons = Counter(row.reason for row in rows if row.reason)
        offered = sum(row.offered for row in rows)
        total = len(rows)
    else:
        points = compute_insertion_points(case.sentence)
        context = build_context(
            0, 0, 0, case.sentence, _slot_objects(case.slots), points, ""
        )
        mapping = {
            "enabled": True,
            "slots": [{"name": n, "values": list(v)} for n, v in case.slots],
        }
        prows = judge_proposals(
            suggestion, request, context, matrix_mapping=mapping, is_visible=visible
        )
        reasons = Counter(row.reason for row in prows if row.reason)
        offered = sum(row.offered for row in prows)
        total = len(prows)
    return CaseResult(
        case.case_id,
        case.kind,
        OutcomeCode.SUGGESTION.value,
        "",
        returned=total,
        offered=offered,
        rejected=total - offered,
        reject_reasons=tuple(sorted(reasons.items())),
        seconds=seconds,
    )


def run_cases(
    generate: Callable[[AssistRequest], str],
    cases: Sequence[SlotCase] = CASES,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[CaseResult, ...]:
    """Run every case through ``generate`` (request in, raw model text out) and score each answer. A generator that raises
    is recorded as ``unavailable`` for that case and the run continues."""

    results: list[CaseResult] = []
    for case in cases:
        request = build_case_request(case)
        started = clock()
        try:
            raw = generate(request)
        except Exception:  # noqa: BLE001 - recorded as a code, never the exception text
            results.append(
                CaseResult(case.case_id, case.kind, OutcomeCode.UNAVAILABLE.value, "generator_error")
            )
            continue
        results.append(score_case(case, raw, seconds=round(clock() - started, 3)))
    return tuple(results)


def summarize(results: Sequence[CaseResult]) -> dict[str, Any]:
    """Rates per kind, from counts and codes only."""

    summary: dict[str, Any] = {"schema": RESULT_SCHEMA, "cases": len(results), "kinds": {}}
    for kind in (KIND_VARIETY, KIND_PROPOSAL):
        mine = [r for r in results if r.kind == kind]
        if not mine:
            continue
        valid = [r for r in mine if r.code == OutcomeCode.SUGGESTION.value]
        reasons: Counter[str] = Counter()
        for result in mine:
            reasons.update(dict(result.reject_reasons))
        summary["kinds"][kind] = {
            "cases": len(mine),
            "valid": len(valid),
            "refused": sum(r.code == OutcomeCode.REFUSED_BY_MODEL.value for r in mine),
            "malformed": sum(r.code == OutcomeCode.MALFORMED.value for r in mine),
            "other": sum(
                r.code
                not in {
                    OutcomeCode.SUGGESTION.value,
                    OutcomeCode.REFUSED_BY_MODEL.value,
                    OutcomeCode.MALFORMED.value,
                }
                for r in mine
            ),
            "returned": sum(r.returned for r in mine),
            "offered": sum(r.offered for r in mine),
            "rejected": sum(r.rejected for r in mine),
            "cases_with_an_offer": sum(r.offered > 0 for r in mine),
            "reject_reasons": dict(sorted(reasons.items())),
            "seconds": round(sum(r.seconds for r in mine), 3),
        }
    return summary


__all__ = [
    "CASES",
    "KIND_PROPOSAL",
    "KIND_VARIETY",
    "RESULT_SCHEMA",
    "CaseResult",
    "SlotCase",
    "build_case_request",
    "run_cases",
    "score_case",
    "summarize",
]
