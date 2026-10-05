from __future__ import annotations

import tkinter as tk
import weakref
from collections.abc import Callable, Mapping, Sequence

from src.gui.zone_map_v2 import get_root_columns, get_root_rows


def configure_root_grid(root: tk.Tk) -> None:
    """Configure the main grid using the declarative zone map."""
    for row in get_root_rows():
        root.rowconfigure(row["index"], weight=row.get("weight", 0), minsize=row.get("minsize", 0))
    for column in get_root_columns():
        root.columnconfigure(
            column["index"], weight=column.get("weight", 0), minsize=column.get("minsize", 0)
        )


def configure_grid_columns(widget: tk.Misc, column_specs: Sequence[Mapping[str, int]]) -> None:
    """Apply shared grid column sizing rules to a widget."""
    for spec in column_specs:
        widget.columnconfigure(
            int(spec["index"]),
            weight=int(spec.get("weight", 0)),
            minsize=int(spec.get("minsize", 0)),
        )


# Normal minsizes of the grid columns lowered by apply_compact_column_minsizes, per widget, so they can be restored.
_COMPACT_ORIGINAL_MINSIZES: weakref.WeakKeyDictionary[tk.Misc, dict[int, int]] = (
    weakref.WeakKeyDictionary()
)


def apply_compact_column_minsizes(
    root_widget: tk.Misc,
    compact: bool,
    compact_minsize: Callable[[int], int],
) -> int:
    """Reversibly lower (or restore) the grid-column minimums in ``root_widget``'s subtree.

    Responsive reflow without moving, recreating or re-parenting any widget: every grid column that declares a minimum
    is shrunk to ``compact_minsize(original)`` while ``compact`` and restored to its recorded original otherwise, so
    toggling in both directions is lossless and idempotent. Returns the number of columns changed.
    """
    changed = 0
    stack: list[tk.Misc] = [root_widget]
    while stack:
        widget = stack.pop()
        stack.extend(widget.winfo_children())
        try:
            column_count = int(widget.grid_size()[0])
        except (tk.TclError, ValueError):
            continue
        originals = _COMPACT_ORIGINAL_MINSIZES.setdefault(widget, {})
        for index in range(column_count):
            try:
                current = int(widget.columnconfigure(index)["minsize"])
            except (tk.TclError, ValueError, TypeError):
                continue
            if compact:
                original = originals.get(index, current)
                target = int(compact_minsize(original))
                if target == original:
                    continue
                originals[index] = original
                if current != target:
                    widget.columnconfigure(index, minsize=target)
                    changed += 1
            elif index in originals:
                original = originals.pop(index)
                if current != original:
                    widget.columnconfigure(index, minsize=original)
                    changed += 1
    return changed


# Normal wraplengths of the labels capped by apply_compact_label_wraps, per widget, so they can be restored.
_COMPACT_ORIGINAL_WRAPS: weakref.WeakKeyDictionary[tk.Misc, int] = weakref.WeakKeyDictionary()


_MIN_COMPACT_WRAPLENGTH = 60


def apply_compact_label_wraps(root_widget: tk.Misc, compact: bool, wraplength_cap: int) -> int:
    """Reversibly cap (or restore) the wraplength of every label in ``root_widget``'s subtree.

    Only labels whose wrap exceeds ``wraplength_cap`` are touched; their normal wrap is recorded and restored when
    ``compact`` is false. Labels already laid out in a slot narrower than the cap are wrapped to that slot instead, so
    no capped caption is cut off. Returns the number of labels changed.
    """
    changed = 0
    stack: list[tk.Misc] = [root_widget]
    while stack:
        widget = stack.pop()
        stack.extend(widget.winfo_children())
        if widget.winfo_class() not in ("TLabel", "Label"):
            continue
        try:
            current = int(str(widget.cget("wraplength")))
        except (tk.TclError, ValueError):
            continue
        if compact:
            original = _COMPACT_ORIGINAL_WRAPS.get(widget, current)
            if original <= wraplength_cap:
                continue
            _COMPACT_ORIGINAL_WRAPS[widget] = original
            target = wraplength_cap
            slot = widget.winfo_width()
            if 1 < slot < target:
                target = max(slot, _MIN_COMPACT_WRAPLENGTH)
            if current != target:
                widget.configure(wraplength=target)
                changed += 1
        elif widget in _COMPACT_ORIGINAL_WRAPS:
            original = _COMPACT_ORIGINAL_WRAPS.pop(widget)
            if current != original:
                widget.configure(wraplength=original)
                changed += 1
    return changed
