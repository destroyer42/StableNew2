"""Selection list contract for deterministic list + selection behavior."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SelectionListState:
    items: tuple[str, ...]
    selected_indices: tuple[int, ...]
    selected_count: int


def update_selection_list(items: list[str], selected_indices: list[int] | tuple[int, ...]) -> SelectionListState:
    normalized_items = tuple(str(item) for item in (items or []))
    valid = tuple(
        idx for idx in (int(i) for i in (selected_indices or [])) if 0 <= idx < len(normalized_items)
    )
    return SelectionListState(
        items=normalized_items,
        selected_indices=valid,
        selected_count=len(valid),
    )
