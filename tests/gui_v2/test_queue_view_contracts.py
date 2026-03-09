from __future__ import annotations

from src.gui.view_contracts.queue_status_contract import (
    resolve_queue_status_display,
    resolve_queue_status_from_label,
)


def test_resolve_queue_status_display_prioritizes_running_and_pause() -> None:
    running = resolve_queue_status_display(is_paused=True, has_running_job=True, queue_count=5)
    assert running.severity == "running"
    assert running.text == "Queue: Running job..."

    paused = resolve_queue_status_display(is_paused=True, has_running_job=False, queue_count=2)
    assert paused.severity == "paused"
    assert paused.text == "Queue: Paused (2 pending)"


def test_resolve_queue_status_display_pending_and_idle() -> None:
    pending_one = resolve_queue_status_display(is_paused=False, has_running_job=False, queue_count=1)
    assert pending_one.severity == "pending"
    assert pending_one.text == "Queue: 1 job pending"

    pending_many = resolve_queue_status_display(is_paused=False, has_running_job=False, queue_count=4)
    assert pending_many.text == "Queue: 4 jobs pending"

    idle = resolve_queue_status_display(is_paused=False, has_running_job=False, queue_count=0)
    assert idle.severity == "idle"
    assert idle.text == "Queue: Idle"


def test_resolve_queue_status_from_label_normalizes_input() -> None:
    assert resolve_queue_status_from_label("running").severity == "running"
    assert resolve_queue_status_from_label(" PAUSED ").severity == "paused"
    assert resolve_queue_status_from_label(None).text == "Queue: Idle"

    custom = resolve_queue_status_from_label("warming up")
    assert custom.severity == "pending"
    assert custom.text == "Queue: Warming Up"
