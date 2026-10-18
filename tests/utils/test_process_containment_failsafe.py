"""Fail-closed process containment (PR-RUNTIME-PROCESS-CONTAINMENT-FAILSAFE).

PR #142 introduced ``run_bounded`` / ``ManagedProcess`` and documented that a child is contained and its whole tree is
killed with it.  These tests pin the corrected contract:

* where containment is required (Windows) a child is never run without its container: a refused or failing attach, or a
  container that cannot even be built, kills the child and reports the reason;
* ``contained`` is true only if the OS accepted the child;
* the child is created suspended and resumed inside the job, so no descendant can be created before containment;
* a guarantee about time never depends on containment: an escaped descendant that holds the pipes cannot make
  ``run_bounded`` or ``stop`` wait for it;
* a managed or bounded child never touches an unrelated process.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from src.utils import managed_process
from src.utils.managed_process import (
    ContainmentError,
    ManagedProcess,
    containment_required,
    run_bounded,
)
from src.utils.process_container_v2 import (
    NullProcessContainer,
    ProcessContainer,
    ProcessContainerConfig,
)

windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows job objects")

# The real interpreter, not the venv launcher: the launcher puts its child in a job of its own, which masks escapes.
_PY = getattr(sys, "_base_executable", sys.executable)
_SLEEP = "import time; time.sleep(60)"
_ESCAPEE_SECONDS = 25


def _wait_until(predicate, seconds: float = 15.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _kill_pid(pid: int, marker: str) -> None:
    """Clean-up of a test-created process, only if the pid still belongs to it.

    ``marker`` is a string unique to the process's command line (its pid-file path).  A recycled pid whose command line
    lacks it is left alone: this file's contract is that nothing unrelated is ever terminated."""

    import psutil

    try:
        process = psutil.Process(pid)
        if marker not in " ".join(process.cmdline()):
            return
        process.kill()
    except psutil.Error:
        return


class _FakeContainer(ProcessContainer):
    """A container whose attach behaviour the test controls.  It never reaches the OS."""

    def __init__(self, job_id: str, config: ProcessContainerConfig, *, attach) -> None:
        super().__init__(job_id, config)
        self._attach = attach
        self.attached: list[int] = []
        self.killed = 0
        self.torn_down = False

    def add_pid(self, pid: int) -> bool:
        result = self._attach(pid)
        if result:
            self.attached.append(pid)
        return bool(result)

    def kill_all(self) -> None:
        self.killed += 1

    def teardown(self) -> None:
        self.torn_down = True


def _use_container(monkeypatch: pytest.MonkeyPatch, factory) -> list:
    made: list = []

    def _build(job_id, config):
        container = factory(job_id, config)
        made.append(container)
        return container

    monkeypatch.setattr(managed_process, "build_process_container", _build)
    return made


def _refuses(job_id, config):
    return _FakeContainer(job_id, config, attach=lambda pid: False)


def _raises(job_id, config):
    def _boom(pid):
        raise OSError("attach exploded")

    return _FakeContainer(job_id, config, attach=_boom)


# --- the platform policy ----------------------------------------------------------------------------------


def test_containment_is_required_exactly_on_windows() -> None:
    assert containment_required() is (os.name == "nt")


# --- fail closed when containment is required ---------------------------------------------------------------


@pytest.mark.parametrize("factory", [_refuses, _raises], ids=["add_pid_false", "add_pid_raises"])
def test_a_required_child_that_cannot_be_attached_is_stopped_and_start_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, factory
) -> None:
    made = _use_container(monkeypatch, factory)
    marker = tmp_path / "ran.txt"
    code = f"import pathlib, time; pathlib.Path({str(marker)!r}).write_text('ran'); time.sleep(60)"
    proc = ManagedProcess([_PY, "-c", code], label="t", require_containment=True)
    with pytest.raises(ContainmentError):
        proc.start()
    assert proc.process is None and proc.pid is None and proc.contained is False
    assert made and made[0].torn_down, "the container must be released on a refused start"
    time.sleep(0.7)  # a child that was merely left running would have written its marker by now
    assert not marker.exists()


