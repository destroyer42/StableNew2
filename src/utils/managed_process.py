"""Contained, bounded child processes (audit P3-3, findings B7/B8/E6; fail-closed containment).

Two primitives share one containment rule: a child is placed in its own anonymous OS container (a Windows job object with
kill-on-close, a Linux cgroup), so it cannot outlive its owner and one kill reaches its whole process tree.

* ``run_bounded`` runs a short-lived child to completion with a wall-clock timeout, a stdout byte cap, a bounded stderr
  prefix and cooperative cancellation.  Output is returned as bytes; nothing is decoded here.
* ``ManagedProcess`` owns a long-lived child (a runtime server).  Its output is read by pump threads that decode UTF-8
  with ``errors="replace"`` (a bad byte can never kill the reader and block the child on a full pipe), keep only a bounded
  tail of bounded lines, and optionally mirror to a size-rotated log file.

Containment policy.  Where the platform is a supported runtime platform (Windows: ``containment_required()``), a child is
**never run uncontained**: if the container cannot be built, or the child cannot be placed in it, the child is killed and
``ContainmentError`` is raised (``run_bounded`` reports it as ``launch_error``).  On Windows the child is created
suspended, placed in the job object and only then resumed, so it and its descendants provably start inside the job.  On
other platforms, or when a caller passes ``require_containment=False``, the child runs uncontained with a WARNING and
``contained`` is ``False``; its descendants are then not tracked and a kill reaches only the direct child.

A guarantee about *time* never depends on containment: even if a descendant escaped and still holds the child's pipes,
``run_bounded`` and ``ManagedProcess.stop`` return promptly (reader threads are abandoned, never closed under, so a close
cannot block on a pipe an escaped descendant keeps open).

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
#: Total time to let the pipe readers drain after a kill; an escaped descendant can hold a pipe open indefinitely.
_DRAIN_SECONDS = 2.0
_READ_CHUNK = 8192
_CREATE_SUSPENDED = 0x00000004

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
    #: Whether the child ran inside an OS container (so a kill reached its whole tree).
    contained: bool = False


class ContainmentError(RuntimeError):
    """A child could not be placed in the OS container this platform requires, so it was not (or no longer) run."""


def containment_required() -> bool:
    """Windows is the supported runtime platform: a child there is never run without its job object."""

    return os.name == "nt"


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


@dataclass
class _Spawned:
    process: subprocess.Popen[bytes]
    container: ProcessContainer
    contained: bool


def _terminate_uncontained(process: subprocess.Popen[Any], container: ProcessContainer) -> None:
    """Kill a child that was just spawned and could not be contained, and release everything it was given."""

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
    for stream in (process.stdin, process.stdout, process.stderr):
        try:
            if stream is not None:
                stream.close()  # no reader exists yet, so this cannot block
        except OSError:
            pass
    _release(container)


def _spawn_contained(
    command: Sequence[str],
    *,
    label: str,
    require_containment: bool | None,
    cwd: str | None,
    env: Mapping[str, str] | None,
) -> _Spawned:
    """Start ``command`` with stdout/stderr piped, inside its own OS container where one is required or available.

    Raises ``ContainmentError`` (with the child already killed) when containment is required and could not be
    established, and ``OSError`` when the child cannot launch at all."""

    required = containment_required() if require_containment is None else require_containment
    container = build_process_container(label, ProcessContainerConfig(enabled=True))
    if isinstance(container, NullProcessContainer):
        reason = getattr(container, "reason", "") or "no container available"
        if required:
            raise ContainmentError(
                f"{label}: an OS process container is required on this platform but none is available "
                f"({reason}); the child was not started"
            )
        logger.warning(
            "[managed_process] %s starts without an OS container (%s); its descendants are not tracked",
            label,
            reason,
        )
    suspended = os.name == "nt" and bool(getattr(container, "supports_suspended_start", False))
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    if suspended:
        creationflags |= _CREATE_SUSPENDED
    try:
        process = subprocess.Popen(  # noqa: S603 - argv list, no shell
            list(command),
            cwd=cwd,
            env=None if env is None else dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
    except BaseException:
        _release(container)
        raise
    if isinstance(container, NullProcessContainer):
        return _Spawned(process, container, False)

    attached = False
    try:
        failure = ""
        try:
            attached = bool(container.add_pid(process.pid))
            if not attached:
                failure = "the OS refused to place the child in its container"
        except Exception as exc:  # noqa: BLE001 - reported below as a containment failure
            failure = f"placing the child in its container failed: {exc}"
        if not attached and required:
            raise ContainmentError(f"{label}: {failure}; the child was stopped")
        if not attached:
            logger.warning("[managed_process] %s: %s; running it uncontained", label, failure)
        if suspended:
            from src.utils.win_jobobject import resume_suspended_process

            if not resume_suspended_process(process.pid):
                raise ContainmentError(
                    f"{label}: the suspended child could not be resumed; it was stopped"
                )
    except BaseException:
        # Whatever went wrong (including an interrupt), a child that may be suspended or uncontained is never left behind.
        _terminate_uncontained(process, container)
        raise
    return _Spawned(process, container, attached)


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


class _CappedBuffer:
    """What a capped reader has read so far.  Updated in place so a reader that never finishes (an escaped
    descendant keeps the pipe open) still yields everything read before the deadline."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.data = bytearray()
        self.overflow = False

    def snapshot(self) -> bytes:
        return bytes(self.data)


