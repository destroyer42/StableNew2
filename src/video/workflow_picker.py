"""Operator-facing workflow choices for the Video Workflow tab (PR-VID-UX-313).

Pure functions over the plain workflow records ``VideoWorkflowController.list_workflow_specs`` returns.
The picker shows the catalog's friendly ``display_name`` instead of a raw workflow id; the id stays the
value the form stores, submits and persists, so saved state and frozen jobs are unaffected.

Governance is read from the record, never assumed:

* the *recommended* workflow is the first ``approved`` one in catalog order (owner decision D2: approved
  Comfy workflows are production backends);
* an experimental workflow is never recommended and never preselected by a handoff.  It stays selectable,
  is labelled as experimental, and still needs the job's own opt-in.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from src.video.workflow_contracts import WORKFLOW_GOVERNANCE_APPROVED

RECOMMENDED_SUFFIX = " (recommended)"
EXPERIMENTAL_SUFFIX = " (experimental)"


@dataclass(frozen=True)
class WorkflowChoice:
    workflow_id: str
    label: str
    approved: bool
    experimental: bool
    recommended: bool


def _is_approved(record: Mapping[str, Any]) -> bool:
    return str(record.get("governance_state") or "") == WORKFLOW_GOVERNANCE_APPROVED


def recommended_workflow_id(records: Iterable[Mapping[str, Any]]) -> str:
    """The first approved workflow, or an empty string when none is approved."""

    for record in records:
        if record.get("workflow_id") and _is_approved(record) and not record.get("experimental"):
            return str(record["workflow_id"])
    return ""


def _base_name(record: Mapping[str, Any]) -> str:
    name = str(record.get("display_name") or "").strip()
    return name or str(record.get("workflow_id") or "").strip()


def workflow_choices(records: Iterable[Mapping[str, Any]]) -> list[WorkflowChoice]:
    """Picker entries in catalog order with unique, friendly labels.

    A label gets a governance marker (recommended / experimental).  When two workflows would still
    read the same, the raw id is appended so every label maps back to exactly one workflow."""

    listed = [dict(record) for record in records if record.get("workflow_id")]
    recommended = recommended_workflow_id(listed)
    drafts: list[tuple[str, dict[str, Any], str]] = []
    for record in listed:
        workflow_id = str(record["workflow_id"])
        name = _base_name(record)
        experimental = bool(record.get("experimental"))
        if experimental and "xperimental" not in name:
            name += EXPERIMENTAL_SUFFIX
        elif workflow_id == recommended:
            name += RECOMMENDED_SUFFIX
        drafts.append((workflow_id, record, name))
    counts: dict[str, int] = {}
    for _id, _record, name in drafts:
        counts[name] = counts.get(name, 0) + 1
    choices: list[WorkflowChoice] = []
    for workflow_id, record, name in drafts:
        label = f"{name} [{workflow_id}]" if counts[name] > 1 else name
        choices.append(
            WorkflowChoice(
                workflow_id=workflow_id,
                label=label,
                approved=_is_approved(record),
                experimental=bool(record.get("experimental")),
                recommended=workflow_id == recommended,
            )
        )
    return choices


__all__ = [
    "EXPERIMENTAL_SUFFIX",
    "RECOMMENDED_SUFFIX",
    "WorkflowChoice",
    "recommended_workflow_id",
    "workflow_choices",
]
