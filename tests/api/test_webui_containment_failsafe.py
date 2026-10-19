"""PR-RUNTIME-WEBUI-CONTAINMENT-FAILSAFE: a StableNew-launched WebUI never runs uncontained.

A WebUI process the manager launches must be assigned to an anonymous, kill-on-close job object (created suspended,
assigned, then resumed) before it can execute or create a descendant. If containment cannot be established the new
child is killed and startup fails visibly. External processes are never adopted, signalled or modified.

Two kinds of test live here. Fake-process tests use a recording container/process and run everywhere; the ``windows_only``
tests use real job objects and the *base* interpreter (the venv launcher puts its child in a job of its own, which
masks an escaping descendant) and are executed, not skipped, by the hosted Windows lane.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from src.api import webui_process_manager as wpm
from src.api.webui_process_manager import (
    WebUIProcessConfig,
    WebUIProcessManager,
    WebUIStartupError,
    clear_global_webui_process_manager,
)
from src.utils.process_container_v2 import build_process_container
from tests.helpers.webui_mocks import FakeWebUIProcess, RecordingContainer

windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows job objects")
suspended_only = pytest.mark.skipif(os.name != "nt", reason="suspended start is Windows-only")

_PY = getattr(sys, "_base_executable", sys.executable)
_NEW_PROCESS_GROUP = 0x00000200
_NEW_CONSOLE = 0x00000010
_BREAKAWAY = 0x01000000
_SUSPENDED = 0x00000004


class _OsAs:
    """The manager module's ``os``, reporting a chosen ``name`` so the platform policy is testable anywhere."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __getattr__(self, attribute: str) -> Any:
        return getattr(os, attribute)


@pytest.fixture(autouse=True)
def _isolated_manager_state(monkeypatch: pytest.MonkeyPatch):
    clear_global_webui_process_manager()
    monkeypatch.delenv("STABLENEW_WEBUI_NEW_CONSOLE", raising=False)
    monkeypatch.setattr(
        "src.utils.single_instance.SingleInstanceLock.is_gui_running",
        staticmethod(lambda: True),
    )
    yield
    clear_global_webui_process_manager()


@pytest.fixture
def windows_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Containment is mandatory (the Windows policy) even when the suite runs on another platform."""

    monkeypatch.setattr(wpm, "os", _OsAs("nt"))


class _Launches:
    """Fake ``Popen`` factory that hands out ``FakeWebUIProcess`` objects and records each call."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, first_pid: int = 41000) -> None:
        self.calls: list[dict[str, Any]] = []
        self.processes: list[FakeWebUIProcess] = []
        self._next_pid = first_pid
        self._lock = threading.Lock()
        monkeypatch.setattr(subprocess, "Popen", self._popen)

    def _popen(self, command: Any, **kwargs: Any) -> FakeWebUIProcess:
        with self._lock:
            process = FakeWebUIProcess(pid=self._next_pid)
            self._next_pid += 1
            self.processes.append(process)
            self.calls.append({"command": list(command), **kwargs})
        return process


def _use_containers(monkeypatch: pytest.MonkeyPatch, *factories: Callable[[], Any]) -> list[Any]:
    """Successive launches get the containers the factories build; the list collects what was handed out."""

    made: list[Any] = []
    queue = list(factories)

    def _build(job_id: str, config: Any) -> Any:
        factory = queue.pop(0) if len(queue) > 1 else queue[0]
        container = factory()
        made.append(container)
        return container

    monkeypatch.setattr(wpm, "build_process_container", _build)
    return made


def _manager(monkeypatch: pytest.MonkeyPatch, **config: Any) -> WebUIProcessManager:
    manager = WebUIProcessManager(
        WebUIProcessConfig(command=config.pop("command", ["python", "webui.py"]), **config)
    )
    return manager


def _assert_no_published_launch(manager: WebUIProcessManager) -> None:
    assert manager.process is None
    assert manager.pid is None
    assert manager.owns_process is False
    assert manager.launch_session_command is None
    assert manager._process_container is None
    assert manager.ready_epoch == 0
    assert manager._stdout_thread is None and manager._stderr_thread is None


# --- containment is mandatory and fail-closed -----------------------------------------------------------------


