"""The N1 warnings for a Comfy video workflow (``src/pipeline/policy_warnings.py``): experimental and licence.

Experimental means *not production-promoted*, not *refused*: the Queue summary shows this warning and selecting
Queue records the job's own opt-in (``AGENTS.md`` section 2, ``VIDEO_PIPELINE.md`` section 10 invariant 4).  A
catalog entry may also declare ``backend_defaults["licence_warning"]`` (``title``, ``why``, ``fix``) when its model's
licence restricts what may be generated; it is shown and recorded the same way and never blocks.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.pipeline.policy_warnings import (
    CODE_VIDEO_EXPERIMENTAL,
    CODE_VIDEO_LICENCE_RESTRICTION,
    PolicyWarning,
)

DEFAULT_WHY = "It has not been promoted for production use, so its output can vary and it has no qualification record."


def workflow_subject(spec: Any) -> str:
    return f"{spec.workflow_id}@{spec.workflow_version}"


def experimental_workflow_warning(spec: Any, *, alternative: str = "") -> PolicyWarning | None:
    """The warning for ``spec`` when it is experimental, else ``None``.

    ``alternative`` names an approved workflow to suggest (display name), when the caller knows one.
    """

    if spec is None or not getattr(spec, "is_experimental", False):
        return None
    notes = str(getattr(spec, "governance_notes", "") or "").strip()
    why = f"{DEFAULT_WHY} {notes}".strip()
    fix = "Queue runs it anyway and records your opt-in on the job."
    if alternative:
        fix += f" For a production result choose {alternative}."
    return PolicyWarning(
        code=CODE_VIDEO_EXPERIMENTAL,
        subject=workflow_subject(spec),
        title=f"{spec.display_name} is experimental.",
        why=why,
        fix=fix,
        source_gate="workflow_registry.governance",
    )


def licence_workflow_warning(spec: Any) -> PolicyWarning | None:
    """The warning ``spec``'s catalog entry declares about its model's licence, else ``None``."""

    declared = (getattr(spec, "backend_defaults", None) or {}).get("licence_warning")
    if not isinstance(declared, Mapping):
        return None
    return PolicyWarning(
        code=CODE_VIDEO_LICENCE_RESTRICTION,
        subject=workflow_subject(spec),
        title=str(declared.get("title") or ""),
        why=str(declared.get("why") or ""),
        fix=str(declared.get("fix") or ""),
        source_gate="workflow_catalog.licence",
    )


def accepted_workflow_warnings(spec: Any, *, opted_in: bool) -> tuple[PolicyWarning, ...]:
    """What a queued job records as accepted: the licence warning, and the experimental one it opted into."""

    if spec is None:
        return ()
    warnings = (
        experimental_workflow_warning(spec) if opted_in else None,
        licence_workflow_warning(spec),
    )
    return tuple(warning for warning in warnings if warning is not None)


def workflow_warning_records(spec: Any) -> list[dict[str, str]]:
    """The Queue summary's warnings for ``spec`` as plain data (rendered by Tk now, by the phone gateway later)."""

    return [warning.as_dict() for warning in accepted_workflow_warnings(spec, opted_in=True)]


__all__ = [
    "DEFAULT_WHY",
    "accepted_workflow_warnings",
    "experimental_workflow_warning",
    "licence_workflow_warning",
    "workflow_subject",
    "workflow_warning_records",
]
