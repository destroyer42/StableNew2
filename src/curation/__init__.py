"""Canonical staged-curation contracts for StableNew.

This package intentionally uses lazy exports so leaf-module imports such as
``src.curation.workflow_summary`` do not pull in the heavier NJR/reprocess
builder path during early app bootstrap.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "CURATION_OUTCOME_SCHEMA",
    "CURATION_REPLAY_DESCRIPTOR_SCHEMA",
    "CURATION_SCHEMA",
    "CURATION_RECORD_KIND",
    "CURATION_WORKFLOW_SUMMARY_SCHEMA",
    "SELECTION_EVENT_SCHEMA",
    "CurationSourceSelection",
    "CurationCandidate",
    "CurationLearningBridge",
    "CurationLearningContext",
    "CurationOutcome",
    "CurationWorkflow",
    "CurationWorkflowBuilder",
    "FaceTriageProfile",
    "RefineProfile",
    "SelectionEvent",
    "build_candidate_replay_entry",
    "build_candidate_lineage_block",
    "build_curation_replay_descriptor_from_snapshot",
    "build_curation_outcome_block",
    "build_selection_event_block",
    "build_workflow_summary",
]

_EXPORT_MAP = {
    "CURATION_OUTCOME_SCHEMA": ("src.curation.curation_manifest", "CURATION_OUTCOME_SCHEMA"),
    "CURATION_SCHEMA": ("src.curation.curation_manifest", "CURATION_SCHEMA"),
    "SELECTION_EVENT_SCHEMA": ("src.curation.curation_manifest", "SELECTION_EVENT_SCHEMA"),
    "build_candidate_lineage_block": ("src.curation.curation_manifest", "build_candidate_lineage_block"),
    "build_curation_outcome_block": ("src.curation.curation_manifest", "build_curation_outcome_block"),
    "build_selection_event_block": ("src.curation.curation_manifest", "build_selection_event_block"),
    "CURATION_RECORD_KIND": ("src.curation.learning_bridge", "CURATION_RECORD_KIND"),
    "CurationLearningBridge": ("src.curation.learning_bridge", "CurationLearningBridge"),
    "CurationLearningContext": ("src.curation.learning_bridge", "CurationLearningContext"),
    "CurationSourceSelection": ("src.curation.curation_workflow_builder", "CurationSourceSelection"),
    "CurationWorkflowBuilder": ("src.curation.curation_workflow_builder", "CurationWorkflowBuilder"),
    "CURATION_REPLAY_DESCRIPTOR_SCHEMA": ("src.curation.workflow_summary", "CURATION_REPLAY_DESCRIPTOR_SCHEMA"),
    "CURATION_WORKFLOW_SUMMARY_SCHEMA": ("src.curation.workflow_summary", "CURATION_WORKFLOW_SUMMARY_SCHEMA"),
    "build_candidate_replay_entry": ("src.curation.workflow_summary", "build_candidate_replay_entry"),
    "build_curation_replay_descriptor_from_snapshot": (
        "src.curation.workflow_summary",
        "build_curation_replay_descriptor_from_snapshot",
    ),
    "build_workflow_summary": ("src.curation.workflow_summary", "build_workflow_summary"),
    "CurationCandidate": ("src.curation.models", "CurationCandidate"),
    "CurationOutcome": ("src.curation.models", "CurationOutcome"),
    "CurationWorkflow": ("src.curation.models", "CurationWorkflow"),
    "FaceTriageProfile": ("src.curation.models", "FaceTriageProfile"),
    "RefineProfile": ("src.curation.models", "RefineProfile"),
    "SelectionEvent": ("src.curation.models", "SelectionEvent"),
}


def __getattr__(name: str) -> Any:
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
