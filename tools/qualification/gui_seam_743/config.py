"""Pure (toolkit-free) experiment definition for GUI-SEAM-743: pump candidates, validation, ordering and run plans.

Nothing here imports Tk or the production dispatcher. The control is the production ``TkInvoker`` default; it is
asserted against the real class in tests, never copied silently.
"""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass
from typing import Any

DIMENSIONS = ("interval_ms", "max_callbacks", "max_pump_ms")
MAX_CONFIRMATIONS = 2
MIN_SAMPLES = 5


class ConfigError(ValueError):
    """A pump configuration or run plan that must not be launched."""


@dataclass(frozen=True)
class PumpConfig:
    name: str
    interval_ms: int
    max_callbacks: int
    max_pump_ms: float

    def validate(self) -> PumpConfig:
        if not self.name or not self.name.isidentifier():
            raise ConfigError(f"invalid condition name {self.name!r}")
        for field, low, high in (("interval_ms", 1, 100), ("max_callbacks", 1, 1024)):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ConfigError(f"{field}={value!r} must be an int in [{low}, {high}]")
        pump = self.max_pump_ms
        if (
            isinstance(pump, bool)
            or not isinstance(pump, (int, float))
            or not math.isfinite(pump)
            or not 0.5 <= pump <= 50.0
        ):
            raise ConfigError(f"max_pump_ms={pump!r} must be finite and in [0.5, 50]")
        return self

    def parameters(self) -> dict[str, Any]:
        return {
            "interval_ms": self.interval_ms,
            "max_callbacks": self.max_callbacks,
            "max_pump_ms": float(self.max_pump_ms),
        }

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, **self.parameters()}


# The immutable control: the production TkInvoker defaults (15 ms / 32 callbacks / 8 ms).
CONTROL = PumpConfig("A", 15, 32, 8.0)
MATRIX: tuple[PumpConfig, ...] = (
    CONTROL,
    PumpConfig("B", 10, 32, 8.0),
    PumpConfig("C", 5, 32, 8.0),
    PumpConfig("D", 15, 64, 8.0),
    PumpConfig("E", 15, 128, 8.0),
    PumpConfig("F", 15, 32, 4.0),
    PumpConfig("G", 15, 32, 12.0),
)
LABELS = {
    "A": "Baseline",
    "B": "Faster polling",
    "C": "Short polling",
    "D": "Larger batch",
    "E": "Large batch",
    "F": "Shorter time budget",
    "G": "Longer time budget",
}
# The measured workload is part of the experiment identity: a record with other sizes is another experiment.
WORKLOAD = {
    "rows": 500,
    "burst_callbacks": 2000,
    "refresh_revisions": 12,
    "sustained_seconds": 1.5,
    "sustained_interval_s": 0.02,
    "idle_quiet_seconds": 3.0,
}


def varied_dimensions(config: PumpConfig, control: PumpConfig = CONTROL) -> tuple[str, ...]:
    return tuple(d for d in DIMENSIONS if getattr(config, d) != getattr(control, d))


def validate_matrix(matrix: tuple[PumpConfig, ...] = MATRIX) -> None:
    names = [c.validate().name for c in matrix]
    if len(set(names)) != len(names):
        raise ConfigError("duplicate condition names")
    if not matrix or matrix[0].parameters() != CONTROL.parameters():
        raise ConfigError("the first condition must be the immutable control")
    for config in matrix[1:]:
        if len(varied_dimensions(config)) != 1:
            raise ConfigError(f"{config.name}: primary candidates change exactly one dimension")


def validate_confirmations(
    configs: list[PumpConfig], matrix: tuple[PumpConfig, ...] = MATRIX
) -> list[PumpConfig]:
    """At most two predeclared combinations, each built only from values already tested in the primary matrix."""

    if not configs:
        raise ConfigError("no confirmation configuration supplied")
    if len(configs) > MAX_CONFIRMATIONS:
        raise ConfigError(f"at most {MAX_CONFIRMATIONS} confirmation configurations are permitted")
    used = {c.name for c in matrix}
    seen: set[tuple[Any, ...]] = {tuple(c.parameters().values()) for c in matrix}
    for config in configs:
        config.validate()
        if config.name in used:
            raise ConfigError(f"{config.name}: confirmation names must be new")
        used.add(config.name)
        for dimension in DIMENSIONS:
            tested = {getattr(c, dimension) for c in matrix}
            if getattr(config, dimension) not in tested:
                raise ConfigError(f"{config.name}: {dimension} was never tested in the matrix")
        key = tuple(config.parameters().values())
        if key in seen:
            raise ConfigError(f"{config.name}: duplicates an existing configuration")
        if len(varied_dimensions(config)) < 2:
            raise ConfigError(f"{config.name}: a confirmation must combine two or more settings")
        seen.add(key)
    return list(configs)


def balanced_order(names: list[str], rounds: int, seed: int) -> list[list[str]]:
    """Cyclic Latin-square rounds over a seeded base order: every condition takes a different position each round."""

    if not names or rounds < 1:
        raise ConfigError("an order needs conditions and at least one round")
    base = list(names)
    random.Random(seed).shuffle(base)
    count = len(base)
    return [base[round_ % count :] + base[: round_ % count] for round_ in range(rounds)]


@dataclass(frozen=True)
class RunSpec:
    run_id: str
    phase: str
    kind: str  # "warmup" or "measured"
    round: int
    position: int
    config: PumpConfig


def plan_runs(configs: list[PumpConfig], *, phase: str, samples: int, seed: int) -> list[RunSpec]:
    """One unmeasured warm-up per candidate (declared order), then ``samples`` counterbalanced measured rounds."""

    if samples < MIN_SAMPLES:
        raise ConfigError(f"at least {MIN_SAMPLES} measured runs per candidate are required")
    if not configs:
        raise ConfigError("a run plan needs at least one candidate")
    by_name = {c.validate().name: c for c in configs}
    if len(by_name) != len(configs):
        raise ConfigError("duplicate condition names in the plan")
    plan = [
        RunSpec(f"{phase}-warmup-{c.name}", phase, "warmup", 0, i, c) for i, c in enumerate(configs)
    ]
    for round_, order in enumerate(balanced_order(list(by_name), samples, seed), start=1):
        plan.extend(
            RunSpec(f"{phase}-r{round_}-{name}", phase, "measured", round_, position, by_name[name])
            for position, name in enumerate(order)
        )
    ids = [r.run_id for r in plan]
    if len(set(ids)) != len(ids):
        raise ConfigError("run identities are not unique")
    return plan


def config_from_dict(raw: dict[str, Any]) -> PumpConfig:
    return PumpConfig(
        str(raw["name"]), raw["interval_ms"], raw["max_callbacks"], raw["max_pump_ms"]
    ).validate()


def describe(config: PumpConfig) -> dict[str, Any]:
    return {**asdict(config), "label": LABELS.get(config.name, "Confirmation")}
