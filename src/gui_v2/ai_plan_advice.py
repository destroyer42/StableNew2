"""Toolkit-neutral advisory planning: closed-list facts, the deterministic judge and the read-only review model (AI-210).

A ``PLAN_PROPOSAL`` is **advice, not a plan** (owner decisions D13 to D17; amendment rules P1, P2, P3, P8). Nothing in this
module creates Intent, edits authored intent, fills a form, compiles, previews or queues, and nothing here can: the only
action a review exposes is "copy this step's text". The model never classifies its own output; every step is judged here, from
facts read from the existing authorities (the model policy projection and the video workflow catalogue plus its preflight
gates), and invalid steps are shown with the reason, never repaired or dropped.

Pure: no Tk, no I/O of its own. The only slow, possibly I/O-bound input is the injected ``preflight`` callable, which the
integration calls on the AI worker thread (never the GUI thread).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from src.ai_assist.contracts import (
    VIDEO_STAGE,
    AssistOutcome,
    AssistRequest,
    AssistSuggestion,
    OutcomeCode,
    PlanStep,
    SuggestionKind,
)
from src.ai_assist.preview import PREVIEW_LABEL

PLAN_ADVICE_LABEL = "Advice, not a plan"
PLAN_ADVICE_NOTICE = (
    "Advice, not a plan. Nothing here creates a job, edits your prompt or settings, or is queued. "
    "Use the ordinary tabs and their checks to act on anything you decide to follow."
)
#: The complete set of things a plan review lets the operator do. There is deliberately no create / queue / apply action.
PLAN_REVIEW_ACTIONS: tuple[str, ...] = ("copy_step_text",)

VERDICT_VALID = "valid"
VERDICT_INCOMPATIBLE = "incompatible"
VERDICT_UNAVAILABLE = "unavailable"
VERDICT_NEEDS_INPUT = "needs_operator_input"
VERDICTS = (VERDICT_VALID, VERDICT_INCOMPATIBLE, VERDICT_UNAVAILABLE, VERDICT_NEEDS_INPUT)

_VERDICT_TEXT = {
    VERDICT_VALID: "valid",
    VERDICT_INCOMPATIBLE: "incompatible",
    VERDICT_UNAVAILABLE: "unavailable",
    VERDICT_NEEDS_INPUT: "needs your input",
}

_GOVERNANCE_APPROVED = "approved"
_GOVERNANCE_EXPERIMENTAL = "experimental"


@dataclass(frozen=True, slots=True)
class TargetFact:
    """What the model policy says about one model id (read from ``project_model_selection``)."""

    label: str
    stages: tuple[str, ...]
    #: Non-empty when the selection cannot run with the configured backend (policy-authored sentence).
    blocking: str = ""


@dataclass(frozen=True, slots=True)
class WorkflowFact:
    """One catalogue workflow with its governance state (read from ``list_workflow_specs``)."""

    label: str
    version: str
    governance_state: str


#: ``preflight(workflow_id, version) -> (blocked, unknown)``: the controller's existing readiness gates, as one sentence per
#: blocked gate and per gate that could not be answered. Called on the worker thread only.
Preflight = Callable[[str, str], tuple[tuple[str, ...], tuple[str, ...]]]


def _no_preflight(_workflow_id: str, _version: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (), ("Readiness was not checked.",)


@dataclass(frozen=True, slots=True)
class PlanFacts:
    """Everything the judge reads, captured once on the GUI thread when the request is made (the closed lists' facts)."""

    targets: Mapping[str, TargetFact] = field(default_factory=dict)
    workflows: Mapping[str, WorkflowFact] = field(default_factory=dict)
    preflight: Preflight = _no_preflight


@dataclass(frozen=True, slots=True)
class StepVerdict:
    step: PlanStep
    verdict: str
    reason: str = ""

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ValueError("unknown verdict")


@dataclass(frozen=True, slots=True)
class PlanJudgement:
    verdicts: tuple[StepVerdict, ...]

    @property
    def all_valid(self) -> bool:
        return bool(self.verdicts) and all(v.verdict == VERDICT_VALID for v in self.verdicts)


def judge_step(step: PlanStep, facts: PlanFacts) -> StepVerdict:
    """Classify one step from existing authorities. Never raises for a missing fact; absence is ``unavailable``."""

    if step.stage == VIDEO_STAGE:
        return _judge_workflow_step(step, facts)
    return _judge_model_step(step, facts)


def _judge_model_step(step: PlanStep, facts: PlanFacts) -> StepVerdict:
    fact = facts.targets.get(step.target or "")
    if fact is None:
        return StepVerdict(
            step, VERDICT_UNAVAILABLE, "The model is not in the installed, policy-valid model list."
        )
    if fact.blocking:
        return StepVerdict(step, VERDICT_INCOMPATIBLE, fact.blocking)
    if step.stage not in fact.stages:
        return StepVerdict(
            step,
            VERDICT_INCOMPATIBLE,
            f"The {step.stage} stage is not supported by the policy of {fact.label}.",
        )
    return StepVerdict(step, VERDICT_VALID)


def _judge_workflow_step(step: PlanStep, facts: PlanFacts) -> StepVerdict:
    fact = facts.workflows.get(step.workflow or "")
    if fact is None:
        return StepVerdict(step, VERDICT_UNAVAILABLE, "The workflow is not offered by the catalogue.")
    if fact.governance_state == _GOVERNANCE_EXPERIMENTAL:
        return StepVerdict(
            step,
            VERDICT_NEEDS_INPUT,
            f"{fact.label} is experimental: running it needs your explicit per-job opt-in on the Video Workflow tab.",
        )
    if fact.governance_state != _GOVERNANCE_APPROVED:
        return StepVerdict(
            step,
            VERDICT_UNAVAILABLE,
            f"{fact.label} is {fact.governance_state or 'not approved'} and is not offered.",
        )
    try:
        blocked, unknown = facts.preflight(step.workflow or "", fact.version)
    except Exception:  # noqa: BLE001 - never "valid by default" when readiness could not be read
        return StepVerdict(step, VERDICT_NEEDS_INPUT, "Readiness could not be checked. Open the Video Workflow tab.")
    if blocked:
        return StepVerdict(step, VERDICT_UNAVAILABLE, f"Prerequisite missing: {blocked[0]}")
    if unknown:
        return StepVerdict(step, VERDICT_NEEDS_INPUT, f"Readiness could not be confirmed: {unknown[0]}")
    return StepVerdict(step, VERDICT_VALID)


def judge_plan(suggestion: AssistSuggestion, facts: PlanFacts) -> PlanJudgement:
    """Judge every step; the model's own text is never consulted for the verdict."""

    if suggestion.kind is not SuggestionKind.PLAN_PROPOSAL:
        raise ValueError("only a plan proposal is judged here")
    return PlanJudgement(tuple(judge_step(step, facts) for step in suggestion.steps))


# -- review model --------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlanRow:
    index: int
    stage: str
    choice: str
    count: int
    rationale: str
    verdict: str
    reason: str
    #: The text the per-step "Copy text" action puts on the clipboard. Plain text, never a payload.
    copy_text: str


@dataclass(frozen=True, slots=True)
class PlanReview:
    """Read-only. Has no field or method that could create, edit, apply, compile, preview or queue anything."""

    status: str
    notice: str = PLAN_ADVICE_NOTICE
    trust_label: str = ""
    rows: tuple[PlanRow, ...] = ()
    summary: str = ""

    @property
    def actions(self) -> tuple[str, ...]:
        return PLAN_REVIEW_ACTIONS if self.rows else ()


def _choice_label(step: PlanStep, targets: Mapping[str, str], workflows: Mapping[str, str]) -> str:
    if step.stage == VIDEO_STAGE:
        return workflows.get(step.workflow or "", step.workflow or "")
    return targets.get(step.target or "", step.target or "")


def _row(
    index: int,
    verdict: StepVerdict,
    targets: Mapping[str, str],
    workflows: Mapping[str, str],
) -> PlanRow:
    step = verdict.step
    choice = _choice_label(step, targets, workflows)
    noun = "clip" if step.stage == VIDEO_STAGE else "image"
    unit = noun if step.count == 1 else f"{noun}s"
    state = _VERDICT_TEXT[verdict.verdict]
    reason = f" ({verdict.reason})" if verdict.reason else ""
    copy_text = (
        f"Step {index}: {step.stage} with {choice}, {step.count} {unit}. {step.rationale} "
        f"[judged {state}{reason}; advice only]"
    )
    return PlanRow(
        index,
        step.stage,
        choice,
        step.count,
        step.rationale,
        verdict.verdict,
        verdict.reason,
        copy_text,
    )


def plan_review(
    judgement: PlanJudgement,
    *,
    targets: tuple[tuple[str, str], ...],
    workflows: tuple[tuple[str, str], ...],
    trust_label: str = "",
) -> PlanReview:
    target_labels, workflow_labels = dict(targets), dict(workflows)
    rows = tuple(
        _row(i, verdict, target_labels, workflow_labels)
        for i, verdict in enumerate(judgement.verdicts, start=1)
    )
    ok = sum(1 for row in rows if row.verdict == VERDICT_VALID)
    summary = f"{ok} of {len(rows)} steps judged valid by deterministic checks. Output quality is not established."
    return PlanReview(
        status="Advisory steps ready. Each step was judged by StableNew's own checks, not by the model.",
        trust_label=trust_label,
        rows=rows,
        summary=summary,
    )


def unavailable_plan_review(text: str, *, trust_label: str = "") -> PlanReview:
    """A refusal, failure or admission outcome: the manual path is unchanged; only the fixed copy is shown."""

    return PlanReview(status=text, trust_label=trust_label)


_OUTCOME_COPY = {
    OutcomeCode.REFUSED_BY_MODEL: "The model refused this request. Nothing was planned.",
    OutcomeCode.MALFORMED: "The response failed validation or exceeded the plan bounds. It cannot be shown.",
}


def outcome_plan_text(outcome: AssistOutcome, fallback: Mapping[OutcomeCode, str]) -> str:
    """Fixed, content-free copy for a non-suggestion outcome (never model text, details or exception messages)."""

    return _OUTCOME_COPY.get(outcome.code) or fallback.get(outcome.code, "The AI request did not complete.")


def review_text(review: PlanReview) -> str:
    """Plain-text rendering for the read-only display (the dialog shows exactly this)."""

    lines = [review.notice]
    if review.trust_label:
        lines.append(review.trust_label)
    lines.append("")
    if not review.rows:
        return "\n".join(lines).rstrip()
    lines.append(review.summary)
    lines.append("")
    for row in review.rows:
        unit = "clip" if row.stage == VIDEO_STAGE else "image"
        lines.append(f"{row.index}. [{_VERDICT_TEXT[row.verdict]}] {row.stage}: {row.choice} x {row.count} {unit}(s)")
        lines.append(f"   Why (model's words): {row.rationale}")
        if row.reason:
            lines.append(f"   Check: {row.reason}")
    return "\n".join(lines)


def plan_trust_prefix(tier: str) -> str:
    return PREVIEW_LABEL if tier == "preview" else ""


def build_plan_request(
    request_id: str,
    goal_text: str,
    *,
    targets: tuple[tuple[str, str], ...],
    workflows: tuple[tuple[str, str], ...],
    stages: tuple[str, ...],
    target_policy_id: str = "",
) -> AssistRequest:
    """The only constructor of a plan request: the closed lists come from the caller's authorities, the goal is data."""

    return AssistRequest(
        request_id,
        SuggestionKind.PLAN_PROPOSAL,
        target_policy_id=target_policy_id,
        allowed_targets=tuple(key for key, _label in targets),
        allowed_workflows=tuple(key for key, _label in workflows),
        allowed_stages=stages,
        goal_text=goal_text,
    )


__all__ = [
    "PLAN_ADVICE_LABEL",
    "PLAN_ADVICE_NOTICE",
    "PLAN_REVIEW_ACTIONS",
    "VERDICTS",
    "VERDICT_INCOMPATIBLE",
    "VERDICT_NEEDS_INPUT",
    "VERDICT_UNAVAILABLE",
    "VERDICT_VALID",
    "PlanFacts",
    "PlanJudgement",
    "PlanReview",
    "PlanRow",
    "StepVerdict",
    "TargetFact",
    "WorkflowFact",
    "build_plan_request",
    "judge_plan",
    "judge_step",
    "outcome_plan_text",
    "plan_review",
    "plan_trust_prefix",
    "review_text",
    "unavailable_plan_review",
]
