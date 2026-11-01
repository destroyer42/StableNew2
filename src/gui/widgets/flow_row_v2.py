"""Wrapping row of controls (GUI-COMPLETE-760). Presentation only; it owns no value, command or state.

A single ``pack(side="left")`` row silently drops every control that does not fit the width its column was given
(Tk leaves the overflow unmapped), so an action bar or option row becomes unreachable on a narrow column. ``FlowRow``
lays the same children out with ``place`` on as many rows as the width it was actually given requires, and gives
itself the resulting height. Children keep their identity, variables, bindings and commands; re-flowing only moves
them, so it is fully reversible (narrow -> wide -> narrow returns to the same rows).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.view_contracts.photo_optimize_layout_contract import flow_rows
from src.gui.view_contracts.workspace_density_contract import RESIZE_COALESCE_MS

FLOW_GAP = 4
FLOW_ROW_GAP = 4


class FlowRow(ttk.Frame):
    """Children created with ``master=flow_row`` and registered with :meth:`add`, wrapped to the available width."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        gap: int = FLOW_GAP,
        row_gap: int = FLOW_ROW_GAP,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self._gap = int(gap)
        self._row_gap = int(row_gap)
        self._items: list[tk.Misc] = []
        self._hidden: set[str] = set()
        self._signature: tuple[Any, ...] | None = None
        self._rows: list[list[tk.Misc]] = []
        self._job: str | None = None
        self.bind("<Configure>", self._on_self_configure, add="+")
        self.bind("<Destroy>", self._on_destroy, add="+")

    # -- public API -------------------------------------------------------------------------------------------------

    def add(self, widget: tk.Misc, *, shown: bool = True) -> tk.Misc:
        """Append ``widget`` (a child of this row) to the flow order."""

        if widget not in self._items:
            self._items.append(widget)
            widget.bind("<Configure>", self._schedule, add="+")
        if shown:
            self._hidden.discard(str(widget))
        else:
            self._hidden.add(str(widget))
        self._signature = None
        self._schedule()
        return widget

    def set_shown(self, widget: tk.Misc, shown: bool) -> None:
        """Show or hide one child without disturbing the order of the others."""

        key = str(widget)
        if shown and key in self._hidden:
            self._hidden.discard(key)
        elif not shown and key not in self._hidden:
            self._hidden.add(key)
        else:
            return
        self._signature = None
        self._schedule()

    def rows(self) -> list[list[tk.Misc]]:
        """The rows laid out by the last reflow (shown children only, in order)."""

        return [list(row) for row in self._rows]

    def reflow(self) -> None:
        """Re-lay out now; a no-op when neither the rows nor any child's size changed."""

        self._cancel_pending()
        try:
            if not self.winfo_exists():
                return
            self._items = [item for item in self._items if item.winfo_exists()]
            shown = [item for item in self._items if str(item) not in self._hidden]
            for item in self._items:
                if str(item) in self._hidden:
                    item.place_forget()
            widths = [item.winfo_reqwidth() for item in shown]
            heights = [item.winfo_reqheight() for item in shown]
            index_rows = flow_rows(widths, self.winfo_width(), gap=self._gap)
            signature = (
                tuple(tuple(row) for row in index_rows),
                tuple(widths),
                tuple(heights),
                tuple(str(item) for item in shown),
            )
            if signature == self._signature:
                return
            self._signature = signature
            self._rows = [[shown[index] for index in row] for row in index_rows]
            y = 0
            for row in index_rows:
                x = 0
                row_height = max(heights[index] for index in row)
                for index in row:
                    shown[index].place(x=x, y=y)
                    x += widths[index] + self._gap
                y += row_height + self._row_gap
            self.configure(height=max(1, y - self._row_gap))
        except tk.TclError:
            return

    # -- internals --------------------------------------------------------------------------------------------------

    def _cancel_pending(self) -> None:
        if self._job is None:
            return
        job, self._job = self._job, None
        try:
            self.after_cancel(job)
        except tk.TclError:
            pass

    def _on_self_configure(self, _event: tk.Event) -> None:
        """A width change re-flows at once, so a caller that resizes this row and measures right after
        ``update_idletasks`` (the fit-driven Pipeline layout) sees the wrapped result, not the stale one."""

        self.reflow()

    def _schedule(self, _event: tk.Event | None = None) -> None:
        if self._job is not None:
            return
        try:
            self._job = self.after(RESIZE_COALESCE_MS, self.reflow)
        except tk.TclError:
            self._job = None

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is self:
            self._cancel_pending()


__all__ = ["FlowRow"]
