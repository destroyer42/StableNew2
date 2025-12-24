"""Helpers for logging when default configuration values are used."""

from __future__ import annotations

import logging
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)


def log_default_value(param_name: str, default_value: Any, source: str = "unknown") -> None:
    """Log when a default value is used instead of user input."""
    logger.warning("[WARN] Using default value for '%s' = %r (source=%s)", param_name, default_value, source)


def track_defaults(param_map: dict[str, Any]) -> Callable[[Callable[..., dict[str, Any]]], Callable[..., dict[str, Any]]]:
    """Decorator to log when returned config values equal known defaults."""

    def decorator(func: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            result = func(*args, **kwargs)
            for param, default in param_map.items():
                try:
                    if result.get(param) == default:
                        log_default_value(param, default, source=func.__name__)
                except Exception:
                    continue
            return result

        return wrapper

    return decorator
