"""Small-sample statistics for the two-tier analysis (PR-AI-VL-242). Pure and deterministic; the standard library only.

* :func:`wilson` — Wilson score interval for a binomial proportion. Unlike the normal (Wald) interval it stays inside [0, 1]
  and keeps close to nominal coverage at the sample sizes planned here (12 to 62), including at 0 or n successes.
* :func:`mcnemar` — exact McNemar test for paired binary outcomes: a binomial test on the discordant pairs only.
* :func:`bootstrap` — stratified percentile bootstrap for statistics with no closed-form interval (F1, balanced accuracy,
  finding precision, differences between tiers). Resampling keeps each stratum's size (the design fixes the number of clean
  and defective images), and a paired statistic is resampled on the same indices for both tiers. A fixed linear
  congruential generator makes every interval identical on every machine and Python version.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

Z_TWO_SIDED_95 = 1.959963984540054
Z_ONE_SIDED_95 = 1.6448536269514722

T = TypeVar("T")


def wilson(successes: int, total: int, z: float = Z_TWO_SIDED_95) -> tuple[float, float] | None:
    """Wilson score interval; ``None`` for an empty sample. With ``z = Z_ONE_SIDED_95`` each end is a one-sided 95 % bound."""

    if total <= 0:
        return None
    if not 0 <= successes <= total:
        raise ValueError("successes outside 0..total")
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return round(max(0.0, centre - half), 6), round(min(1.0, centre + half), 6)


@dataclass(frozen=True, slots=True)
class McNemar:
    """``b``: pairs where the second system is right and the first wrong; ``c``: the reverse."""

    b: int
    c: int
    #: P(at least ``b`` of ``b + c`` discordant pairs favour the second system | no difference).
    p_one_sided: float
    p_two_sided: float


def mcnemar(b: int, c: int) -> McNemar:
    """Exact McNemar test. With no discordant pair both p-values are 1."""

    if b < 0 or c < 0:
        raise ValueError("negative count")
    n = b + c
    if n == 0:
        return McNemar(b, c, 1.0, 1.0)
    upper = sum(math.comb(n, k) for k in range(b, n + 1)) / 2**n
    tail = sum(math.comb(n, k) for k in range(0, min(b, c) + 1)) / 2**n
    return McNemar(b, c, round(upper, 9), round(min(1.0, 2 * tail), 9))


def mcnemar_minimum_discordant(alpha: float = 0.05) -> int:
    """The fewest discordant pairs that can reach a one-sided ``p <= alpha`` (all of them in one direction)."""

    n = 1
    while 0.5**n > alpha:
        n += 1
    return n


class Lcg:
    """A fixed 32-bit linear congruential generator (Numerical Recipes constants)."""

    def __init__(self, seed: int) -> None:
        self._state = seed & 0xFFFFFFFF

    def below(self, bound: int) -> int:
        self._state = (self._state * 1664525 + 1013904223) & 0xFFFFFFFF
        return (self._state >> 8) % bound


@dataclass(frozen=True, slots=True)
class Interval:
    point: float | None
    low: float | None
    high: float | None
    #: One-sided 95 % bounds (the 5th and 95th percentiles of the resamples).
    lower_95: float | None
    upper_95: float | None
    defined: int
    resamples: int

    def record(self) -> dict[str, Any]:
        return {
            "point": self.point, "low": self.low, "high": self.high, "lower_95": self.lower_95,
            "upper_95": self.upper_95, "defined_resamples": self.defined, "resamples": self.resamples,
        }  # fmt: skip


def _percentile(sorted_values: Sequence[float], share: float, *, upper: bool) -> float:
    count = len(sorted_values)
    index = math.ceil(share * count) - 1 if upper else math.floor(share * count)
    return round(sorted_values[min(max(index, 0), count - 1)], 6)


def bootstrap(
    strata: Sequence[Sequence[int]],
    statistic: Callable[[Sequence[int]], float | None],
    *,
    resamples: int,
    seed: int,
    confidence: float = 0.95,
) -> Interval:
    """Percentile interval of ``statistic`` over resampled index lists.

    ``strata`` lists the indices of each stratum; each resample draws, with replacement, as many indices from every stratum as
    it holds, and passes the concatenated list to ``statistic`` (which may return ``None`` when undefined on a resample)."""

    full = [index for stratum in strata for index in stratum]
    point = statistic(full)
    rng = Lcg(seed)
    values: list[float] = []
    for _ in range(resamples):
        drawn: list[int] = []
        for stratum in strata:
            size = len(stratum)
            if size == 0:
                continue
            drawn.extend(stratum[rng.below(size)] for _ in range(size))
        value = statistic(drawn)
        if value is not None:
            values.append(value)
    if not values:
        return Interval(point, None, None, None, None, 0, resamples)
    values.sort()
    alpha = 1 - confidence
    return Interval(
        None if point is None else round(point, 6),
        _percentile(values, alpha / 2, upper=False),
        _percentile(values, 1 - alpha / 2, upper=True),
        _percentile(values, alpha, upper=False),
        _percentile(values, 1 - alpha, upper=True),
        len(values),
        resamples,
    )


__all__ = [
    "Interval",
    "Lcg",
    "McNemar",
    "Z_ONE_SIDED_95",
    "Z_TWO_SIDED_95",
    "bootstrap",
    "mcnemar",
    "mcnemar_minimum_discordant",
    "wilson",
]
