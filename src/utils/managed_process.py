"""Contained, bounded child processes (audit P3-3, findings B7/B8/E6).

Two primitives share one containment rule: a child is assigned to its own anonymous OS container (a Windows job
object with kill-on-close, a Linux cgroup) as soon as it is spawned, so it cannot outlive its owner and one kill reaches
its whole process tree.

* ``run_bounded`` runs a short-lived child to completion with a wall-clock timeout, a stdout byte cap, a bounded stderr
  prefix and cooperative cancellation.  Output is returned as bytes; nothing is decoded here.
* ``ManagedProcess`` owns a long-lived child (a runtime server).  Its output is read by pump threads that decode UTF-8
  with ``errors="replace"`` (a bad byte can never kill the reader and block the child on a full pipe), keep only a bounded
  tail of bounded lines, and optionally mirror to a size-rotated log file.

A container is a safety net, not an authority: if none can be built (non-Windows/Linux host, restricted token) the child
still runs, ``contained`` is ``False`` and the caller decides whether that matters.  The child is assigned right after
``Popen`` returns, not before its first instruction, so a grandchild forked in that window would escape; the supported
runtimes do not fork before they finish importing.

This module imports nothing above ``src.utils``.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from src.utils.process_container_v2 import (
    NullProcessContainer,
    ProcessContainer,
    ProcessContainerConfig,
    build_process_container,
)
from src.utils.thread_registry import get_thread_registry

logger = logging.getLogger(__name__)

OWNER_TOKEN_ENV = "STABLENEW_MANAGED_PROCESS_OWNER"
DEFAULT_MAX_STDERR_BYTES = 64 * 1024
TAIL_LINE_LIMIT = 200
TAIL_LINE_CHARS = 2000
_CANCEL_POLL_SECONDS = 0.05
_KILL_WAIT_SECONDS = 5.0
_READ_CHUNK = 8192

CancelSignal = threading.Event | Callable[[], bool]


@dataclass(frozen=True, slots=True)
class ProcessOutcome:
    """What one bounded child process did.  ``stdout`` never exceeds the requested cap."""

    returncode: int | None
    stdout: bytes = b""
    stderr: bytes = b""
    timed_out: bool = False
    output_truncated: bool = False
    cancelled: bool = False
    launch_error: str = ""


def _spawn_reader(
    target: Callable[..., Any], *args: Any, name: str, **kwargs: Any
) -> threading.Thread:
    """Start a pipe reader through the ThreadRegistry.

    Daemon on purpose: a reader blocks in ``read`` for as long as the child keeps its pipe open, and the child only dies
    when its owner has exited, so a non-daemon reader would make interpreter shutdown wait on the very process it guards.
    """

    return get_thread_registry().spawn(
        target=target,
        args=args,
        kwargs=kwargs,
        name=name,
        daemon=True,
        purpose="Drain a managed child's output pipe",
        suppress_daemon_warning=True,
    )


def _is_cancelled(signal: CancelSignal | None) -> bool:
    if signal is None:
        return False
    if isinstance(signal, threading.Event):
        return signal.is_set()
    try:
        return bool(signal())
    except Exception:  # noqa: BLE001 - a broken cancel probe must not strand a child
        return False


def _contain(process: subprocess.Popen[Any], label: str) -> ProcessContainer:
    container = build_process_container(label, ProcessContainerConfig(enabled=True))
    try:
        if not container.add_pid(process.pid):
            logger.debug("[managed_process] %s runs without an OS container", label)
    except Exception as exc:  # noqa: BLE001 - containment is best-effort, never a reason to fail the run
        logger.debug("[managed_process] containing %s failed: %s", label, exc)
    return container


def _kill_tree(process: subprocess.Popen[Any], container: ProcessContainer | None) -> None:
    if container is not None:
        try:
            container.kill_all()
        except Exception as exc:  # noqa: BLE001
            logger.debug("[managed_process] container kill failed: %s", exc)
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=_KILL_WAIT_SECONDS)
    except (subprocess.TimeoutExpired, OSError):
        pass


def _release(container: ProcessContainer | None) -> None:
    if container is None:
        return
    try:
        container.teardown()
    except Exception as exc:  # noqa: BLE001
        logger.debug("[managed_process] container teardown failed: %s", exc)


def _read_capped(stream: Any, limit: int, sink: dict[str, Any], *, stop_on_overflow: bool) -> None:
    """Read ``stream`` to EOF keeping at most ``limit`` bytes.

    With ``stop_on_overflow`` the read stops as soon as more than ``limit`` bytes arrived (the caller then kills the
    process); otherwise the excess is drained and discarded so the child can never block on a full pipe."""

    kept = bytearray()
    overflow = False
    try:
        while True:
            chunk = stream.read(_READ_CHUNK)
            if not chunk:
                break
            room = limit - len(kept)
            if room > 0:
                kept.extend(chunk[:room])
            if len(chunk) > max(room, 0):
                overflow = True
                if stop_on_overflow:
                    break
    except (OSError, ValueError):
        pass  # the pipe closed under us (process killed); what was read is what we have
    sink["data"] = bytes(kept)
    sink["overflow"] = overflow


def run_bounded(
    command: Sequence[str],
    *,
    timeout_seconds: float,
    max_stdout_bytes: int,
    max_stderr_bytes: int = DEFAULT_MAX_STDERR_BYTES,
    cancel: CancelSignal | None = None,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> ProcessOutcome:
    """Run one child with a wall-clock timeout, output caps and cooperative cancellation.

    The child is contained, so a timeout or cancellation kills its whole tree.  ``stdin`` is closed.  A launch failure
    is reported in ``launch_error``; it never raises."""

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        process = subprocess.Popen(  # noqa: S603 - argv list, no shell
            list(command),
            cwd=None if cwd is None else str(cwd),
            env=None if env is None else dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
    except OSError as exc:
        return ProcessOutcome(returncode=None, launch_error=str(exc) or type(exc).__name__)

    container = _contain(process, f"bounded-{uuid.uuid4().hex[:12]}")
    out_sink: dict[str, Any] = {}
    err_sink: dict[str, Any] = {}
    readers = [
        _spawn_reader(
            _read_capped,
            process.stdout,
            max_stdout_bytes,
            out_sink,
            name="bounded-process-stdout",
            stop_on_overflow=True,
        ),
        _spawn_reader(
            _read_capped,
            process.stderr,
            max_stderr_bytes,
            err_sink,
            name="bounded-process-stderr",
            stop_on_overflow=False,
        ),
    ]

    deadline = time.monotonic() + max(0.0, timeout_seconds)
    timed_out = False
    cancelled = False
    stdout_reader = readers[0]
    try:
        while stdout_reader.is_alive():
            if _is_cancelled(cancel):
                cancelled = True
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            stdout_reader.join(min(_CANCEL_POLL_SECONDS, remaining))

        truncated = bool(out_sink.get("overflow"))
        if timed_out or cancelled or truncated:
            _kill_tree(process, container)
        else:
            # stdout is at EOF; the child is exiting (or holds stdout open only through a grandchild).
            while process.poll() is None:
                if _is_cancelled(cancel):
                    cancelled = True
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                time.sleep(min(_CANCEL_POLL_SECONDS, remaining))
            if timed_out or cancelled:
                _kill_tree(process, container)
        for reader in readers:
            reader.join(_KILL_WAIT_SECONDS)
    finally:
        # Leave nothing behind on any path, including an exception in this thread.
        if process.poll() is None:
            _kill_tree(process, container)
        for stream in (process.stdout, process.stderr):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass
        _release(container)
    return ProcessOutcome(
        returncode=process.returncode,
        stdout=out_sink.get("data", b""),
        stderr=err_sink.get("data", b""),
        timed_out=timed_out,
        output_truncated=bool(out_sink.get("overflow")),
        cancelled=cancelled,
    )


class RotatingTextLog:
    """A size-capped text log: at ``max_bytes`` the file rotates to ``.1`` (older ones shift, ``backups`` are kept)."""

    def __init__(self, path: Path, *, max_bytes: int, backups: int) -> None:
        self._path = Path(path)
        self._max_bytes = max(1024, int(max_bytes))
        self._backups = max(0, int(backups))
        self._lock = threading.Lock()
        self._handle: IO[str] | None = None
        self._size = 0

    def write_line(self, line: str) -> None:
        with self._lock:
            try:
                if self._handle is None:
                    self._open()
                data = line + "\n"
                if self._size + len(data.encode("utf-8", "replace")) > self._max_bytes:
                    self._rotate()
                assert self._handle is not None
                self._handle.write(data)
                self._handle.flush()
                self._size += len(data.encode("utf-8", "replace"))
            except OSError as exc:
                logger.debug("[managed_process] log write failed for %s: %s", self._path, exc)

    def write(self, text: str) -> int:
        """File-like shim so a stream reader can use this as its sink (one call per line)."""

        self.write_line(text.rstrip("\r\n"))
        return len(text)

    def flush(self) -> None:
        with self._lock:
            if self._handle is not None:
                try:
                    self._handle.flush()
                except OSError:
                    pass

    def close(self) -> None:
        with self._lock:
            self._close_handle()

    def _open(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self._path.open("a", encoding="utf-8", errors="replace")
        self._size = self._path.stat().st_size if self._path.exists() else 0

    def _close_handle(self) -> None:
        if self._handle is not None:
            try:
                self._handle.close()
            except OSError:
                pass
            self._handle = None

    def _rotate(self) -> None:
        self._close_handle()
        if self._backups > 0:
            for index in range(self._backups - 1, 0, -1):
                src = self._path.with_name(f"{self._path.name}.{index}")
                if src.exists():
                    os.replace(src, self._path.with_name(f"{self._path.name}.{index + 1}"))
            os.replace(self._path, self._path.with_name(f"{self._path.name}.1"))
        else:
            self._path.unlink(missing_ok=True)
        self._open()


def prune_logs(directory: Path, pattern: str, *, keep: int) -> list[Path]:
    """Delete all but the ``keep`` most recently modified files matching ``pattern`` in ``directory``.

    Returns the deleted paths.  Only direct children that are regular files are considered, and a file that cannot be
    deleted (still open on Windows) is skipped, never an error."""

    try:
        candidates = [path for path in Path(directory).glob(pattern) if path.is_file()]
    except OSError:
        return []
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    removed: list[Path] = []
    for path in candidates[max(0, keep) :]:
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            continue
    return removed


class ManagedProcess:
    """One long-lived, contained child with bounded, decode-safe output capture.

    ``start`` raises ``OSError`` (from ``Popen``) if the child cannot launch.  ``stop`` is idempotent and always leaves the
    container released.  The owner token is exported to the child as ``OWNER_TOKEN_ENV`` so a process listing can tell a
    child this application launched from an unrelated one; it grants no authority by itself.
    """

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        label: str = "managed",
        tail_lines: int = TAIL_LINE_LIMIT,
        log_path: Path | None = None,
        log_max_bytes: int = 5 * 1024 * 1024,
        log_backups: int = 2,
    ) -> None:
        self._command = list(command)
        self._cwd = None if cwd is None else str(cwd)
        self._env = dict(env) if env is not None else dict(os.environ)
        self._label = label
        self.owner_token = f"{os.getpid()}-{uuid.uuid4().hex}"
        self._stdout_tail: deque[str] = deque(maxlen=tail_lines)
        self._stderr_tail: deque[str] = deque(maxlen=tail_lines)
        self._log = (
            RotatingTextLog(log_path, max_bytes=log_max_bytes, backups=log_backups)
            if log_path is not None
            else None
        )
        self._process: subprocess.Popen[bytes] | None = None
        self._container: ProcessContainer | None = None
        self._threads: list[threading.Thread] = []

    @property
    def process(self) -> subprocess.Popen[bytes] | None:
        return self._process

    @property
    def pid(self) -> int | None:
        return None if self._process is None else self._process.pid

    @property
    def contained(self) -> bool:
        return self._container is not None and not isinstance(self._container, NullProcessContainer)

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def stdout_tail(self) -> list[str]:
        return list(self._stdout_tail)

    def stderr_tail(self) -> list[str]:
        return list(self._stderr_tail)

    def start(self) -> subprocess.Popen[bytes]:
        if self.is_running():
            assert self._process is not None
            return self._process
        env = dict(self._env)
        env[OWNER_TOKEN_ENV] = self.owner_token
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        process = subprocess.Popen(  # noqa: S603 - argv list, no shell
            self._command,
            cwd=self._cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
        self._process = process
        self._container = _contain(process, f"{self._label}-{uuid.uuid4().hex[:12]}")
        self._threads = [
            self._start_pump(process.stdout, self._stdout_tail, "stdout"),
            self._start_pump(process.stderr, self._stderr_tail, "stderr"),
        ]
        return process

    def stop(self, *, grace_seconds: float = 5.0) -> None:
        process, container = self._process, self._container
        self._process = None
        self._container = None
        if process is not None:
            if process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=grace_seconds)
                except (subprocess.TimeoutExpired, OSError):
                    pass
            # Always reap the tree: a server's workers can outlive a terminated parent.
            if container is not None or process.poll() is None:
                _kill_tree(process, container)
        _release(container)
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=1.0)
        self._threads = []
        for stream in (
            None if process is None else process.stdout,
            None if process is None else process.stderr,
        ):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass
        if self._log is not None:
            self._log.close()

    def _start_pump(
        self, stream: IO[bytes] | None, sink: deque[str], name: str
    ) -> threading.Thread:
        return _spawn_reader(
            self._pump, stream, sink, name, name=f"managed-process-{self._label}-{name}"
        )

    def _pump(self, stream: IO[bytes] | None, sink: deque[str], name: str) -> None:
        """Drain ``stream`` forever: every byte is consumed, so the child can never block on a full pipe."""

        if stream is None:
            return
        try:
            for raw in iter(lambda: stream.readline(_READ_CHUNK), b""):
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if len(line) > TAIL_LINE_CHARS:
                    line = line[:TAIL_LINE_CHARS] + "..."
                sink.append(line)
                if self._log is not None:
                    self._log.write_line(f"[{name}] {line}")
        except (OSError, ValueError):
            return  # the pipe closed because the process was stopped


__all__ = [
    "DEFAULT_MAX_STDERR_BYTES",
    "OWNER_TOKEN_ENV",
    "CancelSignal",
    "ManagedProcess",
    "ProcessOutcome",
    "RotatingTextLog",
    "prune_logs",
    "run_bounded",
]