def test_refused_assignment_kills_the_child_and_fails_startup(
    monkeypatch: pytest.MonkeyPatch, windows_policy: None
) -> None:
    launches = _Launches(monkeypatch)
    made = _use_containers(monkeypatch, lambda: RecordingContainer(add_pid_result=False))
    manager = _manager(monkeypatch)

    with pytest.raises(WebUIStartupError, match="container"):
        manager.start()

    assert len(launches.calls) == 1
    assert launches.processes[0].killed
    assert "teardown" in made[0].events
    _assert_no_published_launch(manager)


def test_assignment_that_raises_keeps_its_diagnostics(
    monkeypatch: pytest.MonkeyPatch, windows_policy: None
) -> None:
    launches = _Launches(monkeypatch)
    made = _use_containers(
        monkeypatch, lambda: RecordingContainer(add_pid_error=OSError("attach exploded"))
    )
    manager = _manager(monkeypatch)

    with pytest.raises(WebUIStartupError, match="attach exploded"):
        manager.start()

    assert launches.processes[0].killed
    assert "teardown" in made[0].events
    _assert_no_published_launch(manager)


def test_null_container_means_no_child_is_started(
    monkeypatch: pytest.MonkeyPatch, windows_policy: None
) -> None:
    from src.utils.process_container_v2 import NullProcessContainer, ProcessContainerConfig

    launches = _Launches(monkeypatch)
    _use_containers(
        monkeypatch,
        lambda: NullProcessContainer("x", ProcessContainerConfig(), "construction_failed: boom"),
    )
    manager = _manager(monkeypatch)

    with pytest.raises(WebUIStartupError, match="construction_failed: boom"):
        manager.start()

    assert launches.calls == []
    _assert_no_published_launch(manager)


def test_container_factory_that_raises_means_no_child_is_started(
    monkeypatch: pytest.MonkeyPatch, windows_policy: None
) -> None:
    launches = _Launches(monkeypatch)

    def _boom(job_id: str, config: Any) -> Any:
        raise RuntimeError("job object unavailable")

    monkeypatch.setattr(wpm, "build_process_container", _boom)
    manager = _manager(monkeypatch)

    with pytest.raises(WebUIStartupError, match="job object unavailable"):
        manager.start()

    assert launches.calls == []
    _assert_no_published_launch(manager)


def test_container_without_suspended_start_is_refused_on_windows(
    monkeypatch: pytest.MonkeyPatch, windows_policy: None
) -> None:
    if os.name != "nt":
        pytest.skip(
            "the suspended-start requirement is enforced where the child can be created suspended"
        )
    launches = _Launches(monkeypatch)
    container = RecordingContainer()
    container.supports_suspended_start = False
    _use_containers(monkeypatch, lambda: container)

    with pytest.raises(WebUIStartupError, match="suspended"):
        _manager(monkeypatch).start()

    assert launches.calls == []


@suspended_only
def test_child_that_cannot_be_resumed_is_cleaned_up(monkeypatch: pytest.MonkeyPatch) -> None:
    launches = _Launches(monkeypatch)
    made = _use_containers(monkeypatch, lambda: RecordingContainer(resume_result=False))
    manager = _manager(monkeypatch)

    with pytest.raises(WebUIStartupError, match="resum"):
        manager.start()

    assert launches.processes[0].killed
    assert made[0].events[-2:] == ["kill_all", "teardown"]
    _assert_no_published_launch(manager)


@suspended_only
def test_resume_that_raises_is_cleaned_up(monkeypatch: pytest.MonkeyPatch) -> None:
    launches = _Launches(monkeypatch)
    _use_containers(
        monkeypatch, lambda: RecordingContainer(resume_error=OSError("resume exploded"))
    )
    manager = _manager(monkeypatch)

    with pytest.raises(WebUIStartupError, match="resume exploded"):
        manager.start()

    assert launches.processes[0].killed
    _assert_no_published_launch(manager)


def test_containment_failure_is_a_distinct_actionable_startup_error(
    monkeypatch: pytest.MonkeyPatch, windows_policy: None
) -> None:
    _Launches(monkeypatch)
    _use_containers(monkeypatch, lambda: RecordingContainer(add_pid_result=False))

    with pytest.raises(wpm.WebUIContainmentError) as excinfo:
        _manager(monkeypatch).start()

    assert isinstance(excinfo.value, WebUIStartupError)
    assert "will not run uncontained" in str(excinfo.value)
    assert excinfo.value.__cause__ is not None  # the original reason is kept


