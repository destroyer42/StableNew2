"""Exact small-sample statistics with no third-party dependency. Pure."""

from __future__ import annotations

import math


def _binom_tail_ge(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""

    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))


def clopper_pearson_lower(k: int, n: int, alpha: float = 0.05) -> float:
    """One-sided exact lower confidence bound for a proportion: the p at which P(X >= k) = alpha."""

    if not 0 <= k <= n or n <= 0:
        raise ValueError("need 0 <= k <= n and n > 0")
    if k == 0:
        return 0.0
    low, high = 0.0, 1.0
    for _ in range(80):
        mid = (low + high) / 2
        if _binom_tail_ge(k, n, mid) < alpha:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 1.0)
    phat = k / n
    denominator = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denominator
    margin = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denominator
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def sign_test_two_sided(wins: int, losses: int) -> float:
    """Exact two-sided sign test p-value; ties are removed by the caller."""

    n = wins + losses
    if n == 0:
        return 1.0
    extreme = max(wins, losses)
    return min(1.0, 2 * _binom_tail_ge(extreme, n, 0.5))


def preference_summary(
    wins: int, losses: int, ties: int, alpha: float = 0.05
) -> dict[str, float | int]:
    """Win rate among decided pairs with its one-sided exact lower bound and the two-sided sign-test p-value."""

    decided = wins + losses
    return {
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "judged_pairs": decided + ties,
        "decided": decided,
        "win_rate": (wins / decided) if decided else 0.0,
        "win_rate_lower95": clopper_pearson_lower(wins, decided, alpha) if decided else 0.0,
        "sign_test_p": sign_test_two_sided(wins, losses),
    }


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    return (
        float(ordered[middle]) if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    )


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return float(ordered[index])


__all__ = [
    "clopper_pearson_lower",
    "median",
    "percentile",
    "preference_summary",
    "sign_test_two_sided",
    "wilson_interval",
]
