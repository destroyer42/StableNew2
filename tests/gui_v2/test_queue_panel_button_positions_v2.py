"""QueuePanelV2 queue-position-driven button states and move forwarding (live panel).

Migrated from the former ``tests/gui`` surface (PR-TEST-TRUTH-240). The auto-run / pause / send / remove / clear
forwarding contracts live in ``test_pr_mvp_080_action_state_truth.py``; this file owns the position-dependent
behavior that file does not exercise.
"""

import tkinter as tk
from types import SimpleNamespace

from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2


def _job(job_id: str, status: str) -> SimpleNamespace:
    return SimpleNamespace(job_id=job_id, status=status, get_display_summary=lambda: job_id)


def test_queue_panel_disables_remove_and_clear_for_running_only_queue(tk_root: tk.Tk) -> None:
    panel = QueuePanelV2(tk_root)
    running_job = SimpleNamespace(
        job_id="job-1", status="RUNNING", get_display_summary=lambda: "job"
    )

    panel.update_jobs([running_job])
    panel.job_listbox.selection_set(0)
    panel._update_button_states()

    assert "disabled" in panel.remove_button.state()
    assert "disabled" in panel.clear_button.state()
    assert "disabled" in panel.send_job_button.state()

    panel.destroy()


def test_queue_panel_move_buttons_use_queued_position_not_visual_index(tk_root: tk.Tk) -> None:
    panel = QueuePanelV2(
        tk_root,
        controller=SimpleNamespace(on_queue_remove_job_v2=lambda _job_id: True),
    )
    running_job = SimpleNamespace(
        job_id="running", status="RUNNING", get_display_summary=lambda: "running"
    )
    queued_job = SimpleNamespace(
        job_id="queued", status="QUEUED", get_display_summary=lambda: "queued"
    )

    panel.update_jobs([running_job, queued_job])
    panel.job_listbox.selection_set(1)
    panel._update_button_states()

    assert "disabled" in panel.move_up_button.state()
    assert "disabled" in panel.move_to_front_button.state()
    assert "disabled" in panel.move_down_button.state()
    assert "disabled" in panel.move_to_back_button.state()
    assert "disabled" not in panel.remove_button.state()

    panel.destroy()


def test_queue_panel_enables_move_up_for_second_queued_job_below_running(tk_root: tk.Tk) -> None:
    panel = QueuePanelV2(
        tk_root,
        controller=SimpleNamespace(
            on_queue_move_up_v2=lambda _job_id: True,
            on_queue_move_to_front_v2=lambda _job_id: True,
        ),
    )
    running_job = SimpleNamespace(
        job_id="running", status="RUNNING", get_display_summary=lambda: "running"
    )
    queued_job_1 = SimpleNamespace(
        job_id="queued-1", status="QUEUED", get_display_summary=lambda: "queued-1"
    )
    queued_job_2 = SimpleNamespace(
        job_id="queued-2", status="QUEUED", get_display_summary=lambda: "queued-2"
    )

    panel.update_jobs([running_job, queued_job_1, queued_job_2])
    panel.job_listbox.selection_set(2)
    panel._update_button_states()

    assert "disabled" not in panel.move_up_button.state()
    assert "disabled" not in panel.move_to_front_button.state()
    assert "disabled" in panel.move_down_button.state()
    assert "disabled" in panel.move_to_back_button.state()

    panel.destroy()


def test_queue_panel_forwards_move_up_and_move_down_to_the_controller(tk_root: tk.Tk) -> None:
    calls: list[tuple[str, str]] = []
    controller = SimpleNamespace(
        on_queue_move_up_v2=lambda job_id: calls.append(("move_up", job_id)) or True,
        on_queue_move_down_v2=lambda job_id: calls.append(("move_down", job_id)) or True,
    )
    panel = QueuePanelV2(tk_root, controller=controller)
    panel.update_jobs([_job("queued-1", "QUEUED"), _job("queued-2", "QUEUED")])

    panel.job_listbox.selection_clear(0, tk.END)
    panel.job_listbox.selection_set(1)
    panel._update_button_states()
    panel._on_move_up()

    panel.job_listbox.selection_clear(0, tk.END)
    panel.job_listbox.selection_set(0)
    panel._update_button_states()
    panel._on_move_down()

    assert calls == [("move_up", "queued-2"), ("move_down", "queued-1")]
    panel.destroy()
