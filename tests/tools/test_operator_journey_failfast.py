"""Fail-fast contract of the journey drivers (IMG-Q0 physical attempt, 2026-11-05).

A resource monitor tripped 82 s into a physical run, but ``TkDriver.wait_until`` treated the resulting ``JourneyNoGo`` as a
transient probe error and kept polling, so the journey waited out its whole timeout even though the job had finished.  These
tests pin the repaired contract with a stand-in Tk root, synthetic probes and a fake backend: no display, GPU, WebUI,
generation or desktop is involved, and nothing is ever resubmitted.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from tools.operator_journey import control
from tools.operator_journey.control import JourneyAbort, JourneyControl, JourneyHold, JourneyNoGo
from tools.operator_journey.evidence import NO_GO, JourneyEvidence
from tools.operator_journey.golden.host import HostProbes
from tools.operator_journey.golden.physical import ResourceMonitor
from tools.operator_journey.golden.session import GoldenRun, RunConfig, run_journey_body
from tools.operator_journey.observe import SubmissionObserver
from tools.operator_journey.tk_driver import ActionTrace, JourneyTimeout, TkDriver, WidgetNotFound

REPO_ROOT = Path(__file__).resolve().parents[2]
FLOOR_REASON = "available RAM 5.3 GB is below the plan floor"


class _FakeRoot:
    """The two Tk calls ``TkDriver.pump`` makes; no display is created."""

    def update_idletasks(self) -> None:
        return None

    def update(self) -> None:
        return None


def _driver() -> TkDriver:
    return TkDriver(_FakeRoot(), ActionTrace())  # type: ignore[arg-type]


# --- Scope B 1-4: the polling contract ----------------------------------------------------------------------------


def test_a_no_go_on_the_first_poll_propagates_without_entering_a_timeout_loop() -> None:
    driver, calls = _driver(), []

    def probe() -> bool:
        calls.append(1)
        raise JourneyNoGo(FLOOR_REASON)

    started = time.monotonic()
    with pytest.raises(JourneyNoGo) as raised:
        driver.wait_until(probe, timeout=60.0, description="the job reaches a terminal state")
    assert time.monotonic() - started < 5.0  # a 60 s wait did not run
    assert len(calls) == 1
    assert str(raised.value) == FLOOR_REASON
    actions = [e["action"] for e in driver.trace.entries]
    assert "wait_stopped" in actions and "wait_timeout" not in actions
    stopped = next(e for e in driver.trace.entries if e["action"] == "wait_stopped")
    assert stopped["stop"] == "JourneyNoGo" and stopped["reason"] == FLOOR_REASON


@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        (JourneyHold, "FFmpeg is not available on this host"),
        (JourneyAbort, "njr/parent_job_recorded: the edit recorded no parent"),
        (JourneyNoGo, "available RAM 2.6 GB is below the plan floor"),
    ],
)
def test_hold_abort_and_no_go_propagate_with_their_original_reason(
    kind: type[JourneyControl], reason: str
) -> None:
    driver, calls = _driver(), []

    def probe() -> bool:
        calls.append(1)
        raise kind(reason)

    with pytest.raises(kind) as raised:
        driver.wait_until(probe, timeout=30.0, description="anything")
    assert str(raised.value) == reason and type(raised.value) is kind
    assert len(calls) == 1


def test_a_stop_raised_after_transient_failures_still_ends_the_wait_at_once() -> None:
    driver, calls = _driver(), []

    def probe() -> bool:
        calls.append(1)
        if len(calls) < 3:
            raise WidgetNotFound("the History row is rebuilding")
        raise JourneyNoGo("system commit 41.0 GB exceeds the plan ceiling")

    with pytest.raises(JourneyNoGo, match="commit"):
        driver.wait_until(probe, timeout=30.0, description="x")
    assert len(calls) == 3


def test_transient_probe_errors_recover_and_return_success() -> None:
    driver, calls = _driver(), []

    def probe() -> str | None:
        calls.append(1)
        if len(calls) == 1:
            raise WidgetNotFound("the control is not built yet")
        if len(calls) == 2:
            raise RuntimeError("a widget was destroyed mid-read")
        return "ready" if len(calls) >= 4 else None

    assert driver.wait_until(probe, timeout=10.0, description="ready") == "ready"
    assert len(calls) == 4
    assert [e["action"] for e in driver.trace.entries][-1] == "wait_satisfied"


def test_an_unsatisfied_predicate_still_times_out_with_diagnostic_evidence() -> None:
    driver = _driver()

    def probe() -> bool:
        raise ValueError("row 0 is not a job yet")

    with pytest.raises(JourneyTimeout) as raised:
        driver.wait_until(
            probe,
            timeout=0.2,
            description="the image job reaches a terminal state",
            evidence=lambda: [("job-1", "running")],
        )
    text = str(raised.value)
    assert "the image job reaches a terminal state" in text
    assert "ValueError: row 0 is not a job yet" in text
    assert "job-1" in text and "running" in text
    assert driver.trace.entries[-1]["action"] == "wait_timeout"


def test_the_exception_contract_is_shared_and_creates_no_import_cycle() -> None:
    from tools.operator_journey.golden import session
    from tools.operator_journey.journeys import learning_lora_strength as legacy

    for name in ("JourneyAbort", "JourneyHold", "JourneyNoGo"):
        shared = getattr(control, name)
        assert issubclass(shared, JourneyControl)
        assert getattr(session, name) is shared
    assert legacy.JourneyAbort is control.JourneyAbort and legacy.JourneyHold is control.JourneyHold
    # The driver depends on the neutral module only: importing it must not load the golden runner.
    code = (
        "import sys; import tools.operator_journey.tk_driver; "
        "assert 'tools.operator_journey.golden.session' not in sys.modules"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr


# --- Scope B 5-6: the golden-path runner ---------------------------------------------------------------------------


def _tripped_monitor(tmp_path: Path) -> ResourceMonitor:
    """A real monitor fed the incident's RAM reading (5.3 GB available against a 6 GB floor)."""

    gpu = {
        "name": "gpu",
        "driver": "1",
        "total_mib": 12282.0,
        "used_mib": 6580.0,
        "free_mib": 5702.0,
        "uuid": "u",
    }
    memory = {
        "available_gb": 5.3,
        "total_gb": 34.0,
        "commit_used_gb": 29.0,
        "commit_limit_gb": 56.0,
    }
    limits = {
        "max_vram_used_mib": 10500,
        "min_available_ram_gb": 6,
        "max_commit_gb": 40,
        "timeout_seconds": 300,
    }
    monitor = ResourceMonitor(
        limits,
        HostProbes(gpu=lambda: dict(gpu), memory=lambda: dict(memory)),
        tmp_path / "telemetry.jsonl",
        clock=lambda: 82.76,
    )
    monitor.sample_once()
    return monitor


