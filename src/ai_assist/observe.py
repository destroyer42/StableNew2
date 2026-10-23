"""Observe, prioritise and bound the inference child from inside the AI layer (PR-AI-111, deferred finding F2).

``run_bounded`` offers no priority parameter and does not expose the child's pid, and it is a shared safety primitive that
this feature does not change. The child is therefore found the way it can be proven to be *ours*: it is a descendant of
this process whose command line contains the request's unique scratch directory (the prompt file lives there). Once found:

* below-normal priority is applied to the whole tree and **read back from the OS**, so "verified" is an observation, not an
  assumption (Windows only; elsewhere the evidence says ``None`` = not applicable);
* the tree's private memory (commit) and working set are sampled, the peaks are kept as evidence, and a tree above its cap
  for two consecutive samples is a stop.

It is fail-closed: a child that cannot be found within the grace period cannot be bounded, so the request stops. Priority is
best-effort for responsiveness: if it cannot be applied or verified the request still runs and the evidence says so; physical
qualification, not production, requires ``priority_verified`` to be true.
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_GIB = 1024**3
OBSERVE_GRACE_SECONDS = 3.0
CAP_CONSECUTIVE = 2
#: Default cap on the tree's private memory: weights are memory-mapped (file-backed, not private), so this covers the KV
#: cache, compute buffers and any copy the runtime makes, with generous headroom, never "unbounded".
CAP_FACTOR = 1.5
CAP_MARGIN_GIB = 2.0


def default_cap_gib(model_bytes: int) -> float:
    return model_bytes / _GIB * CAP_FACTOR + CAP_MARGIN_GIB


@dataclass(slots=True)
class Evidence:
    """What was actually observed; copied into the outcome so a qualification run can gate on it."""

    child_observed: bool = False
    peak_tree_private_gib: float = 0.0
    peak_tree_working_set_gib: float = 0.0
    max_tree_processes: int = 0
    #: ``True``/``False`` on Windows after read-back; ``None`` where the priority class does not apply.
    priority_verified: bool | None = None
    observed_priority_class: int | None = None

    def as_details(self) -> dict[str, Any]:
        return {
            "child_observed": self.child_observed,
            "peak_tree_private_gib": round(self.peak_tree_private_gib, 3),
            "peak_tree_working_set_gib": round(self.peak_tree_working_set_gib, 3),
            "max_tree_processes": self.max_tree_processes,
            "priority_verified": self.priority_verified,
            "observed_priority_class": self.observed_priority_class,
        }


class ChildObserver:
    """Polled by the service watch. ``poll`` returns ``None`` (carry on) or a stable stop reason."""

    def __init__(
        self,
        marker: str,
        *,
        cap_gib: float,
        clock: Callable[[], float] = time.monotonic,
        grace_seconds: float = OBSERVE_GRACE_SECONDS,
        psutil_module: Any = None,
    ) -> None:
        if psutil_module is None:
            import psutil  # type: ignore[import-untyped,unused-ignore]  # only a request in flight needs it

            psutil_module = psutil
        self._psutil = psutil_module
        self._marker = marker
        self._cap_gib = cap_gib
        self._clock = clock
        self._grace = grace_seconds
        self._started = clock()
        self._root: Any = None
        self._prioritised: set[int] = set()
        self._strikes = 0
        self._unreadable = 0
        self.evidence = Evidence()

    def _find_root(self) -> Any:
        psutil = self._psutil
        for candidate in psutil.Process().children(recursive=True):
            try:
                if self._marker in " ".join(candidate.cmdline()):
                    return candidate
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return None

    def _tree(self) -> list[Any]:
        psutil = self._psutil
        processes = [self._root]
        try:
            processes.extend(self._root.children(recursive=True))
        except psutil.NoSuchProcess:
            return []
        return processes

    def _prioritise(self, process: Any) -> None:
        psutil = self._psutil
        if sys.platform != "win32" or not hasattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS"):
            return
        wanted = psutil.BELOW_NORMAL_PRIORITY_CLASS
        try:
            if process.pid not in self._prioritised:
                self._prioritised.add(process.pid)
                if process.nice() != wanted:
                    process.nice(wanted)
            observed = process.nice()
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return
        except (psutil.AccessDenied, OSError):
            self.evidence.priority_verified = False
            return
        if process is self._root:
            self.evidence.observed_priority_class = int(observed)
        ok = observed == wanted
        previous = self.evidence.priority_verified
        self.evidence.priority_verified = ok if previous is None else (previous and ok)

    @property
    def has_child(self) -> bool:
        return self._root is not None

    def poll(self) -> str | None:
        psutil = self._psutil
        if self._root is None:
            self._root = self._find_root()
            if self._root is None:
                if self._clock() - self._started > self._grace:
                    return "child_not_observable"
                return None
            self.evidence.child_observed = True
        tree = self._tree()
        if not tree:
            return None  # the child just exited; the runner reports how it ended
        private = working_set = 0
        counted = 0
        try:
            for process in tree:
                self._prioritise(process)
                info = process.memory_info()
                private += int(getattr(info, "private", 0) or getattr(info, "vms", 0))
                working_set += int(info.rss)
                counted += 1
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            pass  # a member exited between listing and reading; the next poll sees the rest
        except Exception:  # noqa: BLE001 - unreadable evidence cannot enforce a cap, so it is a strike
            logger.warning("AI assist child memory could not be read", exc_info=True)
            self._unreadable += 1
            if self._unreadable >= CAP_CONSECUTIVE:
                return "process_memory_unreadable"
            return None
        self._unreadable = 0
        if counted:
            self.evidence.max_tree_processes = max(self.evidence.max_tree_processes, counted)
            self.evidence.peak_tree_private_gib = max(
                self.evidence.peak_tree_private_gib, private / _GIB
            )
            self.evidence.peak_tree_working_set_gib = max(
                self.evidence.peak_tree_working_set_gib, working_set / _GIB
            )
        over = private / _GIB > self._cap_gib
        self._strikes = self._strikes + 1 if over else 0
        if self._strikes >= CAP_CONSECUTIVE:
            return "process_memory_cap"
        return None


__all__ = ["CAP_FACTOR", "CAP_MARGIN_GIB", "ChildObserver", "Evidence", "default_cap_gib"]
