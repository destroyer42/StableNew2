"""Per-dimension verdict classification and status proposals.

Automated measures decide only the automated dimensions.  Visual/suggestion quality and operator usability are human
judgments: an automated similarity or metric is recorded as a measure and can never turn them into PASS.  Incomplete,
unsealed or tampered evidence is INCONCLUSIVE, never PASS.  A status *proposal* never changes the ledger and never
promotes anything; promotion is a separate owner decision.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from tools.qualification.system840 import evidence
from tools.qualification.system840.safety import RESOURCE_STOPS
from tools.qualification.system840.statuses import (
    AUTOMATED_DIMENSIONS,
    DIMENSIONS,
    HUMAN_DIMENSIONS,
    Dimension,
    EvidenceKind,
    Status,
    Verdict,
)

_RANK = {
    Verdict.PASS: 0,
    Verdict.PENDING: 1,
    Verdict.NOT_RUN: 2,
    Verdict.INCONCLUSIVE: 3,
    Verdict.HOLD: 4,
    Verdict.FAIL: 5,
    Verdict.NO_GO: 6,
}


def worst(verdicts: Sequence[Verdict]) -> Verdict:
    return max(verdicts, key=lambda v: _RANK[v]) if verdicts else Verdict.NOT_RUN


def _entry(verdict: Verdict, reason: str) -> dict[str, str]:
    return {"verdict": verdict.value, "reason": reason}


def classify_attempt(
    plan: Mapping[str, Any],
    observations: Mapping[str, Any],
    *,
    verification: Mapping[str, Any],
    media_reports: Sequence[Mapping[str, Any]] = (),
    human_ratings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the six dimension verdicts, the overall automated verdict and the reasons.

    ``observations`` keys: ``jobs_admitted``, ``artifacts``, ``stop`` (a stop-condition name or ``None``),
    ``teardown_clean`` (bool or ``None`` when unproven), ``identity_verified``, ``telemetry`` (the
    ``safety.evaluate_telemetry`` result), ``provenance_complete`` and optional ``automated_measures``.
    ``human_ratings`` carries ``quality`` and ``usability`` as ``{"verdict": "PASS"|"FAIL", "rated_by": ...}``.
    """

    dims: dict[str, dict[str, str]] = {}
    sealed = verification.get("status") == evidence.OK
    if not sealed:
        reason = f"evidence is {verification.get('status')}: " + "; ".join(
            list(verification.get("problems") or [])[:2]
        )
        dims = {d.value: _entry(Verdict.INCONCLUSIVE, reason) for d in AUTOMATED_DIMENSIONS}
        for d in HUMAN_DIMENSIONS:
            dims[d.value] = _entry(Verdict.INCONCLUSIVE, reason)
        return _finish(dims, observations, complete=False)

    stop = observations.get("stop")
    telemetry = observations.get("telemetry") or {}
    telemetry_stop = telemetry.get("stop")
    teardown = observations.get("teardown_clean")
    identity = observations.get("identity_verified")
    expected_jobs, expected_artifacts = int(plan.get("jobs", 0)), int(plan.get("artifacts", 0))

    # Functional correctness.
    admitted, produced = observations.get("jobs_admitted"), observations.get("artifacts")
    if admitted is None or produced is None:
        dims[Dimension.FUNCTIONAL.value] = _entry(
            Verdict.INCONCLUSIVE, "job and artifact counts were not recorded"
        )
    elif stop in ("ambiguous_dispatch", "identity_mismatch", "operator_cancel"):
        dims[Dimension.FUNCTIONAL.value] = _entry(Verdict.INCONCLUSIVE, f"stopped: {stop}")
    elif stop and stop not in RESOURCE_STOPS:
        dims[Dimension.FUNCTIONAL.value] = _entry(Verdict.FAIL, f"stopped: {stop}")
    elif stop:
        dims[Dimension.FUNCTIONAL.value] = _entry(
            Verdict.FAIL, f"resource stop before completion: {stop}"
        )
    elif admitted >= expected_jobs and produced >= expected_artifacts:
        dims[Dimension.FUNCTIONAL.value] = _entry(
            Verdict.PASS, f"{produced}/{expected_artifacts} artifacts from {admitted} jobs"
        )
    else:
        dims[Dimension.FUNCTIONAL.value] = _entry(
            Verdict.FAIL, f"{produced}/{expected_artifacts} artifacts from {admitted} jobs"
        )

    # Runtime and resource safety.
    if telemetry_stop == "telemetry_gap" or not telemetry:
        dims[Dimension.RESOURCE_SAFETY.value] = _entry(
            Verdict.INCONCLUSIVE, "telemetry is missing or has a gap"
        )
    elif teardown is not True:
        dims[Dimension.RESOURCE_SAFETY.value] = _entry(
            Verdict.INCONCLUSIVE, "safe teardown is not proven"
        )
    elif identity is not True:
        dims[Dimension.RESOURCE_SAFETY.value] = _entry(
            Verdict.INCONCLUSIVE, "runtime identity was not verified"
        )
    elif stop in RESOURCE_STOPS or telemetry_stop in RESOURCE_STOPS:
        dims[Dimension.RESOURCE_SAFETY.value] = _entry(
            Verdict.NO_GO,
            f"definitive resource refusal of the tested envelope: {stop or telemetry_stop}",
        )
    elif stop == "timeout":
        dims[Dimension.RESOURCE_SAFETY.value] = _entry(Verdict.FAIL, "timeout")
    else:
        dims[Dimension.RESOURCE_SAFETY.value] = _entry(
            Verdict.PASS, "telemetry intact, teardown verified, no stop condition"
        )

    # Artifact and media integrity.
    if expected_artifacts and not media_reports:
        dims[Dimension.ARTIFACT_INTEGRITY.value] = _entry(
            Verdict.INCONCLUSIVE, "no retained media was validated"
        )
    elif any(not r.get("valid") for r in media_reports):
        bad = [r.get("path") for r in media_reports if not r.get("valid")]
        dims[Dimension.ARTIFACT_INTEGRITY.value] = _entry(
            Verdict.FAIL, f"undecodable media: {', '.join(map(str, bad[:3]))}"
        )
    else:
        dims[Dimension.ARTIFACT_INTEGRITY.value] = _entry(
            Verdict.PASS,
            f"{len(media_reports)} retained file(s) decode; sizes and SHA-256 verified",
        )

    # Reproducibility and provenance.
    if identity is False:
        dims[Dimension.REPRODUCIBILITY.value] = _entry(
            Verdict.FAIL, "an identity differed from the frozen plan"
        )
    elif identity is None or not observations.get("provenance_complete"):
        dims[Dimension.REPRODUCIBILITY.value] = _entry(
            Verdict.INCONCLUSIVE, "identity or provenance record is incomplete"
        )
    else:
        dims[Dimension.REPRODUCIBILITY.value] = _entry(
            Verdict.PASS, "frozen plan, identities and provenance recorded"
        )

    # Human dimensions: automated measures never decide them.
    ratings = human_ratings or {}
    for dim, key in ((Dimension.QUALITY, "quality"), (Dimension.USABILITY, "usability")):
        rating = ratings.get(key)
        if (
            rating
            and str(rating.get("verdict")).upper() in ("PASS", "FAIL")
            and rating.get("rated_by")
        ):
            dims[dim.value] = _entry(
                Verdict(str(rating["verdict"]).upper()), f"operator rating by {rating['rated_by']}"
            )
        else:
            dims[dim.value] = _entry(
                Verdict.PENDING, "awaiting a human judgment; automated measures do not decide this"
            )
    return _finish(dims, observations, complete=True)


