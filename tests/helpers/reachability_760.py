"""Real-Tk reachability probe for GUI-COMPLETE-760.

Measures, on live widgets, whether every actionable control that is logically shown can be brought fully inside every
clipping ancestor (scroll viewports, fixed panes, the window client area) by the same paths the application gives an
operator: the ``ScrollableFrame`` reveal that the shared focus handler uses, and keyboard focus. Geometry only: it never
invokes a control, so layout qualification cannot submit work or touch a backend.
"""

from __future__ import annotations

import time
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import ttk

from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame

ACTIONABLE_CLASSES = frozenset(
    {
        "Button",
        "TButton",
        "Checkbutton",
        "TCheckbutton",
        "Radiobutton",
        "TRadiobutton",
        "Entry",
        "TEntry",
        "TCombobox",
        "Spinbox",
        "TSpinbox",
        "Text",
        "Listbox",
        "Treeview",
        "Scale",
        "TScale",
        "TMenubutton",
        "Menubutton",
    }
)
TOLERANCE_PX = 1
SETTLE_SECONDS = 0.3  # a newly selected page reflows its wrapping rows after the coalescing delay
MIN_VISIBLE_FRACTION = 0.5
HIDDEN_RECHECK_SECONDS = 2.0  # a control still unmapped after this long is genuinely hidden


@dataclass(frozen=True)
class Finding:
    kind: str  # clipped_x | clipped_y | hidden | focus_failed
    path: str
    widget_class: str
    label: str
    state: str
    clipped_px: tuple[int, int, int, int] = (0, 0, 0, 0)  # left, top, right, bottom
    size: tuple[int, int] = (0, 0)
    viewport_height: int = 0  # height of the innermost scroll viewport (0 when not scrolled)
    detail: str = (
        ""  # for a hidden control: the outermost ancestor that is not mapped, with its geometry
    )

    @property
    def severity(self) -> str:
        """blocking: unmapped, focus-unreachable or less than half visible; degraded: operable but partly clipped."""
        if self.kind in {"hidden", "focus_failed"}:
            return "blocking"
        width, height = self.size
        left, top, right, bottom = self.clipped_px
        if self.kind == "tall":
            return "degraded"
        visible_x = 1.0 - (left + right) / max(width, 1)
        visible_y = 1.0 - (top + bottom) / max(height, 1)
        return "blocking" if min(visible_x, visible_y) < MIN_VISIBLE_FRACTION else "degraded"

    def describe(self) -> str:
        suffix = f" | {self.detail}" if self.detail else ""
        return f"{self.kind} {self.widget_class} '{self.label}' [{self.state}] clipped(l,t,r,b)={self.clipped_px} {self.path}{suffix}"


@dataclass
class ProbeResult:
    checked: int = 0
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocking(self) -> list[Finding]:
        """Geometry does not depend on enabled state: a control that is disabled now is enabled by a later selection."""
        return [f for f in self.findings if f.severity == "blocking"]

    @property
    def degraded(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "degraded"]


