"""Canonical staged-curation contracts for StableNew."""

from .curation_manifest import (
    CURATION_OUTCOME_SCHEMA,
    CURATION_SCHEMA,
    SELECTION_EVENT_SCHEMA,
    build_candidate_lineage_block,
    build_curation_outcome_block,
    build_selection_event_block,
)
from .curation_workflow_builder import (
    CurationSourceSelection,
    CurationWorkflowBuilder,
)
from .models import (
    CurationCandidate,
    CurationOutcome,
    CurationWorkflow,
    FaceTriageProfile,
    RefineProfile,
    SelectionEvent,
)

__all__ = [
    "CURATION_OUTCOME_SCHEMA",
    "CURATION_SCHEMA",
    "SELECTION_EVENT_SCHEMA",
    "CurationSourceSelection",
    "CurationCandidate",
    "CurationOutcome",
    "CurationWorkflow",
    "CurationWorkflowBuilder",
    "FaceTriageProfile",
    "RefineProfile",
    "SelectionEvent",
    "build_candidate_lineage_block",
    "build_curation_outcome_block",
    "build_selection_event_block",
]
