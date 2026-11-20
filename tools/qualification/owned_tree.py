"""Observation-only evidence about a process tree StableNew started: bounded teardown verification and tree memory.

QUAL-927. Two qualification results were INCONCLUSIVE because of how they observed their own runtime, not because of
what the runtime did: Z-Image-Turbo (PR-IMG-MODELS-154B) and Wan A14B (PR-VID-WAN-321F) each checked teardown once,
immediately after the stop, with no wait; and A14B sampled memory on the Comfy launcher stub instead of its worker.
This module is the shared replacement used by the 154B Forge runtime, the 321F Comfy adapter and the golden-path
physical lane:

* ``OwnedTreeSampler`` samples the whole owned tree (the root and every descendant), summing working set and private
  commit, and records the PID set of every sample plus each process's creation time.
* ``verify_teardown`` polls the recorded processes and the owned ports until every one is gone or a bounded deadline
  passes, recording each observation with timestamps. ``verified`` is true only when every recorded process and port
  is gone within the deadline; otherwise the survivors are named.

It observes only. Nothing here signals, kills, suspends, adopts or restarts a process, and it starts no process: the
runtime's own process manager remains the sole lifecycle authority. A process is "owned" only because it was recorded
as the owned root or one of its descendants while it ran; a PID that now belongs to a different process (its creation
time changed) is reported as reused and left alone, and a process listening on an owned port that was never recorded
is reported as a foreign listener and left alone. Importing the module has no side effects (``psutil`` and the
Windows memory reader load on first use).
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

#: Long enough for a contained tree to finish exiting after its manager's stop; it bounds the wait only when a process
#: really survives. A harness may set its own value; the one used is recorded in the evidence.
DEFAULT_TEARDOWN_DEADLINE_SECONDS = 60.0
DEFAULT_TEARDOWN_POLL_SECONDS = 0.5
#: The same process reports the same creation time on every read; a different time means a reused PID.
CREATE_TIME_TOLERANCE_SECONDS = 1e-3

TEARDOWN_VERIFIED = "verified_clean"
TEARDOWN_SURVIVORS = "survivors_at_deadline"
TEARDOWN_NOTHING_RECORDED = "nothing_recorded"


class ProcessTable(Protocol):
    """Read-only process observation. ``children`` returns every descendant (recursive), never the process itself."""

    def exists(self, pid: int) -> bool: ...

    def create_time(self, pid: int) -> float | None: ...

    def children(self, pid: int) -> list[int]: ...

    def listening_pids(self, port: int) -> list[int]: ...


MemoryReader = Callable[[int], Any]
"""``pid -> object with working_set_gb and private_usage_gb`` (GiB), or ``None`` when the process cannot be read."""


def _real_pid(pid: object) -> bool:
    # psutil reads ``Process(None)`` as the calling process; PID 0 is the system idle process. Neither is ever owned.
    return isinstance(pid, int) and not isinstance(pid, bool) and pid > 0


class PsutilProcessTable:
    """The real process table, through ``psutil`` (imported on first use)."""

    def exists(self, pid: int) -> bool:
        import psutil

        return _real_pid(pid) and bool(psutil.pid_exists(pid))

    def create_time(self, pid: int) -> float | None:
        import psutil

        if not _real_pid(pid):
            return None
        try:
            return float(psutil.Process(pid).create_time())
        except (psutil.Error, OSError):
            return None

    def children(self, pid: int) -> list[int]:
        import psutil

        if not _real_pid(pid):
            return []
        try:
            return [child.pid for child in psutil.Process(pid).children(recursive=True)]
        except (psutil.Error, OSError):
            return []

    def listening_pids(self, port: int) -> list[int]:
        import psutil

        pids: set[int] = set()
        try:
            for conn in psutil.net_connections(kind="inet"):
                laddr = getattr(conn, "laddr", None)
                if (
                    laddr
                    and getattr(laddr, "port", None) == port
                    and conn.status == psutil.CONN_LISTEN
                    and conn.pid
                ):
                    pids.add(int(conn.pid))
        except (psutil.Error, OSError):
            return []
        return sorted(pids)


def read_process_memory(pid: int) -> Any:
    """Working set and private commit of one process (``GetProcessMemoryInfo``), or ``None`` off Windows or if gone."""

    try:
        from tools.qualification.vid160c.win_memory import read_process_memory as reader

        return reader(pid)
    except (OSError, AttributeError, ValueError):
        return None


@dataclass(frozen=True, order=True)
class OwnedProcess:
    """One process StableNew started, identified by PID and creation time (``None`` when it could not be read)."""

    pid: int
    create_time: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"pid": self.pid, "create_time": self.create_time}


def merge_owned(*groups: Iterable[OwnedProcess]) -> tuple[OwnedProcess, ...]:
    """One record per process: a known creation time replaces an unknown one for the same PID."""

    known: dict[tuple[int, float], OwnedProcess] = {}
    unknown: set[int] = set()
    for group in groups:
        for item in group:
            if item.create_time is None:
                unknown.add(item.pid)
            else:
                known[(item.pid, round(item.create_time, 3))] = item
    pids_with_time = {pid for pid, _ in known}
    merged = list(known.values()) + [
        OwnedProcess(pid) for pid in unknown if pid not in pids_with_time
    ]
    return tuple(sorted(merged, key=lambda p: (p.pid, p.create_time or 0.0)))


def _utc() -> str:
    return datetime.now(UTC).isoformat()


def _same_process(recorded: float | None, current: float | None) -> bool:
    if recorded is None or current is None:
        return True  # unknown identity: count it as ours, so it can only keep teardown unverified
    return abs(recorded - current) < CREATE_TIME_TOLERANCE_SECONDS


# ---------------------------------------------------------------------------------------------- bounded teardown wait


@dataclass(frozen=True)
class TeardownVerification:
    verified: bool
    outcome: str
    deadline_seconds: float
    poll_seconds: float
    elapsed_seconds: float
    owned: tuple[OwnedProcess, ...]
    ports: tuple[int, ...]
    survivors: tuple[int, ...]
    held_ports: Mapping[int, tuple[int, ...]]
    foreign_listeners: tuple[int, ...]
    observations: tuple[Mapping[str, Any], ...]
    started_utc: str
    finished_utc: str
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "verified": self.verified,
            "outcome": self.outcome,
            "deadline_seconds": self.deadline_seconds,
            "poll_seconds": self.poll_seconds,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "owned": [item.as_dict() for item in self.owned],
            "ports": list(self.ports),
            "survivors": list(self.survivors),
            "held_ports": {str(port): list(pids) for port, pids in self.held_ports.items()},
            "foreign_listeners": list(self.foreign_listeners),
            "observations": [dict(item) for item in self.observations],
            "started_utc": self.started_utc,
            "finished_utc": self.finished_utc,
            "detail": self.detail,
            "method": "observation only (QUAL-927 tools/qualification/owned_tree.py); no process was signalled",
        }


def verify_teardown(
    owned: Iterable[OwnedProcess],
    ports: Iterable[int] = (),
    *,
    deadline_seconds: float = DEFAULT_TEARDOWN_DEADLINE_SECONDS,
    poll_seconds: float = DEFAULT_TEARDOWN_POLL_SECONDS,
    table: ProcessTable | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    utc: Callable[[], str] = _utc,
) -> TeardownVerification:
    """Poll until every recorded process and owned port is gone, or the deadline passes. Observes; never signals.

    A deadline of zero is a single observation. Nothing recorded is never a clean teardown: the absence of an
    observation proves nothing.
    """

    if not math.isfinite(deadline_seconds) or deadline_seconds < 0:
        raise ValueError("deadline_seconds must be a finite number >= 0")
    if not math.isfinite(poll_seconds) or poll_seconds <= 0:
        raise ValueError("poll_seconds must be a finite number > 0")
    table = table or PsutilProcessTable()
    records = merge_owned(owned)
    port_list = tuple(sorted({int(p) for p in ports}))
    owned_pids = {item.pid for item in records}
    started_utc = utc()
    start = clock()
    observations: list[dict[str, Any]] = []

    while True:
        alive: list[int] = []
        reused: list[int] = []
        for item in records:
            if not table.exists(item.pid):
                continue
            if _same_process(item.create_time, table.create_time(item.pid)):
                alive.append(item.pid)
            else:
                reused.append(item.pid)
        listeners = {port: tuple(sorted(table.listening_pids(port))) for port in port_list}
        held = {port: pids for port, pids in listeners.items() if pids}
        elapsed = clock() - start
        observations.append(
            {
                "t": round(elapsed, 3),
                "utc": utc(),
                "alive_pids": sorted(set(alive)),
                "reused_pids": sorted(set(reused)),
                "listeners": {str(port): list(pids) for port, pids in listeners.items()},
            }
        )
        gone = not alive and not held
        if not records or gone or elapsed >= deadline_seconds:
            break
        sleep(min(poll_seconds, deadline_seconds - elapsed))

    survivors = tuple(sorted(set(alive)))
    foreign = tuple(
        sorted({pid for pids in held.values() for pid in pids if pid not in owned_pids})
    )
    if not records:
        outcome, verified = TEARDOWN_NOTHING_RECORDED, False
        detail = "no owned process was recorded, so its teardown cannot be verified"
    elif gone:
        outcome, verified = TEARDOWN_VERIFIED, True
        detail = f"every recorded process and owned port was gone after {elapsed:.2f} s"
    else:
        outcome, verified = TEARDOWN_SURVIVORS, False
        parts = []
        if survivors:
            parts.append("surviving PIDs " + ", ".join(str(p) for p in survivors))
        if held:
            parts.append(
                "held ports "
                + ", ".join(
                    f"{port} (listener {', '.join(map(str, pids))})" for port, pids in held.items()
                )
            )
        if foreign:
            parts.append(
                "foreign listeners (never recorded as owned; observed only) "
                + ", ".join(map(str, foreign))
            )
        detail = f"not gone within the {deadline_seconds:g} s deadline: " + "; ".join(parts)
    return TeardownVerification(
        verified=verified,
        outcome=outcome,
        deadline_seconds=float(deadline_seconds),
        poll_seconds=float(poll_seconds),
        elapsed_seconds=elapsed,
        owned=records,
        ports=port_list,
        survivors=survivors,
        held_ports=held,
        foreign_listeners=foreign,
        observations=tuple(observations),
        started_utc=started_utc,
        finished_utc=utc(),
        detail=detail,
    )


# -------------------------------------------------------------------------------------------- owned worker-tree memory


@dataclass
class OwnedTreeSampler:
    """Sample the memory of the owned root and every descendant, and remember every process ever seen in the tree.

    ``root`` returns the owned root PID (or ``None`` before launch / after exit). ``include_root=False`` samples only
    the descendants: the golden-path lane runs the application inside the harness process, so the harness itself is
    not a worker. Only the root and its descendants are ever read; nothing outside the tree is adopted.
    """

    root: Callable[[], int | None]
    include_root: bool = True
    table: ProcessTable | None = None
    memory: MemoryReader | None = None
    clock: Callable[[], float] = time.monotonic
    utc: Callable[[], str] = _utc
    samples: int = 0
    peaks: dict[str, float] = field(
        default_factory=lambda: {
            "tree_working_set_gib": 0.0,
            "tree_private_gib": 0.0,
            "max_process_count": 0,
        }
    )
    _seen: dict[tuple[int, float | None], OwnedProcess] = field(default_factory=dict)
    _t0: float | None = None

    def __post_init__(self) -> None:
        self.table = self.table or PsutilProcessTable()
        self.memory = self.memory or read_process_memory

    @property
    def recorded(self) -> tuple[OwnedProcess, ...]:
        return merge_owned(self._seen.values())

    def tree_pids(self) -> list[int]:
        table = self.table
        assert table is not None
        root = self.root()
        if root is None:
            return []
        pids = [root] if self.include_root and table.exists(root) else []
        pids.extend(int(p) for p in table.children(root) if int(p) != root)
        return sorted(set(pids))

    def sample(self, host: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """One sample: the PID set, per-process and summed working set / private commit, and ``host`` as given.

        A child that exits between listing and reading is reported in ``unreadable_pids`` and the sums are then a
        lower bound (``complete`` is false).
        """

        table, memory = self.table, self.memory
        assert table is not None and memory is not None
        now = self.clock()
        if self._t0 is None:
            self._t0 = now
        root = self.root()
        pids = self.tree_pids()
        processes: dict[str, dict[str, float]] = {}
        unreadable: list[int] = []
        working = private = 0.0
        for pid in pids:
            created = table.create_time(pid)
            key = (pid, None if created is None else round(created, 3))
            self._seen.setdefault(key, OwnedProcess(pid, created))
            info = memory(pid)
            if info is None:
                unreadable.append(pid)
                continue
            ws, pv = float(info.working_set_gb), float(info.private_usage_gb)
            processes[str(pid)] = {"working_set_gib": ws, "private_gib": pv}
            working += ws
            private += pv
        self.samples += 1
        self.peaks["tree_working_set_gib"] = max(self.peaks["tree_working_set_gib"], working)
        self.peaks["tree_private_gib"] = max(self.peaks["tree_private_gib"], private)
        self.peaks["max_process_count"] = max(self.peaks["max_process_count"], len(pids))
        return {
            "t": round(now - self._t0, 3),
            "utc": self.utc(),
            "root_pid": root,
            "include_root": self.include_root,
            "pids": pids,
            "readable_pids": sorted(int(p) for p in processes),
            "unreadable_pids": unreadable,
            "processes": processes,
            "tree_working_set_gib": working,
            "tree_private_gib": private,
            "complete": bool(pids) and not unreadable,
            "host": dict(host) if host is not None else None,
        }


__all__ = [
    "CREATE_TIME_TOLERANCE_SECONDS",
    "DEFAULT_TEARDOWN_DEADLINE_SECONDS",
    "DEFAULT_TEARDOWN_POLL_SECONDS",
    "TEARDOWN_NOTHING_RECORDED",
    "TEARDOWN_SURVIVORS",
    "TEARDOWN_VERIFIED",
    "OwnedProcess",
    "OwnedTreeSampler",
    "ProcessTable",
    "PsutilProcessTable",
    "TeardownVerification",
    "merge_owned",
    "read_process_memory",
    "verify_teardown",
]
