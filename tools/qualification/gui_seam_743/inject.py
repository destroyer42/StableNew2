"""Proof-only parameter injection and observation for the production ``TkInvoker`` (GUI-SEAM-743).

The measured scheduler is always the production ``TkInvoker._pump``. This module only (1) holds back the first timer
registration so the requested interval is in force before the first pump is armed, (2) writes the three tuning
attributes on that one instance, and (3) records pump entries/exits around the unmodified production method. It is
never imported by the application and creates no configuration mechanism.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from src.gui.gui_invoker import TkInvoker
from tools.qualification.gui_seam_743.config import ConfigError, PumpConfig


def production_defaults() -> dict[str, Any]:
    """The tuning values a fresh production ``TkInvoker`` actually carries (read from the class, not restated)."""

    class _Root:
        def after(self, delay_ms: int, fn: object) -> None:
            return None

    invoker = TkInvoker(_Root())  # type: ignore[arg-type]
    try:
        return effective_parameters(invoker)
    finally:
        invoker.dispose()


def effective_parameters(invoker: TkInvoker) -> dict[str, Any]:
    return {
        "interval_ms": invoker._pump_interval_ms,
        "max_callbacks": invoker._max_callbacks_per_pump,
        "max_pump_ms": float(invoker._max_pump_duration_ms),
    }


@contextmanager
def deferred_first_pump() -> Iterator[None]:
    """While active, a new ``TkInvoker`` does not arm its first timer; the real method is restored on exit."""

    original = TkInvoker._schedule_pump
    TkInvoker._schedule_pump = lambda self: None  # type: ignore[method-assign]
    try:
        yield
    finally:
        TkInvoker._schedule_pump = original  # type: ignore[method-assign]


@dataclass
class PumpLog:
    """Entry time and duration of every pump of one invoker (monotonic ``perf_counter`` seconds)."""

    starts: list[float] = field(default_factory=list)
    durations_ms: list[float] = field(default_factory=list)

    @property
    def current(self) -> int:
        """Index of the pump now executing (or the last one), usable from inside a callback."""
        return len(self.starts) - 1

    def window(self, begin: int, end: int) -> tuple[list[float], list[float]]:
        return self.starts[begin:end], self.durations_ms[begin:end]


def observe(invoker: TkInvoker) -> PumpLog:
    """Shadow ``_pump`` on this instance with a thin recorder that calls the unmodified production method."""

    log = PumpLog()

    def recorded_pump() -> None:
        started = time.perf_counter()
        log.starts.append(started)
        try:
            TkInvoker._pump(invoker)
        finally:
            log.durations_ms.append((time.perf_counter() - started) * 1000)

    invoker._pump = recorded_pump  # type: ignore[method-assign]
    return log


def configure(invoker: TkInvoker, config: PumpConfig) -> dict[str, Any]:
    """Set the requested values on an invoker whose first timer is still unarmed, then arm it. Returns effective values."""

    config.validate()
    if invoker._pump_scheduled or invoker._disposed:
        raise ConfigError(
            "the invoker already armed its pump; parameters must precede the first timer"
        )
    invoker._pump_interval_ms = config.interval_ms
    invoker._max_callbacks_per_pump = config.max_callbacks
    invoker._max_pump_duration_ms = config.max_pump_ms
    effective = effective_parameters(invoker)
    if effective != config.parameters():
        raise ConfigError(f"effective {effective} differs from requested {config.parameters()}")
    invoker._schedule_pump()
    return effective


def dispatcher_with_config(root: Any, config: PumpConfig) -> tuple[Any, PumpLog, dict[str, Any]]:
    """The root's single registry dispatcher, with ``config`` in force from its first armed timer."""

    from src.gui.ui_dispatcher import tk_dispatcher_for

    with deferred_first_pump():
        dispatcher = tk_dispatcher_for(root)
    invoker = dispatcher._invoker
    if invoker is None:
        raise ConfigError("the dispatcher has no TkInvoker to configure")
    log = observe(invoker)
    effective = configure(invoker, config)
    return dispatcher, log, effective
