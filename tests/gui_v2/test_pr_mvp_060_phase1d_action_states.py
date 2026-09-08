"""Headless Phase 1D presentation-state contracts."""

from __future__ import annotations

from types import SimpleNamespace

from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2
from src.gui.preview_panel_v2 import PreviewPanelV2


def test_add_to_queue_requires_fresh_draft_and_preview_for_three_cycles() -> None:
    empty = SimpleNamespace(packs=[], summary=None)
    draft = SimpleNamespace(packs=[object()], summary=None)

    assert PreviewPanelV2._can_add_to_queue(empty, []) is False

    for _ in range(3):
        assert PreviewPanelV2._can_add_to_queue(draft, [object()]) is True
        assert PreviewPanelV2._can_add_to_queue(empty, []) is False
        assert PreviewPanelV2._can_add_to_queue(draft, []) is False


class _ButtonState:
    def __init__(self) -> None:
        self.disabled = True

    def state(self, states: list[str]) -> None:
        self.disabled = "disabled" in states


def _queue_panel_state(*, paused: bool, running_job: object | None) -> QueuePanelV2:
    panel = object.__new__(QueuePanelV2)
    panel.app_state = SimpleNamespace(
        auto_run_queue=False,
        running_job=running_job,
    )
    panel._is_queue_paused = paused
    panel._get_selected_index = lambda: None
    panel._get_selected_job = lambda: None
    panel._selected_queued_position = lambda: (None, [])
    panel._job_status_value = lambda _job: ""
    panel._has_queued_jobs = lambda: True
    panel.move_to_front_button = _ButtonState()
    panel.move_up_button = _ButtonState()
    panel.move_down_button = _ButtonState()
    panel.move_to_back_button = _ButtonState()
    panel.remove_button = _ButtonState()
    panel.clear_button = _ButtonState()
    panel.send_job_button = _ButtonState()
    return panel


def test_manual_send_job_state_tracks_pause_and_running_job_with_auto_run_off() -> None:
    panel = _queue_panel_state(paused=False, running_job=None)
    panel._update_button_states()
    assert panel.send_job_button.disabled is False

    panel._is_queue_paused = True
    panel._update_button_states()
    assert panel.send_job_button.disabled is True

    panel._is_queue_paused = False
    panel.app_state.running_job = object()
    panel._update_button_states()
    assert panel.send_job_button.disabled is True

    panel.app_state.running_job = None
    panel._update_button_states()
    assert panel.send_job_button.disabled is False
