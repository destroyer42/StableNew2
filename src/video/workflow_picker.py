"""Operator-facing workflow choices for the Video Workflow tab (PR-VID-UX-313).

Pure functions over the plain workflow records ``VideoWorkflowController.list_workflow_specs`` returns.
The picker shows the catalog's friendly ``display_name`` instead of a raw workflow id; the id stays the
value the form stores, submits and persists, so saved state and frozen jobs are unaffected.

Governance is read from the record, never assumed:

* the *recommended* workflow is the approved one the catalog declares as the Make Video default
  (``make_video_default``; the owner's 2026-11-18 decision promoted Wan2.2 I2V-A14B 4-step), else the first
  ``approved`` one in catalog order (owner decision D2: approved Comfy workflows are production backends);
* an experimental workflow is never recommended and never preselected by a handoff.  It stays selectable,
  is labelled as experimental, and still needs the job's own opt-in.

Picker tiers (N13, 2026-11-26) decide only what the picker *offers*.  The catalog, its governance and the
specs are unchanged, stored jobs replay, and the selected engine is always offered, so a restored form or a
handoff keeps it:

* ``default``: always offered (every approved workflow, and the experimental engines that are the only kind
  for a task, such as the driving-clip engines);
* ``experimental_only``: unrated speed arms and superseded alternative arms, offered only with Show
  experimental;
* ``retired``: never offered (Wan-Animate-2 prompt mode failed every run).  It stays registered.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from src.video.workflow_contracts import WORKFLOW_GOVERNANCE_APPROVED

RECOMMENDED_SUFFIX = " (recommended)"
EXPERIMENTAL_SUFFIX = " (experimental)"

TIER_DEFAULT = "default"
TIER_EXPERIMENTAL_ONLY = "experimental_only"
TIER_RETIRED = "retired"


@dataclass(frozen=True)
class PickerTier:
    tier: str
    reason: str = ""


#: N13: presentation tiers by workflow id, each with its reason.  An approved workflow is always ``default``.
_PICKER_TIERS: Mapping[str, PickerTier] = {
    "wan_animate2_prompt_i2v_v1": PickerTier(
        TIER_RETIRED,
        "Retired from the picker: Wan-Animate-2 prompt mode failed 31 of 31 runs here. "
        "Stored jobs still replay.",
    ),
    "wan22_i2v_a14b_4step_ck_v1": PickerTier(
        TIER_EXPERIMENTAL_ONLY, "Unrated speed arm of Wan2.2 I2V-A14B 4-step (CK attention)."
    ),
    "wan22_i2v_a14b_4step_full_picture_v1": PickerTier(
        TIER_EXPERIMENTAL_ONLY,
        "Unrated full-picture sizes of Wan2.2 I2V-A14B 4-step; not yet tested on the GPU.",
    ),
    "wan22_i2v_a14b_svi": PickerTier(
        TIER_EXPERIMENTAL_ONLY, "Unrated SVI 2.0 arm of Wan2.2 I2V-A14B 4-step."
    ),
    "hunyuan_video15_i2v_480p_8step_v1": PickerTier(
        TIER_EXPERIMENTAL_ONLY, "Unrated candidate speed arm (HunyuanVideo 1.5, 8 steps)."
    ),
    "hunyuan_video15_i2v_480p_12step_v1": PickerTier(
        TIER_EXPERIMENTAL_ONLY, "Unrated candidate arm (HunyuanVideo 1.5, 12 steps)."
    ),
    "ltx25_distilled_i2v_v1": PickerTier(
        TIER_EXPERIMENTAL_ONLY, "Unrated candidate (LTX-2.5 distilled, silent)."
    ),
    "ltx25_distilled_i2v_audio_v1": PickerTier(
        TIER_EXPERIMENTAL_ONLY, "Unrated candidate (LTX-2.5 distilled, with audio)."
    ),
}


@dataclass(frozen=True)
class WorkflowChoice:
    workflow_id: str
    label: str
    approved: bool
    experimental: bool
    recommended: bool
    picker_tier: str = TIER_DEFAULT


def _is_approved(record: Mapping[str, Any]) -> bool:
    return str(record.get("governance_state") or "") == WORKFLOW_GOVERNANCE_APPROVED


def approved_in_preference_order(records: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Approved, non-experimental records: the declared Make Video default first, then catalog order."""

    approved = [
        record
        for record in records
        if record.get("workflow_id") and _is_approved(record) and not record.get("experimental")
    ]
    return sorted(approved, key=lambda record: not record.get("make_video_default"))


def recommended_workflow_id(records: Iterable[Mapping[str, Any]]) -> str:
    """The preferred approved workflow, or an empty string when none is approved."""

    ordered = approved_in_preference_order(records)
    return str(ordered[0]["workflow_id"]) if ordered else ""


def picker_tier(record: Mapping[str, Any]) -> PickerTier:
    """The record's picker tier with its reason; an approved workflow is always offered."""

    if _is_approved(record) and not record.get("experimental"):
        return PickerTier(TIER_DEFAULT)
    return _PICKER_TIERS.get(str(record.get("workflow_id") or ""), PickerTier(TIER_DEFAULT))


def is_offered(record: Mapping[str, Any], *, show_experimental: bool) -> bool:
    tier = picker_tier(record).tier
    return tier == TIER_DEFAULT or (tier == TIER_EXPERIMENTAL_ONLY and show_experimental)


def offered_workflow_ids(
    records: Iterable[Mapping[str, Any]],
    *,
    show_experimental: bool,
    keep: Iterable[str] = (),
) -> set[str]:
    """Workflow ids the picker offers, plus ``keep`` (the selected engine is never taken away)."""

    kept = {str(item) for item in keep if item}
    offered: set[str] = set()
    for record in records:
        workflow_id = str(record.get("workflow_id") or "")
        if workflow_id and (
            workflow_id in kept or is_offered(record, show_experimental=show_experimental)
        ):
            offered.add(workflow_id)
    return offered


def _base_name(record: Mapping[str, Any]) -> str:
    name = str(record.get("display_name") or "").strip()
    return name or str(record.get("workflow_id") or "").strip()


def workflow_choices(records: Iterable[Mapping[str, Any]]) -> list[WorkflowChoice]:
    """Picker entries in catalog order with unique, friendly labels.

    A label gets a governance marker (recommended / experimental).  When two workflows would still
    read the same, the raw id is appended so every label maps back to exactly one workflow.  Every
    record gets a choice, whatever its tier, so a restored or handed-off selection always has a label;
    ``offered_workflow_ids`` decides which ones the picker lists."""

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
                picker_tier=picker_tier(record).tier,
            )
        )
    return choices


__all__ = [
    "EXPERIMENTAL_SUFFIX",
    "RECOMMENDED_SUFFIX",
    "TIER_DEFAULT",
    "TIER_EXPERIMENTAL_ONLY",
    "TIER_RETIRED",
    "PickerTier",
    "WorkflowChoice",
    "approved_in_preference_order",
    "is_offered",
    "offered_workflow_ids",
    "picker_tier",
    "recommended_workflow_id",
    "workflow_choices",
]
