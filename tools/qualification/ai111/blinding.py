"""Blind side-by-side pairing for the operator's preference ratings. Pure.

The operator sees only ``left`` and ``right`` text; which arm is which lives in a separate manifest that is joined after the
ratings are collected. Left/right order is randomised per pair from a seed, so position carries no information.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping
from typing import Any

from tools.qualification.ai111.stats import preference_summary


def make_pairs(case_ids: Iterable[str], arm_a: str, arm_b: str, seed: int) -> list[dict[str, str]]:
    rng = random.Random(f"{seed}:{arm_a}:{arm_b}")
    pairs = []
    for number, case_id in enumerate(sorted(case_ids), start=1):
        flipped = rng.random() < 0.5
        left, right = (arm_b, arm_a) if flipped else (arm_a, arm_b)
        pairs.append(
            {"pair_id": f"p{number:04d}", "case_id": case_id, "left": left, "right": right}
        )
    return pairs


def blinded_view(
    pairs: list[dict[str, str]], texts: Mapping[tuple[str, str], str]
) -> list[dict[str, str]]:
    """What the operator is shown: no arm names. ``texts`` maps (case_id, arm) to the candidate text."""

    return [
        {
            "pair_id": pair["pair_id"],
            "left": texts[(pair["case_id"], pair["left"])],
            "right": texts[(pair["case_id"], pair["right"])],
        }
        for pair in pairs
    ]


def unblind(
    pairs: list[dict[str, str]], ratings: Mapping[str, str], candidate: str, baseline: str
) -> dict[str, Any]:
    """Join ratings (``left``/``right``/``tie`` per pair id) with the manifest: wins are for ``candidate`` over ``baseline``."""

    wins = losses = ties = 0
    for pair in pairs:
        choice = ratings.get(pair["pair_id"])
        if choice is None:
            continue
        if choice == "tie":
            ties += 1
        elif choice in ("left", "right"):
            winner = pair[choice]
            if winner == candidate:
                wins += 1
            elif winner == baseline:
                losses += 1
        else:
            raise ValueError(f"unknown rating {choice!r} for {pair['pair_id']}")
    return preference_summary(wins, losses, ties)


__all__ = ["blinded_view", "make_pairs", "unblind"]