@pytest.mark.parametrize("factory", [_refuses, _raises], ids=["add_pid_false", "add_pid_raises"])
def test_run_bounded_does_not_run_a_command_it_could_not_contain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, factory
) -> None:
    _use_container(monkeypatch, factory)
    marker = tmp_path / "ran.txt"
    code = f"import pathlib; pathlib.Path({str(marker)!r}).write_text('ran')"
    outcome = run_bounded(
        [_PY, "-c", code], timeout_seconds=10, max_stdout_bytes=100, require_containment=True
    )
    assert outcome.launch_error.startswith("containment unavailable")
    assert outcome.returncode is None and outcome.contained is False
    time.sleep(0.5)
    assert not marker.exists()


def test_a_required_child_is_not_started_when_the_container_cannot_be_built(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    spawned: list = []
    real_popen = subprocess.Popen
    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **k: spawned.append(a) or real_popen(*a, **k)
    )
    _use_container(
        monkeypatch,
        lambda job_id, config: NullProcessContainer(
            job_id, config, "construction_failed: windows job object: denied"
        ),
    )
    with pytest.raises(ContainmentError, match="construction_failed"):
        ManagedProcess([_PY, "-c", _SLEEP], require_containment=True).start()
    outcome = run_bounded(
        [_PY, "-c", "pass"], timeout_seconds=5, max_stdout_bytes=10, require_containment=True
    )
    assert "construction_failed" in outcome.launch_error
    assert spawned == [], "nothing may be spawned when the required container does not exist"


# --- best effort where containment is not required ---------------------------------------------------------


