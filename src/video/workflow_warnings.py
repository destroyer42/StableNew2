"""The N1 warning for an experimental Comfy video workflow (``src/pipeline/policy_warnings.py``).

Experimental means *not production-promoted*, not *refused*: the Queue summary shows this warning and selecting
Queue records the job's own opt-in (``AGENTS.md`` section 2, ``VIDEO_PIPELINE.md`` section 10 invariant 4).
"""

from __future__ import annotations

from typing import Any

from src.pipeline.policy_warnings import CODE_VIDEO_EXPERIMENTAL, PolicyWarning

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


def workflow_warning_records(spec: Any) -> list[dict[str, str]]:
    """The Queue summary's warnings for ``spec`` as plain data (rendered by Tk now, by the phone gateway later)."""

    warning = experimental_workflow_warning(spec)
    return [] if warning is None else [warning.as_dict()]


__all__ = [
    "DEFAULT_WHY",
    "experimental_workflow_warning",
    "workflow_subject",
    "workflow_warning_records",
]
