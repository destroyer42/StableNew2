"""Vocabulary of the qualification ledger: statuses, evidence classes, verdicts and the six verdict dimensions."""

from __future__ import annotations

from enum import StrEnum


class Status(StrEnum):
    QUALIFIED = "QUALIFIED"
    PARTIALLY_QUALIFIED = "PARTIALLY QUALIFIED"
    FEASIBLE = "FEASIBLE"
    INCONCLUSIVE = "INCONCLUSIVE"
    NOT_TESTED = "NOT TESTED"
    HOLD = "HOLD"
    NO_GO = "NO-GO"
    UNSUPPORTED = "UNSUPPORTED"


STATUS_DEFINITIONS: dict[Status, str] = {
    Status.QUALIFIED: (
        "Resource, visual/product-quality and integration qualification are each backed by applicable physical evidence "
        "from an exact, still-matching model/workflow/runtime/hardware identity and an accepted acceptance contract."
    ),
    Status.PARTIALLY_QUALIFIED: (
        "At least one qualification dimension is backed by applicable physical evidence; at least one other is not."
    ),
    Status.FEASIBLE: (
        "A standalone feasibility harness completed on the target workstation; production-path integration and "
        "product-quality evidence are absent. Feasibility is not integration and not promotion."
    ),
    Status.INCONCLUSIVE: (
        "A physical attempt exists but its evidence is incomplete or its safety/teardown proof is missing, so it neither "
        "qualifies nor refuses the capability."
    ),
    Status.NOT_TESTED: "Implemented or registered, but no applicable physical evidence exists.",
    Status.HOLD: "Blocked by a named hold or a missing owner decision; no physical arm may be planned for it.",
    Status.NO_GO: "Refused on evidence (resource risk, repeatable failure or an explicit owner/policy refusal).",
    Status.UNSUPPORTED: "Not a supported StableNew capability (retired, absent backend route or never integrated).",
}

#: Statuses for which no executable physical arm may be planned.
NON_EXECUTABLE = frozenset({Status.HOLD, Status.NO_GO, Status.UNSUPPORTED})


class EvidenceKind(StrEnum):
    """What an evidence item can prove.  The classes are never interchangeable."""

    OFFLINE_CONTRACT = "offline_contract"  # unit/contract/readiness evidence, no inference
    STANDALONE_FEASIBILITY = (
        "standalone_feasibility"  # isolated harness inference, not the production path
    )
    PRODUCTION_WORKFLOW = "production_workflow"  # normal operator GUI + canonical execution path
    OWNER_DECISION = "owner_decision"  # a recorded owner decision or hold (not a measurement)

    @property
    def physical(self) -> bool:
        return self in (EvidenceKind.STANDALONE_FEASIBILITY, EvidenceKind.PRODUCTION_WORKFLOW)


class Confidence(StrEnum):
    HIGH = "high"  # a retained record names the exact source and the claim was re-checked against current code
    MEDIUM = "medium"  # a dated document states it; the record could not be re-verified here
    LOW = "low"  # inferred from structure; treat as a lead, not as evidence


class Verdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    HOLD = "HOLD"
    INCONCLUSIVE = "INCONCLUSIVE"
    NO_GO = "NO-GO"
    NOT_RUN = "NOT RUN"
    PENDING = "PENDING_OPERATOR_REVIEW"  # a human quality judgment that has not been made yet


class Dimension(StrEnum):
    FUNCTIONAL = "functional_correctness"
    RESOURCE_SAFETY = "resource_runtime_safety"
    ARTIFACT_INTEGRITY = "artifact_media_integrity"
    REPRODUCIBILITY = "reproducibility_provenance"
    QUALITY = "visual_or_suggestion_quality"
    USABILITY = "operator_usability"


DIMENSIONS = tuple(Dimension)
#: The dimensions an automated measure may decide; quality and usability are human judgments.
AUTOMATED_DIMENSIONS = (
    Dimension.FUNCTIONAL,
    Dimension.RESOURCE_SAFETY,
    Dimension.ARTIFACT_INTEGRITY,
    Dimension.REPRODUCIBILITY,
)
HUMAN_DIMENSIONS = (Dimension.QUALITY, Dimension.USABILITY)


def parse_status(value: str) -> Status:
    try:
        return Status(value)
    except ValueError:
        raise ValueError(
            f"unknown status {value!r}; allowed: {', '.join(s.value for s in Status)}"
        ) from None
