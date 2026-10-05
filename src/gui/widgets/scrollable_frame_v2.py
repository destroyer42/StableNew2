from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui import theme_v2

# Widgets that scroll themselves (or must not be hijacked): the wheel acts on them, not on the page behind.
_SELF_SCROLLING_CLASSES = ("combobox", "listbox", "spinbox", "text", "treeview")
_WHEEL_SEQUENCES = ("<MouseWheel>", "<Button-4>", "<Button-5>")


class _WheelRouter:
    """The single mouse-wheel dispatcher of one Tk interpreter (PR-GUI-100).

    The previous per-frame ``bind_all``/``unbind_all`` on enter/leave let one frame replace or remove another
    frame's global binding and could leave a stale handler behind. Instead every ``ScrollableFrame`` registers here;
    one ``bind_all`` is installed while at least one frame exists and removed (only our own binding) when the last
    frame is destroyed. Each wheel event is routed to the nearest overflowing frame that contains the widget under
    the pointer, so only the region under the pointer scrolls, hidden tabs never receive events, and combobox /
    listbox / spinbox / text / treeview widgets keep their own wheel behavior.
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
        for sequence in _WHEEL_SEQUENCES:
            handler = self._on_wheel if sequence == "<MouseWheel>" else self._on_button_wheel
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


__all__ = ["ScrollableFrame"]
