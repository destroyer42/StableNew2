"""One idle warm hold of a StableNew-owned runtime between consecutive jobs (VID-WARM-373).

A workflow whose runtime policy releases the owned runtime after every job may also declare
``keep_warm_between_jobs_seconds``. After a successful job the backend then *holds* the owned process
instead of stopping it, so the next job for the same workflow skips the cold start and model load.

The hold is a single process-wide slot (backend instances are not guaranteed to outlive one job) and
ends in exactly one of these ways:

* the next job for the same runtime and workflow key claims it while the held process is still the one
  StableNew owns: that process is reused warm;
* a job for a different workflow key claims it, or any job prepares a runtime through
  ``RuntimeTransitionCoordinator.prepare_for``: the held process is released first, so that job starts
  exactly as it would have without the hold;
* the idle grace passes with no claim: a watcher thread releases it;
* application or interpreter shutdown: the watcher exits without acting (the app's own exit cleanup owns
  the process).

This module never stops a process itself. Release goes through the callback the backend registered,
which uses the runtime manager's own ``stop()`` and only while the very process it held is still the one
StableNew owns. A release runs under the slot lock, so a job that claims while a release is in progress
waits for it and then starts cold.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

CLAIM_WARM = "warm"
CLAIM_RELEASED = "released"
CLAIM_NONE = "none"

#: Longest single wait of the watcher, so it notices interpreter shutdown promptly.
_WATCH_SLICE_SECONDS = 1.0

ReleaseFn = Callable[[], Mapping[str, Any]]


@dataclass(frozen=True)
class WarmHoldClaim:
    """What a job found in the slot when it claimed it."""

    status: str
    held_key: tuple[str, ...] | None = None
    pid: int | None = None
    idle_seconds: float | None = None
    release: Mapping[str, Any] | None = None

    @property
    def warm(self) -> bool:
        return self.status == CLAIM_WARM

    def to_dict(self) -> dict[str, Any]:
        record: dict[str, Any] = {"status": self.status}
        if self.held_key is not None:
            record["held_key"] = list(self.held_key)
        if self.pid is not None:
            record["pid"] = self.pid
        if self.idle_seconds is not None:
            record["idle_seconds"] = round(self.idle_seconds, 1)
        if self.release is not None:
            record["release"] = dict(self.release)
        return record


@dataclass
class _Hold:
    runtime: str
    key: tuple[str, ...]
    pid: int
    seconds: float
    held_at: float
    release: ReleaseFn
    generation: int
    cancelled: threading.Event = field(default_factory=threading.Event)


def _default_spawn(**kwargs: Any) -> Any:
    from src.utils.thread_registry import get_thread_registry

    return get_thread_registry().spawn(**kwargs)


def _default_shutdown_requested() -> bool:
    from src.utils.thread_registry import get_thread_registry

    return bool(get_thread_registry().is_shutdown_requested())


def _default_add_shutdown_listener(listener: Callable[[], None]) -> Any:
    from src.utils.thread_registry import get_thread_registry

    return get_thread_registry().add_shutdown_listener(listener)


def _interpreter_running() -> bool:
    return threading.main_thread().is_alive()


class RuntimeWarmHold:
    """The single warm-hold slot; see the module docstring for its contract."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        spawn: Callable[..., Any] = _default_spawn,
        shutdown_requested: Callable[[], bool] = _default_shutdown_requested,
        add_shutdown_listener: Callable[[Callable[[], None]], Any] = _default_add_shutdown_listener,
        interpreter_running: Callable[[], bool] = _interpreter_running,
    ) -> None:
        self._clock = clock
        self._spawn = spawn
        self._shutdown_requested = shutdown_requested
        self._add_shutdown_listener = add_shutdown_listener
        self._interpreter_running = interpreter_running
        # Re-entrant: a release callback that (indirectly) ends the hold again must not deadlock.
        self._lock = threading.RLock()
        self._hold: _Hold | None = None
        self._generation = 0
        self._closed = threading.Event()
        self._listening = False

    # -- the three ways a job interacts with the slot -------------------------------------------------------

    def hold(
        self,
        *,
        runtime: str,
        key: Sequence[str],
        pid: int,
        seconds: float,
        release: ReleaseFn,
    ) -> dict[str, Any]:
        """Keep ``pid`` warm for ``seconds`` of idle time. ``held`` is False when it could not be armed.

        When it could not be armed (shutdown under way, no watcher thread) nothing is held, and the caller
        releases the runtime exactly as it would have without a hold.
        """

        if seconds <= 0:
            raise ValueError("a warm hold needs a positive idle grace")
        if self._closed.is_set() or self._shutdown_requested():
            return {"held": False, "reason": "shutdown_requested"}
        self._listen_for_shutdown()
        with self._lock:
            previous = self._take_locked()
            if previous is not None and previous.pid != pid:
                self._release_locked(previous, reason="replaced")
            self._generation += 1
            entry = _Hold(
                runtime=str(runtime),
                key=tuple(str(part) for part in key),
                pid=int(pid),
                seconds=float(seconds),
                held_at=self._clock(),
                release=release,
                generation=self._generation,
            )
            self._hold = entry
        try:
            self._spawn(
                target=self._watch,
                args=(entry,),
                name=f"RuntimeWarmHold-{entry.runtime}",
                purpose=f"Release the idle warm {entry.runtime} runtime after {entry.seconds:.0f} s",
            )
        except Exception as exc:  # noqa: BLE001 - an unarmed hold must not keep the process
            with self._lock:
                if self._hold is entry:
                    self._hold = None
            entry.cancelled.set()
            return {
                "held": False,
                "reason": f"watcher unavailable: {type(exc).__name__}: {exc}"[:300],
            }
        logger.info(
            "Keeping StableNew-owned %s pid %s warm for %.0f s of idle time (%s)",
            entry.runtime,
            entry.pid,
            entry.seconds,
            "/".join(entry.key),
        )
        return {
            "held": True,
            "runtime": entry.runtime,
            "key": list(entry.key),
            "pid": entry.pid,
            "idle_release_seconds": entry.seconds,
        }

    def claim(
        self,
        *,
        runtime: str,
        key: Sequence[str],
        current_pid: Callable[[], int | None],
    ) -> WarmHoldClaim:
        """Take whatever is held. Warm only for the same runtime and key on the very same owned process.

        Anything else held is released before this returns, so the claiming job starts cold.
        """

        wanted = (str(runtime), tuple(str(part) for part in key))
        with self._lock:
            entry = self._take_locked()
            if entry is None:
                return WarmHoldClaim(CLAIM_NONE)
            idle = max(0.0, self._clock() - entry.held_at)
            try:
                pid = current_pid()
            except Exception:  # noqa: BLE001 - an unreadable owner is never treated as warm
                pid = None
            if (entry.runtime, entry.key) == wanted and pid is not None and int(pid) == entry.pid:
                return WarmHoldClaim(
                    CLAIM_WARM, held_key=entry.key, pid=entry.pid, idle_seconds=idle
                )
            outcome = self._release_locked(entry, reason="claimed_by_another_job")
            return WarmHoldClaim(
                CLAIM_RELEASED,
                held_key=entry.key,
                pid=entry.pid,
                idle_seconds=idle,
                release=outcome,
            )

    def end(self, *, reason: str) -> dict[str, Any] | None:
        """Release whatever is held (another runtime or job is being prepared). ``None`` when nothing was."""

        with self._lock:
            entry = self._take_locked()
            if entry is None:
                return None
            return self._release_locked(entry, reason=reason)

    def snapshot(self) -> dict[str, Any] | None:
        """Read-only view of the slot for diagnostics."""

        with self._lock:
            entry = self._hold
            if entry is None:
                return None
            return {
                "runtime": entry.runtime,
                "key": list(entry.key),
                "pid": entry.pid,
                "idle_release_seconds": entry.seconds,
                "held_for_seconds": round(max(0.0, self._clock() - entry.held_at), 1),
            }

    # -- watcher ---------------------------------------------------------------------------------------

    def _watch(self, entry: _Hold) -> None:
        deadline = entry.held_at + entry.seconds
        while True:
            remaining = deadline - self._clock()
            if remaining <= 0:
                break
            if entry.cancelled.wait(min(remaining, _WATCH_SLICE_SECONDS)):
                return  # claimed, ended or replaced
            if self._closed.is_set() or not self._interpreter_running():
                return  # shutting down: the app's exit cleanup owns the process
        self.expire(entry.generation)

    def expire(self, generation: int) -> dict[str, Any] | None:
        """Release the hold of ``generation`` if it is still the one in the slot (the idle grace passed)."""

        with self._lock:
            entry = self._hold
            if entry is None or entry.generation != generation or self._closed.is_set():
                return None
            self._take_locked()
            return self._release_locked(entry, reason="idle_grace_elapsed")

    def _on_shutdown(self) -> None:
        # Signal only (no lock): a release in progress must never delay application shutdown.
        self._closed.set()
        entry = self._hold
        if entry is not None:
            entry.cancelled.set()

    def _listen_for_shutdown(self) -> None:
        if self._listening:
            return
        try:
            self._add_shutdown_listener(self._on_shutdown)
            self._listening = True
        except Exception:  # noqa: BLE001 - the watcher still stops at interpreter shutdown
            logger.debug("Could not register the warm-hold shutdown listener", exc_info=True)

    # -- slot helpers (lock held) ------------------------------------------------------------------------

    def _take_locked(self) -> _Hold | None:
        entry = self._hold
        self._hold = None
        if entry is not None:
            entry.cancelled.set()
        return entry

    def _release_locked(self, entry: _Hold, *, reason: str) -> dict[str, Any]:
        try:
            outcome = dict(entry.release() or {})
        except Exception as exc:  # noqa: BLE001 - a release problem is reported, never raised
            outcome = {"released": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
        outcome.update(
            warm_hold_end=reason,
            held_for_seconds=round(max(0.0, self._clock() - entry.held_at), 1),
        )
        logger.info(
            "Ended the warm hold of StableNew-owned %s pid %s (%s): %s",
            entry.runtime,
            entry.pid,
            reason,
            outcome,
        )
        return outcome


_GLOBAL_HOLD: RuntimeWarmHold | None = None
_GLOBAL_LOCK = threading.Lock()


def get_runtime_warm_hold() -> RuntimeWarmHold:
    """The process-wide slot."""

    global _GLOBAL_HOLD
    if _GLOBAL_HOLD is None:
        with _GLOBAL_LOCK:
            if _GLOBAL_HOLD is None:
                _GLOBAL_HOLD = RuntimeWarmHold()
    return _GLOBAL_HOLD


def end_runtime_warm_hold(reason: str) -> dict[str, Any] | None:
    """Release the process-wide hold, if any (used by the runtime transition coordinator)."""

    return get_runtime_warm_hold().end(reason=reason)


__all__ = [
    "CLAIM_NONE",
    "CLAIM_RELEASED",
    "CLAIM_WARM",
    "RuntimeWarmHold",
    "WarmHoldClaim",
    "end_runtime_warm_hold",
    "get_runtime_warm_hold",
]
