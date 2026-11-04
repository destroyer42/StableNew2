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
_WHEEL_STEP_MIN_PX = 40  # one wheel notch never moves less than this, however short the viewport
# An unused grid column and a row span covering every row carry the stretch-to-viewport ruler (``fill_height``).
_RULER_COLUMN = 999
_RULER_ROWSPAN = 999


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
        # Innermost first; a frame already at its limit in this direction hands the wheel to the page around it
        # instead of trapping it (a nested scroll box at its end must not freeze the page behind it).
        for frame in self._frames_under_pointer(event.x_root, event.y_root):
            if frame.can_scroll(units):
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

    @staticmethod
    def _pointer_over(widget: tk.Misc) -> bool:
        """Whether the pointer is on ``widget`` or one of its descendants (so the person can already see it)."""
        try:
            x, y = widget.winfo_pointerxy()
            target = widget.winfo_containing(x, y)
        except (tk.TclError, KeyError):
            return False
        while target is not None:
            if target is widget:
                return True
            target = getattr(target, "master", None)
        return False

    def _on_focus_in(self, event: tk.Event) -> None:
        """Scroll every ``ScrollableFrame`` around the focused widget so the widget is visible (never consumes).

        A control the pointer is already on is visible by definition, and focus gained from a mouse press must not
        scroll the page: the control would move between button press and release and the click would land on
        whatever scrolled under the pointer (PR-GUI-RELIABILITY-831).  Only focus that arrives elsewhere (Tab,
        programmatic focus) reveals the control.
        """
        widget = getattr(event, "widget", None)
        if not isinstance(widget, tk.Misc):
            return
        if self._pointer_over(widget):
            return
        node: tk.Misc | None = widget
        while node is not None:
            if isinstance(node, ScrollableFrame) and node in self._frames:
                node.reveal(widget)
            node = getattr(node, "master", None)


class ScrollableFrame(ttk.Frame):
    """Reusable vertically scrollable frame for V2 panels.

    ``fill_height`` is for content laid out with ``grid`` inside ``inner``: sections keep their natural height and
    the page scrolls when the viewport is shorter, but when the viewport is taller the weighted rows stretch to use
    it, as they would in a plain frame.  (A plain frame squeezes weighted rows to nothing instead of scrolling; a
    plain ``ScrollableFrame`` never stretches.)  It works by giving ``inner`` a minimum height equal to the
    viewport through a zero-width ruler spanning every row, so the canvas still sees a normal requested size.
    """

    def __init__(
        self, master: tk.Misc, *, style: str | None = None, fill_height: bool = False, **kwargs
    ) -> None:
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
        self._ruler: tk.Frame | None = None
        if fill_height:
            self._ruler = tk.Frame(
                self.inner, width=0, height=1, borderwidth=0, highlightthickness=0
            )
            self._ruler.grid(row=0, column=_RULER_COLUMN, rowspan=_RULER_ROWSPAN, sticky="ns")

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
        if self._ruler is not None:
            self._ruler.configure(height=max(1, int(event.height)))

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

    def can_scroll(self, units: int) -> bool:
        """True when scrolling ``units`` (negative is up) would move the content."""
        try:
            first, last = self._canvas.yview()
        except tk.TclError:
            return False
        return first > 0.0 if units < 0 else last < 1.0

    def viewport_width(self) -> int:
        """Width of the visible region (the content never scrolls horizontally)."""
        return int(self._canvas.winfo_width())

    def scroll_units(self, units: int) -> None:
        """Scroll ``units`` wheel notches (negative is up).

        A notch moves a tenth of the viewport but at least ``_WHEEL_STEP_MIN_PX``: Tk's own unit is a tenth of the
        window, which in a short pane is a few pixels and takes dozens of notches to cross the page.
        """
        try:
            total = self._canvas.bbox("all")
            view = int(self._canvas.winfo_height())
            if not total or int(total[3]) - int(total[1]) <= 0:
                return
            span = int(total[3]) - int(total[1])
            step = max(_WHEEL_STEP_MIN_PX, view // 10)
            first, _last = self._canvas.yview()
            target = min(max(first + int(units) * step / span, 0.0), 1.0)
            self._canvas.yview_moveto(target)
        except tk.TclError:
            return

    def reveal(self, widget: tk.Misc) -> None:
        """Scroll just enough that ``widget`` (a descendant of ``inner``) is inside the viewport.

        A control taller than the viewport is aligned to its top. Nothing happens when the content fits or the
        widget is not inside this frame.
        """
        try:
            # Preview/toolbar reflow can still be queued when focus requests a reveal.
            # Measure only after Tk has committed the current child sizes and scroll region.
            self.update_idletasks()
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
            margin = min(_REVEAL_MARGIN, max(0, (view - (bottom - top)) // 2))
            if top < visible_top or bottom - top > view:
                target = top - margin
            else:
                target = bottom + margin - view
            self._canvas.yview_moveto(max(target, 0) / total)
        except tk.TclError:
            return


__all__ = ["ScrollableFrame"]
