"""Status banner contract independent of toolkit widgets."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StatusBannerState:
    workflow_state: str
    display_text: str
    severity: str


def update_status_banner(workflow_state: str) -> StatusBannerState:
    state_value = str(workflow_state or "idle").strip().lower() or "idle"
    severity_map = {
        "idle": "neutral",
        "designing": "info",
        "planned": "info",
        "running": "info",
        "reviewing": "warning",
        "failed": "error",
        "completed": "success",
    }
    severity = severity_map.get(state_value, "neutral")
    display = f"Workflow: {state_value.replace('_', ' ').title()}"
    return StatusBannerState(
        workflow_state=state_value,
        display_text=display,
        severity=severity,
    )
