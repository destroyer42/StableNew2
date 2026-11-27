"""One resolver for the Comfy Kitchen attention launch profile a workflow declares.

The profile comes from the immutable workflow identity (id and version), never from a mutable setting, so a job frozen at
an earlier version replays with the launch it was admitted with.  ``None`` means the workflow declares no profile.
"""

from __future__ import annotations

from typing import Any

from src.video.workflow_catalog_wan_a14b import a14b_launch_attention
from src.video.workflow_catalog_wan_animate2 import animate2_launch_attention


def launch_attention(spec: Any) -> str | None:
    """``"baseline"`` or ``"ck"`` for A14B and ``"ck"`` for Animate 1.3.0; ``None`` for everything else."""

    return a14b_launch_attention(spec) or animate2_launch_attention(spec)


__all__ = ["launch_attention"]
