from __future__ import annotations

import tkinter as tk
from collections.abc import Mapping, Sequence

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
