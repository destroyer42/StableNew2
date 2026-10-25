"""PR-AI-QUAL-113: the bounded runner's ownership-bound process-tree and teardown evidence.

Every child is a tiny Python process; nothing downloaded is ever run. The evidence comes from the owned job object's own
creation/exit notifications and accounting, so a descendant that lives for milliseconds is recorded where sampling
would miss it.
"""

from __future__ import annotations

import os
import sys
import textwrap

import pytest

from src.utils import managed_process
from src.utils.managed_process import run_bounded
from src.utils.process_container_v2 import NullProcessContainer

windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows job objects")

_PY = sys.executable


def _script(body: str) -> list[str]:
    return [_PY, "-c", textwrap.dedent(body)]


def _kinds(evidence, pid: int) -> list[str]:
    return [e.kind for e in evidence.events if e.pid == pid]


@windows_only
def test_ownership_is_absent_unless_requested() -> None:
    outcome = run_bounded(_script("print('x')"), timeout_seconds=20, max_stdout_bytes=100)
    assert outcome.returncode == 0
    assert outcome.ownership is None


@windows_only
def test_clean_single_child_has_a_complete_record() -> None:
    outcome = run_bounded(
        _script("print('x')"),
        timeout_seconds=20,
        max_stdout_bytes=100,
        record_ownership=True,
    )
    evidence = outcome.ownership
    assert evidence is not None and evidence.complete, evidence
    assert evidence.active_after_teardown == 0
    assert not evidence.runner_terminated_survivors
    assert any(e.kind == "new" and e.pid == evidence.root_pid for e in evidence.events)
    assert "exit" in _kinds(evidence, evidence.root_pid)
    assert not [e for e in evidence.events if e.kind == "terminated"]


@windows_only
def test_a_millisecond_descendant_is_recorded() -> None:
    """The grandchild is gone long before any 50 ms sampler could look; the kernel notification still names it."""

    outcome = run_bounded(
        _script(
            """
            import os, subprocess, sys
            done = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"],
                                  capture_output=True, text=True)
            print(done.stdout.strip())
            """
        ),
        timeout_seconds=30,
        max_stdout_bytes=100,
        record_ownership=True,
    )
    grandchild_pid = int(outcome.stdout.decode().strip())
    evidence = outcome.ownership
    assert evidence is not None and evidence.complete, evidence
    assert grandchild_pid != evidence.root_pid
    assert _kinds(evidence, grandchild_pid) == ["new", "exit"]


@windows_only
def test_descendant_that_outlives_the_root_is_terminated_and_attributed(tmp_path) -> None:
    pidfile = tmp_path / "pid.txt"
    outcome = run_bounded(
        _script(
            f"""
            import subprocess, sys
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            open({str(pidfile)!r}, "w").write(str(child.pid))
            """
        ),
        timeout_seconds=30,
        max_stdout_bytes=100,
        record_ownership=True,
    )
    survivor = int(pidfile.read_text())
    evidence = outcome.ownership
    assert evidence is not None and evidence.complete, evidence
    assert evidence.runner_terminated_survivors
    assert evidence.active_after_teardown == 0
    assert _kinds(evidence, survivor) == ["new", "terminated"]


@windows_only
def test_timeout_kill_still_yields_a_verified_teardown() -> None:
    outcome = run_bounded(
        _script("import time; time.sleep(120)"),
        timeout_seconds=1.0,
        max_stdout_bytes=100,
        record_ownership=True,
    )
    assert outcome.timed_out
    evidence = outcome.ownership
    assert evidence is not None and evidence.complete, evidence
    assert evidence.runner_terminated_survivors and evidence.active_after_teardown == 0
    assert "terminated" in _kinds(evidence, evidence.root_pid)


@windows_only
def test_cancel_probe_sees_every_creation_before_it_decides() -> None:
    seen: list[int] = []
    observations: list[object] = []

    def cancel() -> bool:
        events = observations[0].process_events()
        pids = {e.pid for e in events if e.kind == "new"}
        seen.append(len(pids))
        return len(pids) >= 2

    outcome = run_bounded(
        _script(
            """
            import subprocess, sys, time
            subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
            time.sleep(120)
            """
        ),
        timeout_seconds=60,
        max_stdout_bytes=100,
        cancel=cancel,
        observe=observations.append,
        record_ownership=True,
    )
    assert outcome.cancelled and max(seen) >= 2
    assert outcome.ownership is not None and outcome.ownership.complete
    assert outcome.ownership.active_after_teardown == 0


@windows_only
def test_unverifiable_teardown_is_never_reported_clean(monkeypatch) -> None:
    real = managed_process.build_process_container

    def broken(label, config):
        container = real(label, config)

        def fail(root_pid):
            raise OSError("accounting unavailable")

        container.verify_teardown = fail
        return container

    monkeypatch.setattr(managed_process, "build_process_container", broken)
    outcome = run_bounded(
        _script("print('x')"), timeout_seconds=20, max_stdout_bytes=100, record_ownership=True
    )
    assert outcome.returncode == 0
    assert outcome.ownership is not None
    assert not outcome.ownership.complete
    assert "teardown_verification_failed" in outcome.ownership.problems


def test_a_container_that_cannot_record_members_means_the_child_does_not_run(monkeypatch) -> None:
    real = managed_process.build_process_container

    def without_evidence(label, config):
        container = real(label, config)
        container.supports_lifecycle_evidence = False
        return container

    monkeypatch.setattr(managed_process, "build_process_container", without_evidence)
    outcome = run_bounded(
        _script("open('should_not_exist_either', 'w')"),
        timeout_seconds=20,
        max_stdout_bytes=100,
        record_ownership=True,
    )
    assert outcome.returncode is None
    assert "ownership evidence" in outcome.launch_error
    assert not os.path.exists("should_not_exist_either")


def test_no_container_means_the_child_does_not_run(monkeypatch) -> None:
    monkeypatch.setattr(
        managed_process,
        "build_process_container",
        lambda label, config: NullProcessContainer(label, config, "disabled"),
    )
    outcome = run_bounded(
        _script("open('should_not_exist', 'w')"),
        timeout_seconds=20,
        max_stdout_bytes=100,
        record_ownership=True,
        require_containment=False,
    )
    assert outcome.returncode is None
    assert outcome.launch_error.startswith("containment unavailable")
    assert not os.path.exists("should_not_exist")
