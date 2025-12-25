"""Helpers for logging when default configuration values are used."""

from __future__ import annotations

import logging
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)


def log_default_value(param_name: str, default_value: Any, source: str = "unknown") -> None:
    """Log when a default value is used instead of user input."""
    logger.warning("[WARN] Using default value for '%s' = %r (source=%s)", param_name, default_value, source)


def get_with_fallback_warning(
    config: dict[str, Any],
    key: str,
    default: Any,
    *,
    source: str = "unknown",
    warn: bool = True
) -> Any:
    """
    Get config value with optional warning when key is missing (true fallback).
    
    This distinguishes between:
    - User explicitly set a value (no warning, even if it matches default)
    - Key missing, falling back to default (warning, indicates potential problem)
    
    Args:
        config: Configuration dictionary
        key: Key to retrieve
        default: Default value if key missing
        source: Source identifier for logging
        warn: Whether to log warning on fallback (default True)
    
    Returns:
        Value from config or default if key missing
    """
    if key not in config:
        if warn:
            log_default_value(key, default, source=source)
        return default
    return config[key]


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
