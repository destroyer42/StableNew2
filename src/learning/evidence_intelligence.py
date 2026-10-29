"""Read-only Learning evidence intelligence for one exact checkpoint.

``assess`` is pure over already-loaded inputs; ``load_sources`` is the only part that reads files (rating log,
saved experiments) and belongs on a worker thread. Nothing here submits jobs, writes ratings or profiles,
changes Pipeline settings, calls a backend, or invokes AI. Every consumed authority is the existing one:
the proposal planner, ``ModelPolicy`` through the resolved model, the evidence catalog, saved ratings and the
publication eligibility rule.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.learning.evidence_autopilot import EvidenceProposalPlanner, ProposalPlanningContext
from src.learning.experiment_store import LearningExperimentStore
from src.learning.intelligence_contracts import (
    CONTRACT,
    ExperimentConclusion,
    IntelligenceReport,
    digest,
)
from src.learning.intelligence_findings import (
    build_findings,
    conclude,
    is_applicable,
    model_ref,
)
from src.learning.intelligence_sources import (
    ExperimentLoad,
    RatingLog,
    load_experiments,
    read_rating_log,
)
from src.learning.next_actions import ActionInputs, build_actions, rated_map
from src.learning.preference_evidence import (
    OUTCOME_CONTROLLED,
    attribute_ratings,
    summarize_preferences,
)
from src.learning.profile_publication import ProfilePublicationService, PublicationProposal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntelligenceSources:
    context: ProposalPlanningContext
    rating_log: RatingLog
    experiments: ExperimentLoad
    publication_service: ProfilePublicationService | None = None


def load_sources(
    context: ProposalPlanningContext,
    *,
    records_path: Path | None,
    store: LearningExperimentStore | None,
    publication_service: ProfilePublicationService | None = None,
) -> IntelligenceSources:
    """Read the rating log and saved experiments. Worker thread only; never writes."""
    return IntelligenceSources(
        context, read_rating_log(records_path), load_experiments(store), publication_service
    )


def _publication(sources: IntelligenceSources, problems: list[str]) -> PublicationProposal | None:
    service = sources.publication_service
    if service is None:
        return None
    try:
        return service.evaluate(
            sources.rating_log.rows,
            sources.context.target.identity.display_name,
            catalogs=sources.context.resources,
        )
    except (KeyError, TypeError, ValueError, AttributeError, OSError) as exc:
        # Publication is optional context; its failure stays visible and is not fatal.
        logger.warning("Publication eligibility unavailable", exc_info=True)
        problems.append(
            f"Recommendation eligibility could not be evaluated ({type(exc).__name__})."
        )
        return None


def assess(sources: IntelligenceSources) -> IntelligenceReport:
    context = sources.context
    target = context.target
    problems = [*sources.rating_log.problems, *sources.experiments.problems]
    plan = None
    try:
        plan = EvidenceProposalPlanner().plan(context)
        plan_core: Any = {
            k: v for k, v in plan.document.items() if k not in ("contract", "plan_id", "proposals")
        }
    except (ValueError, TypeError, KeyError) as exc:
        problems.append(f"Experiment planning is unavailable ({type(exc).__name__}: {exc}).")
        plan_core = {"planning": "unavailable"}

    attributions = attribute_ratings(sources.rating_log.rows, target)
    preference = summarize_preferences(attributions, target)
    applicable = tuple(v for v in sources.experiments.views if is_applicable(v, target))
    controlled_overall: dict[str, dict[str, float]] = {}
    for item in attributions:
        if item.outcome == OUTCOME_CONTROLLED and item.overall is not None:
            controlled_overall.setdefault(item.experiment, {})[item.image] = item.overall
    conclusions: dict[str, ExperimentConclusion] = {}
    for view in applicable:
        result = conclude(view, controlled_overall.get(view.experiment_id, {}))
        if result is not None:
            conclusions[view.experiment_id] = result
    publication = _publication(sources, problems)
    rating_revision = sources.rating_log.revision
    fingerprint = digest(
        {
            "contract": CONTRACT,
            "plan": plan_core,
            "ratings": rating_revision,
            "experiments": sources.experiments.revision,
            "publication": publication.evidence_digest if publication else "",
            "problems": problems,
        }
    )
    findings = build_findings(
        target,
        context.catalog,
        applicable,
        tuple(conclusions.values()),
        preference,
        publication,
        rating_revision=rating_revision,
    )
    actions = build_actions(
        ActionInputs(
            target=target,
            plan=plan,
            experiments=sources.experiments.views,
            rated=rated_map(attributions),
            conclusions=conclusions,
            findings=findings,
            publication=publication,
            fingerprint=fingerprint,
            problems=tuple(problems),
        )
    )
    coverage = {
        row.field: row.status
        for row in context.catalog.coverage(target.identity, variant=context.variant)
    }
    return IntelligenceReport(
        model_ref=model_ref(target),
        display_name=target.identity.display_name,
        family=target.identity.family,
        identity_verified=bool(
            target.identity.sha256
            and target.verified_family
            and target.identity.family != "unknown"
        ),
        findings=findings,
        conclusions=tuple(sorted(conclusions.values(), key=lambda c: c.experiment_id)),
        preference=preference,
        actions=actions,
        problems=tuple(problems),
        fingerprint=fingerprint,
        coverage=dict(sorted(coverage.items())),
    )
