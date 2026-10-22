"""Task-first navigation bar for the main window (PR-GUI-410).

One compact row: the task groups (Create, Edit, Motion, Learn, Advanced), a divider, then the destinations of the
active group. It is a view over the contract in ``src.gui.view_contracts.task_navigation_contract`` and owns no
selection state of its own: choosing a destination calls ``on_select(tab_id)`` and the caller drives the single
``ttk.Notebook``; ``show_selected`` only mirrors the notebook's current tab back into the highlight and never calls
``on_select``, so a ``<<NotebookTabChanged>>`` -> ``show_selected`` round trip cannot cycle.

Every control is a ``ttk.Radiobutton`` (focusable, Space activates, Left/Right move within the row), so mouse and
keyboard reach every workspace without the notebook's own tab strip.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from functools import partial
from tkinter import ttk
from typing import Any

from src.gui import theme_v2 as theme
from src.gui.view_contracts.task_navigation_contract import (
    TASK_GROUPS,
    NavDestination,
    default_tab_for_group,
    get_destination,
    get_group,
)

GROUP_STYLE = "TaskNavGroup.Toolbutton"
DESTINATION_STYLE = "TaskNavDestination.Toolbutton"
HOLD_STYLE = "TaskNavHold.Toolbutton"
HIDDEN_TABS_NOTEBOOK_STYLE = "TaskNavHiddenTabs.TNotebook"


def configure_task_navigation_styles(style: ttk.Style) -> None:
    """Define the bar's styles from the shared theme constants (no new tokens)."""

    base: dict[str, Any] = {
        "padding": (14, 5),
        "borderwidth": 1,
        "relief": "flat",
        "focusthickness": 2,
    }
    style.configure(
        GROUP_STYLE,
        background=theme.BACKGROUND_ELEVATED,
        foreground=theme.TEXT_PRIMARY,
        **base,
    )
    style.map(
        GROUP_STYLE,
        background=[
            ("selected", theme.ACCENT_GOLD),
            ("active", theme.ASWF_MED_GREY),
        ],
        foreground=[("selected", theme.BACKGROUND_DARK)],
    )
    style.configure(
        DESTINATION_STYLE,
        background=theme.BACKGROUND_DARK,
        foreground=theme.TEXT_MUTED,
        **base,
    )
    style.map(
        DESTINATION_STYLE,
        background=[("selected", theme.BACKGROUND_ELEVATED), ("active", theme.ASWF_MED_GREY)],
        foreground=[
            ("disabled", theme.TEXT_DISABLED),
            ("selected", theme.ACCENT_GOLD),
            ("active", theme.TEXT_PRIMARY),
        ],
    )
    style.configure(
        HOLD_STYLE,
        background=theme.BACKGROUND_DARK,
        foreground=theme.HIGHLIGHT_WARNING,
        **base,
    )
    style.map(
        HOLD_STYLE,
        background=[("selected", theme.BACKGROUND_ELEVATED), ("active", theme.ASWF_MED_GREY)],
        foreground=[("disabled", theme.TEXT_DISABLED)],
    )


def hide_notebook_tab_strip(notebook: ttk.Notebook) -> bool:
    """Hide a notebook's native tab strip; the tabs themselves (``add``/``select``/``tab``) are untouched.

    Returns False and leaves the native strip visible when the theme refuses the empty tab layout, which is the
    documented fallback: navigation then shows both the bar and the notebook's own tabs rather than losing either.
    """

    try:
        style = ttk.Style(notebook)
        style.layout(f"{HIDDEN_TABS_NOTEBOOK_STYLE}.Tab", [])
        notebook.configure(style=HIDDEN_TABS_NOTEBOOK_STYLE)
    except tk.TclError:
        return False
    return True