# --- interruption ---------------------------------------------------------------------------------------------


def test_interrupt_while_assigning_leaves_no_survivor(
    monkeypatch: pytest.MonkeyPatch, windows_policy: None
) -> None:
    launches = _Launches(monkeypatch)
    made = _use_containers(
        monkeypatch, lambda: RecordingContainer(add_pid_error=KeyboardInterrupt())
    )
    manager = _manager(monkeypatch)

    with pytest.raises(KeyboardInterrupt):
        manager.start()

    assert launches.processes[0].killed
    assert "teardown" in made[0].events
    _assert_no_published_launch(manager)


@suspended_only
def test_interrupt_while_resuming_leaves_no_survivor(monkeypatch: pytest.MonkeyPatch) -> None:
    launches = _Launches(monkeypatch)
    _use_containers(monkeypatch, lambda: RecordingContainer(resume_error=KeyboardInterrupt()))
    manager = _manager(monkeypatch)

    with pytest.raises(KeyboardInterrupt):
        manager.start()

    assert launches.processes[0].killed
    _assert_no_published_launch(manager)


@pytest.mark.parametrize("failing", ["_start_output_capture", "_start_orphan_monitor"])
@pytest.mark.parametrize("failure", [RuntimeError("late failure"), KeyboardInterrupt()])
def test_failure_after_publication_unwinds_the_launch(
    monkeypatch: pytest.MonkeyPatch, windows_policy: None, failing: str, failure: BaseException
) -> None:
    launches = _Launches(monkeypatch)
    made = _use_containers(monkeypatch, lambda: RecordingContainer())
    manager = _manager(monkeypatch)

    def _fail(*args: Any, **kwargs: Any) -> None:
        raise failure

    monkeypatch.setattr(manager, failing, _fail)
    if failing == "_start_orphan_monitor":
        monkeypatch.setattr(manager, "_start_output_capture", lambda session: None)

    expected = type(failure) if isinstance(failure, KeyboardInterrupt) else WebUIStartupError
    started = time.monotonic()
    with pytest.raises(expected):
        manager.start()

    assert time.monotonic() - started < 15.0
    assert launches.processes[0].killed
    assert made[0].events[-2:] == ["kill_all", "teardown"]
    _assert_no_published_launch(manager)
    assert manager.exit_diagnostics() is None
    assert manager.is_running() is False


def test_failure_after_publication_reports_the_original_error(
    monkeypatch: pytest.MonkeyPatch, windows_policy: None
) -> None:
    _Launches(monkeypatch)
    _use_containers(monkeypatch, lambda: RecordingContainer())
    manager = _manager(monkeypatch)

    def _fail(session: str) -> None:
        raise RuntimeError("disk full opening the log")

    monkeypatch.setattr(manager, "_start_output_capture", _fail)

    with pytest.raises(WebUIStartupError, match="disk full opening the log") as excinfo:
        manager.start()

    assert isinstance(excinfo.value.__cause__, RuntimeError)


# --- reuse, serialization and loops ---------------------------------------------------------------------------


def test_failed_startup_leaves_the_manager_reusable(
    monkeypatch: pytest.MonkeyPatch, windows_policy: None
) -> None:
    launches = _Launches(monkeypatch)
    made = _use_containers(
        monkeypatch,
        lambda: RecordingContainer(add_pid_result=False),
        lambda: RecordingContainer(),
    )
    manager = _manager(monkeypatch)
    monkeypatch.setattr(manager, "_start_orphan_monitor", lambda: None)

    with pytest.raises(WebUIStartupError):
        manager.start()
    process = manager.start()

    assert process is launches.processes[1]
    assert manager.owns_process and manager.pid == launches.processes[1].pid
    assert manager._process_container is made[1]
    assert made[1].pids == [launches.processes[1].pid]
    assert launches.processes[0].killed and not launches.processes[1].killed


def test_concurrent_start_requests_create_exactly_one_process(
    monkeypatch: pytest.MonkeyPatch, windows_policy: None
) -> None:
    launches = _Launches(monkeypatch)
    _use_containers(monkeypatch, lambda: RecordingContainer())
    manager = _manager(monkeypatch)
    monkeypatch.setattr(manager, "_start_orphan_monitor", lambda: None)
    monkeypatch.setattr(manager, "check_health", lambda: True)
    results: list[Any] = []
    barrier = threading.Barrier(6)

    def _worker(index: int) -> None:
        barrier.wait()
        if index % 3 == 0:
            results.append(manager.start())
        elif index % 3 == 1:
            results.append(manager.ensure_running())
        else:
            results.append(manager.start())

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(launches.calls) == 1
    assert len(results) == 6


