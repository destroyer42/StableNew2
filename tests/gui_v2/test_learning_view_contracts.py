from __future__ import annotations

from src.gui.view_contracts.status_banner_contract import update_status_banner


def test_status_banner_contract_maps_workflow_state() -> None:
    state = update_status_banner("reviewing")
    assert state.workflow_state == "reviewing"
    assert state.severity == "warning"
    assert state.display_text == "Workflow: Reviewing"

    state_idle = update_status_banner("")
    assert state_idle.workflow_state == "idle"
    assert state_idle.severity == "neutral"
