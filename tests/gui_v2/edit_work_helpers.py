"""Deterministic drivers for the Edit workspaces' background work (PR-GUI-UX-580).

``ManualRegistry`` replaces the tracked-thread registry under ``BackgroundTaskCoordinator`` so a test decides when each
worker runs; ``HeldDelivery`` runs workers inline but holds the UI-thread delivery of their results, so a result can be
made to arrive *after* the operator moved on. Neither sleeps nor spawns a real thread.
"""

from __future__ import annotations

from collections.abc import Callable

from src.controller.app_controller_services.background_task_coordinator import (
    BackgroundTaskCoordinator,
)
from src.gui.view_contracts import edit_work_runner
from src.gui.view_contracts.edit_work_runner import EditWorkRunner


class ManualRegistry:
    """A thread registry whose "threads" run only when the test says so (in start order)."""

    def __init__(self) -> None:
        self.queued: list[tuple[str | None, Callable[..., object], tuple]] = []
        self.ran: list[str | None] = []

    def spawn(self, *, target, args=(), kwargs=None, name=None, daemon=False, purpose=None, **_):
        self.queued.append((name, target, tuple(args)))
        return None

    def run_next(self) -> bool:
        if not self.queued:
            return False
        name, target, args = self.queued.pop(0)
        self.ran.append(name)
        target(*args)
        return True

    def run_all(self) -> int:
        count = 0
        while self.run_next():
            count += 1
        return count


class HeldDelivery:
    """Collects the UI-thread callbacks of finished work until ``deliver`` is called."""

    def __init__(self) -> None:
        self.pending: list[Callable[[], None]] = []

    def dispatch(self, callback: Callable[[], None]) -> None:
        self.pending.append(callback)

    def deliver(self) -> int:
        delivered = 0
        while self.pending:
            self.pending.pop(0)()
            delivered += 1
        return delivered


def use_manual_registry(monkeypatch) -> ManualRegistry:
    registry = ManualRegistry()
    monkeypatch.setattr(
        edit_work_runner,
        "coordinator_factory",
        lambda widget: BackgroundTaskCoordinator(
            dispatcher=lambda fn: fn(),
            thread_registry=registry,  # type: ignore[arg-type]
        ),
    )
    return registry


def use_held_delivery(monkeypatch) -> HeldDelivery:
    held = HeldDelivery()
    monkeypatch.setattr(
        edit_work_runner,
        "coordinator_factory",
        lambda widget: BackgroundTaskCoordinator(run_inline=True, dispatcher=held.dispatch),
    )
    return held


def manual_runner(registry: ManualRegistry, *, alive: bool = True) -> EditWorkRunner:
    coordinator = BackgroundTaskCoordinator(
        dispatcher=lambda fn: fn(),
        thread_registry=registry,  # type: ignore[arg-type]
    )
    return EditWorkRunner(coordinator, is_alive=lambda: alive)