def _read_capped(stream: Any, buffer: _CappedBuffer, *, stop_on_overflow: bool) -> None:
    """Read ``stream`` to EOF keeping at most ``buffer.limit`` bytes.

    With ``stop_on_overflow`` the read stops as soon as more than the limit arrived (the caller then kills the process);
    otherwise the excess is drained and discarded so the child can never block on a full pipe."""

    # read1 returns what is available (``read(n)`` would wait for n bytes or EOF), so output is captured as it
    # arrives and survives a pipe that never reaches EOF.
    read = getattr(stream, "read1", stream.read)
    try:
        while True:
            chunk = read(_READ_CHUNK)
            if not chunk:
                break
            room = buffer.limit - len(buffer.data)
            if room > 0:
                buffer.data.extend(chunk[:room])
            if len(chunk) > max(room, 0):
                buffer.overflow = True
                if stop_on_overflow:
                    break
    except (OSError, ValueError):
        pass  # the pipe closed under us (process killed); what was read is what we have


def run_bounded(
    command: Sequence[str],
    *,
    timeout_seconds: float,
    max_stdout_bytes: int,
    max_stderr_bytes: int = DEFAULT_MAX_STDERR_BYTES,
    cancel: CancelSignal | None = None,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    require_containment: bool | None = None,
) -> ProcessOutcome:
    """Run one child with a wall-clock timeout, output caps and cooperative cancellation.

    Where containment is required (``containment_required()``) the child runs inside its own container, so a timeout or
    cancellation kills its whole tree; if that cannot be arranged the child is not run and the reason is reported in
    ``launch_error``.  ``stdin`` is closed.  A launch failure never raises.  The call returns within the timeout plus a
    short drain even if a descendant that escaped containment still holds the child's pipes."""

    try:
        spawned = _spawn_contained(
            command,
            label=f"bounded-{uuid.uuid4().hex[:12]}",
            require_containment=require_containment,
            cwd=None if cwd is None else str(cwd),
            env=env,
        )
    except ContainmentError as exc:
        return ProcessOutcome(returncode=None, launch_error=f"containment unavailable: {exc}")
    except OSError as exc:
        return ProcessOutcome(returncode=None, launch_error=str(exc) or type(exc).__name__)

    process, container = spawned.process, spawned.container
    out_buf = _CappedBuffer(max_stdout_bytes)
    err_buf = _CappedBuffer(max_stderr_bytes)
    readers: list[threading.Thread] = []

    deadline = time.monotonic() + max(0.0, timeout_seconds)
    timed_out = False
    cancelled = False
    try:
        # Inside the try: if a reader cannot start, the (already running) child is still killed and released below.
        readers.append(
            _spawn_reader(
                _read_capped,
                process.stdout,
                out_buf,
                name="bounded-process-stdout",
                stop_on_overflow=True,
            )
        )
        readers.append(
            _spawn_reader(
                _read_capped,
                process.stderr,
                err_buf,
                name="bounded-process-stderr",
                stop_on_overflow=False,
            )
        )
        stdout_reader = readers[0]
        while stdout_reader.is_alive():
            if _is_cancelled(cancel):
                cancelled = True
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            stdout_reader.join(min(_CANCEL_POLL_SECONDS, remaining))

        if timed_out or cancelled or out_buf.overflow:
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
        drain_deadline = time.monotonic() + _DRAIN_SECONDS
        for reader in readers:
            reader.join(max(0.0, drain_deadline - time.monotonic()))
    finally:
        # Leave nothing behind on any path, including an exception in this thread.
        if process.poll() is None:
            _kill_tree(process, container)
        # Never close a stream a reader is still blocked on: that close waits for the pipe's EOF, which an escaped
        # descendant can withhold indefinitely.  The (daemon) reader ends by itself when the pipe finally closes.
        for reader, stream in zip(readers, (process.stdout, process.stderr), strict=False):
            try:
                if stream is not None and not reader.is_alive():
                    stream.close()
            except OSError:
                pass
        _release(container)
    return ProcessOutcome(
        returncode=process.returncode,
        stdout=out_buf.snapshot(),
        stderr=err_buf.snapshot(),
        timed_out=timed_out,
        output_truncated=out_buf.overflow,
        cancelled=cancelled,
        contained=spawned.contained,
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
        self._closed = False

    def write_line(self, line: str) -> None:
        with self._lock:
            if self._closed:
                return  # a pump that outlived its process must not reopen a closed log
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
            self._closed = True
            self._close_handle()

    def reopen(self) -> None:
        """Allow writes again after ``close`` (a restarted process appends to the same log)."""

        with self._lock:
            self._closed = False

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

    ``start`` raises ``OSError`` (from ``Popen``) if the child cannot launch and ``ContainmentError`` if containment is
    required (``containment_required()``, or ``require_containment=True``) and could not be established; in both cases no
    child is left running.  ``stop`` is idempotent, never blocks on a pipe an escaped descendant holds, and always leaves
    the container released.  The owner token is exported to the child as ``OWNER_TOKEN_ENV`` so a process listing can tell a
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
        require_containment: bool | None = None,
    ) -> None:
        self._command = list(command)
        self._require_containment = require_containment
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
        self._contained = False
        self._generation = 0
        self._threads: list[threading.Thread] = []

    @property
    def process(self) -> subprocess.Popen[bytes] | None:
        return self._process

    @property
    def pid(self) -> int | None:
        return None if self._process is None else self._process.pid

    @property
    def contained(self) -> bool:
        """True only if the OS accepted the child into its container (so a kill reaches its whole tree)."""

        return self._contained and self._process is not None

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
        spawned = _spawn_contained(
            self._command,
            label=f"{self._label}-{uuid.uuid4().hex[:12]}",
            require_containment=self._require_containment,
            cwd=self._cwd,
            env=env,
        )
        process = spawned.process
        if self._container is not None:
            _release(
                self._container
            )  # a previous process exited without stop(): do not leak its job handle
        self._process = process
        self._container = spawned.container
        self._contained = spawned.contained
        self._generation += 1
        if self._log is not None:
            self._log.reopen()
        try:
            self._threads = [
                self._start_pump(process.stdout, self._stdout_tail, "stdout"),
                self._start_pump(process.stderr, self._stderr_tail, "stderr"),
            ]
        except BaseException:
            self.stop(grace_seconds=0.0)  # never leave a running child nobody reads
            raise
        return process

    def stop(self, *, grace_seconds: float = 5.0) -> None:
        process, container = self._process, self._container
        self._process = None
        self._container = None
        self._contained = False
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
        # A pump still blocked on its pipe means a descendant that escaped containment holds it open.  Closing the stream
        # would wait for that descendant to exit, so it is left to the (daemon) pump, which ends at the pipe's EOF.
        if process is not None:
            for thread, stream in zip(
                self._threads, (process.stdout, process.stderr), strict=False
            ):
                try:
                    if stream is not None and not thread.is_alive():
                        stream.close()
                except OSError:
                    pass
        self._threads = []
        if self._log is not None:
            self._log.close()

    def _start_pump(
        self, stream: IO[bytes] | None, sink: deque[str], name: str
    ) -> threading.Thread:
        return _spawn_reader(
            self._pump,
            stream,
            sink,
            name,
            self._generation,
            name=f"managed-process-{self._label}-{name}",
        )

    def _pump(self, stream: IO[bytes] | None, sink: deque[str], name: str, generation: int) -> None:
        """Drain ``stream`` forever: every byte is consumed, so the child can never block on a full pipe.

        A pump abandoned by ``stop`` (an escaped descendant still holds its pipe) keeps draining but, once the process
        has been restarted, no longer records anything: its output is not the new process's."""

        if stream is None:
            return
        try:
            for raw in iter(lambda: stream.readline(_READ_CHUNK), b""):
                if generation != self._generation:
                    continue
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
    "ContainmentError",
    "CancelSignal",
    "ManagedProcess",
    "ProcessOutcome",
    "RotatingTextLog",
    "prune_logs",
    "containment_required",
    "run_bounded",
]
