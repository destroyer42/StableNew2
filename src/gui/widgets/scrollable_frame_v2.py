from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui import theme_v2

# Widgets that scroll themselves (or must not be hijacked): the wheel acts on them, not on the page behind.
_SELF_SCROLLING_CLASSES = ("combobox", "listbox", "spinbox", "text", "treeview")
_WHEEL_SEQUENCES = ("<MouseWheel>", "<Button-4>", "<Button-5>")
_FOCUS_SEQUENCE = "<FocusIn>"
_REVEAL_MARGIN = 8  # px of context kept around a control scrolled into view


class _WheelRouter:
    """The single mouse-wheel dispatcher of one Tk interpreter (PR-GUI-100).

    The previous per-frame ``bind_all``/``unbind_all`` on enter/leave let one frame replace or remove another
    frame's global binding and could leave a stale handler behind. Instead every ``ScrollableFrame`` registers here;
    one ``bind_all`` is installed while at least one frame exists and removed (only our own binding) when the last
    frame is destroyed. Each wheel event is routed to the nearest overflowing frame that contains the widget under
    the pointer, so only the region under the pointer scrolls, hidden tabs never receive events, and combobox /
    listbox / spinbox / text / treeview widgets keep their own wheel behavior.

    The same router reveals a control that takes keyboard focus (PR-GUI-400): Tab used to move focus into controls
    scrolled out of view (42 of 76 tab stops on the Pipeline tab), so a keyboard user typed into something invisible.
    ``<FocusIn>`` scrolls every containing frame just enough to show the focused widget.
    """

    _routers: dict[int, _WheelRouter] = {}

    def __init__(self, tk_interp: Any) -> None:
        self._tk = tk_interp
        self._owner: Any = None  # the Tk root: it outlives every frame, so the Tcl commands do too
        self._frames: list[ScrollableFrame] = []
        self._funcids: dict[str, str] = {}

    @classmethod
    def for_widget(cls, widget: tk.Misc) -> _WheelRouter:
        key = id(widget.tk)
        router = cls._routers.get(key)
        if router is None:
            router = cls(widget.tk)
            cls._routers[key] = router
        return router

    @property
    def installed(self) -> bool:
        return bool(self._funcids)

    @property
    def frame_count(self) -> int:
        return len(self._frames)

    def add(self, frame: ScrollableFrame) -> None:
        if frame not in self._frames:
            self._frames.append(frame)
        if not self._funcids:
            self._install(frame)

    def remove(self, frame: ScrollableFrame) -> None:
        if frame in self._frames:
            self._frames.remove(frame)
        if not self._frames:
            self._uninstall()
            self._routers.pop(id(self._tk), None)

    def _install(self, anchor: tk.Misc) -> None:
        self._owner = anchor._root()
        handlers = {
            "<MouseWheel>": self._on_wheel,
            "<Button-4>": self._on_button_wheel,
            "<Button-5>": self._on_button_wheel,
            _FOCUS_SEQUENCE: self._on_focus_in,
        }
        for sequence, handler in handlers.items():
            self._funcids[sequence] = self._owner.bind_all(sequence, handler, add="+")

    def _uninstall(self) -> None:
        """Remove exactly the bindings this router added, leaving any other global binding intact."""
        for sequence, funcid in list(self._funcids.items()):
            try:
                script = str(self._tk.call("bind", "all", sequence))
                kept = "\n".join(line for line in script.split("\n") if funcid not in line)
                self._tk.call("bind", "all", sequence, kept)
                self._tk.deletecommand(funcid)
                owner_commands = getattr(self._owner, "_tclCommands", None)
                if owner_commands and funcid in owner_commands:
                    owner_commands.remove(funcid)  # so Tkinter does not delete it a second time
            except tk.TclError:
                pass
        self._funcids.clear()
        self._owner = None

    # -- routing ------------------------------------------------------------------------------------------------

    def _frames_under_pointer(self, x_root: int, y_root: int) -> list[ScrollableFrame]:
        """Frames containing the widget under the pointer, innermost first (none over self-scrolling widgets)."""
        if not self._frames:
            return []
        try:
            target = self._frames[0].winfo_containing(x_root, y_root)
        except (tk.TclError, KeyError):
            return []
        if target is None:
            return []
        try:
            if any(name in str(target.winfo_class()).lower() for name in _SELF_SCROLLING_CLASSES):
                return []
        except tk.TclError:
            return []
        chain: list[ScrollableFrame] = []
        widget: tk.Misc | None = target
        while widget is not None:
            if isinstance(widget, ScrollableFrame) and widget in self._frames:
                chain.append(widget)
            widget = getattr(widget, "master", None)
        return chain

    def _dispatch(self, event: tk.Event, units: int) -> str | None:
        if not units:
            return None
        for frame in self._frames_under_pointer(event.x_root, event.y_root):
            if frame.has_scroll_overflow():
                frame.scroll_units(units)
                return "break"
        return None

    def _on_wheel(self, event: tk.Event) -> str | None:
        delta = int(getattr(event, "delta", 0) or 0)
        units = int(-1 * (delta / 120)) or (-1 if delta > 0 else (1 if delta < 0 else 0))
        return self._dispatch(event, units)

    def _on_button_wheel(self, event: tk.Event) -> str | None:
        """Linux X11 wheel buttons."""
        return self._dispatch(event, -1 if getattr(event, "num", 0) == 4 else 1)

    def _on_focus_in(self, event: tk.Event) -> None:
        """Scroll every ``ScrollableFrame`` around the focused widget so the widget is visible (never consumes)."""
        widget = getattr(event, "widget", None)
        if not isinstance(widget, tk.Misc):
            return
        node: tk.Misc | None = widget
        while node is not None:
            if isinstance(node, ScrollableFrame) and node in self._frames:
                node.reveal(widget)
            node = getattr(node, "master", None)


