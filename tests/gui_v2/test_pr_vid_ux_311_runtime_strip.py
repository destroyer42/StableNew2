"""PR-VID-UX-311: the Video Workflow "Runtime readiness" strip and the Queue gate it drives.

The neutral session is driven with scripted callables (staleness, blocking rules); the Tk tests drive the real tab
against the real controller with injected probes and a manual worker. No ComfyUI, GPU or network is touched.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.video_workflow_controller import VideoWorkflowController
from src.gui.view_contracts.video_experiment_contract import WorkOutcome
from src.gui.view_contracts.video_runtime_readiness_contract import (
    STATE_ERROR,
    STATE_IDLE,
    STATE_LOADING,
    STATE_READY,
    RuntimeReadinessSession,
)
from src.gui.views import video_workflow_tab_frame_v2 as tab_module
from src.gui.views.video_workflow_runtime_strip_v2 import WorkflowRuntimeReadinessStrip
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.video.workflow_preflight import (
    GATE_BLOCKED,
    GATE_OK,
    GATE_UNKNOWN,
    PreflightGate,
    PreflightProbes,
    WorkflowPreflight,
)
from tests.gui_v2.test_video_workflow_motion_prep_ui import _JobService, _ManualRunner, _Messages

TI2V_ID = "wan22_ti2v_5b_i2v_v1"


def _preflight(*states: str, workflow_id: str = "wf", version: str = "1") -> WorkflowPreflight:
    gates = tuple(
        PreflightGate(
            f"g{i}", f"Gate {i}", state, f"detail {i}", "fix it" if state == GATE_BLOCKED else ""
        )
        for i, state in enumerate(states)
    )
    return WorkflowPreflight(workflow_id, version, gates)


# --------------------------------------------------------------------------- neutral session


def _session(results: dict[str, Any]) -> tuple[RuntimeReadinessSession, list[str]]:
    seen: list[str] = []

    def _evaluate(workflow_id: str, version: str) -> WorkflowPreflight:
        seen.append(workflow_id)
        value = results[workflow_id]
        if isinstance(value, Exception):
            raise value
        return value

    return RuntimeReadinessSession(evaluate=_evaluate), seen


def test_an_empty_selection_shows_nothing() -> None:
    session, _ = _session({})

    assert session.refresh("", "") is None
    assert session.view().state == STATE_IDLE and session.block_reason() == ""


def test_a_blocked_gate_blocks_and_an_unknown_one_does_not() -> None:
    session, _ = _session(
        {"a": _preflight(GATE_OK, GATE_BLOCKED), "b": _preflight(GATE_OK, GATE_UNKNOWN)}
    )

    work = session.refresh("a", "1")
    assert session.view().state == STATE_LOADING and session.block_reason() == ""
    session.finish(work, session.run(work))
    assert session.view().state == STATE_READY
    assert session.block_reason().startswith("Queue is off: Gate 1: detail 1")
    assert "1 gate blocking" in session.view().summary

    work = session.refresh("b", "1")
    session.finish(work, session.run(work))
    assert session.block_reason() == ""
    assert "Ready to queue." in session.view().summary
    assert "1 item can only be checked once ComfyUI is running" in session.view().summary


def test_a_probe_error_is_shown_and_never_blocks() -> None:
    session, _ = _session({"a": RuntimeError("nvidia-smi exploded")})

    work = session.refresh("a", "1")
    session.finish(work, session.run(work))

    assert session.view().state == STATE_ERROR and "nvidia-smi exploded" in session.view().summary
    assert session.block_reason() == ""


def test_a_finished_probe_never_overwrites_a_newer_selection() -> None:
    session, seen = _session({"a": _preflight(GATE_BLOCKED), "b": _preflight(GATE_OK)})

    work_a = session.refresh("a", "1")
    assert work_a is not None
    assert session.refresh("b", "1") is None  # a worker is running: it will follow up
    follow_up = session.finish(work_a, session.run(work_a))  # a's answer is stale
    assert follow_up is not None and follow_up.workflow_id == "b"
    assert session.block_reason() == ""  # a's blocked gate is not b's
    assert session.finish(follow_up, session.run(follow_up)) is None

    assert seen == ["a", "b"]
    assert session.view().state == STATE_READY and session.block_reason() == ""


def test_a_forced_reprobe_keeps_the_blocking_reason_until_the_new_answer() -> None:
    session, _ = _session({"a": _preflight(GATE_BLOCKED)})
    work = session.refresh("a", "1")
    session.finish(work, session.run(work))
    reason = session.block_reason()
    assert reason

    again = session.refresh("a", "1", force=True)

    assert again is not None and session.view().busy
    assert session.block_reason() == reason  # Queue does not flicker on during the re-probe
    assert session.refresh("a", "1") is None  # an unchanged selection is not probed twice


def test_closing_the_session_ignores_late_results() -> None:
    session, _ = _session({"a": _preflight(GATE_BLOCKED)})
    work = session.refresh("a", "1")
    session.close()

    assert session.finish(work, session.run(work)) is None
    assert session.block_reason() == ""
    assert session.refresh("a", "1") is None


def test_a_bad_outcome_value_is_an_error_not_a_crash() -> None:
    session, _ = _session({"a": _preflight(GATE_OK)})
    work = session.refresh("a", "1")

    session.finish(work, WorkOutcome(value="not a preflight"))

    assert session.view().state == STATE_ERROR and session.block_reason() == ""


# --------------------------------------------------------------------------- the real tab


class _Probes:
    """Mutable probe values behind ``PreflightProbes`` so a test can fix the machine and refresh."""

    def __init__(self) -> None:
        self.ram = 64.0
        self.vram: tuple[float, float] | None = (12282.0, 12000.0)
        self.state = "free"
        self.command: tuple[str, ...] = ("comfy", "main.py")
        self.requested = 0

    def build(self) -> PreflightProbes:
        self.requested += 1
        return PreflightProbes(
            command=self.command,
            base_url="http://127.0.0.1:8000",
            autostart=True,
            endpoint_state=lambda _url: self.state,
            fetch_object_info=lambda _url: None,
            fetch_system_stats=lambda _url: None,
            ram_probe=lambda: self.ram,
            gpu_probe=lambda _index: self.vram,
        )


def _tab(tk_root, tmp_path: Path, monkeypatch, probes: _Probes, *, shown: bool = True):
    service = _JobService()
    app = SimpleNamespace(job_service=service, output_dir=str(tmp_path / "output"))
    app.sync_queue_state_after_direct_submission = lambda: None
    controller = VideoWorkflowController(app_controller=app, preflight_probes=probes.build)
    app.get_video_workflow_controller = lambda: controller
    app.get_video_workflow_specs = controller.list_workflow_specs
    app.build_video_workflow_defaults = controller.build_default_form_state
    app.submit_video_workflow_job = controller.submit_video_workflow_job
    monkeypatch.setattr(tab_module, "messagebox", _Messages())
    runner = _ManualRunner()
    # Installed before the tab exists: building the tab selects the default workflow and starts a probe.
    monkeypatch.setattr(WorkflowRuntimeReadinessStrip, "_work_runner", lambda _self: runner)
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    source = tmp_path / "portrait.png"
    Image.new("RGB", (600, 900), (20, 120, 200)).save(source)
    tab.set_source_image_path(str(source))
    tab.workflow_var.set(TI2V_ID)
    tab._refresh_workspace_summary()
    if shown:
        tab._on_tab_shown()  # what Tk does when the tab is mapped (the test root is withdrawn)
    return tab, runner


@pytest.mark.gui
def test_a_blocked_gate_disables_queue_with_the_reason_and_a_refresh_enables_it(
    tk_root, tmp_path, monkeypatch
) -> None:
    probes = _Probes()
    probes.ram = 15.0  # below the 16 GB floor once ComfyUI's own start-up is counted
    tab, runner = _tab(tk_root, tmp_path, monkeypatch, probes)
    strip = tab.runtime_readiness_strip
    assert len(runner.jobs) == 1  # showing the tab started one probe, on the worker

    runner.drain()

    assert strip.last_view is not None and strip.last_view.state == STATE_READY
    assert strip.grid_info()
    assert tab.queue_workflow_button.instate(["disabled"])
    assert "System RAM" in tab.queue_block_reason_var.get()
    assert tab.queue_block_reason_var.get().startswith("Queue is off:")
    assert any(row.state == GATE_BLOCKED for row in strip.last_view.rows)

    probes.ram = 64.0
    strip.request_refresh(force=True)
    assert tab.queue_workflow_button.instate(["disabled"])  # still off until the new answer arrives
    runner.drain()

    assert tab.queue_workflow_button.instate(["!disabled"])
    assert tab.queue_block_reason_var.get() == ""
    assert not any(row.state == GATE_BLOCKED for row in strip.last_view.rows)


@pytest.mark.gui
def test_a_ready_machine_with_unknown_runtime_gates_leaves_queue_on(
    tk_root, tmp_path, monkeypatch
) -> None:
    tab, runner = _tab(tk_root, tmp_path, monkeypatch, _Probes())

    runner.drain()

    strip = tab.runtime_readiness_strip
    assert strip.last_view.state == STATE_READY
    assert {row.state for row in strip.last_view.rows} >= {GATE_OK, GATE_UNKNOWN}
    assert tab.queue_workflow_button.instate(["!disabled"])
    assert tab.queue_block_reason_var.get() == ""


@pytest.mark.gui
def test_selecting_another_workflow_discards_the_previous_workflows_answer(
    tk_root, tmp_path, monkeypatch
) -> None:
    probes = _Probes()
    probes.ram = 15.0
    tab, runner = _tab(tk_root, tmp_path, monkeypatch, probes)
    runner.drain()
    assert tab.queue_workflow_button.instate(["disabled"])

    other = next(
        meta["workflow_id"] for meta in tab._workflow_map.values() if meta["workflow_id"] != TI2V_ID
    )
    tab.workflow_var.set(next(k for k, v in tab._workflow_map.items() if v["workflow_id"] == other))
    tab._refresh_workspace_summary()
    tab.runtime_readiness_strip.request_refresh()  # the tab is shown (the test root is withdrawn)

    # The new selection is being probed; the old workflow's blocked gate must not describe it.
    assert tab.runtime_readiness_strip._session.view().state == STATE_LOADING
    assert tab.runtime_readiness_strip._session.block_reason() == ""


@pytest.mark.gui
def test_the_probe_never_submits_anything(tk_root, tmp_path, monkeypatch) -> None:
    probes = _Probes()
    tab, runner = _tab(tk_root, tmp_path, monkeypatch, probes)
    service = tab.app_controller.job_service

    runner.drain()
    tab.runtime_readiness_strip.request_refresh(force=True)
    runner.drain()

    assert probes.requested >= 2  # the gates were evaluated more than once
    assert service.calls == []  # and nothing reached JobService.submit_njrs


@pytest.mark.gui
def test_a_hidden_tab_probes_nothing_until_it_is_shown(tk_root, tmp_path, monkeypatch) -> None:
    probes = _Probes()
    tab, runner = _tab(tk_root, tmp_path, monkeypatch, probes, shown=False)

    tab._refresh_workspace_summary()
    assert runner.jobs == [] and probes.requested == 0  # no host read at start-up
    assert tab.runtime_readiness_strip._session.view().state == STATE_IDLE

    tab._on_tab_shown()
    runner.drain()

    assert probes.requested == 1
    assert tab.runtime_readiness_strip._session.view().state == STATE_READY
