"""experiment_persistence — pure serialisation helpers for LearningController
resume state.

Extracted from LearningController.export_resume_state and
LearningController.restore_resume_state (PR-047).  These functions hold only
the serialisation/deserialisation contract and carry no GUI or widget
dependencies.  LearningController delegates the data transformation work here
and retains only the UI-facing wiring.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

# Schema version bump when the resume payload format changes.
RESUME_SCHEMA_VERSION = 1


def build_resume_payload(
    state_dict: dict[str, Any],
    workflow_state: str,
    learning_enabled: bool,
) -> dict[str, Any]:
    """Serialise a LearningState into a resumable payload dict.

    Args:
        state_dict: The result of ``LearningState.to_dict()``.
        workflow_state: Current workflow state string (e.g. ``"running"``).
        learning_enabled: Whether learning is currently enabled.

    Returns:
        A dict that can be persisted and later passed to
        ``restore_resume_payload``.
    """
    payload = dict(state_dict)
    payload["workflow_state"] = workflow_state
    payload["learning_enabled"] = bool(learning_enabled)
    payload["resume_schema_version"] = RESUME_SCHEMA_VERSION
    payload["saved_at"] = datetime.utcnow().isoformat() + "Z"
    return payload


def validate_resume_payload(payload: Any) -> bool:
    """Return True if *payload* is a non-empty dict that can be restored.

    Does not raise; callers should treat ``False`` as a no-op restore.
    """
    if not isinstance(payload, dict):
        return False
    if not payload:
        return False
    return True


def extract_workflow_state(payload: dict[str, Any]) -> str:
    """Return the workflow state string stored in *payload*, or ``""``."""
    return str(payload.get("workflow_state", "") or "").strip().lower()