def _pump(root: tk.Misc, seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        root.update()
        time.sleep(0.01)


def _wait_until_viewable(root: tk.Misc, widget: tk.Misc) -> None:
    """Give a freshly selected page time to map: a canvas window maps on a redraw, which a slow host can delay."""

    deadline = time.perf_counter() + HIDDEN_RECHECK_SECONDS
    while not widget.winfo_viewable() and time.perf_counter() < deadline:
        _pump(root, 0.1)
        for frame in scroll_chain(widget):
            frame.reveal(widget)


def _unmapped_ancestor(widget: tk.Misc) -> str:
    """Outermost ancestor of ``widget`` that is not mapped, with its manager and size (diagnoses a hidden control)."""

    outermost = ""
    node: tk.Misc | None = widget
    while node is not None:
        if not node.winfo_ismapped():
            outermost = (
                f"{node} {node.winfo_class()} manager={node.winfo_manager() or '-'} "
                f"size={node.winfo_width()}x{node.winfo_height()} req={node.winfo_reqwidth()}x{node.winfo_reqheight()}"
            )
        node = getattr(node, "master", None)
    return outermost + _canvas_state(widget)


def _canvas_state(widget: tk.Misc) -> str:
    """Geometry of the nearest scroll canvas above ``widget``: a canvas window outside its view is unmapped."""

    node: tk.Misc | None = widget
    while node is not None:
        if isinstance(node, tk.Canvas):
            return (
                f" canvas={node.winfo_width()}x{node.winfo_height()} mapped={node.winfo_ismapped()} "
                f"yview={tuple(round(v, 3) for v in node.yview())} xview={tuple(round(v, 3) for v in node.xview())} "
                f"scrollregion={node.cget('scrollregion')} items={node.find_all()} "
                f"bbox={[node.bbox(item) for item in node.find_all()]}"
            )
        node = getattr(node, "master", None)
    return ""


def _label(widget: tk.Misc) -> str:
    for option in ("text", "textvariable"):
        try:
            value = str(widget.cget(option))
        except tk.TclError:
            continue
        if option == "textvariable" and value:
            try:
                value = str(widget.tk.globalgetvar(value))
            except tk.TclError:
                pass
        if value:
            return value[:48]
    return widget.winfo_name()


def _state(widget: tk.Misc) -> str:
    try:
        raw = str(widget.cget("state"))
    except tk.TclError:
        return "normal"
    return "disabled" if raw == "disabled" else "normal"


def _rect(widget: tk.Misc) -> tuple[int, int, int, int]:
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    return x, y, x + widget.winfo_width(), y + widget.winfo_height()


def _chain(widget: tk.Misc) -> list[tk.Misc]:
    out: list[tk.Misc] = []
    node = getattr(widget, "master", None)
    while node is not None:
        out.append(node)
        node = getattr(node, "master", None)
    return out


def logically_shown(widget: tk.Misc, within: tk.Misc) -> bool:
    """Managed by a geometry manager all the way up to ``within``, and on the selected page of every notebook."""

    node: tk.Misc | None = widget
    while node is not None and node is not within:
        parent = getattr(node, "master", None)
        if node.winfo_manager() == "" and parent is not None:
            return False
        if isinstance(parent, ttk.Notebook):
            try:
                if parent.nametowidget(parent.select()) is not node:
                    return False
            except (tk.TclError, KeyError):
                return False
        node = parent
    return True


def scroll_chain(widget: tk.Misc) -> list[ScrollableFrame]:
    return [node for node in _chain(widget) if isinstance(node, ScrollableFrame)]


def clipped_px(widget: tk.Misc) -> tuple[int, int, int, int]:
    """Pixels of ``widget`` cut off on each side by its tightest clipping ancestors."""

    left, top, right, bottom = _rect(widget)
    cl, ct, cr, cb = left, top, right, bottom
    for ancestor in _chain(widget):
        al, at, ar, ab = _rect(ancestor)
        cl, ct, cr, cb = max(cl, al), max(ct, at), min(cr, ar), min(cb, ab)
    return max(0, cl - left), max(0, ct - top), max(0, right - cr), max(0, bottom - cb)


def _top_all_scrollers(widgets: list[ScrollableFrame]) -> None:
    for frame in widgets:
        try:
            frame._canvas.yview_moveto(0)
        except tk.TclError:
            pass


def _walk(container: tk.Misc) -> list[tk.Misc]:
    out: list[tk.Misc] = []
    stack = list(container.winfo_children())
    while stack:
        node = stack.pop(0)
        out.append(node)
        stack[0:0] = list(node.winfo_children())
    return out


def probe(root: tk.Misc, container: tk.Misc, *, keyboard: bool = False) -> ProbeResult:
    """Check every logically shown actionable widget under ``container`` (current notebook page selection only)."""

    result = ProbeResult()
    root.update_idletasks()
    root.update()
    frames = [n for n in _walk(container) if isinstance(n, ScrollableFrame)]
    for widget in _walk(container):
        if widget.winfo_class() not in ACTIONABLE_CLASSES or not logically_shown(widget, container):
            continue
        try:
            if not widget.winfo_exists():
                continue
        except tk.TclError:
            continue
        result.checked += 1
        _top_all_scrollers(frames)
        root.update_idletasks()
        if keyboard:
            try:
                widget.focus_force()
            except tk.TclError:
                pass
            root.update()
            if root.focus_get() is not widget:
                result.findings.append(
                    Finding(
                        "focus_failed",
                        str(widget),
                        widget.winfo_class(),
                        _label(widget),
                        _state(widget),
                    )
                )
                continue
        else:
            for frame in scroll_chain(widget):
                frame.reveal(widget)
            root.update_idletasks()
            root.update()
        if not widget.winfo_viewable():
            _wait_until_viewable(root, widget)
        if not widget.winfo_viewable():
            result.findings.append(
                Finding(
                    "hidden",
                    str(widget),
                    widget.winfo_class(),
                    _label(widget),
                    _state(widget),
                    (0, 0, 0, 0),
                    (widget.winfo_width(), widget.winfo_height()),
                    0,
                    _unmapped_ancestor(widget),
                )
            )
            continue
        left, top, right, bottom = clipped_px(widget)
        frames_above = scroll_chain(widget)
        view_h = frames_above[0]._canvas.winfo_height() if frames_above else 0
        if max(left, right) > TOLERANCE_PX:
            kind = "clipped_x"
        elif max(top, bottom) > TOLERANCE_PX:
            # a widget taller than its whole scroll viewport can never fit it; its top is reachable, the rest by scrolling
            kind = (
                "tall"
                if view_h and widget.winfo_height() > view_h and top <= TOLERANCE_PX
                else "clipped_y"
            )
        else:
            continue
        result.findings.append(
            Finding(
                kind,
                str(widget),
                widget.winfo_class(),
                _label(widget),
                _state(widget),
                (left, top, right, bottom),
                (widget.winfo_width(), widget.winfo_height()),
                view_h,
            )
        )
    _top_all_scrollers(frames)
    return result


def probe_notebook_pages(
    root: tk.Misc, container: tk.Misc, *, keyboard: bool = False
) -> ProbeResult:
    """Probe the container, then every page of every nested ``ttk.Notebook`` in it (selection is restored)."""

    total = probe(root, container, keyboard=keyboard)
    for notebook in [n for n in _walk(container) if isinstance(n, ttk.Notebook)]:
        if not logically_shown(notebook, container):
            continue
        try:
            original = notebook.select()
            tabs = list(notebook.tabs())
        except tk.TclError:
            continue
        for tab in tabs:
            if tab == original:
                continue
            try:
                notebook.select(tab)
            except tk.TclError:
                continue
            _pump(root, SETTLE_SECONDS)
            part = probe(root, container, keyboard=keyboard)
            total.checked += part.checked
            seen = {(f.kind, f.path) for f in total.findings}
            total.findings.extend(f for f in part.findings if (f.kind, f.path) not in seen)
        try:
            notebook.select(original)
        except tk.TclError:
            pass
    return total
