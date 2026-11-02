"""Verdicts and the guarded phase runner for the Fun Control 5B qualification.

``run_qualification`` can only reach an executor when (a) Q0 is READY for this exact plan and (b) an ``Authorization`` bound to the
plan's digest is supplied.  This package ships no physical executor: tests drive it with fakes, and a future authorized session
supplies its own.  Verdicts are NOT RUN / INCONCLUSIVE / FEASIBLE / NO-GO and FEASIBLE is technical feasibility only, never a
quality claim or a change to the immutable catalog policy.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Protocol

from tools.qualification.fun354.plan import (
    PHASE_Q0,
    RESOURCE_STOPS,
    STOP_IDENTITY,
    STOP_OPERATOR,
    STOP_TEARDOWN,
    STOP_TELEMETRY,
    STOP_TIMEOUT,
    CasePlan,
    PhasePlan,
    QualificationPlan,
)
from tools.qualification.fun354.q0 import Q0Report

NOT_RUN, INCONCLUSIVE, FEASIBLE, NO_GO = "NOT RUN", "INCONCLUSIVE", "FEASIBLE", "NO-GO"
SCOPE = "physical_execution"
EXECUTOR_ERROR = "executor_error"


@dataclass(frozen=True)
class Authorization:
    """An owner's explicit go-ahead for exactly one plan digest."""

    plan_digest: str
    authorized_by: str
    scope: str = SCOPE


@dataclass(frozen=True)
class CaseObservation:
    phase_id: str
    case_id: str
    completed: bool
    frames_expected: int
    frames_delivered: int
    stop_code: str = ""
    identity_verified: bool = True
    telemetry_complete: bool = True
    teardown_clean: bool = True
    peak_host_commit_fraction: float | None = None
    min_available_ram_mib: int | None = None
    peak_vram_mib: int | None = None
    wall_seconds: float = 0.0
    note: str = ""


class CaseExecutor(Protocol):
    def run_case(
        self, plan: QualificationPlan, phase: PhasePlan, case: CasePlan
    ) -> CaseObservation: ...


@dataclass(frozen=True)
class Outcome:
    verdict: str
    reason: str
    observations: tuple[CaseObservation, ...]
    q0_status: str

    def to_record(self) -> dict[str, object]:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "q0_status": self.q0_status,
            "observations": [asdict(o) for o in self.observations],
            "scope": "technical feasibility on this host only; not visual quality; the frozen catalog policy is unchanged",
        }


def _clean(obs: CaseObservation) -> bool:
    return (
        obs.completed
        and not obs.stop_code
        and obs.frames_delivered == obs.frames_expected
        and obs.identity_verified
        and obs.telemetry_complete
        and obs.teardown_clean
    )


def judge(plan: QualificationPlan, observations: Sequence[CaseObservation]) -> tuple[str, str]:
    """Pure verdict from what was observed; absence of evidence is never FEASIBLE."""

    if not observations:
        return NOT_RUN, "No physical case was executed."
    expected = {c.case_id for c in plan.physical_cases}
    seen = {o.case_id for o in observations}
    for obs in observations:
        if not obs.identity_verified or obs.stop_code == STOP_IDENTITY:
            return (
                INCONCLUSIVE,
                f"{obs.case_id}: runtime, graph or input identity was not verified.",
            )
    for obs in observations:
        if obs.stop_code in RESOURCE_STOPS:
            if obs.telemetry_complete:
                return (
                    NO_GO,
                    f"{obs.case_id}: {obs.stop_code} with complete telemetry at {obs.peak_host_commit_fraction}/{obs.peak_vram_mib}.",
                )
            return INCONCLUSIVE, f"{obs.case_id}: {obs.stop_code} but telemetry was incomplete."
    for obs in observations:
        if obs.stop_code in {
            STOP_TIMEOUT,
            STOP_TELEMETRY,
            STOP_OPERATOR,
            STOP_TEARDOWN,
            EXECUTOR_ERROR,
        }:
            return INCONCLUSIVE, f"{obs.case_id}: stopped by {obs.stop_code}."
        if not obs.telemetry_complete:
            return INCONCLUSIVE, f"{obs.case_id}: telemetry was incomplete."
        if not obs.teardown_clean:
            return INCONCLUSIVE, f"{obs.case_id}: the owned runtime did not release cleanly."
        if obs.completed and obs.frames_delivered != obs.frames_expected:
            return (
                INCONCLUSIVE,
                f"{obs.case_id}: delivered {obs.frames_delivered} of {obs.frames_expected} frames.",
            )
        if not obs.completed:
            return INCONCLUSIVE, f"{obs.case_id}: did not complete."
    if not expected <= seen:
        return INCONCLUSIVE, f"Not every planned case ran: missing {sorted(expected - seen)}."
    return (
        FEASIBLE,
        "Every planned case completed with exact frames, complete telemetry and clean teardown.",
    )


def run_qualification(
    plan: QualificationPlan,
    q0: Q0Report,
    executor: CaseExecutor,
    authorization: Authorization | None,
) -> Outcome:
    """Run Q1 then Q2 through ``executor``; stops at the first non-clean case and never retries."""

    if (
        authorization is None
        or authorization.scope != SCOPE
        or authorization.plan_digest != plan.digest
    ):
        return Outcome(
            NOT_RUN, "Physical execution is not authorized for this plan digest.", (), q0.status
        )
    if q0.plan_digest != plan.digest:
        return Outcome(NOT_RUN, "The Q0 report belongs to a different plan.", (), q0.status)
    if not q0.ready:
        reasons = (
            "; ".join(f"{c.check_id}: {c.detail}" for c in q0.blockers) or f"Q0 is {q0.status}."
        )
        return Outcome(NOT_RUN, f"Q0 is not READY: {reasons}", (), q0.status)

    observations: list[CaseObservation] = []
    for phase in plan.phases:
        if phase.phase_id == PHASE_Q0 or not phase.physical:
            continue
        for case in phase.cases:
            try:
                obs = executor.run_case(plan, phase, case)
            except Exception as exc:  # noqa: BLE001 - recorded, never retried
                obs = CaseObservation(
                    phase.phase_id,
                    case.case_id,
                    False,
                    case.frames,
                    0,
                    stop_code=EXECUTOR_ERROR,
                    note=str(exc),
                )
            if obs.case_id != case.case_id or obs.phase_id != phase.phase_id:
                obs = CaseObservation(
                    phase.phase_id,
                    case.case_id,
                    False,
                    case.frames,
                    0,
                    stop_code=STOP_IDENTITY,
                    identity_verified=False,
                    note="The executor answered for a different case.",
                )
            observations.append(obs)
            if not _clean(obs):
                verdict, reason = judge(plan, observations)
                return Outcome(verdict, reason, tuple(observations), q0.status)
    verdict, reason = judge(plan, observations)
    return Outcome(verdict, reason, tuple(observations), q0.status)