def test_containment_failure_does_not_cause_a_restart_loop(
    monkeypatch: pytest.MonkeyPatch, windows_policy: None
) -> None:
    launches = _Launches(monkeypatch)
    made = _use_containers(
        monkeypatch,
        lambda: RecordingContainer(),
        lambda: RecordingContainer(add_pid_result=False),
    )
    manager = _manager(monkeypatch)
    monkeypatch.setattr(manager, "_start_orphan_monitor", lambda: None)
    manager.start()
    assert manager.owns_process

    restarted = manager.restart_webui(
        wait_ready=False, max_attempts=5, base_delay=0.0, max_delay=0.0
    )

    assert restarted is False
    assert len(launches.calls) == 2  # the original launch and exactly one refused relaunch
    assert len(made) == 2
    _assert_no_published_launch(manager)


def test_ensure_running_does_not_retry_after_a_containment_failure(
    monkeypatch: pytest.MonkeyPatch, windows_policy: None
) -> None:
    launches = _Launches(monkeypatch)
    _use_containers(monkeypatch, lambda: RecordingContainer(add_pid_result=False))
    manager = _manager(monkeypatch)

    assert manager.ensure_running() is False

    assert len(launches.calls) == 1
    assert "container" in str(manager.get_status().get("last_startup_failure", "")).lower()


def test_each_launch_gets_a_fresh_container_and_the_stale_one_is_released(
    monkeypatch: pytest.MonkeyPatch, windows_policy: None
) -> None:
    launches = _Launches(monkeypatch)
    made = _use_containers(monkeypatch, lambda: RecordingContainer(), lambda: RecordingContainer())
    manager = _manager(monkeypatch)
    monkeypatch.setattr(manager, "_start_orphan_monitor", lambda: None)
    manager.start()
    first_pid = manager.pid
    launches.processes[0].exit_naturally(1)  # the process dies on its own: nobody called stop

    manager.start()

    assert len(made) == 2 and made[0] is not made[1]
    assert made[0].events[-2:] == [
        "kill_all",
        "teardown",
    ]  # the dead launch's container no longer lingers
    assert manager._process_container is made[1]
    assert manager.pid != first_pid
    assert made[1].pids == [manager.pid] and made[0].pids == [first_pid]


def test_stop_releases_the_container_so_a_later_launch_cannot_inherit_it(
    monkeypatch: pytest.MonkeyPatch, windows_policy: None
) -> None:
    _Launches(monkeypatch)
    made = _use_containers(monkeypatch, lambda: RecordingContainer(), lambda: RecordingContainer())
    manager = _manager(monkeypatch)
    monkeypatch.setattr(manager, "_start_orphan_monitor", lambda: None)
    manager.start()

    assert manager.stop_webui(grace_seconds=0.1)

    assert manager._process_container is None
    assert made[0].events[-2:] == ["kill_all", "teardown"]
    manager.start()
    assert manager._process_container is made[1]


# --- platform policy and launch compatibility -----------------------------------------------------------------


def test_other_platforms_keep_their_best_effort_behaviour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.utils.process_container_v2 import NullProcessContainer, ProcessContainerConfig

    monkeypatch.setattr(wpm, "os", _OsAs("posix"))
    launches = _Launches(monkeypatch)
    _use_containers(
        monkeypatch,
        lambda: NullProcessContainer("x", ProcessContainerConfig(), "unsupported_platform: test"),
    )
    manager = _manager(monkeypatch)
    monkeypatch.setattr(manager, "_start_orphan_monitor", lambda: None)

    manager.start()

    assert len(launches.calls) == 1
    assert manager.owns_process


