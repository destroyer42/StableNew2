"""Helper utilities for global negative prompt merging."""

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
