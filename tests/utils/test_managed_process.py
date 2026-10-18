"""Contained, bounded child processes (audit P3-3, findings B7/B8/E6)."""

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
    OWNER_TOKEN_ENV,
    ManagedProcess,
    RotatingTextLog,
    prune_logs,
    run_bounded,
)

windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows job objects")

_PY = sys.executable
_SLEEP = "import time; time.sleep(60)"


def _wait_until(predicate, seconds: float = 10.0) -> bool:
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


def _tree_script(pid_file: Path) -> str:
    """A parent that spawns a recorded grandchild, then idles."""

    child = (
        "import os, pathlib, time; "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(60)"
    )
    return (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
        "time.sleep(60)\n"
    )


# --- run_bounded ----------------------------------------------------------------------------------


def test_run_bounded_returns_output_and_exit_code() -> None:
    outcome = run_bounded(
        [_PY, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"],
        timeout_seconds=30,
        max_stdout_bytes=1024,
    )
    assert outcome.returncode == 3
    assert outcome.stdout.strip() == b"out"
    assert outcome.stderr.strip() == b"err"
    assert not (outcome.timed_out or outcome.cancelled or outcome.output_truncated)


def test_run_bounded_times_out_and_kills_a_hung_child() -> None:
    started = time.monotonic()
    outcome = run_bounded([_PY, "-c", _SLEEP], timeout_seconds=0.5, max_stdout_bytes=1024)
    assert outcome.timed_out is True
    assert time.monotonic() - started < 15


def test_run_bounded_times_out_when_the_child_closed_stdout_but_keeps_running() -> None:
    code = "import os, time; os.close(1); time.sleep(60)"
    outcome = run_bounded([_PY, "-c", code], timeout_seconds=0.5, max_stdout_bytes=1024)
    assert outcome.timed_out is True


def test_run_bounded_cancel_event_stops_the_child() -> None:
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    outcome = run_bounded(
        [_PY, "-c", _SLEEP], timeout_seconds=60, max_stdout_bytes=1024, cancel=cancel
    )
    assert outcome.cancelled is True
    assert outcome.timed_out is False


def test_run_bounded_accepts_a_callable_cancel_probe() -> None:
    flag = {"set": False}
    threading.Timer(0.3, lambda: flag.update(set=True)).start()
    outcome = run_bounded(
        [_PY, "-c", _SLEEP],
        timeout_seconds=60,
        max_stdout_bytes=1024,
        cancel=lambda: flag["set"],
    )
    assert outcome.cancelled is True


def test_run_bounded_caps_stdout_and_stops_the_child() -> None:
    code = "import sys\nwhile True:\n    sys.stdout.write('x' * 4096)\n    sys.stdout.flush()\n"
    outcome = run_bounded([_PY, "-c", code], timeout_seconds=30, max_stdout_bytes=10_000)
    assert outcome.output_truncated is True
    assert len(outcome.stdout) == 10_000


def test_run_bounded_drains_stderr_beyond_its_cap_without_blocking() -> None:
    code = "import sys; sys.stderr.write('e' * 500000); sys.stdout.write('done')"
    outcome = run_bounded(
        [_PY, "-c", code], timeout_seconds=30, max_stdout_bytes=1024, max_stderr_bytes=100
    )
    assert outcome.returncode == 0
    assert outcome.stdout == b"done"
    assert len(outcome.stderr) == 100


def test_run_bounded_reports_a_launch_failure_without_raising() -> None:
    missing = str(Path("definitely") / "not" / "a" / "program.exe")
    outcome = run_bounded([missing], timeout_seconds=5, max_stdout_bytes=10)
    assert outcome.launch_error
    assert outcome.returncode is None


@windows_only
def test_run_bounded_timeout_kills_the_whole_process_tree(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    outcome = run_bounded(
        [_PY, "-c", _tree_script(pid_file)], timeout_seconds=3, max_stdout_bytes=1024
    )
    assert outcome.timed_out is True
    assert pid_file.exists(), "the grandchild never started; the test proves nothing"
    grandchild = int(pid_file.read_text())
    assert _wait_until(lambda: not _pid_alive(grandchild)), "a grandchild outlived its parent"


# --- ManagedProcess -------------------------------------------------------------------------------


def test_managed_process_captures_bounded_tails_and_survives_undecodable_bytes() -> None:
    code = (
        "import sys\n"
        "sys.stdout.buffer.write(b'bad \\xff\\xfe byte\\n')\n"
        "sys.stdout.buffer.write(b'x' * 5000 + b'\\n')\n"
        "for i in range(500): print('line', i)\n"
        "sys.stderr.write('oops\\n')\n"
    )
    proc = ManagedProcess([_PY, "-c", code], label="test")
    proc.start()
    assert _wait_until(lambda: "oops" in proc.stderr_tail())
    assert _wait_until(lambda: bool(proc.stdout_tail()) and proc.stdout_tail()[-1] == "line 499")
    tail = proc.stdout_tail()
    proc.stop()
    assert len(tail) <= managed_process.TAIL_LINE_LIMIT
    assert all(len(line) <= managed_process.TAIL_LINE_CHARS + 3 for line in tail)


def test_managed_process_reader_keeps_draining_after_a_bad_byte() -> None:
    code = (
        "import sys\n"
        "sys.stdout.buffer.write(b'\\xff\\xfe\\n')\n"
        "sys.stdout.flush()\n"
        "print('after bad byte')\n"
    )
    proc = ManagedProcess([_PY, "-c", code], label="test")
    proc.start()
    assert _wait_until(lambda: "after bad byte" in proc.stdout_tail())
    proc.stop()


def test_managed_process_exports_a_per_instance_owner_token_to_the_child() -> None:
    code = f"import os; print(os.environ.get({OWNER_TOKEN_ENV!r}))"
    first = ManagedProcess([_PY, "-c", code], label="test")
    second = ManagedProcess([_PY, "-c", code], label="test")
    assert first.owner_token != second.owner_token
    first.start()
    assert _wait_until(lambda: bool(first.stdout_tail()))
    assert first.stdout_tail()[0] == first.owner_token
    first.stop()


def test_managed_process_stop_is_idempotent_and_terminates_the_child() -> None:
    proc = ManagedProcess([_PY, "-c", _SLEEP], label="test")
    process = proc.start()
    assert proc.is_running()
    proc.stop(grace_seconds=2)
    proc.stop(grace_seconds=2)
    assert process.poll() is not None
    assert proc.process is None
    assert not proc.is_running()


@windows_only
def test_managed_process_is_contained_and_stop_reaps_its_tree(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    proc = ManagedProcess([_PY, "-c", _tree_script(pid_file)], label="test")
    proc.start()
    assert proc.contained is True
    assert _wait_until(pid_file.exists, 20)
    grandchild = int(pid_file.read_text())
    assert _pid_alive(grandchild)
    proc.stop(grace_seconds=2)
    assert _wait_until(lambda: not _pid_alive(grandchild)), "stop() left a descendant running"


@windows_only
def test_managed_process_child_dies_when_its_owner_dies(tmp_path: Path) -> None:
    """The orphan case behind audit B7: a hard-killed owner must not leave a managed server behind."""

    pid_file = tmp_path / "managed.pid"
    repo_root = Path(__file__).resolve().parents[2]
    owner_code = (
        "import pathlib, sys, time\n"
        f"sys.path.insert(0, {str(repo_root)!r})\n"
        "from src.utils.managed_process import ManagedProcess\n"
        "p = ManagedProcess([sys.executable, '-c', 'import time; time.sleep(60)'], label='owner')\n"
        "p.start()\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid))\n"
        "time.sleep(60)\n"
    )
    owner = subprocess.Popen([_PY, "-c", owner_code])
    try:
        assert _wait_until(pid_file.exists, 30)
        managed_pid = int(pid_file.read_text())
        assert _pid_alive(managed_pid)
        owner.kill()
        owner.wait(timeout=10)
        assert _wait_until(lambda: not _pid_alive(managed_pid)), "managed child outlived its owner"
    finally:
        if owner.poll() is None:
            owner.kill()


def test_managed_process_without_a_container_still_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.utils.process_container_v2 import NullProcessContainer

    monkeypatch.setattr(
        managed_process,
        "build_process_container",
        lambda job_id, config: NullProcessContainer(job_id, config),
    )
    proc = ManagedProcess([_PY, "-c", "print('hi')"], label="test")
    proc.start()
    assert proc.contained is False
    assert _wait_until(lambda: "hi" in proc.stdout_tail())
    proc.stop()


# --- rotating log ---------------------------------------------------------------------------------


def test_rotating_log_rotates_and_bounds_total_size(tmp_path: Path) -> None:
    log = RotatingTextLog(tmp_path / "run.log", max_bytes=2048, backups=2)
    for index in range(400):
        log.write_line(f"line {index:04d} " + "x" * 40)
    log.close()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["run.log", "run.log.1", "run.log.2"]
    assert all(path.stat().st_size <= 2048 + 100 for path in tmp_path.iterdir())
    assert "line 0399" in (tmp_path / "run.log").read_text(encoding="utf-8")


def test_managed_process_mirrors_output_to_its_log(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "p.log"
    proc = ManagedProcess([_PY, "-c", "print('to the log')"], label="test", log_path=log_path)
    proc.start()
    assert _wait_until(lambda: "to the log" in proc.stdout_tail())
    proc.stop()
    assert "[stdout] to the log" in log_path.read_text(encoding="utf-8")


def test_rotating_log_works_as_a_file_like_sink(tmp_path: Path) -> None:
    log = RotatingTextLog(tmp_path / "sink.log", max_bytes=4096, backups=1)
    assert log.write("first line\n") == len("first line\n")
    log.write("second line\r\n")
    log.flush()
    log.close()
    assert (tmp_path / "sink.log").read_text(encoding="utf-8").splitlines() == [
        "first line",
        "second line",
    ]


def test_prune_logs_keeps_only_the_newest_matches(tmp_path: Path) -> None:
    for index in range(5):
        path = tmp_path / f"run_{index}.log"
        path.write_text("x", encoding="utf-8")
        os.utime(path, (1_000_000 + index, 1_000_000 + index))
    other = tmp_path / "keep_me.txt"
    other.write_text("x", encoding="utf-8")
    removed = prune_logs(tmp_path, "run_*.log", keep=2)
    assert sorted(path.name for path in removed) == ["run_0.log", "run_1.log", "run_2.log"]
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "keep_me.txt",
        "run_3.log",
        "run_4.log",
    ]
    assert prune_logs(tmp_path / "missing", "*.log", keep=1) == []
