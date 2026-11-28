"""A lock that reports the operation that held it, or waited for it, long enough to stall other threads.

The job repository shares ONE SQLite connection behind one lock and the job queue holds its own lock across the
repository commit, so a single slow operation (a table scan, a commit waiting on a busy disk) stalls every other
thread that needs either. Those stalls were visible only as symptoms (a job claim logged at 12 s, a queue projection
at 10 s). ``ContentionLock`` is a drop-in ``threading.Lock``/``RLock`` that logs ONE structured warning when a hold
or a wait crosses a threshold, naming the call site and thread, so the cause is read from the log.

It changes no locking behaviour: same blocking semantics, same re-entrancy, same ``with`` and ``acquire`` surface.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
import weakref
from dataclasses import dataclass
from types import FrameType
from typing import TypedDict

from src.utils.logger import LogContext, log_with_ctx
from src.utils.stack_sites import describe_frame

logger = logging.getLogger(__name__)

#: Frames that only forward an acquisition (context-manager plumbing, ``transaction()`` helpers) and so never name
#: the operation that wanted the lock.
_FORWARDING_FUNCTIONS = frozenset({"__enter__", "acquire", "transaction", "_acquire_restore"})


#: Every live lock, so a stalled UI thread's record can name what was held at the time.
_LOCKS: weakref.WeakSet[ContentionLock] = weakref.WeakSet()


@dataclass(frozen=True)
class _Holder:
    site: str
    thread: str
    since: float
    #: The holder thread's CPU seconds when it took the lock.
    cpu_since: float = 0.0


class HeldLock(TypedDict):
    lock: str
    thread: str
    site: str
    held_s: float


def held_locks(min_held_s: float) -> list[HeldLock]:
    """Locks held for at least ``min_held_s`` right now (read racily, for attribution only)."""

    try:
        locks = list(_LOCKS)
    except RuntimeError:  # another thread built a lock while the set was being copied
        return []
    now = time.perf_counter()
    found: list[HeldLock] = []
    for lock in locks:
        holder = lock._holder
        if holder is not None and now - holder.since >= min_held_s:
            found.append(
                {
                    "lock": lock._name,
                    "thread": holder.thread,
                    "site": holder.site,
                    "held_s": round(now - holder.since, 2),
                }
            )
    return found


def _caller_site(frame: FrameType | None) -> str:
    """The first frame above the lock plumbing: the code that actually asked for the lock."""

    while frame is not None:
        filename = frame.f_code.co_filename.replace("\\", "/")
        if frame.f_code.co_name not in _FORWARDING_FUNCTIONS and not filename.endswith(
            ("/contextlib.py", "/contention_lock.py")
        ):
            return describe_frame(frame)
        frame = frame.f_back
    return "unknown"


class ContentionLock:
    """``threading.RLock`` (or ``Lock``) that logs holds and waits above a threshold."""

    def __init__(
        self,
        name: str,
        *,
        reentrant: bool = True,
        hold_warn_s: float = 1.0,
        wait_warn_s: float = 0.5,
    ) -> None:
        self._name = name
        self._lock = threading.RLock() if reentrant else threading.Lock()
        self._hold_warn_s = float(hold_warn_s)
        self._wait_warn_s = float(wait_warn_s)
        # Written only by the thread that owns the underlying lock; read racily by waiters for attribution only.
        self._depth = 0
        self._holder: _Holder | None = None
        _LOCKS.add(self)

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        waiting_on = self._holder
        started = time.perf_counter()
        if not self._lock.acquire(blocking, timeout):
            return False
        now = time.perf_counter()
        if self._depth == 0:
            self._holder = _Holder(
                site=_caller_site(sys._getframe(1)),
                thread=threading.current_thread().name,
                since=now,
                cpu_since=time.thread_time(),
            )
        self._depth += 1
        waited = now - started
        if waited >= self._wait_warn_s:
            self._report("wait", waited, self._holder, waiting_on)
        return True

    def release(self) -> None:
        holder = None
        held = cpu = 0.0
        if self._depth == 1:
            holder = self._holder
            if holder is not None:
                held = time.perf_counter() - holder.since
                cpu = time.thread_time() - holder.cpu_since
            self._holder = None
        self._depth -= 1
        self._lock.release()
        # Reported after the underlying lock is free so that logging can never lengthen the hold it describes.
        if holder is not None and held >= self._hold_warn_s:
            self._report("hold", held, holder, None, cpu_s=cpu)

    def locked(self) -> bool:
        """Whether any thread holds the lock (the ``threading.Lock`` surface; an RLock has none of its own)."""

        if self._lock.acquire(blocking=False):
            self._lock.release()
            return False
        return True

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, *_exc: object) -> None:
        self.release()

    def _report(
        self,
        kind: str,
        seconds: float,
        subject: _Holder | None,
        holder: _Holder | None,
        *,
        cpu_s: float | None = None,
    ) -> None:
        fields: dict[str, object] = {
            "lock": self._name,
            "kind": kind,
            "seconds": round(seconds, 3),
            "site": subject.site if subject is not None else "unknown",
            "thread": subject.thread if subject is not None else threading.current_thread().name,
        }
        if cpu_s is not None:
            fields["cpu_s"] = round(cpu_s, 3)
        if holder is not None:
            fields["holder_site"] = holder.site
            fields["holder_thread"] = holder.thread
        try:
            log_with_ctx(
                logger,
                logging.WARNING,
                "Lock contention",
                ctx=LogContext(subsystem="locks", stage="lock_contention"),
                extra_fields=fields,
            )
        except Exception:  # noqa: BLE001 - a diagnostic must never fail the work the lock protects
            return