def test_without_a_required_container_the_child_runs_and_says_it_is_uncontained(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _use_container(
        monkeypatch,
        lambda job_id, config: NullProcessContainer(job_id, config, "unsupported_platform: plan9"),
    )
    with caplog.at_level("WARNING", logger=managed_process.logger.name):
        proc = ManagedProcess([_PY, "-c", "print('hi')"], require_containment=False)
        proc.start()
    assert proc.contained is False
    assert "without an OS container" in caplog.text and "unsupported_platform" in caplog.text
    assert _wait_until(lambda: "hi" in proc.stdout_tail())
    proc.stop()
    outcome = run_bounded(
        [_PY, "-c", "print('ran')"],
        timeout_seconds=10,
        max_stdout_bytes=100,
        require_containment=False,
    )
    assert outcome.stdout.strip() == b"ran" and outcome.contained is False


@pytest.mark.parametrize("factory", [_refuses, _raises], ids=["add_pid_false", "add_pid_raises"])
def test_an_optional_child_whose_attach_failed_runs_but_is_not_reported_as_contained(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, factory
) -> None:
    _use_container(monkeypatch, factory)
    with caplog.at_level("WARNING", logger=managed_process.logger.name):
        proc = ManagedProcess([_PY, "-c", "print('hi')"], require_containment=False)
        proc.start()
    assert _wait_until(lambda: "hi" in proc.stdout_tail())
    assert proc.contained is False, (
        "contained must report what the OS accepted, not what was attempted"
    )
    assert "running it uncontained" in caplog.text
    proc.stop()


# --- a successful attach is reported truthfully -------------------------------------------------------------


@windows_only
def test_a_really_contained_child_reports_contained_and_dies_with_its_tree(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    child = (
        "import os, pathlib, time; "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(60)"
    )
    parent = (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([{_PY!r}, '-c', {child!r}])\n"
        "time.sleep(60)\n"
    )
    proc = ManagedProcess([_PY, "-c", parent], label="t")
    proc.start()
    assert proc.contained is True
    assert _wait_until(pid_file.exists)
    grandchild = int(pid_file.read_text())
    proc.stop(grace_seconds=2)
    assert _wait_until(lambda: not _pid_alive(grandchild)), "stop() left a descendant running"


# --- early children: no descendant before containment (the spawn-then-attach window) -----------------------------


@windows_only
def test_a_child_cannot_create_descendants_before_it_is_inside_the_job(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Make the attach slow.  A child that ran during that window would fork a grandchild outside the job."""

    from src.utils.process_container_v2 import WindowsContainerAdapter

    real_add_pid = WindowsContainerAdapter.add_pid

    def _slow_add_pid(self, pid: int) -> bool:
        time.sleep(1.5)
        return real_add_pid(self, pid)

    monkeypatch.setattr(WindowsContainerAdapter, "add_pid", _slow_add_pid)
    pid_file = tmp_path / "grandchild.pid"
    child = (
        "import os, pathlib, time; "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep({_ESCAPEE_SECONDS})"
    )
    parent = (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([{_PY!r}, '-c', {child!r}])\n"
        "time.sleep(60)\n"
    )
    proc = ManagedProcess([_PY, "-c", parent], label="t")
    grandchild = None
    try:
        proc.start()
        assert proc.contained is True
        assert _wait_until(pid_file.exists)
        grandchild = int(pid_file.read_text())
        started = time.monotonic()
        proc.stop(grace_seconds=1)
        # The grandchild lives for _ESCAPEE_SECONDS on its own: it must have been killed by stop(), not outlived it,
        # and stop() must not have waited for it.
        assert time.monotonic() - started < 10
        assert _wait_until(lambda: not _pid_alive(grandchild), 5), (
            "a grandchild created before containment escaped the job and outlived stop()"
        )
    finally:
        proc.stop(grace_seconds=1)
        if grandchild is not None:
            _kill_pid(grandchild, str(pid_file))


@windows_only
def test_the_child_does_not_execute_until_it_is_in_its_container(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from src.utils.process_container_v2 import WindowsContainerAdapter

    marker = tmp_path / "started.txt"
    seen_before_attach: list[bool] = []
    real_add_pid = WindowsContainerAdapter.add_pid

    def _observing_add_pid(self, pid: int) -> bool:
        time.sleep(1.0)
        seen_before_attach.append(marker.exists())
        return real_add_pid(self, pid)

    monkeypatch.setattr(WindowsContainerAdapter, "add_pid", _observing_add_pid)
    code = f"import pathlib, time; pathlib.Path({str(marker)!r}).write_text('x'); time.sleep(60)"
    proc = ManagedProcess([_PY, "-c", code], label="t")
    try:
        proc.start()
        assert seen_before_attach == [False], "the child ran instructions before it was contained"
        assert _wait_until(marker.exists), "the child must run once it has been resumed"
    finally:
        proc.stop(grace_seconds=1)


# --- time bounds do not depend on containment ----------------------------------------------------------------


def _escapee_parent() -> str:
    return (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([{_PY!r}, '-c', 'import time; time.sleep({_ESCAPEE_SECONDS})'])\n"
        "time.sleep(60)\n"
    )


def test_run_bounded_returns_promptly_when_an_escaped_descendant_holds_the_pipes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_container(
        monkeypatch,
        lambda job_id, config: NullProcessContainer(job_id, config, "unsupported_platform: test"),
    )
    started = time.monotonic()
    outcome = run_bounded(
        [_PY, "-c", _escapee_parent()],
        timeout_seconds=1.0,
        max_stdout_bytes=100,
        require_containment=False,
    )
    elapsed = time.monotonic() - started
    assert outcome.timed_out is True
    assert elapsed < 10, f"run_bounded waited {elapsed:.0f}s for a descendant it could not kill"


def test_stop_returns_promptly_when_an_escaped_descendant_holds_the_pipes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_container(
        monkeypatch,
        lambda job_id, config: NullProcessContainer(job_id, config, "unsupported_platform: test"),
    )
    proc = ManagedProcess([_PY, "-c", _escapee_parent()], label="t", require_containment=False)
    proc.start()
    time.sleep(1.0)
    started = time.monotonic()
    proc.stop(grace_seconds=1)
    elapsed = time.monotonic() - started
    assert elapsed < 10, f"stop() waited {elapsed:.0f}s for a descendant it could not kill"


def test_output_read_before_the_deadline_survives_a_reader_that_never_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_container(
        monkeypatch,
        lambda job_id, config: NullProcessContainer(job_id, config, "unsupported_platform: test"),
    )
    code = (
        "import subprocess, sys, time\n"
        "print('early output', flush=True)\n"
        f"subprocess.Popen([{_PY!r}, '-c', 'import time; time.sleep({_ESCAPEE_SECONDS})'])\n"
        "time.sleep(60)\n"
    )
    outcome = run_bounded(
        [_PY, "-c", code], timeout_seconds=2.0, max_stdout_bytes=1000, require_containment=False
    )
    assert outcome.timed_out is True
    assert b"early output" in outcome.stdout


# --- cancellation and owner death -------------------------------------------------------------------------------


@windows_only
def test_cancelling_a_contained_run_kills_the_whole_tree(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    child = (
        "import os, pathlib, time; "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(60)"
    )
    parent = (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([{_PY!r}, '-c', {child!r}])\n"
        "time.sleep(60)\n"
    )
    cancel = threading.Event()

    def _cancel_once_the_grandchild_exists() -> None:
        _wait_until(pid_file.exists, 30)
        cancel.set()

    threading.Thread(target=_cancel_once_the_grandchild_exists, daemon=True).start()
    outcome = run_bounded(
        [_PY, "-c", parent], timeout_seconds=60, max_stdout_bytes=100, cancel=cancel
    )
    assert outcome.cancelled is True and outcome.contained is True
    assert pid_file.exists()
    grandchild = int(pid_file.read_text())
    assert _wait_until(lambda: not _pid_alive(grandchild), 10)


@windows_only
def test_a_bounded_child_dies_when_its_owner_dies(tmp_path: Path) -> None:
    pid_file = tmp_path / "bounded.pid"
    repo_root = Path(__file__).resolve().parents[2]
    child = (
        "import os, pathlib, time; "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(60)"
    )
    owner_code = (
        "import sys\n"
        f"sys.path.insert(0, {str(repo_root)!r})\n"
        "from src.utils.managed_process import run_bounded\n"
        f"run_bounded([{_PY!r}, '-c', {child!r}], timeout_seconds=120, max_stdout_bytes=100)\n"
    )
    owner = subprocess.Popen([_PY, "-c", owner_code])
    try:
        assert _wait_until(pid_file.exists, 30)
        bounded = int(pid_file.read_text())
        assert _pid_alive(bounded)
        owner.kill()
        owner.wait(timeout=10)
        assert _wait_until(lambda: not _pid_alive(bounded), 10), "bounded child outlived its owner"
    finally:
        if owner.poll() is None:
            owner.kill()
        if pid_file.exists():
            _kill_pid(int(pid_file.read_text()), str(pid_file))


# --- the production failure path: the real Windows adapter, a suspended child ---------------------------------------------


def _marker_script(marker: Path) -> str:
    return f"import pathlib, time; pathlib.Path({str(marker)!r}).write_text('ran'); time.sleep(60)"


@windows_only
def test_a_suspended_child_whose_attach_is_refused_never_executes_and_start_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from src.utils.process_container_v2 import WindowsContainerAdapter

    attached: list[int] = []
    monkeypatch.setattr(
        WindowsContainerAdapter, "add_pid", lambda self, pid: attached.append(pid) or False
    )
    marker = tmp_path / "ran.txt"
    proc = ManagedProcess([_PY, "-c", _marker_script(marker)], label="t")
    with pytest.raises(ContainmentError, match="refused"):
        proc.start()
    assert attached, "the real adapter must have been asked to attach"
    time.sleep(
        2.0
    )  # long enough for an interpreter to start and write the marker, were it ever resumed
    assert not marker.exists(), "a child whose containment failed executed instructions"


@windows_only
def test_a_child_that_cannot_be_resumed_is_stopped_and_start_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from src.utils import win_jobobject

    monkeypatch.setattr(win_jobobject, "resume_suspended_process", lambda pid: False)
    marker = tmp_path / "ran.txt"
    proc = ManagedProcess([_PY, "-c", _marker_script(marker)], label="t")
    with pytest.raises(ContainmentError, match="resumed"):
        proc.start()
    assert proc.process is None
    time.sleep(2.0)
    assert not marker.exists()
    outcome = run_bounded(
        [_PY, "-c", _marker_script(marker)], timeout_seconds=5, max_stdout_bytes=10
    )
    assert outcome.launch_error.startswith("containment unavailable") and not marker.exists()


@windows_only
def test_an_optional_suspended_child_whose_attach_is_refused_still_runs_uncontained(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from src.utils.process_container_v2 import WindowsContainerAdapter

    monkeypatch.setattr(WindowsContainerAdapter, "add_pid", lambda self, pid: False)
    marker = tmp_path / "ran.txt"
    proc = ManagedProcess([_PY, "-c", _marker_script(marker)], label="t", require_containment=False)
    try:
        proc.start()
        assert proc.contained is False
        assert _wait_until(marker.exists), (
            "an optional child must be resumed, not left suspended forever"
        )
    finally:
        proc.stop(grace_seconds=1)


def test_an_interrupt_while_attaching_leaves_no_child_and_no_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spawned: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    def _recording_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        spawned.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", _recording_popen)

    def _interrupt(pid: int) -> bool:
        raise KeyboardInterrupt

    made = _use_container(
        monkeypatch, lambda job_id, config: _FakeContainer(job_id, config, attach=_interrupt)
    )
    with pytest.raises(KeyboardInterrupt):
        ManagedProcess([_PY, "-c", _SLEEP], label="t", require_containment=True).start()
    (process,) = spawned
    try:
        assert process.poll() is not None, "an interrupted start left its child running"
        assert made[0].torn_down
    finally:
        if process.poll() is None:
            process.kill()


@windows_only
def test_a_job_that_cannot_enforce_kill_on_close_is_never_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.utils import win_jobobject

    class _Refusing:
        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

        def SetInformationJobObject(self, *args):  # noqa: N802 - mirrors the Win32 name
            return 0

    monkeypatch.setattr(win_jobobject, "kernel32", _Refusing(win_jobobject.kernel32))
    with pytest.raises(OSError, match="kill-on-close"):
        win_jobobject.WindowsJobObject("refusing", memory_limit_mb=64)
    # And the factory turns that into a Null container with a reason, which a required child then refuses.
    from src.utils.process_container_v2 import build_process_container

    container = build_process_container("refusing", ProcessContainerConfig(enabled=True))
    assert isinstance(container, NullProcessContainer)
    assert "construction_failed" in container.reason


@windows_only
def test_a_refused_memory_limit_still_yields_a_kill_on_close_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.utils import win_jobobject

    calls: list[int] = []

    class _FirstCallRefused:
        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

        def SetInformationJobObject(self, *args):  # noqa: N802 - mirrors the Win32 name
            calls.append(1)
            return 0 if len(calls) == 1 else self._real.SetInformationJobObject(*args)

    monkeypatch.setattr(win_jobobject, "kernel32", _FirstCallRefused(win_jobobject.kernel32))
    job = win_jobobject.WindowsJobObject("limited", memory_limit_mb=64)
    try:
        assert len(calls) == 2
    finally:
        job.close()


def test_output_of_a_pump_abandoned_by_stop_never_leaks_into_the_restarted_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_container(
        monkeypatch,
        lambda job_id, config: NullProcessContainer(job_id, config, "unsupported_platform: test"),
    )
    escapee = (
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(3); print(\"OLD-OUTPUT\", flush=True)'])\n"
        "time.sleep(60)\n"
    )
    proc = ManagedProcess(
        [_PY, "-c", escapee.replace("sys.executable", repr(_PY))],
        label="t",
        require_containment=False,
    )
    proc.start()
    time.sleep(1.0)
    proc.stop(grace_seconds=1)  # the escaped grandchild still holds the pipe: its pump is abandoned
    proc._command = [_PY, "-c", "import time; print('NEW-OUTPUT', flush=True); time.sleep(8)"]  # noqa: SLF001
    proc.start()
    try:
        assert _wait_until(lambda: "NEW-OUTPUT" in proc.stdout_tail())
        time.sleep(3.5)  # the abandoned pump receives OLD-OUTPUT meanwhile
        assert "OLD-OUTPUT" not in proc.stdout_tail()
    finally:
        proc.stop(grace_seconds=1)


# --- no interference with processes it does not own -----------------------------------------------------------------


def test_stopping_or_timing_out_a_child_never_touches_an_unrelated_process() -> None:
    bystander = subprocess.Popen(
        [_PY, "-c", _SLEEP], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        proc = ManagedProcess([_PY, "-c", _SLEEP], label="t")
        proc.start()
        proc.stop(grace_seconds=1)
        run_bounded([_PY, "-c", _SLEEP], timeout_seconds=0.5, max_stdout_bytes=10)
        time.sleep(0.5)
        assert bystander.poll() is None, "an unrelated process was terminated"
    finally:
        bystander.kill()
        bystander.wait(timeout=10)


@windows_only
def test_a_process_inside_another_job_is_not_adopted_or_killed_by_the_managed_one() -> None:
    from src.utils.win_jobobject import WindowsJobObject

    foreign = WindowsJobObject("foreign-owner")
    external = subprocess.Popen(
        [_PY, "-c", _SLEEP], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        assert foreign.assign(external.pid)
        proc = ManagedProcess([_PY, "-c", _SLEEP], label="t")
        proc.start()
        proc.stop(grace_seconds=1)
        time.sleep(0.5)
        assert external.poll() is None, "a process owned by someone else was killed"
    finally:
        external.kill()
        external.wait(timeout=10)
        foreign.close()
