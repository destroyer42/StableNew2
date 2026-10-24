"""Consume only the read capability minted by run_bounded for this request (F2)."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.utils.managed_process import OwnedChildObservation
from src.utils.process_observation import ProcessTreeSample

_GIB = 1024**3
OBSERVE_GRACE_SECONDS = 3.0
CAP_CONSECUTIVE = 2
CAP_FACTOR = 1.5
CAP_MARGIN_GIB = 2.0


def default_cap_gib(model_bytes: int) -> float:
    return model_bytes / _GIB * CAP_FACTOR + CAP_MARGIN_GIB


@dataclass(slots=True)
class Evidence:
    child_observed: bool = False
    peak_tree_private_gib: float = 0.0
    peak_tree_working_set_gib: float = 0.0
    tree_cpu_seconds: float = 0.0
    max_tree_processes: int = 0
    priority_verified: bool | None = None
    observed_priority_class: int | None = None

    def as_details(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


class ChildObserver:
    """No discovery or process mutation. Invalid/missing telemetry fails closed."""

    def __init__(
        self,
        *,
        cap_gib: float,
        clock: Callable[[], float] = time.monotonic,
        grace_seconds: float = OBSERVE_GRACE_SECONDS,
    ) -> None:
        if not math.isfinite(cap_gib) or cap_gib <= 0:
            raise ValueError("finite positive process cap required")
        self._cap_gib = cap_gib
        self._clock = clock
        self._grace = grace_seconds
        self._started = clock()
        self._child: OwnedChildObservation | None = None
        self._strikes = 0
        self.evidence = Evidence()

    def bind(self, child: OwnedChildObservation) -> None:
        if self._child is not None:
            raise ValueError("observer already bound")
        self._child = child

    @property
    def has_child(self) -> bool:
        return self._child is not None

    def poll(self) -> str | None:
        if self._child is None:
            return "child_not_observable" if self._clock() - self._started > self._grace else None
        try:
            sample = self._child.sample()
        except Exception:  # noqa: BLE001 - telemetry failure must terminate the owned request
            return "process_memory_unreadable"
        if not isinstance(sample, ProcessTreeSample) or sample.root_pid != self._child.pid:
            return "process_observation_invalid"
        values = (
            sample.process_count,
            sample.private_bytes,
            sample.working_set_bytes,
            sample.cpu_seconds,
        )
        if (
            any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values)
            or sample.process_count < 1
        ):
            return "process_observation_invalid"
        if sample.priority_verified is not None and sample.priority_verified is not True:
            self.evidence.priority_verified = False
            return "process_priority_unverified"
        self.evidence.child_observed = True
        self.evidence.priority_verified = sample.priority_verified
        self.evidence.observed_priority_class = sample.priority_class
        self.evidence.max_tree_processes = max(
            self.evidence.max_tree_processes, sample.process_count
        )
        self.evidence.peak_tree_private_gib = max(
            self.evidence.peak_tree_private_gib, sample.private_bytes / _GIB
        )
        self.evidence.peak_tree_working_set_gib = max(
            self.evidence.peak_tree_working_set_gib, sample.working_set_bytes / _GIB
        )
        self.evidence.tree_cpu_seconds = max(self.evidence.tree_cpu_seconds, sample.cpu_seconds)
        self._strikes = self._strikes + 1 if sample.private_bytes / _GIB > self._cap_gib else 0
        return "process_memory_cap" if self._strikes >= CAP_CONSECUTIVE else None


__all__ = ["CAP_FACTOR", "CAP_MARGIN_GIB", "ChildObserver", "Evidence", "default_cap_gib"]
