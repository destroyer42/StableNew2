"""The queue panel says why nothing starts while dispatch is held, and stops saying it when the hold clears."""

from __future__ import annotations

import tkinter as tk
from unittest.mock import Mock

from src.contracts import QueueProjection
from src.controller.app_controller_services.background_task_coordinator import (
    BackgroundTaskCoordinator,
)
from src.controller.app_controller_services.runtime_projection_coordinator import (
    RuntimeProjectionCoordinator,
)
from src.gui.app_state_projection_sink import AppStateProjectionSink
from src.gui.app_state_v2 import AppStateV2
from src.gui.panels_v2.queue_panel_v2 import QueueActionState, QueuePanelV2
from src.gui.view_contracts.queue_status_contract import resolve_queue_status_display

HOLD = "Dispatch is held: 2 held by the GPU device-loss quarantine - open Readiness and use 'Confirm GPU recovered...'"


def test_status_contract_prefers_the_hold_over_paused_and_pending() -> None:
    held = resolve_queue_status_display(
        is_paused=False, has_running_job=False, queue_count=2, dispatch_hold=HOLD
    )
    paused_and_held = resolve_queue_status_display(
        is_paused=True, has_running_job=False, queue_count=2, dispatch_hold=HOLD
    )

    assert held.severity == "held" and HOLD in held.text and "2 pending" in held.text
    assert "(paused)" in paused_and_held.text and HOLD in paused_and_held.text


def test_status_contract_ignores_a_hold_when_nothing_is_queued_or_a_job_runs() -> None:
    running = resolve_queue_status_display(
        is_paused=False, has_running_job=True, queue_count=2, dispatch_hold=HOLD
    )
    empty = resolve_queue_status_display(
        is_paused=False, has_running_job=False, queue_count=0, dispatch_hold=HOLD
    )

    assert running.severity == "running"
    assert empty.text == "Queue: Idle"
    assert (
        resolve_queue_status_display(is_paused=False, has_running_job=False, queue_count=2).severity
        == "pending"
    )


def test_app_state_notifies_only_when_the_hold_changes() -> None:
    state = AppStateV2()
    seen: list[str] = []
    state.subscribe("queue_dispatch_hold", lambda: seen.append(state.queue_dispatch_hold))

    state.set_queue_dispatch_hold(HOLD)
    state.set_queue_dispatch_hold(HOLD)
    state.set_queue_dispatch_hold(None)

    assert seen == [HOLD, ""]


def test_the_projection_carries_the_hold_into_app_state() -> None:
    state = AppStateV2()
    sink = AppStateProjectionSink(state, dispatcher=lambda fn: fn())

    sink.apply_queue_projection(QueueProjection(revision=1, dispatch_hold=HOLD))
    assert state.queue_dispatch_hold == HOLD

    sink.apply_queue_projection(QueueProjection(revision=2))
    assert state.queue_dispatch_hold == ""


def test_the_coordinator_builds_the_hold_with_each_queue_refresh() -> None:
    state = AppStateV2()
    sink = AppStateProjectionSink(state, dispatcher=lambda fn: fn())
    holds = [HOLD, ""]
    coordinator = RuntimeProjectionCoordinator(
        sink=sink,
        background_tasks=BackgroundTaskCoordinator(dispatcher=lambda fn: fn(), run_inline=True),
        build_queue_projection=lambda: ([], []),
        load_history_entries=lambda _limit: [],
        summarize_running_job=lambda _job: None,
        describe_dispatch_hold=lambda: holds.pop(0),
    )

    coordinator.publish_queue_refresh()
    assert state.queue_dispatch_hold == HOLD
    coordinator.publish_queue_refresh()  # e.g. after the operator confirms GPU recovery
    assert state.queue_dispatch_hold == ""


def _panel(root: tk.Tk, state: AppStateV2, controller: Mock) -> QueuePanelV2:
    panel = QueuePanelV2(root, controller=controller, app_state=state)
    panel.pack()
    return panel


def test_the_panel_label_follows_the_hold(tk_root: tk.Tk) -> None:
    state = AppStateV2()
    panel = _panel(tk_root, state, Mock())
    panel.update_jobs([_job("a"), _job("b")])

    state.set_queue_dispatch_hold(HOLD)
    assert HOLD in str(panel.queue_status_label.cget("text"))

    state.set_queue_dispatch_hold("")
    assert HOLD not in str(panel.queue_status_label.cget("text"))


def test_a_refused_send_job_names_the_hold(tk_root: tk.Tk, monkeypatch) -> None:
    state = AppStateV2()
    controller = Mock()
    controller.on_queue_send_job_v2.return_value = False
    panel = _panel(tk_root, state, controller)
    monkeypatch.setattr(
        panel,
        "_queue_action_state",
        lambda: QueueActionState(auto_run=True, pause_resume=True, send=True, **_rest()),
    )
    state.set_queue_dispatch_hold(HOLD)

    panel._on_send_job()

    logged = [call.args[0] for call in controller._append_log.call_args_list]
    assert any(HOLD in line for line in logged), logged


def test_a_refused_send_job_without_a_hold_keeps_the_plain_message(
    tk_root: tk.Tk, monkeypatch
) -> None:
    controller = Mock()
    controller.on_queue_send_job_v2.return_value = False
    panel = _panel(tk_root, AppStateV2(), controller)
    monkeypatch.setattr(
        panel,
        "_queue_action_state",
        lambda: QueueActionState(auto_run=True, pause_resume=True, send=True, **_rest()),
    )

    panel._on_send_job()

    assert any(
        "Queued job was not sent" in call.args[0] for call in controller._append_log.call_args_list
    )


def _rest() -> dict:
    """Any other QueueActionState fields default-free; filled from the dataclass's own field list."""
    import dataclasses

    names = {f.name for f in dataclasses.fields(QueueActionState)} - {
        "auto_run",
        "pause_resume",
        "send",
    }
    return dict.fromkeys(names, True)


def _job(job_id: str):
    from src.pipeline.job_models_v2 import UnifiedJobSummary

    job = Mock(spec=UnifiedJobSummary)
    job.job_id = job_id
    job.positive_prompt_preview = job_id
    job.get_display_summary = Mock(return_value=job_id)
    job.is_running = False
    job.status = "QUEUED"
    job.stage = "queued"
    job.expected_images = 1
    job.base_params = {}
    return job
