"""Helper utilities for global prompt merging."""

from __future__ import annotations


def merge_global_negative(
    base_negative: str | None,
    global_terms: str | None,
) -> tuple[str, str, bool, str]:
    """Return (original, final, applied, global_terms) for negatives."""
    base = (base_negative or "").strip()
    global_clean = (global_terms or "").strip()
    if not global_clean:
        return base, base, False, ""
    final = f"{base}, {global_clean}" if base else global_clean
    return base, final, True, global_clean


def merge_global_positive(
    base_positive: str | None,
    global_terms: str | None,
) -> tuple[str, str, bool, str]:
    """Return (original, final, applied, global_terms) for positives."""
    base = (base_positive or "").strip()
    global_clean = (global_terms or "").strip()
    if not global_clean:
        return base, base, False, ""
    # Prepend global positive to the beginning (quality/style terms first)
    final = f"{global_clean}, {base}" if base else global_clean
    return base, final, True, global_clean