class ScrollableFrame(ttk.Frame):
    """Reusable vertically scrollable frame for V2 panels."""

    def __init__(self, master: tk.Misc, *, style: str | None = None, **kwargs) -> None:
        super().__init__(master, style=style, **kwargs)

        self._canvas = tk.Canvas(
            self,
            highlightthickness=0,
            borderwidth=0,
            bg=theme_v2.BACKGROUND_DARK,
        )
        self._canvas.grid(row=0, column=0, sticky="nsew")

        self._vsb = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._vsb.grid(row=0, column=1, sticky="ns")
        self._canvas.configure(yscrollcommand=self._vsb.set)

        self.inner = ttk.Frame(self._canvas, style="Panel.TFrame")
        self._inner_window = self._canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._wheel_router = _WheelRouter.for_widget(self)
        self._wheel_router.add(self)
        self.bind("<Destroy>", self._on_destroy, add="+")

    def _on_inner_configure(self, event: tk.Event) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        canvas_width = event.width
        self._canvas.itemconfigure(self._inner_window, width=canvas_width)

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is self:
            self._wheel_router.remove(self)

    def has_scroll_overflow(self) -> bool:
        """True when content extends beyond the viewport (so the wheel has something to scroll)."""
        try:
            first, last = self._canvas.yview()
        except tk.TclError:
            return False
        return first > 0.0 or last < 1.0

    def viewport_width(self) -> int:
        """Width of the visible region (the content never scrolls horizontally)."""
        return int(self._canvas.winfo_width())

    def scroll_units(self, units: int) -> None:
        self._canvas.yview_scroll(int(units), "units")

    def reveal(self, widget: tk.Misc) -> None:
        """Scroll just enough that ``widget`` (a descendant of ``inner``) is inside the viewport.

        A control taller than the viewport is aligned to its top. Nothing happens when the content fits or the
        widget is not inside this frame.
        """
        try:
            if not self.has_scroll_overflow():
                return
            top = 0
            node: tk.Misc | None = widget
            while node is not None and node is not self.inner:
                top += int(node.winfo_y())
                node = getattr(node, "master", None)
            if node is not self.inner:
                return
            bottom = top + int(widget.winfo_height())
            total = max(int(self.inner.winfo_height()), 1)
            view = int(self._canvas.winfo_height())
            first, _last = self._canvas.yview()
            visible_top = first * total
            visible_bottom = visible_top + view
            if top >= visible_top and bottom <= visible_bottom:
                return
            if top < visible_top or bottom - top > view:
                target = top - _REVEAL_MARGIN
            else:
                target = bottom + _REVEAL_MARGIN - view
            self._canvas.yview_moveto(max(target, 0) / total)
        except tk.TclError:
            return


__all__ = ["ScrollableFrame"]
