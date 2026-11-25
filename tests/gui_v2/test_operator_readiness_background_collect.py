"""PR-GUI-STALL-ATTRIBUTION: Operator Readiness collects off the Tk thread.

A captured 10.9 s UI stall had the Tk thread inside ``OperatorReadinessPanelV2.refresh`` ->
``OperatorReadinessService.collect`` -> ``JobRepository.count_jobs_with_last_control_action``, a scan of the whole
4.9 GB jobs table, while a video job was running. The panel is opened on startup, by the Refresh button, when the WebUI
attaches and by a GPU-quarantine event, so the collection now runs on a tracked worker thread and the snapshot is
rendered on the Tk thread when it arrives.
"""

from __future__ import annotations

import threading
import time
import tkinter as tk
from pathlib import Path

import pytest

from src.gui.panels_v2.operator_readiness_panel_v2 import OperatorReadinessPanelV2
from src.services.operator_readiness_service import (
    OperatorReadinessRecord,
    OperatorReadinessSnapshot,
    OperatorReadinessState,
    product_support_surfaces,
)
from src.services.ui_state_store import UIStateStore


def _snapshot(label: str = "ready") -> OperatorReadinessSnapshot:
    return OperatorReadinessSnapshot(
        support_surfaces=product_support_surfaces(),
        records=(
            OperatorReadinessRecord(
                id=label,
                display_name=f"{label} record",
                state=OperatorReadinessState.READY,
                summary=f"{label} summary.",
                blocking_reasons=(),
                operator_actions=(),
                source="test",
            ),
        ),
    )


class _Service:
    """Collects on whatever thread calls it; can be held open to model a slow scan."""

    def __init__(self, *, hold: bool = False, fail: bool = False) -> None:
        self.hold = threading.Event()
        if not hold:
            self.hold.set()
        self.fail = fail
        self.started = threading.Event()
        self.calls = 0
        self.threads: list[int] = []
        self.concurrent = 0
        self.max_concurrent = 0
        self._guard = threading.Lock()

    def collect(self, *, source_image_path: str | None = None) -> OperatorReadinessSnapshot:
        with self._guard:
            self.calls += 1
            call = self.calls
            self.concurrent += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent)
        self.threads.append(threading.get_ident())
        self.started.set()
        try:
            assert self.hold.wait(10.0)
            if self.fail:
                raise RuntimeError("the repository is unreadable")
            return _snapshot(f"call{call}")
        finally:
            with self._guard:
                self.concurrent -= 1


def _pump_until(root: tk.Tk, predicate, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached while pumping the Tk loop")


def _panel(root: tk.Tk, service: _Service, tmp_path: Path) -> OperatorReadinessPanelV2:
    panel = OperatorReadinessPanelV2(
        root,
        service=service,
        ui_state_store=UIStateStore(tmp_path / "ui_state.json"),  # type: ignore[arg-type]
    )
    panel.pack()
    return panel


@pytest.mark.gui
def test_collection_runs_off_the_tk_thread_and_renders_when_it_arrives(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    service = _Service(hold=True)
    panel = _panel(tk_root, service, tmp_path)
    try:
        # The constructor returned although the collection has not finished: the Tk thread was not blocked on it.
        assert service.started.wait(5.0)
        assert panel.snapshot is None
        assert "Collecting" in panel.snapshot_var.get()
        assert "disabled" in panel.refresh_button.state()

        service.hold.set()
        _pump_until(tk_root, lambda: panel.snapshot is not None)

        assert service.threads == [service.threads[0]]
        assert service.threads[0] != threading.get_ident()
        assert "call1" in panel.record_widgets
        assert "State as of" in panel.snapshot_var.get()
        assert "disabled" not in panel.refresh_button.state()
    finally:
        service.hold.set()
        panel.destroy()


@pytest.mark.gui
def test_refreshes_while_collecting_are_coalesced_into_one_more_collection(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    service = _Service(hold=True)
    panel = _panel(tk_root, service, tmp_path)
    try:
        assert service.started.wait(5.0)

        for _ in range(5):
            panel.refresh()

        service.hold.set()
        _pump_until(
            tk_root,
            lambda: service.calls == 2
            and panel.snapshot is not None
            and not panel._collect_inflight,
        )

        assert service.max_concurrent == 1  # never two scans at once
        assert service.calls == 2  # the running one, then one for every refresh asked for meanwhile
    finally:
        service.hold.set()
        panel.destroy()


@pytest.mark.gui
def test_a_failed_collection_is_reported_not_raised_and_refresh_works_again(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    service = _Service(fail=True)
    panel = _panel(tk_root, service, tmp_path)
    try:
        _pump_until(tk_root, lambda: not panel._collect_inflight)

        assert "could not be collected" in panel.snapshot_var.get()
        assert "the repository is unreadable" in panel.snapshot_var.get()
        assert "disabled" not in panel.refresh_button.state()

        service.fail = False
        panel.refresh()
        _pump_until(tk_root, lambda: panel.snapshot is not None)
        assert "State as of" in panel.snapshot_var.get()
    finally:
        panel.destroy()


@pytest.mark.gui
def test_destroying_the_panel_while_collecting_is_safe(tk_root: tk.Tk, tmp_path: Path) -> None:
    service = _Service(hold=True)
    panel = _panel(tk_root, service, tmp_path)
    assert service.started.wait(5.0)

    panel.destroy()
    service.hold.set()
    time.sleep(0.2)
    tk_root.update()  # nothing may fire into the destroyed widget

    assert service.calls == 1


@pytest.mark.gui
def test_synchronous_mode_keeps_the_blocking_contract_for_callers_that_need_it(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    service = _Service()
    panel = OperatorReadinessPanelV2(
        tk_root,
        service=service,  # type: ignore[arg-type]
        ui_state_store=UIStateStore(tmp_path / "ui_state.json"),
        collect_in_background=False,
    )
    try:
        assert service.calls == 1
        assert service.threads == [threading.get_ident()]
        assert panel.snapshot is not None
    finally:
        panel.destroy()