def _finish(
    dims: dict[str, dict[str, str]], observations: Mapping[str, Any], *, complete: bool
) -> dict[str, Any]:
    automated = worst([Verdict(dims[d.value]["verdict"]) for d in AUTOMATED_DIMENSIONS])
    human = [Verdict(dims[d.value]["verdict"]) for d in HUMAN_DIMENSIONS]
    pending = any(v == Verdict.PENDING for v in human)
    overall = (
        automated
        if automated != Verdict.PASS
        else worst([Verdict.PASS, *[v for v in human if v != Verdict.PENDING]])
    )
    return {
        "dimensions": {d.value: dims[d.value] for d in DIMENSIONS},
        "overall": overall.value,
        "human_review_pending": pending,
        "complete": complete and not pending,
        "automated_measures": dict(observations.get("automated_measures") or {}),
        "note": "automated measures are recorded beside, never in place of, the human quality and usability judgments",
    }


def propose_status(
    current: Status,
    kind: EvidenceKind,
    result: Mapping[str, Any],
    *,
    prior_dimensions_qualified: bool = False,
) -> dict[str, Any]:
    """What the evidence could support.  A proposal only: the ledger changes by owner-accepted edit, never here."""

    overall = Verdict(result["overall"])
    dims = result["dimensions"]
    resource = Verdict(dims[Dimension.RESOURCE_SAFETY.value]["verdict"])
    quality = Verdict(dims[Dimension.QUALITY.value]["verdict"])
    if resource == Verdict.NO_GO or overall == Verdict.NO_GO:
        proposed, why = Status.NO_GO, "a definitive resource refusal"
    elif overall in (Verdict.INCONCLUSIVE, Verdict.HOLD):
        proposed, why = (
            (current if current == Status.HOLD else Status.INCONCLUSIVE),
            "evidence is incomplete or held",
        )
    elif overall == Verdict.FAIL:
        proposed, why = current, "the attempt failed; the existing status is unchanged"
    elif kind == EvidenceKind.PRODUCTION_WORKFLOW:
        proposed, why = (
            Status.PARTIALLY_QUALIFIED,
            "production-path attempt passed its automated dimensions",
        )
        if quality == Verdict.PASS and prior_dimensions_qualified:
            proposed, why = Status.QUALIFIED, "all dimensions passed with a human quality judgment"
    elif kind == EvidenceKind.STANDALONE_FEASIBILITY:
        proposed, why = (
            Status.FEASIBLE,
            "standalone harness passed; production integration is separate",
        )
    else:
        proposed, why = current, "offline evidence cannot change a physical status"
    return {
        "current": current.value,
        "proposed": proposed.value,
        "reason": why,
        "requires_owner_acceptance": True,
        "ledger_changed": False,
        "promotion": "NOT AUTHORIZED",
        "eligible_for_promotion_review": proposed == Status.QUALIFIED,
    }
