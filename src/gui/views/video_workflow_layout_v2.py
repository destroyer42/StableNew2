"""Layout scaffolding for the Video Workflow tab (VID-UX-384).

Presentation only.  Two small widgets and one pure helper:

* ``ViewSwitch`` - the Create | Evaluate segmented control that lives in the fixed header.
* ``TwoPaneLayout`` - a left (scrolling form) and right (scrolling media/status) pane that switches to a
  single stacked column below ``BREAKPOINT_PX``.
* ``media_allowed`` - the one place the tab asks the content-visibility policy whether a path may be
  rendered, so an application "hidden" mode wins over the local Show media preference.

Nothing here reads a workflow record, builds a job or talks to a controller.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from src.controller.content_visibility_resolver import ContentVisibilityResolver
from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame

VIEW_CREATE = "create"
VIEW_EVALUATE = "evaluate"
VIEWS = ((VIEW_CREATE, "Create"), (VIEW_EVALUATE, "Evaluate"))

BREAKPOINT_PX = 1100  # below this width the right pane stacks under the left one
RIGHT_MIN_PX = 360
LEFT_WEIGHT = 3
RIGHT_WEIGHT = 2


def media_allowed(mode: str | None, path: str) -> bool:
    """Whether the application content-visibility policy lets ``path`` be rendered as media."""

    return bool(
        ContentVisibilityResolver(str(mode or "nsfw")).is_visible({"name": str(path or "")})
    )


class ViewSwitch(ttk.Frame):
    """Segmented control (Create | Evaluate by default); the owner decides what each choice shows."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_change: Callable[[str], None],
        initial: str = VIEW_CREATE,
        choices: tuple[tuple[str, str], ...] = VIEWS,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, style="Panel.TFrame", **kwargs)
        self._on_change = on_change
        self.view_var = tk.StringVar(master=self, value=initial)
        self.buttons: dict[str, ttk.Radiobutton] = {}
        for view_id, label in choices:
            button = ttk.Radiobutton(
                self,
                text=label,
                value=view_id,
                variable=self.view_var,
                style="Dark.TRadiobutton",
                command=self._clicked,
            )
            button.pack(side="left", padx=(0, 12))
            self.buttons[view_id] = button

    def _clicked(self) -> None:
        self._on_change(self.view_var.get())

    @property
    def view(self) -> str:
        return self.view_var.get()

    def set_view(self, view_id: str) -> None:
        """Show ``view_id`` as selected without notifying the owner."""

        if view_id in self.buttons:
            self.view_var.set(view_id)


PANE_FORM = "form"
PANE_MEDIA = "media"


class TwoPaneLayout(ttk.Frame):
    """Left (weight 3) and right (weight 2, at least ``RIGHT_MIN_PX``) scrolling panes.

    Below ``breakpoint_px`` the panes do not share the height (two small nested viewports would leave each a few
    lines tall on a small display); one pane shows at a time, each with the full height, chosen by ``show_pane``.
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        breakpoint_px: int = BREAKPOINT_PX,
        on_mode_change: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, style="Panel.TFrame", **kwargs)
        self._breakpoint = breakpoint_px
        self._on_mode_change = on_mode_change
        self.stacked = False
        self.active_pane = PANE_FORM
        self.left_pane = ttk.Frame(self, style="Panel.TFrame")
        self.right_scroll = ScrollableFrame(self, style="Panel.TFrame")
        self.right_scroll.inner.columnconfigure(0, weight=1)
        # Hosts for the owner's widgets: ``left`` takes the form's scroll region, ``right`` the media pane body.
        self.left = self.left_pane
        self.right = ttk.Frame(self.right_scroll.inner, style="Panel.TFrame", padding=(8, 8, 8, 0))
        self.right.grid(row=1, column=0, sticky="nsew")
        self.right.columnconfigure(0, weight=1)
        self.left_pane.columnconfigure(0, weight=1)
        self.left_pane.rowconfigure(0, weight=1)
        self._layout()
        self.bind("<Configure>", self._on_configure, add="+")

    @property
    def media_scroller(self) -> ScrollableFrame:
        return self.right_scroll

    def show_pane(self, pane: str) -> None:
        """Choose the pane shown while stacked (a no-op in two-pane mode, where both show)."""

        if pane not in (PANE_FORM, PANE_MEDIA) or pane == self.active_pane:
            return
        self.active_pane = pane
        self._layout()

    def apply_width(self, width: int) -> bool:
        """Switch between one and two columns for ``width``; returns whether the mode changed."""

        stacked = width > 1 and width < self._breakpoint
        if stacked == self.stacked:
            return False
        self.stacked = stacked
        self._layout()
        return True

    def _on_configure(self, event: Any) -> None:
        if getattr(event, "widget", None) is self:
            self.apply_width(int(event.width))

    def _layout(self) -> None:
        for widget in (self.left_pane, self.right_scroll):
            widget.grid_forget()
        for index in range(2):
            self.columnconfigure(index, weight=0, minsize=0)
            self.rowconfigure(index, weight=0)
        if self.stacked:
            self.columnconfigure(0, weight=1)
            self.rowconfigure(0, weight=1)
            if self.active_pane == PANE_MEDIA:
                self.right_scroll.grid(row=0, column=0, sticky="nsew")
            else:
                self.left_pane.grid(row=0, column=0, sticky="nsew")
        else:
            self.rowconfigure(0, weight=1)
            self.columnconfigure(0, weight=LEFT_WEIGHT)
            self.columnconfigure(1, weight=RIGHT_WEIGHT, minsize=RIGHT_MIN_PX)
            self.left_pane.grid(row=0, column=0, sticky="nsew")
            self.right_scroll.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        if self._on_mode_change is not None:
            self._on_mode_change()


__all__ = [
    "BREAKPOINT_PX",
    "PANE_FORM",
    "PANE_MEDIA",
    "RIGHT_MIN_PX",
    "TwoPaneLayout",
    "VIEWS",
    "VIEW_CREATE",
    "VIEW_EVALUATE",
    "ViewSwitch",
    "media_allowed",
]