def test_launch_parameters_are_preserved_alongside_containment(
    monkeypatch: pytest.MonkeyPatch, windows_policy: None
) -> None:
    launches = _Launches(monkeypatch)
    container = RecordingContainer()
    _use_containers(monkeypatch, lambda: container)
    manager = _manager(
        monkeypatch,
        command=["python", "webui.py", "--api"],
        working_dir="C:/webui",
        env_overrides={"A": "1"},
    )
    monkeypatch.setattr(manager, "_start_orphan_monitor", lambda: None)

    manager.start()

    call = launches.calls[0]
    assert call["command"] == ["python", "webui.py", "--api"]
    assert call["cwd"] == "C:/webui" and call["env"]["A"] == "1"
    assert call["shell"] is False
    assert call["text"] is True and call["encoding"] == "utf-8" and call["errors"] == "replace"
    assert call["bufsize"] == 1
    assert (call["creationflags"] & _BREAKAWAY) == 0
    if os.name == "nt":
        assert call["creationflags"] & _NEW_PROCESS_GROUP
        assert call["creationflags"] & _SUSPENDED
        assert container.events[:2] == ["add_pid", "resume"]
    assert manager.launch_session_command == ["python", "webui.py", "--api"]


@pytest.mark.parametrize("suffix", [".bat", ".cmd"])
def test_batch_launchers_go_through_cmd_exe_without_a_shell(
    monkeypatch: pytest.MonkeyPatch, windows_policy: None, suffix: str
) -> None:
    launches = _Launches(monkeypatch)
    _use_containers(monkeypatch, lambda: RecordingContainer())
    manager = _manager(monkeypatch, command=[f"webui-user{suffix}", "--api"])
    monkeypatch.setattr(manager, "_start_orphan_monitor", lambda: None)

    manager.start()

    call = launches.calls[0]
    assert call["command"][:4] == ["cmd.exe", "/d", "/s", "/c"]
    assert call["shell"] is False
    assert (call["creationflags"] & _BREAKAWAY) == 0
    assert manager.launch_session_command == [f"webui-user{suffix}", "--api"]


def test_new_console_mode_is_preserved_alongside_containment(
    monkeypatch: pytest.MonkeyPatch, windows_policy: None
) -> None:
    monkeypatch.setenv("STABLENEW_WEBUI_NEW_CONSOLE", "1")
    launches = _Launches(monkeypatch)
    _use_containers(monkeypatch, lambda: RecordingContainer())
    manager = _manager(monkeypatch)
    monkeypatch.setattr(manager, "_start_orphan_monitor", lambda: None)

    manager.start()

    call = launches.calls[0]
    assert call["stdout"] is None and call["stderr"] is None
    if os.name == "nt":
        assert call["creationflags"] & _NEW_CONSOLE and call["creationflags"] & _NEW_PROCESS_GROUP
    assert (call["creationflags"] & _BREAKAWAY) == 0


def test_occupied_endpoint_is_refused_before_any_container_or_process(
    monkeypatch: pytest.MonkeyPatch, windows_policy: None
) -> None:
    launches = _Launches(monkeypatch)
    made = _use_containers(monkeypatch, lambda: RecordingContainer())
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    try:
        manager = _manager(monkeypatch, base_url=f"http://127.0.0.1:{listener.getsockname()[1]}")
        with pytest.raises(WebUIStartupError, match="already occupied"):
            manager.start()
    finally:
        listener.close()

    assert launches.calls == [] and made == []


def test_another_managers_live_process_cannot_be_stolen(
    monkeypatch: pytest.MonkeyPatch, windows_policy: None
) -> None:
    launches = _Launches(monkeypatch)
    made = _use_containers(monkeypatch, lambda: RecordingContainer())
    first = _manager(monkeypatch)
    monkeypatch.setattr(first, "_start_orphan_monitor", lambda: None)
    first.start()
    second = _manager(monkeypatch)

    with pytest.raises(WebUIStartupError, match="already owns"):
        second.start()

    assert len(launches.calls) == 1 and len(made) == 1
    assert not launches.processes[0].killed and first.owns_process
    assert second.stop_webui() is True  # an unowned manager takes no OS action
    assert not launches.processes[0].killed


# --- real Windows job objects ---------------------------------------------------------------------------------


