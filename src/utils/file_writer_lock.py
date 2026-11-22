"""A bounded cross-process lock for a file that may be atomically replaced."""

from __future__ import annotations

import errno
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def _set_writer_lock(descriptor: int, *, unlock: bool) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK if unlock else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN if unlock else fcntl.LOCK_EX | fcntl.LOCK_NB)


@contextmanager
def file_writer_lock(path: Path, *, timeout: float = 2.0) -> Iterator[None]:
    """Serialize writes to one replaceable file across processes.

    The empty sidecar is never removed or rotated: every writer locks the same
    file even when the data file moves. OS handle closure releases it on a crash.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0), 0o600)
    acquired = False
    try:
        deadline = time.monotonic() + timeout
        while not acquired:
            try:
                _set_writer_lock(descriptor, unlock=False)
                acquired = True
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError("File writer lock timed out") from exc
                time.sleep(0.01)
        try:
            yield
        finally:
            try:
                _set_writer_lock(descriptor, unlock=True)
            except OSError as exc:
                # An append may already be durable. Do not retry it as a permission
                # failure and risk duplicating a completed record.
                raise OSError("File writer lock release failed") from exc
    finally:
        os.close(descriptor)
