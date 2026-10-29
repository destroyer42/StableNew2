"""Adapter between the Model Evidence window and the read-only Learning intelligence service.

Capture runs on the UI thread (no I/O beyond attribute reads); ``assess_model`` and ``revalidate`` run on the
window's existing bounded worker. Nothing here submits jobs, writes ratings or profiles, or changes settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.learning.evidence_autopilot import ProposalPlanningContext
from src.learning.evidence_intelligence import assess, load_sources
from src.learning.experiment_store import LearningExperimentStore
from src.learning.intelligence_contracts import IntelligenceReport, NextAction, StaleActionError
from src.learning.profile_publication import ProfilePublicationService


@dataclass(frozen=True)
class NextTestServices:
    records_path: Path | None
    store: LearningExperimentStore | None
    publication: ProfilePublicationService | None


def capture_services(owner: Any) -> NextTestServices:
    controller = getattr(owner, "learning_controller", None)
    writer = getattr(controller, "_learning_record_writer", None)
    records = getattr(writer, "records_path", None)
    profiles = getattr(getattr(controller, "app_controller", None), "generation_profiles", None)
    service = getattr(profiles, "service", None)
    return NextTestServices(
        Path(records) if records else None,
        getattr(owner, "experiment_store", None),
        ProfilePublicationService(service.store, service) if service is not None else None,
    )


def assess_model(
    context: ProposalPlanningContext, services: NextTestServices
) -> IntelligenceReport:
    return assess(
        load_sources(
            context,
            records_path=services.records_path,
            store=services.store,
            publication_service=services.publication,
        )
    )


def revalidate(
    action_id: str, context: ProposalPlanningContext, services: NextTestServices
) -> tuple[NextAction, IntelligenceReport] | None:
    """Re-derive current evidence; ``None`` means the chosen suggestion is no longer valid."""
    fresh = assess_model(context, services)
    try:
        return fresh.actions.revalidate(action_id), fresh
    except StaleActionError:
        return None