def _wait_for(predicate: Callable[[], bool], seconds: float = 20.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _alive(pid: int) -> bool:
    import psutil

    try:
        return psutil.Process(pid).is_running() and psutil.Process(pid).status() != "zombie"
    except psutil.Error:
        return False


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _wrapper_script(tmp_path: Path, name: str = "webui_stub.py") -> tuple[Path, Path, Path, Path]:
    """A stand-in WebUI: it marks that it ran, prints a line, starts a grandchild that holds its pipes, and sleeps."""

    marker = tmp_path / f"{name}.parent.marker"
    child_marker = tmp_path / f"{name}.child.marker"
    child_pid = tmp_path / f"{name}.child.pid"
    script = tmp_path / name
    script.write_text(
        textwrap.dedent(
            f"""
            import os, subprocess, sys, time
            open({marker.as_posix()!r}, "w").write(str(os.getpid()))
            child = subprocess.Popen([sys.executable, "-c",
                "import os, time; open({child_marker.as_posix()!r}, 'w').write(str(os.getpid())); time.sleep(120)"])
            open({child_pid.as_posix()!r}, "w").write(str(child.pid))
            print("stub-webui-ready", flush=True)
            time.sleep(120)
            """
        ),
        encoding="utf-8",
    )
    return script, marker, child_marker, child_pid


def _real_container(
    monkeypatch: pytest.MonkeyPatch, wrap: Callable[[Any], Any] | None = None
) -> list[Any]:
    made: list[Any] = []

    def _build(job_id: str, config: Any) -> Any:
        container = build_process_container(job_id, config)
        if wrap is not None:
            container = wrap(container)
        made.append(container)
        return container

    monkeypatch.setattr(wpm, "build_process_container", _build)
    return made


def _real_manager(
    monkeypatch: pytest.MonkeyPatch, command: list[str], **config: Any
) -> WebUIProcessManager:
    monkeypatch.setenv("STABLENEW_NO_WEBUI", "0")
    manager = WebUIProcessManager(WebUIProcessConfig(command=command, **config))
    return manager


def _force_cleanup(*pids: int | None) -> None:
    import psutil

    for pid in pids:
        if not pid:
            continue
        try:
            psutil.Process(pid).kill()
        except psutil.Error:
            pass


@windows_only
def test_real_contained_startup_captures_output_and_shutdown_kills_the_tree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script, marker, child_marker, child_pid_file = _wrapper_script(tmp_path)
    made = _real_container(monkeypatch)
    manager = _real_manager(monkeypatch, [_PY, str(script)], working_dir=str(tmp_path))
    child_pid = None
    try:
        process = manager.start()
        assert manager.owns_process and manager.pid == process.pid
        assert manager.launch_session_command == [_PY, str(script)]
        assert type(made[0]).__name__ == "WindowsContainerAdapter"
        assert manager._process_container is made[0]
        assert _wait_for(lambda: child_pid_file.exists() and _read_pid(child_pid_file) is not None)
        child_pid = _read_pid(child_pid_file)
        assert _wait_for(lambda: "stub-webui-ready" in manager.get_stdout_tail_text())
        assert manager._orphan_monitor_thread is not None

        assert manager.stop_webui(grace_seconds=2.0) is True

        assert not _alive(process.pid)
        assert _wait_for(lambda: child_pid is not None and not _alive(child_pid), 10.0)
        _assert_no_published_launch(manager)
    finally:
        manager.stop()
        _force_cleanup(child_pid)


@windows_only
def test_nothing_runs_before_assignment_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script, marker, child_marker, child_pid_file = _wrapper_script(tmp_path)
    seen_at_assignment: list[tuple[bool, bool]] = []

    class _Slow:
        """Delegates to the real job object, but only after a delay in which an unsuspended child would run."""

        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

        def add_pid(self, pid: int) -> bool:
            time.sleep(1.5)
            seen_at_assignment.append((marker.exists(), child_marker.exists()))
            return self._inner.add_pid(pid)

    _real_container(monkeypatch, wrap=_Slow)
    manager = _real_manager(monkeypatch, [_PY, str(script)], working_dir=str(tmp_path))
    child_pid = None
    try:
        manager.start()
        assert seen_at_assignment == [(False, False)]
        assert _wait_for(
            lambda: marker.exists() and child_marker.exists()
        )  # it does run once resumed
        child_pid = _read_pid(child_pid_file) or _read_pid(child_marker)
    finally:
        manager.stop()
        _force_cleanup(child_pid)


@windows_only
@pytest.mark.parametrize("mode", ["refused", "raises"])
def test_real_child_is_killed_when_assignment_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str
) -> None:
    script, marker, child_marker, _child_pid = _wrapper_script(tmp_path)
    spawned: list[int] = []
    real_popen = subprocess.Popen

    def _recording_popen(*args: Any, **kwargs: Any) -> subprocess.Popen:
        process = real_popen(*args, **kwargs)
        spawned.append(process.pid)
        return process

    monkeypatch.setattr(subprocess, "Popen", _recording_popen)

    class _Failing:
        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

        def add_pid(self, pid: int) -> bool:
            if mode == "raises":
                raise OSError("attach exploded")
            return False

    _real_container(monkeypatch, wrap=_Failing)
    manager = _real_manager(monkeypatch, [_PY, str(script)], working_dir=str(tmp_path))
    try:
        with pytest.raises(WebUIStartupError):
            manager.start()
        assert len(spawned) == 1
        assert _wait_for(lambda: not _alive(spawned[0]), 10.0)
        time.sleep(0.5)
        assert (
            not marker.exists() and not child_marker.exists()
        )  # the stub never executed one instruction
        _assert_no_published_launch(manager)
    finally:
        _force_cleanup(*spawned)


