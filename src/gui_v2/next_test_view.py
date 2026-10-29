"""Toolkit-neutral presentation of "What Should I Test Next?".

Turns an ``IntelligenceReport`` into plain strings and a navigation route. It imports no Tk, starts no work and
holds no state; the Tk dialog renders it and the existing Model Evidence / Learning navigation executes the route.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.learning.intelligence_contracts import (
    ACTION_COMPLETE_RATINGS,
    ACTION_INVESTIGATE_EXECUTION,
    ACTION_NO_SAFE_EXPERIMENT,
    ACTION_REPEAT_EXPERIMENT,
    ACTION_RESEARCH_EVIDENCE,
    ACTION_RESOLVE_IDENTITY,
    ACTION_REVIEW_RECOMMENDATION,
    ACTION_RUN_EXPERIMENT,
    ELIGIBILITY_BLOCKED,
    ELIGIBILITY_OPERATOR,
    ELIGIBILITY_READY,
    SOURCE_CLASSES,
    WORKFLOW_CATALOG_RESEARCH,
    WORKFLOW_DRAFT_PREPARATION,
    WORKFLOW_IDENTITY_VERIFICATION,
    WORKFLOW_LEARNING_REVIEW,
    WORKFLOW_PROPOSED_EXPERIMENTS,
    WORKFLOW_RECOMMENDATION_APPLY,
    IntelligenceReport,
    NextAction,
)

TITLES = {
    ACTION_COMPLETE_RATINGS: "Finish rating your generated images",
    ACTION_INVESTIGATE_EXECUTION: "Investigate an experiment's execution evidence",
    ACTION_RESOLVE_IDENTITY: "Verify this checkpoint's identity",
    ACTION_REVIEW_RECOMMENDATION: "Review a qualified recommendation",
    ACTION_RUN_EXPERIMENT: "Run a controlled experiment",
    ACTION_REPEAT_EXPERIMENT: "Repeat an inconclusive test in another prompt context",
    ACTION_RESEARCH_EVIDENCE: "Research missing or conflicting model information",
    ACTION_NO_SAFE_EXPERIMENT: "No safe experiment is available right now",
}
BUTTONS = {
    WORKFLOW_PROPOSED_EXPERIMENTS: "Open Proposed Experiments",
    WORKFLOW_DRAFT_PREPARATION: "Open the Experiment Library",
    WORKFLOW_LEARNING_REVIEW: "Open in Learning Review",
    WORKFLOW_RECOMMENDATION_APPLY: "Open Recommendations",
    WORKFLOW_IDENTITY_VERIFICATION: "Show me the step",
    WORKFLOW_CATALOG_RESEARCH: "Show me the step",
}
READINESS = {
    ELIGIBILITY_READY: "Ready. Opens an existing workflow; you confirm every step.",
    ELIGIBILITY_OPERATOR: "Needs a step from you first. Nothing runs automatically.",
    ELIGIBILITY_BLOCKED: "Not available now.",
}
SOURCE_TITLES = {
    "policy_fact": "Established by policy",
    "research_claim": "Reviewed research claims",
    "controlled_observation": "Controlled observations",
    "subjective_preference": "Your saved preferences",
}


@dataclass(frozen=True)
class NextTestCard:
    action_id: str
    title: str
    purpose: str
    readiness: str
    workload: str
    addresses: str
    step: str
    reasons: tuple[str, ...]
    blockers: tuple[str, ...]
    button: str  # "" when nothing can be opened
    ready: bool


@dataclass(frozen=True)
class NextTestView:
    headline: str
    status: str
    primary: NextTestCard | None
    alternatives: tuple[NextTestCard, ...]
    details: str
    notice: str  # degraded-evidence notice; empty when evidence loaded cleanly


@dataclass(frozen=True)
class NextTestRoute:
    """Where the existing UI should go. The route never carries a setting or an instruction to run."""

    workflow: str
    target_id: str
    guidance: str


def _workload(action: NextAction) -> str:
    work = action.workload_map()
    if not work:
        return ""
    parts = []
    if work.get("images_to_generate"):
        parts.append(f"{work['images_to_generate']} new image(s)")
    if work.get("images_to_rate"):
        parts.append(f"{work['images_to_rate']} image(s) to rate")
    if work.get("denoising_steps"):
        parts.append(f"about {work['denoising_steps']:g} denoising steps")
    if "seconds" in work and work["seconds"] is None and work.get("images_to_generate"):
        parts.append("elapsed time unknown")
    return "; ".join(parts) if parts else "No new generation."


def card(action: NextAction) -> NextTestCard:
    return NextTestCard(
        action.action_id,
        TITLES[action.kind],
        action.purpose,
        READINESS[action.eligibility],
        _workload(action),
        action.addresses,
        action.confirmation,
        action.reasons,
        action.blockers,
        BUTTONS.get(action.workflow, "") if action.eligibility != ELIGIBILITY_BLOCKED else "",
        action.executable,
    )


def route_for(action: NextAction) -> NextTestRoute:
    return NextTestRoute(action.workflow, action.target_id, action.confirmation)


def details_text(report: IntelligenceReport) -> str:
    lines = [
        f"Model {report.display_name} ({report.family}); "
        + ("identity verified." if report.identity_verified else "identity NOT verified."),
        "",
    ]
    for source in SOURCE_CLASSES:
        rows = [f for f in report.findings if f.source_class == source]
        if not rows:
            continue
        lines.append(SOURCE_TITLES[source].upper())
        for finding in rows:
            lines.append(f"- [{finding.status}] {finding.statement}")
            lines.append(f"    applies to: {finding.applicability}; source: {finding.source_ref}")
            lines.append(f"    freshness: {finding.freshness}; limitation: {finding.limitation}")
        lines.append("")
    if report.preference.groups:
        lines.append("PREFERENCE SUMMARY (observations, not a learned preference)")
        for group in report.preference.groups:
            lines.append(f"- {group.verdict}: {group.statement}")
            for reason in group.insufficiency:
                lines.append(f"    {reason}")
    if report.preference.excluded:
        lines.append(
            "Not pooled: "
            + ", ".join(f"{name} {count}" for name, count in report.preference.excluded)
        )
    if report.actions.suppressed:
        lines.append("")
        lines.append("NOT PROPOSED")
        lines.extend(f"- {name}: {why}" for name, why in report.actions.suppressed)
    if report.problems:
        lines.append("")
        lines.append("EVIDENCE PROBLEMS")
        lines.extend(f"- {p}" for p in report.problems)
    return "\n".join(lines).rstrip() + "\n"


def build_view(report: IntelligenceReport) -> NextTestView:
    primary = report.actions.primary
    ready = [a for a in report.actions.actions if a.executable]
    if primary is None:
        status = "Nothing to suggest."
    elif primary.executable:
        status = f"Ready: {len(ready)} action(s) can be opened now."
    elif primary.eligibility == ELIGIBILITY_OPERATOR:
        status = "Needs your step: resolve the missing evidence first."
    else:
        status = "No supported experiment is available."
    return NextTestView(
        headline=f"What Should I Test Next? — {report.display_name}",
        status=status,
        primary=card(primary) if primary else None,
        alternatives=tuple(card(a) for a in report.actions.alternatives),
        details=details_text(report),
        notice=(
            "Some saved evidence could not be read: " + " ".join(report.problems[:2])
            if report.problems
            else ""
        ),
    )
