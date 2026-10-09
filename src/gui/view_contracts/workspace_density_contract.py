"""Pure sizing/disclosure rules for the focused operator workspace (PR-GUI-110). No Tk, no state.

The Tk widgets own *when* these are applied; this module owns the numbers, so they are testable
without a display and identical on every platform.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

# Review preview: never larger than the historical 620 px square, never smaller than a recognisable thumbnail.
PREVIEW_MAX_EDGE = 620
PREVIEW_MIN_EDGE = 200
# Ignore sub-pixel/scrollbar jitter so a settled layout does not re-render the preview.
PREVIEW_RESIZE_TOLERANCE = 4
# Idle-coalescing delay for width-driven updates (preview fit, label wraps).
RESIZE_COALESCE_MS = 60

WRAP_MIN = 160


def preview_side(
    available_width: int, *, max_edge: int = PREVIEW_MAX_EDGE, min_edge: int = PREVIEW_MIN_EDGE
) -> int:
    """Edge of the square preview box for a parent that is ``available_width`` px wide.

    The image is fitted inside this square with its aspect ratio preserved (letterboxed), so the box
    itself only has to be bounded by the parent's real width.
    """

    if available_width <= 1:  # not yet laid out: keep the historical size rather than collapsing
        return max_edge
    return max(min_edge, min(max_edge, int(available_width)))


def preview_resize_needed(
    current_side: int, target_side: int, *, tolerance: int = PREVIEW_RESIZE_TOLERANCE
) -> bool:
    return abs(int(current_side) - int(target_side)) >= max(1, int(tolerance))


def wrap_width(
    container_width: int, *, margin: int = 24, minimum: int = WRAP_MIN, maximum: int | None = None
) -> int:
    """Pixel ``wraplength`` for a label inside a container ``container_width`` px wide."""

    if container_width <= 1:
        return maximum if maximum is not None else max(minimum, 520)
    width = max(minimum, int(container_width) - int(margin))
    return min(width, maximum) if maximum is not None else width


def preview_panel_stacked(body_width: int, *, thumbnail_edge: int, label_min: int, gutter: int = 8) -> bool:
    """True when the Pipeline preview thumbnail must sit under the job info instead of beside it.

    Beside it only while the labels keep ``label_min`` px next to the ``thumbnail_edge`` thumbnail; the caller
    measures ``label_min`` from the real font, so the decision is not a fixed pixel breakpoint.
    """

    if body_width <= 1:  # not laid out yet
        return False
    return int(body_width) < int(thumbnail_edge) + int(gutter) + int(label_min)


def severity_counts(entries: Iterable[Mapping[str, Any]]) -> tuple[int, int]:
    """(warning_count, error_count) over log entries, counting repeats; CRITICAL counts as an error."""

    warnings = errors = 0
    for entry in entries:
        level = str(entry.get("level", "")).upper()
        if level not in ("WARNING", "ERROR", "CRITICAL"):
            continue
        try:
            repeats = max(1, int(entry.get("repeat_count", 1) or 1))
        except (TypeError, ValueError):
            repeats = 1
        if level == "WARNING":
            warnings += repeats
        else:
            errors += repeats
    return warnings, errors


def severity_summary(warnings: int, errors: int) -> str:
    """Compact, truthful header text; empty when there is nothing to report."""

    parts: list[str] = []
    if errors:
        parts.append(f"{errors} error{'s' if errors != 1 else ''}")
    if warnings:
        parts.append(f"{warnings} warning{'s' if warnings != 1 else ''}")
    return " | ".join(parts)


def changed_value_count(current: Mapping[str, Any], defaults: Mapping[str, Any]) -> int:
    """Number of keys whose normalised current value differs from its default (missing default == empty)."""

    changed = 0
    for key, value in current.items():
        if _normalise(value) != _normalise(defaults.get(key, "")):
            changed += 1
    return changed


def _normalise(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    try:
        return repr(float(text))  # "1" == "1.0" == "1.00"
    except ValueError:
        return text


def disclosure_title(title: str, *, expanded: bool, status: str = "") -> str:
    """Header caption for a collapsible section: arrow, title and optional status (shown while collapsed)."""

    arrow = "▾" if expanded else "▸"
    suffix = f"  — {status}" if status and not expanded else ""
    return f"{arrow} {title}{suffix}"


__all__ = [
    "PREVIEW_MAX_EDGE",
    "PREVIEW_MIN_EDGE",
    "PREVIEW_RESIZE_TOLERANCE",
    "RESIZE_COALESCE_MS",
    "WRAP_MIN",
    "changed_value_count",
    "disclosure_title",
    "preview_panel_stacked",
    "preview_resize_needed",
    "preview_side",
    "severity_counts",
    "severity_summary",
    "wrap_width",
]
