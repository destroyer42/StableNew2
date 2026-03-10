"""Toolkit-agnostic layout contracts for Pipeline tab behavior."""

from __future__ import annotations


def normalize_window_geometry(current_geometry: str, min_width: int) -> str | None:
    """Return updated geometry string if width is below minimum, else None."""
    text = str(current_geometry or "")
    if "x" not in text:
        return None
    width_str, rest = text.split("x", 1)
    try:
        width = int(width_str)
        required = max(0, int(min_width))
    except Exception:
        return None
    if width >= required:
        return None
    parts = rest.split("+")
    height = parts[0]
    if not height:
        return None
    if len(parts) >= 3 and parts[1] and parts[2]:
        return f"{required}x{height}+{parts[1]}+{parts[2]}"
    return f"{required}x{height}"


def get_visible_stage_order(stage_order: list[str], enabled_stages: list[str]) -> tuple[str, ...]:
    ordered = [str(name) for name in (stage_order or [])]
    enabled = {str(name) for name in (enabled_stages or [])}
    return tuple(name for name in ordered if name in enabled)


__all__ = ["normalize_window_geometry", "get_visible_stage_order"]
