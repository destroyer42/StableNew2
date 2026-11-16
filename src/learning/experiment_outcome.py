"""The derived outcome of a Learning experiment, and the operator's closure of it.

The outcome is **derived**: ``derive_outcome`` is a pure function of a saved session payload and the saved ratings. It
reads no file, calls no backend and persists nothing, and it adds no threshold or evidence rule. Each study keeps its own
mechanism; this module only delegates to it and reports the result in one vocabulary:

* ordinary sweeps use the ``RecommendationEngine`` threshold constants (through ``evidence_progress``);
* 2 x 6 seed-paired pilots use ``intelligence_findings.conclude`` (the six-pair screening rule);
* every other cataloged study uses its own ``conclusion`` function, found through ``study_catalog``.

**Closure records an operator act, not a conclusion.** A closure is a small additive block in the session payload (when it
was closed, the evidence fingerprint at that moment, the outcome code at that moment and an optional note). It is written
only through ``LearningExperimentStore.set_closure`` and never touches jobs, the repository, the ratings file or any other
part of the session. The outcome is always re-derived; a closure whose fingerprint no longer matches the current evidence
is shown as "changed since closure". Closing an experiment that still has unrated images is allowed and is shown as
"insufficient evidence, closed by operator".
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.learning import study_catalog
from src.learning.evidence_progress import evidence_progress
from src.learning.experiment_conclusion import build_experiment_conclusion
from src.learning.experiment_lifecycle import has_successful_admission
from src.learning.intelligence_contracts import digest
from src.learning.intelligence_findings import conclude, invalid_evidence
from src.learning.intelligence_sources import (
    ExperimentView,
    project_experiment,
    valid_rating,
)

CLOSURE_KEY = "closure"
CLOSURE_SCHEMA = "learning_closure/1"

OUTCOME_AWAITING_EXECUTION = "awaiting_execution"
OUTCOME_NEEDS_EXECUTION_REVIEW = "needs_execution_review"
OUTCOME_AWAITING_RATINGS = "awaiting_ratings"
OUTCOME_SUPPORTED = "supported"
OUTCOME_INCONCLUSIVE = "inconclusive"
OUTCOME_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
OUTCOME_CODES = (
    OUTCOME_AWAITING_EXECUTION,
    OUTCOME_NEEDS_EXECUTION_REVIEW,
    OUTCOME_AWAITING_RATINGS,
    OUTCOME_SUPPORTED,
    OUTCOME_INCONCLUSIVE,
    OUTCOME_INSUFFICIENT_EVIDENCE,
)

LABELS = {
    OUTCOME_AWAITING_EXECUTION: "Generation not finished",
    OUTCOME_NEEDS_EXECUTION_REVIEW: "Needs execution review",
    OUTCOME_AWAITING_RATINGS: "Awaiting ratings",
    OUTCOME_SUPPORTED: "Finding supported",
    OUTCOME_INCONCLUSIVE: "Inconclusive",
    OUTCOME_INSUFFICIENT_EVIDENCE: "Insufficient evidence, closed by operator",
}
CHANGED_SINCE_CLOSURE = "changed since closure"

#: Variant statuses after which no job is still expected to change the evidence.
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "canceled", "uncontrolled"})
_ATTENTION_STATUS = "requires_attention"
_REPEAT_ADVICE = "Repeat the test under a different controlled prompt context; the same prompt cannot separate the values."

_FROM_PAYLOAD: Any = object()


class ClosureRefused(ValueError):
    """The experiment cannot be closed (or reopened) right now; the message says why."""


@dataclass(frozen=True)
class ExperimentOutcome:
    """One experiment's outcome in the single Learning vocabulary (derived, never stored)."""

    code: str
    study: str
    detail: str = ""
    #: Fewest further saved ratings that would let the study's own rule reach a conclusion (awaiting ratings only).
    ratings_needed: int = 0
    #: Generated, completed images that still have no saved rating.
    unrated: int = 0
    #: A plain recommended next test (inconclusive only).
    next_test: str = ""
    #: What the study may claim: its own claim, never upgraded here.
    claim: str = ""
    #: Only a controlled local study with a unique highest-rated candidate names one; envelope, exploratory and
    #: ordinary studies never claim a winner here.
    winner: Any = None
    fingerprint: str = ""
    closed: bool = False
    changed_since_closure: bool = False

    @property
    def label(self) -> str:
        if self.code == OUTCOME_AWAITING_RATINGS and self.ratings_needed:
            return f"{LABELS[self.code]} ({self.ratings_needed} more needed)"
        return LABELS[self.code]

    @property
    def text(self) -> str:
        """The one line shown for the experiment, including a closure and whether it changed after it."""
        parts = [self.label]
        if self.closed and self.code != OUTCOME_INSUFFICIENT_EVIDENCE:
            parts.append("closed by operator")
        if self.changed_since_closure:
            parts.append(CHANGED_SINCE_CLOSURE)
        return " - ".join(parts)