@windows_only
def test_real_resume_failure_leaves_no_suspended_survivor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from src.utils import win_jobobject

    script, marker, child_marker, _child_pid = _wrapper_script(tmp_path)
    spawned: list[int] = []
    real_popen = subprocess.Popen

    def _recording_popen(*args: Any, **kwargs: Any) -> subprocess.Popen:
        process = real_popen(*args, **kwargs)
        spawned.append(process.pid)
        return process

    monkeypatch.setattr(subprocess, "Popen", _recording_popen)
    monkeypatch.setattr(win_jobobject, "resume_suspended_process", lambda pid: False)
    _real_container(monkeypatch)
    manager = _real_manager(monkeypatch, [_PY, str(script)], working_dir=str(tmp_path))
    try:
        with pytest.raises(WebUIStartupError, match="resum"):
            manager.start()
        assert len(spawned) == 1
        assert _wait_for(lambda: not _alive(spawned[0]), 10.0)
        assert not marker.exists()
        _assert_no_published_launch(manager)
    finally:
        _force_cleanup(*spawned)


@windows_only
def test_batch_launcher_descendants_are_contained_and_stopped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script, marker, child_marker, child_pid_file = _wrapper_script(tmp_path)
    launcher = tmp_path / "webui-user.cmd"
    launcher.write_text(f'@echo off\r\n"{_PY}" "{script}"\r\n', encoding="utf-8")
    _real_container(monkeypatch)
    manager = _real_manager(monkeypatch, [str(launcher)], working_dir=str(tmp_path))
    child_pid = None
    try:
        process = manager.start()
        assert _wait_for(lambda: _read_pid(child_pid_file) is not None)
        child_pid = _read_pid(child_pid_file)
        assert manager.launch_session_command == [str(launcher)]

        assert manager.stop_webui(grace_seconds=2.0) is True

        assert not _alive(process.pid)
        assert _wait_for(lambda: child_pid is not None and not _alive(child_pid), 10.0)
    finally:
        manager.stop()
        _force_cleanup(child_pid)


@windows_only
def test_new_console_launch_is_contained_and_stopped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("STABLENEW_WEBUI_NEW_CONSOLE", "1")
    script, marker, child_marker, child_pid_file = _wrapper_script(tmp_path)
    _real_container(monkeypatch)
    manager = _real_manager(monkeypatch, [_PY, str(script)], working_dir=str(tmp_path))
    child_pid = None
    try:
        process = manager.start()
        assert (
            process.stdout is None and process.stderr is None
        )  # the operator reads the console instead
        assert _wait_for(lambda: _read_pid(child_pid_file) is not None)
        child_pid = _read_pid(child_pid_file)

        assert manager.stop_webui(grace_seconds=2.0) is True

        assert not _alive(process.pid)
        assert _wait_for(lambda: child_pid is not None and not _alive(child_pid), 10.0)
    finally:
        manager.stop()
        _force_cleanup(child_pid)


