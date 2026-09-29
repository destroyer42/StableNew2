"""Neutral, spec-declared generation-length contract (PR-VID-190).

A workflow opts into an operator-selectable frame count by declaring both a ``frame_count`` input
binding and ``backend_defaults["frame_count_policy"]``::

    {"default": 49, "minimum": 17, "maximum": 81, "step": 4, "offset": 1, "fps": 24}

A length ``n`` is legal when ``minimum <= n <= maximum`` and ``(n - offset) % step == 0`` (for Wan's
VAE that is the ``4n+1`` rule).  Illegal values are rejected, never rounded.  Nothing here branches
on a workflow or model name, and FPS is reported, not chosen.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

FRAME_COUNT_INPUT = "frame_count"


def frame_count_policy(spec: Any) -> dict[str, int] | None:
    """The declared policy, or None when the workflow does not accept a frame count."""

    if FRAME_COUNT_INPUT not in tuple(getattr(spec, "declared_input_names", ()) or ()):
        return None
    raw = (getattr(spec, "backend_defaults", None) or {}).get("frame_count_policy")
    if not isinstance(raw, Mapping):
        return None
    try:
        policy = {
            key: int(raw[key]) for key in ("default", "minimum", "maximum", "step", "offset", "fps")
        }
    except (KeyError, TypeError, ValueError):
        return None
    if policy["step"] < 1 or policy["fps"] < 1 or policy["minimum"] > policy["maximum"]:
        return None
    return policy


def legal_frame_counts(spec: Any) -> list[int]:
    policy = frame_count_policy(spec)
    if policy is None:
        return []
    return [
        count
        for count in range(policy["minimum"], policy["maximum"] + 1)
        if (count - policy["offset"]) % policy["step"] == 0
    ]


def approximate_seconds(frame_count: int, fps: int) -> float:
    return round(frame_count / fps, 1) if fps else 0.0


def frame_count_projection(spec: Any) -> dict[str, Any] | None:
    """What an operator form needs: the default, the legal choices and their durations."""

    policy = frame_count_policy(spec)
    if policy is None:
        return None
    return {
        "default": policy["default"],
        "fps": policy["fps"],
        "choices": [
            {"frames": count, "seconds": approximate_seconds(count, policy["fps"])}
            for count in legal_frame_counts(spec)
        ],
    }


def parse_frame_count(spec: Any, value: Any) -> int:
    """Validate an operator frame count against the spec; empty means the declared default."""

    policy = frame_count_policy(spec)
    name = getattr(spec, "display_name", None) or getattr(spec, "workflow_id", "workflow")
    if policy is None:
        raise ValueError(f"'{name}' does not accept a frame count.")
    text = str(value if value is not None else "").strip()
    if not text:
        return policy["default"]
    try:
        count = int(text)
    except (TypeError, ValueError) as exc:
        raise ValueError("Frame count must be a whole number of frames.") from exc
    legal = legal_frame_counts(spec)
    if count not in legal:
        examples = ", ".join(str(item) for item in legal[:4])
        raise ValueError(
            f"'{name}' cannot generate {count} frames. Choose a length from "
            f"{policy['minimum']} to {policy['maximum']} that is {policy['offset']} more than a "
            f"multiple of {policy['step']} (for example {examples}, ... {legal[-1]})."
        )
    return count


__all__ = [
    "FRAME_COUNT_INPUT",
    "approximate_seconds",
    "frame_count_policy",
    "frame_count_projection",
    "legal_frame_counts",
    "parse_frame_count",
]
