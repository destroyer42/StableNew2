"""One admission check for every retired execution (AnimateDiff, secondary motion).

Each retirement keeps its own predicate, error and message in its own module; this is the single call a submission
boundary makes, so adding a retirement does not grow the boundary (the controller line ceilings are ratcheted).
"""

from __future__ import annotations

from typing import Any

from src.pipeline.animatediff_retirement import require_animatediff_not_enabled
from src.pipeline.secondary_motion_retirement import require_secondary_motion_not_enabled


def require_no_retired_execution(njr: Any) -> None:
    """Raise the typed retirement error when the NJR would execute any retired feature."""

    require_animatediff_not_enabled(njr)
    require_secondary_motion_not_enabled(njr)


__all__ = ["require_no_retired_execution"]