@windows_only
def test_external_processes_survive_failed_and_successful_launches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from src.utils.win_jobobject import WindowsJobObject

    script, marker, child_marker, child_pid_file = _wrapper_script(tmp_path)
    marker_path = tmp_path / "external.alive"
    external = subprocess.Popen(
        [
            _PY,
            "-c",
            f"import time; open({marker_path.as_posix()!r}, 'w').write('x'); time.sleep(120)",
        ]
    )
    foreign_job = WindowsJobObject(
        "foreign"
    )  # an external process in a job StableNew did not create
    assert foreign_job.assign(external.pid)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    port = listener.getsockname()[1]
    child_pid = None
    try:
        _real_container(monkeypatch)
        # 1. a launch refused because the endpoint is occupied by an external server
        occupied = _real_manager(
            monkeypatch,
            [_PY, str(script)],
            working_dir=str(tmp_path),
            base_url=f"http://127.0.0.1:{port}",
        )
        with pytest.raises(WebUIStartupError, match="already occupied"):
            occupied.start()
        assert not marker.exists()
        assert occupied.stop_webui() is True

        # 2. a launch that fails containment must not touch the external process either
        class _Refusing:
            def __init__(self, inner: Any) -> None:
                self._inner = inner

            def __getattr__(self, name: str) -> Any:
                return getattr(self._inner, name)

            def add_pid(self, pid: int) -> bool:
                return False

        _real_container(monkeypatch, wrap=_Refusing)
        failing = _real_manager(monkeypatch, [_PY, str(script)], working_dir=str(tmp_path))
        with pytest.raises(WebUIStartupError):
            failing.start()

        # 3. a successful launch and stop, then a second manager refused while the first owns a live process
        _real_container(monkeypatch)
        owner = _real_manager(monkeypatch, [_PY, str(script)], working_dir=str(tmp_path))
        owner.start()
        assert _wait_for(lambda: _read_pid(child_pid_file) is not None)
        child_pid = _read_pid(child_pid_file)
        other = _real_manager(monkeypatch, [_PY, str(script)], working_dir=str(tmp_path))
        with pytest.raises(WebUIStartupError, match="already owns"):
            other.start()
        assert other.stop_webui() is True
        assert owner.process is not None and owner.process.poll() is None
        assert owner.stop_webui(grace_seconds=2.0) is True

        assert external.poll() is None and _alive(external.pid)
        assert marker_path.exists()
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            pass
    finally:
        listener.close()
        external.kill()
        external.wait(timeout=10)
        foreign_job.close()
        _force_cleanup(child_pid)


@windows_only
def test_shutdown_is_bounded_when_a_descendant_still_holds_the_output_pipes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Containment that does not reach a descendant (here a container whose kill is a no-op, and a descendant whose
    parent already exited so no process tree walk finds it) must not make ``stop_webui`` wait on a reader whose
    pipe that descendant keeps open."""

    holder_pid = tmp_path / "holder.pid"
    script = tmp_path / "orphaning_stub.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import subprocess, sys, time
            mid = subprocess.Popen([sys.executable, "-c",
                "import os, subprocess, sys; "
                "h = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); "
                "open({holder_pid.as_posix()!r}, 'w').write(str(h.pid))"])
            mid.wait()
            print("stub-webui-ready", flush=True)
            time.sleep(120)
            """
        ),
        encoding="utf-8",
    )

    class _Leaky(RecordingContainer):
        """Accepts the pid and really resumes the child, but contains nothing and kills nothing."""

        def resume_suspended(self, pid: int) -> bool:
            from src.utils.win_jobobject import resume_suspended_process

            super().resume_suspended(pid)
            return resume_suspended_process(pid)

    leaky_made = _use_containers(monkeypatch, lambda: _Leaky())
    manager = _real_manager(monkeypatch, [_PY, str(script)], working_dir=str(tmp_path))
    holder = None
    try:
        process = manager.start()
        assert _wait_for(lambda: _read_pid(holder_pid) is not None)
        holder = _read_pid(holder_pid)
        assert _wait_for(lambda: "stub-webui-ready" in manager.get_stdout_tail_text())

        started = time.monotonic()
        stopper = threading.Thread(
            target=lambda: manager.stop_webui(grace_seconds=1.0), daemon=True
        )
        stopper.start()
        stopper.join(timeout=30)

        assert not stopper.is_alive(), (
            "stop_webui blocked on a reader whose pipe a descendant holds"
        )
        assert time.monotonic() - started < 8, "shutdown must not wait out the reader join timeouts"
        assert not _alive(process.pid)
        assert _alive(holder), "the scenario must leave a descendant holding the pipes"
        assert leaky_made[0].events[-2:] == ["kill_all", "teardown"]
        assert manager._stdout_thread is None and manager._stderr_thread is None
    finally:
        _force_cleanup(holder)