# ---------------------------------------------------------------------------------------------------------------------
# Inputs


def closure_of(payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The valid closure block of a session payload, else ``None`` (a malformed block is not a closure)."""
    block = (payload or {}).get(CLOSURE_KEY)
    if (
        isinstance(block, Mapping)
        and isinstance(block.get("closed_at"), str)
        and block["closed_at"]
        and isinstance(block.get("evidence_fingerprint"), str)
    ):
        return dict(block)
    return None


def overall_ratings(ratings: Mapping[str, Any] | None) -> dict[str, float]:
    """``{image path: overall 1-5 rating}`` from rating details (``{"overall_rating": n}``) or plain numbers."""
    result: dict[str, float] = {}
    for path, detail in (ratings or {}).items():
        raw = detail.get("overall_rating") if isinstance(detail, Mapping) else detail
        rating = valid_rating(raw)
        if rating is not None:
            result[str(path)] = rating
    return result


def _study_slug(view: ExperimentView) -> str:
    descriptor = study_catalog.lookup(view.study_type)
    return descriptor.slug if descriptor else view.study_type


def _fingerprint(study: str, view: ExperimentView, overall: Mapping[str, float]) -> str:
    """Digest of the evidence a conclusion rests on: outcomes of each variant and each saved rating of its images."""
    refs = sorted({ref for variant in view.variants for ref in variant.image_refs})
    return (
        "evd-"
        + digest(
            {
                "study": study,
                "variants": [
                    [v.variant_id, v.status, v.controlled, v.reason, sorted(v.image_refs)]
                    for v in view.variants
                ],
                "ratings": [[ref, overall[ref]] for ref in refs if ref in overall],
            }
        )[:24]
    )


def _variants(payload: Mapping[str, Any]) -> list[Any]:
    from src.gui.learning_state import LearningVariant

    return [
        LearningVariant.from_dict(dict(item))
        for item in (payload.get("plan") or [])
        if isinstance(item, Mapping)
    ]


# ---------------------------------------------------------------------------------------------------------------------
# Derivation


def _execution_problems(view: ExperimentView) -> list[str]:
    problems = invalid_evidence(view)
    for variant in view.variants:
        if variant.status in ("uncontrolled", "cancelled", "canceled"):
            problems.append(f"variant {variant.variant_id or '?'} is {variant.status}")
    return problems


def _needs_attention(payload: Mapping[str, Any]) -> bool:
    for item in payload.get("plan") or []:
        if not isinstance(item, Mapping):
            continue
        meta = item.get("execution_metadata")
        meta = meta if isinstance(meta, Mapping) else {}
        if (
            str(item.get("status") or "").strip().lower() == _ATTENTION_STATUS
            or meta.get("action_required")
            or meta.get("admission_error")
        ):
            return True
    current = payload.get("current_experiment")
    metadata = current.get("metadata") if isinstance(current, Mapping) else None
    return bool(isinstance(metadata, Mapping) and metadata.get("resume_persistence_error"))


def _unrated_images(view: ExperimentView, overall: Mapping[str, float]) -> list[tuple[str, str]]:
    return [(variant, image) for variant, image in view.images if image not in overall]


def _ordinary(
    view: ExperimentView, overall: Mapping[str, float], base: dict[str, Any], next_test: str
) -> ExperimentOutcome:
    pilot = conclude(view, overall)
    if pilot is not None and pilot.status == "supported":
        return ExperimentOutcome(OUTCOME_SUPPORTED, detail=pilot.text, **base)
    if pilot is not None and pilot.status == "inconclusive":
        return ExperimentOutcome(
            OUTCOME_INCONCLUSIVE, detail=pilot.text, next_test=_REPEAT_ADVICE, **base
        )
    if pilot is not None and pilot.status == "insufficient":
        first, second = view.variants[0], view.variants[1]
        needed = sum(
            (a not in overall) + (b not in overall)
            for a, b in zip(first.image_refs, second.image_refs, strict=True)
        )
        return ExperimentOutcome(
            OUTCOME_AWAITING_RATINGS, detail=pilot.text, ratings_needed=needed, **base
        )
    # No screening rule applies to this design: the recommendation engine's own thresholds decide.
    per_value = [sum(ref in overall for ref in v.image_refs) for v in view.variants]
    progress = evidence_progress(per_value)
    if progress.ready:
        return ExperimentOutcome(
            OUTCOME_SUPPORTED,
            detail=f"{progress.ratings} controlled ratings across {progress.values_rated} tested values "
            "meet the recommendation thresholds.",
            **base,
        )
    unrated = _unrated_images(view, overall)
    open_values = sum(
        1
        for variant, count in zip(view.variants, per_value, strict=True)
        if not count and any(image not in overall for image in variant.image_refs)
    )
    needed = max(progress.ratings_needed, progress.values_needed)
    if progress.values_needed <= open_values and len(unrated) >= needed:
        return ExperimentOutcome(
            OUTCOME_AWAITING_RATINGS, detail=progress.message(), ratings_needed=needed, **base
        )
    return ExperimentOutcome(
        OUTCOME_INCONCLUSIVE,
        detail=f"{progress.message()} No unrated image remains that could supply them.",
        next_test=next_test,
        **base,
    )


def _by_class(
    study: str,
    descriptor: study_catalog.StudyDescriptor,
    variants: list[Any],
    overall: Mapping[str, float],
    base: dict[str, Any],
) -> ExperimentOutcome:
    details = {path: {"overall_rating": rating} for path, rating in overall.items()}
    result = build_experiment_conclusion(variants, details, {}, study_type=study)
    rows = list(result.get("values") or [])
    unsaved = [row for row in rows if not row.get("saved_count")]
    base = {**base, "claim": str(result.get("comparison_claim") or descriptor.evidence_class)}
    unreachable = len(rows) < 2 or any(not row.get("sample_count") for row in unsaved)
    if unsaved:
        if unreachable:
            return ExperimentOutcome(
                OUTCOME_INCONCLUSIVE,
                detail="Not every tested value has generated images that could be rated.",
                next_test=descriptor.next_test,
                **base,
            )
        return ExperimentOutcome(
            OUTCOME_AWAITING_RATINGS,
            detail=f"{len(unsaved)} tested value(s) still have no saved rating.",
            ratings_needed=len(unsaved),
            **base,
        )
    if descriptor.evidence_class == study_catalog.CLASS_EXPLORATORY:
        return ExperimentOutcome(
            OUTCOME_INCONCLUSIVE,
            detail="Every value is rated; this study is descriptive and chooses no winner.",
            next_test=descriptor.next_test,
            **base,
        )
    if not result.get("sufficient_evidence"):
        return ExperimentOutcome(
            OUTCOME_INCONCLUSIVE,
            detail=str(result.get("message") or "The saved ratings are not sufficient."),
            next_test=descriptor.next_test,
            **base,
        )
    models = result.get("models")
    all_tied = (
        isinstance(models, Mapping)
        and bool(models)
        and all(item.get("status") == "tie" for item in models.values())
    )
    winner = (
        result.get("best_value") if descriptor.evidence_class == study_catalog.CLASS_LOCAL else None
    )
    tied_local = descriptor.evidence_class == study_catalog.CLASS_LOCAL and winner is None
    if all_tied or tied_local:
        return ExperimentOutcome(
            OUTCOME_INCONCLUSIVE,
            detail="The saved ratings tie; no candidate is unique.",
            next_test=descriptor.next_test,
            **base,
        )
    return ExperimentOutcome(
        OUTCOME_SUPPORTED, detail=str(result.get("message") or ""), winner=winner, **base
    )


def derive_outcome(
    payload: Mapping[str, Any] | None,
    ratings: Mapping[str, Any] | None,
    *,
    closure: Mapping[str, Any] | None = _FROM_PAYLOAD,
) -> ExperimentOutcome:
    """The outcome of one saved experiment: pure, deterministic and always re-derived.

    ``ratings`` maps an image path to its saved rating detail (``{"overall_rating": n}``) or to the number itself.
    ``closure`` defaults to the payload's own block; pass ``None`` to ignore it.
    """
    payload = payload or {}
    block = closure_of(payload) if closure is _FROM_PAYLOAD else closure_of({CLOSURE_KEY: closure})
    overall = overall_ratings(ratings)
    try:
        view = project_experiment(
            str((payload.get("current_experiment") or {}).get("experiment_id") or ""), payload
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        return ExperimentOutcome(
            OUTCOME_NEEDS_EXECUTION_REVIEW,
            "unknown",
            detail="The saved experiment could not be read; open it to reconcile.",
        )
    study = _study_slug(view)
    fingerprint = _fingerprint(study, view, overall)
    descriptor = study_catalog.lookup(study)
    base: dict[str, Any] = {"study": study, "fingerprint": fingerprint}
    base["unrated"] = len(_unrated_images(view, overall))
    outcome = _derive_base(payload, view, study, descriptor, overall, base)
    if block is None:
        return outcome
    changed = block.get("evidence_fingerprint") != fingerprint
    code = (
        OUTCOME_INSUFFICIENT_EVIDENCE if outcome.code == OUTCOME_AWAITING_RATINGS else outcome.code
    )
    return ExperimentOutcome(
        code,
        outcome.study,
        detail=outcome.detail,
        ratings_needed=outcome.ratings_needed,
        unrated=outcome.unrated,
        next_test=outcome.next_test,
        claim=outcome.claim,
        winner=outcome.winner,
        fingerprint=outcome.fingerprint,
        closed=True,
        changed_since_closure=changed,
    )


def _derive_base(
    payload: Mapping[str, Any],
    view: ExperimentView,
    study: str,
    descriptor: study_catalog.StudyDescriptor | None,
    overall: Mapping[str, float],
    base: dict[str, Any],
) -> ExperimentOutcome:
    if not has_successful_admission(payload):
        return ExperimentOutcome(
            OUTCOME_AWAITING_EXECUTION, detail="No job has been admitted yet.", **base
        )
    if _needs_attention(payload):
        return ExperimentOutcome(
            OUTCOME_NEEDS_EXECUTION_REVIEW,
            detail="An admission or resume step needs attention; open the experiment to reconcile.",
            **base,
        )
    if any(v.status.lower() not in TERMINAL_STATUSES for v in view.variants):
        return ExperimentOutcome(
            OUTCOME_AWAITING_EXECUTION, detail="Generation has not finished.", **base
        )
    problems = _execution_problems(view)
    if problems or not any(v.status == "completed" for v in view.variants):
        shown = "; ".join(problems[:3]) or "no variant completed"
        return ExperimentOutcome(
            OUTCOME_NEEDS_EXECUTION_REVIEW,
            detail=f"Execution evidence is not valid: {shown}.",
            **base,
        )
    if descriptor is None:
        return ExperimentOutcome(
            OUTCOME_INCONCLUSIVE,
            detail=f"No outcome rule is cataloged for study type {study!r}.",
            **base,
        )
    if descriptor.evidence_class == study_catalog.CLASS_CONTROLLED:
        return _ordinary(
            view, overall, {**base, "claim": "controlled_variable"}, descriptor.next_test
        )
    return _by_class(study, descriptor, _variants(payload), overall, base)


# ---------------------------------------------------------------------------------------------------------------------
# Closure (an operator act; the store writes it)


def closure_blocker(payload: Mapping[str, Any] | None) -> str:
    """Why this experiment cannot be closed yet (empty when it can)."""
    if not has_successful_admission(payload):
        return "Run the experiment before closing it."
    statuses = [
        str(item.get("status") or "").strip().lower()
        for item in (payload or {}).get("plan") or []
        if isinstance(item, Mapping)
    ]
    if any(status not in TERMINAL_STATUSES for status in statuses):
        return (
            "Generation has not finished. Close the experiment after every variant has completed, "
            "failed or been cancelled."
        )
    return ""


def build_closure(
    payload: Mapping[str, Any],
    ratings: Mapping[str, Any] | None,
    *,
    note: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """The closure block for the evidence as it is right now (pure; nothing is saved)."""
    reason = closure_blocker(payload)
    if reason:
        raise ClosureRefused(reason)
    outcome = derive_outcome(payload, ratings, closure=None)
    code = (
        OUTCOME_INSUFFICIENT_EVIDENCE if outcome.code == OUTCOME_AWAITING_RATINGS else outcome.code
    )
    return {
        "schema": CLOSURE_SCHEMA,
        "closed_at": (now or datetime.now(UTC)).isoformat(),
        "evidence_fingerprint": outcome.fingerprint,
        "outcome_code": code,
        "note": str(note or "").strip(),
    }


def close_experiment(
    store: Any,
    experiment_id: str,
    payload: Mapping[str, Any],
    ratings: Mapping[str, Any] | None,
    *,
    note: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Record the operator's closure in the saved session (the closure block only); returns the block.

    ``payload`` is the experiment as the operator sees it (the open session or the stored one). Only
    ``LearningExperimentStore.set_closure`` writes; no job, repository, rating or draft is touched.
    """
    closure = build_closure(payload, ratings, note=note, now=now)
    if not store.set_closure(experiment_id, closure):
        raise ClosureRefused("This experiment has no saved session to close. Save it first.")
    return closure


def reopen_experiment(store: Any, experiment_id: str) -> bool:
    """Remove the closure block (and nothing else); returns whether the session had one."""
    had = closure_of(store.load_session(experiment_id)) is not None
    if not store.set_closure(experiment_id, None):
        raise ClosureRefused("This experiment has no saved session to reopen.")
    return had