def test_a_tripped_monitor_ends_the_job_wait_at_once_with_its_own_reason(tmp_path: Path) -> None:
    monitor = _tripped_monitor(tmp_path)
    assert monitor.tripped == FLOOR_REASON
    run = GoldenRun.__new__(GoldenRun)
    run.config = RunConfig(run_timeout=60.0)
    run.config.extras["abort_check"] = lambda: monitor.tripped
    run.driver = _driver()
    run.submissions = SubmissionObserver()
    run.ev = JourneyEvidence(journey_id="IMG-01", backend_mode="physical")
    reads: list[int] = []
    run.job_rows = lambda: reads.append(1) or [{"job_id": "j", "status": "completed"}]  # type: ignore[method-assign]

    started = time.monotonic()
    with pytest.raises(JourneyNoGo) as raised:
        run.wait_jobs_terminal(1, description="the image job reaches a terminal state")
    assert time.monotonic() - started < 5.0
    assert str(raised.value) == FLOOR_REASON
    assert reads == []  # the stop is checked before the repository is read again
    assert run.submissions.calls == []


class _FakeBackend:
    """Stands in for the loopback WebUI: records every generation request it would have received."""

    base_url = "http://127.0.0.1:9"

    def __init__(self) -> None:
        self.generation_requests: list[str] = []
        self.started = self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


def test_the_runner_records_the_no_go_cleans_up_and_dispatches_nothing_more(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor = _tripped_monitor(tmp_path)
    backend = _FakeBackend()
    shutdowns: list[int] = []
    monkeypatch.setattr(GoldenRun, "shutdown_app", lambda self: shutdowns.append(1))
    observed: dict[str, Any] = {"reads": 0}

    def body(run: GoldenRun) -> None:
        run.driver = observed["driver"] = _driver()
        run.root = object()  # type: ignore[assignment]  # an app was "booted": the runner must shut it down
        run.job_rows = lambda: observed.__setitem__("reads", observed["reads"] + 1) or []  # type: ignore[method-assign]
        run.wait_jobs_terminal(1, description="the image job reaches a terminal state")
        observed["reached_after_wait"] = True

    config = RunConfig(evidence_dir=tmp_path / "evidence", run_timeout=60.0)
    config.extras["abort_check"] = lambda: monitor.tripped

    started = time.monotonic()
    ev = run_journey_body(
        "IMG-01", body, config, mode_label="physical", fake_a1111_factory=lambda: backend
    )
    assert time.monotonic() - started < 30.0  # never the 60 s run timeout

    assert ev.no_go_reason == FLOOR_REASON and not ev.abort_reason and not ev.hold_reason
    assert ev.verdict == NO_GO
    assert "reached_after_wait" not in observed and observed["reads"] == 0
    # Cleanup ran and the evidence survived.
    assert shutdowns == [1]
    assert backend.started and backend.stopped
    written = json.loads(next((tmp_path / "evidence").rglob("evidence.json")).read_text("utf-8"))
    assert written["no_go_reason"] == FLOOR_REASON
    assert any(e["action"] == "wait_stopped" for e in observed["driver"].trace.entries)
    # No failure path resubmitted or redispatched anything.
    assert backend.generation_requests == []
