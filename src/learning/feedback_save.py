"""Post-append projections cannot change the authoritative feedback save outcome."""

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def refresh_saved_feedback(refresh: Callable[[], Any]) -> str:
    try:
        refresh()
    except Exception as exc:
        logger.exception("Feedback is saved, but its derived projection could not refresh")
        return str(exc)
    return ""
