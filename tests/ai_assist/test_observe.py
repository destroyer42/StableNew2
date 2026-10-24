"""Owned observation, invalid telemetry and real contained Python children; no model execution."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.ai_assist.contracts import OutcomeCode
from src.ai_assist.events import ALLOWED_FIELDS
from src.ai_assist.observe import ChildObserver, default_cap_gib
from src.ai_assist.paths import events_path
from src.ai_assist.service import ServicePolicy
from src.utils.managed_process import run_bounded
from src.utils.process_observation import ProcessTreeSample

from .conftest import Install, request_for
from .test_service_runtime import make_service

GIB = 1024**3
SAMPLE = ProcessTreeSample(10, 2, 2 * GIB, 3 * GIB, 1.25, True, 16384)


def bound(sample=SAMPLE, cap=100):
    observer = ChildObserver(cap_gib=cap)
    child = SimpleNamespace(pid=10, sample=lambda: sample)
    observer.bind(child)
    return observer, child


def test_only_explicitly_bound_request_is_observed():
    observer, child = bound()
    unrelated = SimpleNamespace(
        pid=99, cmdline=lambda: ["same", "scratch"], sample=lambda: pytest.fail("unowned read")
    )
    assert observer.poll() is None
    assert observer.evidence.max_tree_processes == 2
    assert observer.evidence.peak_tree_private_gib == 2
    assert observer.evidence.peak_tree_working_set_gib == 3
    assert observer.evidence.tree_cpu_seconds == 1.25
    assert unrelated.pid != child.pid
    with pytest.raises(ValueError):
        observer.bind(unrelated)


def test_missing_child_fails_after_grace():
    now = [0.0]
    observer = ChildObserver(cap_gib=1, clock=lambda: now[0])
    assert observer.poll() is None
    now[0] = 4
    assert observer.poll() == "child_not_observable"


@pytest.mark.parametrize(
    "sample",
    [
        None,
        replace(SAMPLE, root_pid=99),
        replace(SAMPLE, process_count=0),
        replace(SAMPLE, private_bytes=-1),
        replace(SAMPLE, working_set_bytes=float("nan")),
        replace(SAMPLE, cpu_seconds=float("inf")),
    ],
)
def test_invalid_or_wrong_identity_samples_fail_closed(sample):
    observer, _ = bound(sample)
    assert observer.poll() == "process_observation_invalid"
    assert not observer.evidence.child_observed


def test_inaccessible_or_exited_child_never_passes():
    observer, child = bound()
    child.sample = lambda: (_ for _ in ()).throw(OSError("exited or denied"))
    assert observer.poll() == "process_memory_unreadable"
    assert not observer.evidence.child_observed


def test_priority_requires_readback():
    observer, _ = bound(replace(SAMPLE, priority_verified=False))
    assert observer.poll() == "process_priority_unverified"
    assert observer.evidence.priority_verified is False


def test_cap_requires_two_consecutive_samples_and_recovery_resets():
    observer, child = bound(cap=1)
    assert observer.poll() is None
    child.sample = lambda: replace(SAMPLE, private_bytes=GIB // 2)
    assert observer.poll() is None
    child.sample = lambda: SAMPLE
    assert observer.poll() is None
    assert observer.poll() == "process_memory_cap"


def test_default_cap():
    assert default_cap_gib(2 * GIB) == 5


def test_real_child_evidence_reaches_outcome_and_event(installation: Install):
    outcome = make_service(installation).run(request_for("ok", extra="TEST_SLEEP:1.5"))
    assert outcome.ok
    assert outcome.details["child_observed"] is True
    assert outcome.details["peak_tree_private_gib"] > 0
    assert outcome.details["tree_cpu_seconds"] >= 0
    if sys.platform == "win32":
        assert outcome.details["priority_verified"] is True
    record = json.loads(events_path(installation.root).read_text(encoding="utf-8").splitlines()[-1])
    assert record["child_observed"] and set(record) <= ALLOWED_FIELDS


def test_real_memory_breach_cancels_request_and_removes_scratch(installation: Install):
    started = time.monotonic()
    outcome = make_service(
        installation, policy=ServicePolicy(watch_interval_seconds=0.05, process_memory_cap_gib=0.15)
    ).run(request_for("ok", extra="TEST_ALLOC_MB:300\nTEST_SLEEP:30", request_id="obs1"))
    assert (outcome.code, outcome.reason) == (
        OutcomeCode.RESOURCE_INSUFFICIENT,
        "process_memory_cap",
    )
    assert time.monotonic() - started < 15
    assert not (installation.root / "work" / "obs1").exists()


def test_observation_capability_expires_after_timeout():
    views = []
    result = run_bounded(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        timeout_seconds=0.25,
        max_stdout_bytes=100,
        observe=views.append,
    )
    assert result.timed_out
    assert len(views) == 1
    with pytest.raises(OSError, match="expired"):
        views[0].sample()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows job membership / retained handles")
def test_pid_reuse_cannot_read_unrelated_process(monkeypatch):
    from src.utils import win_jobobject as win

    reads = []
    closes = []
    monkeypatch.setattr(win.kernel32, "OpenProcess", lambda *_: 123)
    monkeypatch.setattr(win.kernel32, "IsProcessInJob", lambda *_: True)  # member BOOL stays false
    monkeypatch.setattr(win.kernel32, "GetPriorityClass", lambda *_: reads.append("priority"))
    monkeypatch.setattr(win, "get_process_memory_info", lambda *_: reads.append("memory"))
    monkeypatch.setattr(win.kernel32, "CloseHandle", closes.append)
    with pytest.raises(OSError, match="not in the owned job"):
        win._member_sample(888, 10)
    assert reads == [] and closes == [123]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows owned job tree accounting")
def test_worker_memory_and_cpu_are_counted_beyond_launcher():
    samples = []
    views = []
    worker = "import time; held=bytearray(100*1024**2); end=time.monotonic()+3; exec('while time.monotonic()<end: pass')"
    launcher = (
        "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',"
        + repr(worker)
        + "]); time.sleep(30)"
    )

    def poll():
        if views:
            samples.append(views[0].sample())
        return any(
            s.process_count >= 2 and s.private_bytes > 90 * 1024**2 and s.cpu_seconds > 0.1
            for s in samples
        )

    result = run_bounded(
        [sys.executable, "-c", launcher],
        timeout_seconds=8,
        max_stdout_bytes=100,
        observe=views.append,
        cancel=poll,
    )
    assert result.cancelled and result.contained
    assert any(
        s.process_count >= 2 and s.private_bytes > 90 * 1024**2 and s.cpu_seconds > 0.1
        for s in samples
    )
    assert all(s.priority_verified for s in samples)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows retained-handle access failures")
def test_inaccessible_member_is_rejected_without_reading_or_modification(monkeypatch):
    from src.utils import win_jobobject as win

    monkeypatch.setattr(win.kernel32, "OpenProcess", lambda *_: 0)
    monkeypatch.setattr(win.kernel32, "GetPriorityClass", lambda *_: pytest.fail("unowned access"))
    with pytest.raises(OSError, match="inaccessible"):
        win._member_sample(888, 10)