class TaskNavigationBar(ttk.Frame):
    """Group buttons plus the active group's destination buttons."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_select: Callable[[str], None],
        is_available: Callable[[str], bool],
        **kwargs: object,
    ) -> None:
        super().__init__(master, **kwargs)  # type: ignore[arg-type]
        self._on_select = on_select
        self._is_available = is_available
        self._active_group_id = TASK_GROUPS[0].group_id
        self._selected_tab_id = ""
        self._last_tab_in_group: dict[str, str] = {}
        self._group_var = tk.StringVar(master=self, value=self._active_group_id)
        self._destination_var = tk.StringVar(master=self, value="")
        self._group_buttons: dict[str, ttk.Radiobutton] = {}
        self._destination_buttons: dict[str, ttk.Radiobutton] = {}

        configure_task_navigation_styles(ttk.Style(self))
        self._build()
        self.refresh_availability()
        self._show_group_destinations(self._active_group_id)

    def _build(self) -> None:
        groups = ttk.Frame(self)
        groups.pack(side=tk.LEFT, padx=(8, 0), pady=4)
        for group in TASK_GROUPS:
            button = ttk.Radiobutton(
                groups,
                text=group.label,
                value=group.group_id,
                variable=self._group_var,
                style=GROUP_STYLE,
                command=partial(self._on_group_chosen, group.group_id),
            )
            button.pack(side=tk.LEFT, padx=(0, 2))
            self._group_buttons[group.group_id] = button
        self._bind_arrow_keys(list(self._group_buttons.values()))

        self._divider = ttk.Separator(self, orient=tk.VERTICAL)
        self._divider.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=6)

        self._destinations_frame = ttk.Frame(self)
        self._destinations_frame.pack(side=tk.LEFT, pady=4)
        for group in TASK_GROUPS:
            for destination in group.destinations:
                self._destination_buttons[destination.tab_id] = self._make_destination_button(
                    destination
                )
            self._bind_arrow_keys([self._destination_buttons[tab_id] for tab_id in group.tab_ids])

    def _make_destination_button(self, destination: NavDestination) -> ttk.Radiobutton:
        return ttk.Radiobutton(
            self._destinations_frame,
            text=destination.display_label,
            value=destination.tab_id,
            variable=self._destination_var,
            style=HOLD_STYLE if destination.hold else DESTINATION_STYLE,
            command=partial(self._on_destination_chosen, destination.tab_id),
        )

    def _bind_arrow_keys(self, buttons: list[ttk.Radiobutton]) -> None:
        for button in buttons:
            button.bind("<Left>", partial(self._step_focus, row=buttons, step=-1))
            button.bind("<Right>", partial(self._step_focus, row=buttons, step=1))

    def _step_focus(self, event: tk.Event, *, row: list[ttk.Radiobutton], step: int) -> str:
        """Move focus and activate the neighbouring enabled button in a row (wraps)."""

        visible = [button for button in row if button.winfo_manager() and self._enabled(button)]
        if event.widget in visible and len(visible) > 1:
            target = visible[(visible.index(event.widget) + step) % len(visible)]
            target.focus_set()
            target.invoke()
        return "break"

    @staticmethod
    def _enabled(button: ttk.Radiobutton) -> bool:
        return not button.instate(["disabled"])

    # -- choices made by the operator -------------------------------------------------------------------------------

    def _on_group_chosen(self, group_id: str) -> None:
        available = {tab_id for tab_id in self._destination_buttons if self._is_available(tab_id)}
        remembered = self._last_tab_in_group.get(group_id)
        target = (
            remembered if remembered in available else default_tab_for_group(group_id, available)
        )
        if target is None:
            # nothing in this group can open; keep the highlight on the group that is really shown
            self._sync_group_variable()
            return
        self._on_select(target)

    def _on_destination_chosen(self, tab_id: str) -> None:
        self._on_select(tab_id)

    # -- mirroring the notebook ---------------------------------------------------------------------------------------

    def show_selected(self, tab_id: str) -> None:
        """Highlight ``tab_id`` (the notebook's current tab). Never calls ``on_select``."""

        destination = get_destination(tab_id)
        if destination is None:
            return
        self._selected_tab_id = tab_id
        self._last_tab_in_group[destination.group_id] = tab_id
        self._active_group_id = destination.group_id
        self._group_var.set(destination.group_id)
        self._show_group_destinations(destination.group_id)
        self._destination_var.set(tab_id)

    def refresh_availability(self) -> None:
        """Disable destinations whose tab is not in the notebook (it failed to build or to be added)."""

        for tab_id, button in self._destination_buttons.items():
            state = "!disabled" if self._is_available(tab_id) else "disabled"
            button.state([state])
        for group in TASK_GROUPS:
            usable = any(self._is_available(tab_id) for tab_id in group.tab_ids)
            self._group_buttons[group.group_id].state(["!disabled" if usable else "disabled"])

    def _show_group_destinations(self, group_id: str) -> None:
        group = get_group(group_id)
        group_tab_ids = set(group.tab_ids) if group is not None else set()
        for tab_id, button in self._destination_buttons.items():
            if tab_id in group_tab_ids:
                if not button.winfo_manager():
                    button.pack(side=tk.LEFT, padx=(0, 2))
            elif button.winfo_manager():
                button.pack_forget()

    def _sync_group_variable(self) -> None:
        self._group_var.set(self._active_group_id)

    # -- introspection for tests and the shell -------------------------------------------------------------------------

    @property
    def selected_tab_id(self) -> str:
        return self._selected_tab_id

    @property
    def active_group_id(self) -> str:
        return self._active_group_id

    def group_button(self, group_id: str) -> ttk.Radiobutton:
        return self._group_buttons[group_id]

    def destination_button(self, tab_id: str) -> ttk.Radiobutton:
        return self._destination_buttons[tab_id]

    def visible_destination_ids(self) -> list[str]:
        return [
            tab_id for tab_id, button in self._destination_buttons.items() if button.winfo_manager()
        ]


__all__ = [
    "DESTINATION_STYLE",
    "GROUP_STYLE",
    "HIDDEN_TABS_NOTEBOOK_STYLE",
    "HOLD_STYLE",
    "TaskNavigationBar",
    "configure_task_navigation_styles",
    "hide_notebook_tab_strip",
]
