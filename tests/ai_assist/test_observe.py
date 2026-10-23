"""The AI layer finds its own child, applies and reads back below-normal priority, and bounds the tree's memory (F2)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from src.ai_assist.contracts import OutcomeCode
from src.ai_assist.events import ALLOWED_FIELDS
from src.ai_assist.observe import (
    CAP_CONSECUTIVE,
    ChildObserver,
    default_cap_gib,
)
from src.ai_assist.paths import events_path
from src.ai_assist.runtime import AiRuntime
from src.ai_assist.service import AiAssistService, ServicePolicy

from .conftest import Install, idle, request_for, roomy
from .test_service_runtime import FAST, make_service

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows priority classes")
_MB = 1024 * 1024
_GIB = 1024**3


def _policy(**overrides) -> ServicePolicy:
    return ServicePolicy(watch_interval_seconds=0.05, **overrides)


# -- deterministic unit tests of the observer with a fake psutil ---------------------------------------------------------


class FakeProc:
    def __init__(self, pid, cmd, private=0, rss=0, children=(), nice=32, raises=None):
        self.pid, self._cmd, self.private, self.rss = pid, cmd, private, rss
        self._children, self._nice, self._raises = list(children), nice, raises
        self.nice_calls: list = []

    def cmdline(self):
        if self._raises:
            raise self._raises
        return self._cmd

    def children(self, recursive=False):
        return list(self._children)

    def memory_info(self):
        return SimpleNamespace(private=self.private, rss=self.rss)

    def nice(self, value=None):
        if value is None:
            return self._nice
        self.nice_calls.append(value)
        self._nice = value


def fake_psutil(procs):
    module = SimpleNamespace(
        NoSuchProcess=psutil.NoSuchProcess,
        AccessDenied=psutil.AccessDenied,
        ZombieProcess=psutil.ZombieProcess,
        BELOW_NORMAL_PRIORITY_CLASS=16384,
    )
    module.Process = lambda: SimpleNamespace(children=lambda recursive=False: list(procs))
    return module


def test_the_child_is_found_by_its_unique_scratch_marker_and_nothing_else(monkeypatch) -> None:
    ours = FakeProc(10, ["llama", "-f", "C:/ai/work/r1/prompt.txt"], private=2 * _GIB)
    other = FakeProc(11, ["llama", "-f", "C:/ai/work/r2/prompt.txt"], private=50 * _GIB)
    denied = FakeProc(12, [], raises=psutil.AccessDenied(12))
    observer = ChildObserver(
        "C:/ai/work/r1", cap_gib=100, psutil_module=fake_psutil([denied, other, ours])
    )
    assert observer.poll() is None
    assert observer.evidence.child_observed
    assert observer.evidence.peak_tree_private_gib == pytest.approx(2.0)


def test_an_unfound_child_is_a_stop_only_after_the_grace_period() -> None:
    now = [0.0]
    observer = ChildObserver(
        "C:/ai/work/r1",
        cap_gib=1,
        clock=lambda: now[0],
        grace_seconds=3.0,
        psutil_module=fake_psutil([]),
    )
    assert observer.poll() is None
    now[0] = 2.9
    assert observer.poll() is None
    now[0] = 3.1
    assert observer.poll() == "child_not_observable"


def test_the_cap_needs_consecutive_breaches_and_a_recovery_resets_the_count() -> None:
    child = FakeProc(10, ["x", "C:/ai/work/r1/p"], private=3 * _GIB)
    observer = ChildObserver("C:/ai/work/r1", cap_gib=2, psutil_module=fake_psutil([child]))
    results = [observer.poll()]  # strike 1
    child.private = 1 * _GIB
    results.append(observer.poll())  # recovery resets
    child.private = 3 * _GIB
    results.append(observer.poll())  # strike 1 again
    assert results == [None, None, None] and CAP_CONSECUTIVE == 2
    assert observer.poll() == "process_memory_cap"


def test_descendants_count_toward_the_tree_and_peaks_are_kept() -> None:
    grandchild = FakeProc(20, ["x"], private=1 * _GIB, rss=2 * _GIB)
    child = FakeProc(
        10, ["x", "C:/ai/work/r1/p"], private=1 * _GIB, rss=1 * _GIB, children=[grandchild]
    )
    observer = ChildObserver("C:/ai/work/r1", cap_gib=100, psutil_module=fake_psutil([child]))
    observer.poll()
    child.private = 0
    observer.poll()
    assert observer.evidence.max_tree_processes == 2
    assert observer.evidence.peak_tree_private_gib == pytest.approx(2.0)
    assert observer.evidence.peak_tree_working_set_gib == pytest.approx(3.0)


def test_an_exited_child_is_not_a_failure() -> None:
    child = FakeProc(10, ["x", "C:/ai/work/r1/p"])
    observer = ChildObserver("C:/ai/work/r1", cap_gib=1, psutil_module=fake_psutil([child]))
    assert observer.poll() is None
    child.children = lambda recursive=False: (_ for _ in ()).throw(psutil.NoSuchProcess(10))
    assert observer.poll() is None


def test_unreadable_memory_twice_in_a_row_is_a_stop_not_a_pass() -> None:
    child = FakeProc(10, ["x", "C:/ai/work/r1/p"])
    child.memory_info = lambda: (_ for _ in ()).throw(RuntimeError("denied"))
    observer = ChildObserver("C:/ai/work/r1", cap_gib=1, psutil_module=fake_psutil([child]))
    assert observer.poll() is None
    assert observer.poll() == "process_memory_unreadable"


def test_the_default_cap_scales_with_the_model_and_is_never_unbounded() -> None:
    assert default_cap_gib(0) == pytest.approx(2.0)
    assert default_cap_gib(int(5.68e9)) == pytest.approx(5.68e9 / _GIB * 1.5 + 2.0)


def test_priority_is_requested_then_read_back_not_assumed() -> None:
    if sys.platform != "win32":
        pytest.skip("priority classes are a Windows concept")
    child = FakeProc(10, ["x", "C:/ai/work/r1/p"], nice=32)
    observer = ChildObserver("C:/ai/work/r1", cap_gib=100, psutil_module=fake_psutil([child]))
    observer.poll()
    assert child.nice_calls == [16384]
    assert (
        observer.evidence.priority_verified is True
        and observer.evidence.observed_priority_class == 16384
    )
    stubborn = FakeProc(11, ["x", "C:/ai/work/r1/p"], nice=32)
    stubborn.nice = lambda value=None: 32  # accepts the call but the OS never changes it
    refused = ChildObserver("C:/ai/work/r1", cap_gib=100, psutil_module=fake_psutil([stubborn]))
    refused.poll()
    assert refused.evidence.priority_verified is False


# -- real children through the real service -------------------------------------------------------------------------------


def test_a_real_child_is_observed_and_the_evidence_reaches_the_outcome_and_the_event_record(
    installation: Install,
) -> None:
    outcome = make_service(installation).run(request_for("ok", extra="TEST_SLEEP:1.5"))
    assert outcome.ok
    details = outcome.details
    assert details["child_observed"] is True
    assert details["peak_tree_private_gib"] > 0 and details["max_tree_processes"] >= 1
    if sys.platform == "win32":
        assert details["priority_verified"] is True
        assert details["observed_priority_class"] == psutil.BELOW_NORMAL_PRIORITY_CLASS
    record = json.loads(events_path(installation.root).read_text(encoding="utf-8").splitlines()[-1])
    assert record["child_observed"] is True and record["peak_private_gib"] > 0
    assert set(record) <= ALLOWED_FIELDS


def test_a_child_over_its_memory_cap_is_stopped_and_its_tree_ends(installation: Install) -> None:
    started = time.monotonic()
    outcome = make_service(installation, policy=_policy(process_memory_cap_gib=0.15)).run(
        request_for("ok", extra="TEST_ALLOC_MB:300\nTEST_SLEEP:30")
    )
    assert (outcome.code, outcome.reason) == (
        OutcomeCode.RESOURCE_INSUFFICIENT,
        "process_memory_cap",
    )
    assert time.monotonic() - started < 15
    assert outcome.details["peak_tree_private_gib"] > 0.15


def test_the_same_child_is_fine_under_a_realistic_cap(installation: Install) -> None:
    outcome = make_service(installation).run(
        request_for("ok", extra="TEST_ALLOC_MB:100\nTEST_SLEEP:1")
    )
    assert outcome.ok and outcome.details["peak_tree_private_gib"] >= 0.09


def test_a_child_that_cannot_be_identified_cannot_be_bounded_so_it_is_stopped(
    installation: Install,
) -> None:
    runtime = AiRuntime(
        installation.root,
        command_factory=lambda _exe, _argv: [sys.executable, "-c", "import time; time.sleep(60)"],
        environ={"SystemRoot": "C:/Windows"},
    )
    service = AiAssistService(
        root=installation.root,
        runtime_manifest=installation.manifest,
        registry=installation.registry,
        activity_provider=idle,
        memory_probe=roomy,
        runtime=runtime,
        policy=_policy(observe_grace_seconds=0.6),
        limits=FAST,
    )
    started = time.monotonic()
    outcome = service.run(request_for("ok"))
    assert (outcome.code, outcome.reason) == (
        OutcomeCode.RESOURCE_INSUFFICIENT,
        "child_not_observable",
    )
    assert time.monotonic() - started < 15


@windows_only
def test_a_refused_priority_change_is_reported_but_does_not_fail_the_request(
    installation: Install, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_nice = psutil.Process.nice

    def deny(self, value=None):
        if value is not None:
            raise psutil.AccessDenied(self.pid)
        return real_nice(self)

    monkeypatch.setattr(psutil.Process, "nice", deny)
    outcome = make_service(installation).run(request_for("ok", extra="TEST_SLEEP:1.5"))
    assert outcome.ok and outcome.details["priority_verified"] is False


def test_unreadable_child_memory_stops_a_real_request(
    installation: Install, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(self):
        raise RuntimeError("memory unreadable")

    monkeypatch.setattr(psutil.Process, "memory_info", broken)
    outcome = make_service(installation).run(request_for("ok", extra="TEST_SLEEP:20"))
    assert (outcome.code, outcome.reason) == (
        OutcomeCode.RESOURCE_INSUFFICIENT,
        "process_memory_unreadable",
    )


def test_the_scratch_directory_is_still_removed_after_an_observer_stop(
    installation: Install,
) -> None:
    make_service(installation, policy=_policy(process_memory_cap_gib=0.15)).run(
        request_for("ok", extra="TEST_ALLOC_MB:300\nTEST_SLEEP:30", request_id="obs1")
    )
    assert not Path(installation.root / "work" / "obs1").exists()
