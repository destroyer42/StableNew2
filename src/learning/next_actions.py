"""Deterministic gap classification and ranking of suggested next actions.

Executable experiment candidates come only from the existing proposal planner (``evidence_gaps`` and
``EvidenceProposalPlanner``); this module classifies and orders what those authorities already allow and never
invents a candidate. Ordering is a documented lexicographic rule over ordinal integers:

    (eligibility, class order, -evidence severity, -operator relevance, bounded image cost, planner position, id)

None of these is a probability. Every action requires a further, explicit operator step in an existing workflow.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from src.generation_profiles.identity import ResolvedModel
from src.learning.evidence_autopilot import VARIABLES, ProposalPlan
from src.learning.intelligence_contracts import (
    ACTION_COMPLETE_RATINGS,
    ACTION_INVESTIGATE_EXECUTION,
    ACTION_KINDS,
    ACTION_NO_SAFE_EXPERIMENT,
    ACTION_REPEAT_EXPERIMENT,
    ACTION_RESEARCH_EVIDENCE,
    ACTION_RESOLVE_IDENTITY,
    ACTION_REVIEW_RECOMMENDATION,
    ACTION_RUN_EXPERIMENT,
    ELIGIBILITY_BLOCKED,
    ELIGIBILITY_OPERATOR,
    ELIGIBILITY_READY,
    MAX_IMAGE_COST,
    WORKFLOW_CATALOG_RESEARCH,
    WORKFLOW_DRAFT_PREPARATION,
    WORKFLOW_IDENTITY_VERIFICATION,
    WORKFLOW_LEARNING_REVIEW,
    WORKFLOW_NONE,
    WORKFLOW_PROPOSED_EXPERIMENTS,
    WORKFLOW_RECOMMENDATION_APPLY,
    EvidenceFinding,
    ExperimentConclusion,
    NextAction,
    NextActionSet,
    digest,
)
from src.learning.intelligence_findings import invalid_evidence, is_applicable
from src.learning.intelligence_sources import (
    STATE_COMPLETED,
    STATE_DRAFT,
    STATE_FAILED,
    STATE_PREPARED,
    STATE_RUNNING,
    ExperimentView,
)
from src.learning.profile_publication import PublicationProposal

_CLASS_ORDER = {kind: index for index, kind in enumerate(ACTION_KINDS)}
_ELIGIBILITY_ORDER = {ELIGIBILITY_READY: 0, ELIGIBILITY_OPERATOR: 1, ELIGIBILITY_BLOCKED: 2}
_STATE_RANK = {
    STATE_COMPLETED: 4,
    STATE_RUNNING: 3,
    STATE_FAILED: 2,
    STATE_PREPARED: 1,
    STATE_DRAFT: 0,
}
_RATED_STUDIES = ("ordinary", "controlled_variable")
_FIELD_OF = dict(VARIABLES)
_NO_ALTERNATE = "No source-backed alternate"

CONFIRMATION = {
    ACTION_RUN_EXPERIMENT: "Choose a prompt context, save or Preview drafts, then explicitly Run in Learning.",
    ACTION_REPEAT_EXPERIMENT: "Choose a different prompt context, Preview, then explicitly Run in Learning.",
    ACTION_COMPLETE_RATINGS: "Rate each unrated image in Learning Review and save the rating.",
    ACTION_INVESTIGATE_EXECUTION: "Open the experiment, use Inspect active experiment, then decide on a rerun.",
    ACTION_REVIEW_RECOMMENDATION: "Review the qualified findings; Apply or publication needs your explicit confirmation.",
    ACTION_RESOLVE_IDENTITY: "Choose Evidence… > Verify identities (bounded) for this checkpoint.",
    ACTION_RESEARCH_EVIDENCE: "Choose a lookup or import a reviewed catalog from Evidence…; claims stay unreviewed until you accept them.",
    ACTION_NO_SAFE_EXPERIMENT: "",
}


@dataclass(frozen=True)
class ActionInputs:
    target: ResolvedModel
    plan: ProposalPlan | None
    experiments: tuple[ExperimentView, ...]
    rated: Mapping[tuple[str, str], float]
    conclusions: Mapping[str, ExperimentConclusion]
    findings: tuple[EvidenceFinding, ...]
    publication: PublicationProposal | None
    fingerprint: str
    problems: tuple[str, ...] = ()


def _finding_ids(findings: Iterable[EvidenceFinding], *topics: str) -> tuple[str, ...]:
    wanted = set(topics)
    return tuple(sorted(f.finding_id for f in findings if f.topic in wanted))


def _make(
    inputs: ActionInputs,
    kind: str,
    target: str,
    purpose: str,
    reasons: Iterable[str],
    codes: Iterable[str],
    addresses: tuple[str, str],
    *,
    eligibility: str = ELIGIBILITY_READY,
    blockers: Iterable[str] = (),
    workflow: str = WORKFLOW_NONE,
    workload: Mapping[str, int | None] | None = None,
    refs: Iterable[str] = (),
    severity: int = 1,
    relevance: int = 1,
) -> NextAction:
    return NextAction(
        action_id="act-" + digest([inputs.fingerprint, kind, target])[:24],
        kind=kind,
        target_id=target,
        purpose=purpose,
        reasons=tuple(dict.fromkeys(reasons)),
        reason_codes=tuple(dict.fromkeys(codes)),
        addresses=addresses[0],
        addresses_code=addresses[1],
        eligibility=eligibility,
        blockers=tuple(dict.fromkeys(blockers)),
        workflow=workflow,
        workload=tuple(sorted((workload or {}).items())),
        context_fingerprint=inputs.fingerprint,
        confirmation=CONFIRMATION[kind],
        evidence_refs=tuple(sorted(set(refs))),
        severity=severity,
        relevance=relevance,
    )


def _experiment_actions(inputs: ActionInputs, applicable: list[ExperimentView]) -> list[NextAction]:
    actions = []
    for view in applicable:
        if view.study_type not in _RATED_STUDIES:
            continue
        refs = _finding_ids(inputs.findings, f"experiment:{view.experiment_id}")
        problems = invalid_evidence(view)
        if problems and view.state in (STATE_COMPLETED, STATE_FAILED):
            actions.append(
                _make(
                    inputs,
                    ACTION_INVESTIGATE_EXECUTION,
                    view.experiment_id,
                    f"Investigate why the {view.variable or 'saved'} experiment has no valid controlled readback.",
                    [f"Controlled execution evidence is invalid: {'; '.join(problems[:3])}."],
                    ["invalid_readback"],
                    ("Whether the run can count as evidence at all.", "invalid_readback"),
                    workflow=WORKFLOW_LEARNING_REVIEW,
                    workload={"images_to_generate": 0, "images_to_rate": 0},
                    refs=refs,
                    severity=3,
                    relevance=2,
                )
            )
            continue
        if view.state != STATE_COMPLETED:
            continue
        unrated = [
            (v, img) for v, img in view.images if (view.experiment_id, img) not in inputs.rated
        ]
        if unrated:
            actions.append(
                _make(
                    inputs,
                    ACTION_COMPLETE_RATINGS,
                    view.experiment_id,
                    f"Finish rating the {len(unrated)} unrated image(s) already generated for {view.variable or 'this experiment'}.",
                    [
                        f"{len(unrated)} of {len(view.images)} generated images have no saved rating.",
                        "Completing existing work needs no new generation.",
                    ],
                    ["unrated_images"],
                    (
                        "The missing ratings that stop the experiment reaching a conclusion.",
                        "unrated_images",
                    ),
                    workflow=WORKFLOW_LEARNING_REVIEW,
                    workload={"images_to_generate": 0, "images_to_rate": len(unrated)},
                    refs=refs,
                    severity=2,
                    relevance=2,
                )
            )
    return actions


def _matches(view: ExperimentView, document: Mapping[str, Any], sha: str) -> bool:
    fixed = (document.get("planning_context") or {}).get("fixed_execution_digest") or ""
    if view.proposal_id and view.proposal_id == document.get("proposal_id"):
        return True
    return bool(
        view.model_sha == sha
        and view.variable == document.get("variable")
        and list(view.values) == list(document.get("values") or ())
        and fixed
        and view.fixed_digest == fixed
    )


def _coverage_severity(document: Mapping[str, Any]) -> tuple[int, str]:
    field = _FIELD_OF.get(str(document.get("variable")), "")
    status = next(
        (c["status"] for c in document.get("coverage", []) if c.get("field") == field), ""
    )
    if status == "conflicting":
        return 3, "conflicting_claim"
    if status == "unavailable":
        return 2, "missing_claim"
    return 1, "unverified_claim"


def _plan_actions(
    inputs: ActionInputs, applicable: list[ExperimentView]
) -> tuple[list[tuple[int, NextAction]], list[tuple[str, str]], list[str]]:
    sha = inputs.target.identity.sha256
    found: list[tuple[int, NextAction]] = []
    suppressed: list[tuple[str, str]] = []
    blockers: list[str] = []
    for position, proposal in enumerate(inputs.plan.proposals if inputs.plan else ()):
        doc = proposal.document
        variable = str(doc["variable"])
        reasons = [str(r) for r in doc.get("blocked_reasons", [])]
        if proposal.runnable:
            matches = sorted(
                (v for v in applicable if _matches(v, doc, sha)),
                key=lambda v: (_STATE_RANK.get(v.state, 0), v.experiment_id),
            )
            best = matches[-1] if matches else None
            conclusion = inputs.conclusions.get(best.experiment_id) if best else None
            repeat = False
            if best is not None:
                if (
                    best.state == STATE_COMPLETED
                    and conclusion
                    and conclusion.status == "inconclusive"
                ):
                    repeat = True
                elif best.state in (STATE_COMPLETED, STATE_RUNNING, STATE_FAILED):
                    why = {
                        STATE_RUNNING: "an equivalent experiment is already running",
                        STATE_FAILED: "an equivalent experiment failed; investigate it first",
                    }.get(best.state)
                    if why is None:
                        if invalid_evidence(best):
                            why = "an equivalent run has invalid execution evidence; investigate it first"
                        elif conclusion is None or conclusion.status == "insufficient":
                            why = "an equivalent run is awaiting ratings"
                        else:
                            why = f"an equivalent controlled run is complete ({conclusion.status})"
                    suppressed.append((variable, f"Not proposed again: {why}."))
                    continue
            severity, code = _coverage_severity(doc)
            images = int(doc["expected_images"])
            work = {
                "images_to_generate": images,
                "images_to_rate": images,
                "denoising_steps": int(
                    (doc.get("estimated_work") or {}).get("denoising_steps") or 0
                ),
                "seconds": None,
            }
            over = images > MAX_IMAGE_COST
            existing = best is not None and not repeat
            kind = ACTION_REPEAT_EXPERIMENT if repeat else ACTION_RUN_EXPERIMENT
            why_lines = [str(doc["priority_reason"])]
            if repeat and best is not None:
                why_lines.append(
                    f"An equivalent run (prompt context {best.prompt_context or 'unrecorded'}) was inconclusive; "
                    "a repeat is only meaningful under a different controlled prompt context."
                )
            if existing and best is not None:
                why_lines.append(
                    "A saved draft for this exact experiment already exists in the Library."
                )
            found.append(
                (
                    position,
                    _make(
                        inputs,
                        kind,
                        str(doc["proposal_id"]),
                        f"Test {variable} alternatives ({', '.join(str(v) for v in doc['values'])}) "
                        f"against the current baseline with {images} controlled images.",
                        why_lines,
                        [code, *(["equivalent_inconclusive"] if repeat else [])],
                        (
                            f"Which {variable} value is better rated on this exact checkpoint, "
                            "under controlled conditions.",
                            code,
                        ),
                        eligibility=ELIGIBILITY_BLOCKED if over else ELIGIBILITY_READY,
                        blockers=[f"Needs {images} images; the bounded cost is {MAX_IMAGE_COST}."]
                        if over
                        else [],
                        workflow=WORKFLOW_DRAFT_PREPARATION
                        if existing
                        else WORKFLOW_PROPOSED_EXPERIMENTS,
                        workload=work,
                        refs=_finding_ids(
                            inputs.findings, f"claim:{_FIELD_OF.get(variable, variable)}"
                        ),
                        severity=severity + (0 if not repeat else -1),
                        relevance=2 if existing or repeat else 1,
                    ),
                )
            )
            continue
        if variable == "identity":
            found.append(
                (
                    position,
                    _make(
                        inputs,
                        ACTION_RESOLVE_IDENTITY,
                        "identity",
                        "Verify the checkpoint's byte identity and resolve compatibility before any generation.",
                        reasons,
                        ["unverified_identity"],
                        (
                            "Which model this is and whether it is compatible.",
                            "unverified_identity",
                        ),
                        eligibility=ELIGIBILITY_OPERATOR,
                        workflow=WORKFLOW_IDENTITY_VERIFICATION,
                        refs=_finding_ids(inputs.findings, "identity", "policy"),
                        severity=4,
                    ),
                )
            )
        elif variable == "variant" or (variable == "metadata" and doc["status"] == "metadata_only"):
            missing = variable == "metadata"
            found.append(
                (
                    position,
                    _make(
                        inputs,
                        ACTION_RESEARCH_EVIDENCE,
                        variable,
                        "Research missing model information; no execution value is inferred from it."
                        if missing
                        else "Qualify the exact accelerator/subtype recipe before generation.",
                        reasons,
                        ["missing_metadata" if missing else "unqualified_variant"],
                        ("Model facts nobody has reviewed yet.", "missing_metadata"),
                        eligibility=ELIGIBILITY_OPERATOR,
                        workflow=WORKFLOW_CATALOG_RESEARCH,
                        severity=1 if missing else 3,
                    ),
                )
            )
        elif variable in _FIELD_OF and any(_NO_ALTERNATE in r for r in reasons):
            severity, code = _coverage_severity(doc)
            found.append(
                (
                    position,
                    _make(
                        inputs,
                        ACTION_RESEARCH_EVIDENCE,
                        variable,
                        f"Research {variable}: no source-backed alternate exists to test.",
                        reasons,
                        [code, "no_alternative"],
                        (f"Which {variable} values are credibly worth testing.", code),
                        eligibility=ELIGIBILITY_OPERATOR,
                        workflow=WORKFLOW_CATALOG_RESEARCH,
                        refs=_finding_ids(inputs.findings, f"claim:{_FIELD_OF[variable]}"),
                        severity=severity,
                    ),
                )
            )
        elif doc["status"] == "blocked":
            blockers.extend(f"{variable}: {r}" for r in reasons)
    return found, suppressed, blockers


def _recommendation_action(inputs: ActionInputs) -> list[NextAction]:
    publication = inputs.publication
    if publication is None or not publication.ready or publication.already_published() is not None:
        return []
    settings = ", ".join(f"{k}={v}" for k, v in sorted(publication.settings.items()))
    return [
        _make(
            inputs,
            ACTION_REVIEW_RECOMMENDATION,
            "publication:" + publication.evidence_digest[:16],
            f"Review the qualified controlled findings ({settings}) for this checkpoint.",
            [
                f"{publication.sample_count} controlled rating(s) in {publication.experiment_count} "
                "experiment(s) meet the publication thresholds.",
                "Findings describe the tested prompts only; they are a starting point, not an optimum.",
            ],
            ["recommendation_ready"],
            (
                "Whether the qualified findings should be reviewed for use.",
                "unreviewed_recommendation",
            ),
            workflow=WORKFLOW_RECOMMENDATION_APPLY,
            refs=_finding_ids(inputs.findings, "publication"),
            relevance=2,
        )
    ]


def _sort_key(item: tuple[int, NextAction]) -> tuple[Any, ...]:
    position, action = item
    cost = action.workload_map().get("images_to_generate") or 0
    return (
        _ELIGIBILITY_ORDER[action.eligibility],
        _CLASS_ORDER[action.kind],
        -action.severity,
        -action.relevance,
        min(int(cost), MAX_IMAGE_COST + 1),
        position,
        action.target_id,
        action.action_id,
    )


def build_actions(inputs: ActionInputs) -> NextActionSet:
    applicable = sorted(
        (v for v in inputs.experiments if is_applicable(v, inputs.target)),
        key=lambda v: v.experiment_id,
    )
    ranked: list[tuple[int, NextAction]] = [
        (-1, a) for a in _experiment_actions(inputs, applicable)
    ]
    planned, suppressed, blockers = _plan_actions(inputs, applicable)
    ranked.extend(planned)
    ranked.extend((-1, a) for a in _recommendation_action(inputs))
    offered = {a.kind for _, a in ranked if a.eligibility == ELIGIBILITY_READY}
    if not offered & {ACTION_RUN_EXPERIMENT, ACTION_REPEAT_EXPERIMENT}:
        why = ["No supported, current, non-duplicate controlled experiment is available."]
        why.extend(reason for _, reason in suppressed)
        ranked.append(
            (
                10_000,
                _make(
                    inputs,
                    ACTION_NO_SAFE_EXPERIMENT,
                    "none",
                    "No safe experiment is available right now.",
                    why,
                    ["no_safe_experiment"],
                    ("Why nothing can be proposed without inventing evidence.", "no_alternative"),
                    eligibility=ELIGIBILITY_BLOCKED,
                    blockers=blockers[:6],
                ),
            )
        )
    ranked.sort(key=_sort_key)
    return NextActionSet(
        fingerprint=inputs.fingerprint,
        actions=tuple(a for _, a in ranked),
        suppressed=tuple(sorted(dict.fromkeys(suppressed))),
        problems=inputs.problems,
    )


def rated_map(attributions: Iterable[Any]) -> dict[tuple[str, str], float]:
    """(experiment, image) -> operator overall rating, for every image that has a valid saved rating."""
    return {
        (item.experiment, item.image): item.overall
        for item in attributions
        if item.overall is not None
    }
