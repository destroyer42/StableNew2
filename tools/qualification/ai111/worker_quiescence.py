"""Record one-request owned-runtime lifecycles for the AI-111 preflight."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

SHA = re.compile(r"[0-9a-f]{64}")
OUTCOMES = {
    "success": frozenset({"completed"}),
    "invalid_request": frozenset({"rejected"}),
    "cancellation": frozenset({"cancelled", "timed_out"}),
}
EVENTS = ("admitted", "populated", "terminal", "empty")
METHOD = "owned_cgroup_v2_teardown"


class Population(Protocol):
    @property
    def cgroup_sha256(self) -> str: ...
    def population(self) -> str: ...


@dataclass(frozen=True)
class Runtime:
    invocation: str
    population: Population
    current_invocation: Callable[[], str]


class Recorder:
    """Single synchronous admission controller. All clocks and epochs share one observer."""

    def __init__(self, clock: Callable[[], int]):
        self._clock = clock
        self._events: list[dict[str, object]] = []
        self._used: dict[str, set[str]] = {
            field: set() for field in ("request", "category", "invocation", "cgroup")
        }
        self._active: tuple[Runtime, dict[str, str]] | None = None
        self._failed = False

    def _check(self, condition: bool) -> None:
        if self._failed or not condition:
            self._failed = True
            raise ValueError("qualification lifecycle cannot be verified")

    def _emit(self, event: str, outcome: str | None = None) -> None:
        self._check(self._active is not None)
        assert self._active is not None
        runtime, context = self._active
        try:
            self._check(runtime.current_invocation() == context["invocation"])
            if event in {"populated", "empty"}:
                self._check(runtime.population.population() == event)
                self._check(runtime.current_invocation() == context["invocation"])
            self._check(runtime.population.cgroup_sha256 == context["cgroup"])
            now = self._clock()
            self._check(type(now) is int and now >= 0)
            if self._events:
                last_time = self._events[-1]["monotonic_ns"]
                assert isinstance(last_time, int)
                self._check(now > last_time)
        except Exception:
            self._failed = True
            raise
        self._events.append(
            {
                **context,
                "sequence": len(self._events),
                "monotonic_ns": now,
                "event": event,
                "outcome": outcome,
            }
        )

    def admit(self, request: str, category: str, runtime: Runtime) -> None:
        """Record intent for an owned unit. Dispatch requires a subsequent populated sample."""
        self._check(self._active is None and isinstance(category, str) and category in OUTCOMES)
        try:
            context = {
                "request": request,
                "category": category,
                "invocation": runtime.invocation,
                "cgroup": runtime.population.cgroup_sha256,
            }
        except Exception:
            self._failed = True
            raise
        self._check(
            all(
                isinstance(value, str)
                and (field == "category" or SHA.fullmatch(value) is not None)
                and value not in self._used[field]
                for field, value in context.items()
            )
        )
        self._active = runtime, context
        self._emit("admitted")
        for field, value in context.items():
            self._used[field].add(value)

    def populated(self) -> None:
        self._check(bool(self._events) and self._events[-1]["event"] == "admitted")
        self._emit("populated")

    def terminal(self, outcome: str) -> None:
        self._check(bool(self._events) and self._events[-1]["event"] == "populated")
        assert self._active is not None
        category = self._active[1]["category"]
        self._check(isinstance(outcome, str) and outcome in OUTCOMES[category])
        self._emit("terminal", outcome)

    def empty(self) -> None:
        self._check(bool(self._events) and self._events[-1]["event"] == "terminal")
        self._emit("empty")
        self._active = None

    def evidence(self, *, event_loss: int, other_clients: int) -> dict[str, object]:
        return {
            "method": METHOD,
            "observer_complete": not self._failed
            and self._active is None
            and self._used["category"] == OUTCOMES.keys(),
            "event_loss": event_loss,
            "other_clients": other_clients,
            "events": [record.copy() for record in self._events],
        }
