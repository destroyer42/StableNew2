"""Windows desktop driver: real OS mouse, keyboard and wheel input aimed at visible Tk controls.

Tk exposes no UI Automation tree for its controls, so the *semantic* target is the Tk widget (found by text, variable or
class exactly as ``TkDriver`` does) and the *physical* action is Win32 input injected at that widget's on-screen point.
Before every click the point is hit-tested twice: ``winfo_containing`` (in-app overlap) and ``WindowFromPoint`` (another
application covering the window).  A control that is disabled, unmapped, off-screen, obscured or on an unresponsive
event loop raises ``ControlUnreachable``; the driver never falls back to calling a callback or controller.

Never used in headless CI (``tools.operator_journey.golden.modes.validate_combination`` refuses it).  The Win32 surface is
the injectable ``Win32`` class so the geometry and diagnosis logic is testable without a desktop.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
import tkinter as tk
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path
from tkinter import ttk
from typing import Any

from tools.operator_journey.tk_driver import (
    ActionTrace,
    JourneyTimeout,
    TkDriver,
    WidgetNotFound,
    is_disabled,
    iter_widgets,
)

VK_RETURN, VK_TAB, VK_CONTROL, VK_SHIFT, VK_DELETE = 0x0D, 0x09, 0x11, 0x10, 0x2E
VK_HOME, VK_END, VK_ESCAPE = 0x24, 0x23, 0x1B
WM_SYSCOMMAND, SC_CLOSE = 0x0112, 0xF060
BM_CLICK, WM_SETTEXT, WM_COMMAND, IDOK = 0x00F5, 0x000C, 0x0111, 1
GA_ROOT = 2


class ControlUnreachable(WidgetNotFound):
    """The control cannot be operated by a person right now; ``reason`` is the acceptance failure."""

    def __init__(self, label: str, reason: str, detail: str = "") -> None:
        self.reason = reason
        super().__init__(f"{label}: control is {reason}" + (f" ({detail})" if detail else ""))


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class Win32:
    """The only place user32 is touched; replaced by a fake in unit tests."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("the Windows desktop driver requires Windows")
        self.u = ctypes.WinDLL("user32", use_last_error=True)
        u = self.u
        u.GetForegroundWindow.restype = wintypes.HWND
        u.WindowFromPoint.restype = wintypes.HWND
        u.WindowFromPoint.argtypes = [wintypes.POINT]
        u.GetAncestor.restype = wintypes.HWND
        u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        u.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
        u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_void_p]
        u.SendMessageW.restype = ctypes.c_ssize_t
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

    # -- pointer / keyboard -------------------------------------------------
    def _send(self, *inputs: _INPUT) -> None:
        array = (_INPUT * len(inputs))(*inputs)
        if self.u.SendInput(len(inputs), array, ctypes.sizeof(_INPUT)) != len(inputs):
            raise OSError(f"SendInput blocked (UIPI or locked desktop): {ctypes.get_last_error()}")

    @staticmethod
    def _mouse(flags: int, data: int = 0) -> _INPUT:
        return _INPUT(0, _INPUTUNION(mi=_MOUSEINPUT(0, 0, data & 0xFFFFFFFF, flags, 0, 0)))

    @staticmethod
    def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> _INPUT:
        return _INPUT(1, _INPUTUNION(ki=_KEYBDINPUT(vk, scan, flags, 0, 0)))

    def move(self, x: int, y: int) -> None:
        self.u.SetCursorPos(int(x), int(y))

    def click(
        self,
        x: int,
        y: int,
        *,
        double: bool = False,
        settle: Callable[[], tuple[int, int] | None] | None = None,
    ) -> tuple[int, int]:
        """Press and release the left button; returns the point where it was released.

        ``settle`` runs between press and release and may return a new point: a press can focus the control and the
        application can then scroll it away from under the pointer, so the pointer follows the control before release
        (the same thing a person does by keeping the button down and sliding back onto it).
        """

        self.move(x, y)
        time.sleep(0.04)
        released = (x, y)
        for _ in range(2 if double else 1):
            if settle is None or double:
                self._send(self._mouse(0x0002), self._mouse(0x0004))  # left down, left up
            else:
                self._send(self._mouse(0x0002))
                moved = settle()
                if moved is not None and moved != released:
                    released = moved
                    self.move(*moved)
                    time.sleep(0.02)
                self._send(self._mouse(0x0004))
            time.sleep(0.05)
        return released

    def drag(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        *,
        steps: int = 14,
        pump: Callable[[float], None] | None = None,
    ) -> None:
        """Press at (x1, y1), move to (x2, y2) in small steps, release (pump lets Tk follow the pointer)."""

        self.move(x1, y1)
        time.sleep(0.08)
        self._send(self._mouse(0x0002))
        time.sleep(0.05)
        for i in range(1, steps + 1):
            self.move(x1 + (x2 - x1) * i // steps, y1 + (y2 - y1) * i // steps)
            if pump is not None:
                pump(0.03)
            time.sleep(0.02)
        self._send(self._mouse(0x0004))
        time.sleep(0.05)

    def wheel(self, x: int, y: int, notches: int) -> None:
        self.move(x, y)
        self._send(self._mouse(0x0800, notches * 120))  # MOUSEEVENTF_WHEEL

    def type_text(self, text: str) -> None:
        for char in text:
            if char == "\n":
                self.press(VK_RETURN)
                continue
            for unit in (
                char.encode("utf-16-le")[i : i + 2]
                for i in range(0, len(char.encode("utf-16-le")), 2)
            ):
                code = int.from_bytes(unit, "little")
                self._send(self._key(0, code, 0x0004), self._key(0, code, 0x0004 | 0x0002))
            time.sleep(0.004)

    #: Navigation/editing keys are "extended" keys: without the flag Windows delivers the numpad variants.
    _EXTENDED = frozenset({0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E})

    def press(self, vk: int, *modifiers: int) -> None:
        extended = 0x0001 if vk in self._EXTENDED else 0
        downs = [self._key(m) for m in modifiers] + [self._key(vk, flags=extended)]
        ups = [self._key(vk, flags=0x0002 | extended)] + [
            self._key(m, flags=0x0002) for m in reversed(modifiers)
        ]
        self._send(*downs, *ups)
        time.sleep(0.03)

    # -- windows ---------------------------------------------------------------
    def foreground(self) -> int:
        return int(self.u.GetForegroundWindow() or 0)

    def window_from_point(self, x: int, y: int) -> int:
        return int(self.u.WindowFromPoint(wintypes.POINT(int(x), int(y))) or 0)

    def root_of(self, hwnd: int) -> int:
        return int(self.u.GetAncestor(hwnd, GA_ROOT) or 0)

    def is_child(self, parent: int, child: int) -> bool:
        return parent == child or bool(self.u.IsChild(parent, child))

    def rect(self, hwnd: int) -> tuple[int, int, int, int]:
        r = wintypes.RECT()
        self.u.GetWindowRect(hwnd, ctypes.byref(r))
        return r.left, r.top, r.right, r.bottom

    def pid_of(self, hwnd: int) -> int:
        owner = wintypes.DWORD(0)
        self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        return int(owner.value)

    def raise_window(self, hwnd: int) -> bool:
        self.press(
            0x12
        )  # a bare Alt tap lets SetForegroundWindow succeed from a background process
        return bool(self.u.SetForegroundWindow(hwnd))

    def post_close(self, hwnd: int) -> None:
        self.u.PostMessageW(hwnd, WM_SYSCOMMAND, SC_CLOSE, 0)

    def screen_size(self) -> tuple[int, int]:
        return self.u.GetSystemMetrics(0), self.u.GetSystemMetrics(1)

    def screenshot(self, path: Path, bbox: tuple[int, int, int, int] | None = None) -> Path:
        from PIL import ImageGrab

        path.parent.mkdir(parents=True, exist_ok=True)
        ImageGrab.grab(bbox=bbox, all_screens=True).save(path)
        return path

    # -- top-level dialogs ---------------------------------------------------------
    def dialogs_of(self, pid: int) -> list[int]:
        found: list[int] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def visit(hwnd: int, _l: int) -> bool:
            owner = wintypes.DWORD()
            self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if (
                owner.value == pid
                and self.u.IsWindowVisible(hwnd)
                and self.class_name(hwnd) == "#32770"
            ):
                found.append(int(hwnd))
            return True

        self.u.EnumWindows(callback_type(visit), 0)
        return found

    def children_of(self, hwnd: int) -> list[tuple[int, str, str]]:
        kids: list[tuple[int, str, str]] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def visit(child: int, _l: int) -> bool:
            kids.append((int(child), self.class_name(child), self.text(child)))
            return True

        self.u.EnumChildWindows(hwnd, callback_type(visit), 0)
        return kids

    def class_name(self, hwnd: int) -> str:
        buf = ctypes.create_unicode_buffer(256)
        self.u.GetClassNameW(hwnd, buf, 256)
        return buf.value

    def text(self, hwnd: int) -> str:
        buf = ctypes.create_unicode_buffer(1024)
        self.u.GetWindowTextW(hwnd, buf, 1024)
        return buf.value

    def set_text(self, hwnd: int, value: str) -> None:
        buffer = ctypes.create_unicode_buffer(value)
        self.u.SendMessageW(hwnd, WM_SETTEXT, 0, ctypes.cast(buffer, ctypes.c_void_p))

    def click_button(self, hwnd: int) -> None:
        self.u.PostMessageW(hwnd, BM_CLICK, 0, 0)


def display_facts(win32: Win32 | None = None) -> dict[str, Any]:
    """Resolution and scaling this run used (recorded in the evidence)."""

    from tools.operator_journey.golden.host import probe_display

    facts = probe_display()
    facts["tk_scaling"] = None
    return facts


class WindowsDesktopDriver(TkDriver):
    """``TkDriver`` whose operator actions are physical Win32 input at the target widget's screen point."""

    driver_kind = "windows"

    def __init__(
        self, root: tk.Tk, trace: ActionTrace | None = None, *, win32: Win32 | None = None
    ) -> None:
        super().__init__(root, trace, use_mainloop=False)
        self.trace.driver = self.driver_kind
        self.win32 = win32 or Win32()
        self.screenshots: list[str] = []

    # -- window / reachability --------------------------------------------------------
    @property
    def hwnd(self) -> int:
        return self.win32.root_of(int(self.root.winfo_id()))

    def _window_for(self, widget: tk.Misc | None) -> int:
        """The operating-system window that shows ``widget`` (the main window, or the dialog it lives in)."""

        if widget is None:
            return self.hwnd
        try:
            top = widget.winfo_toplevel()
            if top is self.root:
                return self.hwnd
            return int(self.win32.root_of(int(top.winfo_id()))) or self.hwnd
        except tk.TclError:
            return self.hwnd

    def _dialog_open(self) -> bool:
        return any(
            isinstance(c, tk.Toplevel) and c.winfo_viewable() for c in self.root.winfo_children()
        )

    def ensure_foreground(self, widget: tk.Misc | None = None) -> None:
        """A StableNew window (the one showing ``widget``) must be in the foreground before any input is sent."""

        target = self._window_for(widget)
        shown = self.root if widget is None else widget.winfo_toplevel()
        shown.deiconify()
        if shown is self.root and not self._dialog_open():
            shown.lift()  # never lift the main window over a dialog the operator opened
        self.pump(0.1)
        own_pid = self.win32.pid_of(self.hwnd)

        def ours() -> bool:
            front = self.win32.foreground()
            return bool(front) and self.win32.pid_of(self.win32.root_of(front) or front) == own_pid

        if not ours():
            self.win32.raise_window(target)
            self.pump(0.3)
        if not ours():
            raise ControlUnreachable(
                "StableNew window",
                "not the foreground window",
                f"foreground hwnd {self.win32.foreground()} is not a StableNew window",
            )

    def window_facts(self) -> dict[str, Any]:
        """The StableNew window as the operator sees it (no input is sent)."""

        left, top, right, bottom = self.win32.rect(self.hwnd)
        return {
            "state": str(self.root.state()),
            "left": left,
            "top": top,
            "width": right - left,
            "height": bottom - top,
        }

    def maximize_window(self) -> dict[str, Any]:
        """Maximize by double-clicking the title bar, as a person does; returns the resulting window facts."""

        self.ensure_foreground()
        if str(self.root.state()) != "zoomed":
            left, top, right, _bottom = self.win32.rect(self.hwnd)
            x, y = left + (right - left) // 2, top + 14
            self.win32.click(x, y, double=True)
            self.pump(1.0)
            if str(self.root.state()) != "zoomed":
                raise ControlUnreachable(
                    "window title bar", "double-click did not maximize the window"
                )
        left, top, right, bottom = self.win32.rect(self.hwnd)
        facts = {
            "state": str(self.root.state()),
            "left": left,
            "top": top,
            "width": right - left,
            "height": bottom - top,
        }
        self.trace.record("maximize_window", **facts)
        return facts

    def responsive(self, timeout: float = 5.0) -> bool:
        """The Tk event loop answers: an idle callback scheduled now runs before the timeout."""

        flag: list[bool] = []
        self.root.after_idle(lambda: flag.append(True))
        deadline = time.monotonic() + timeout
        while not flag and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        return bool(flag)

    def diagnose(self, widget: tk.Misc, x: int, y: int) -> str | None:
        """Why a person could not click ``widget`` at screen point (x, y), or ``None`` when they can."""

        try:
            if not widget.winfo_exists():
                return "destroyed"
            if not widget.winfo_viewable():
                return "hidden (unmapped or on an unselected tab)"
            if is_disabled(widget):
                return "disabled"
        except tk.TclError:
            pass
        sw, sh = self.win32.screen_size()
        if not (0 <= x < sw and 0 <= y < sh):
            return f"off-screen at ({x},{y})"
        window = self._window_for(widget)
        left, top, right, bottom = self.win32.rect(window)
        if not (left <= x < right and top <= y < bottom):
            return "outside the StableNew window"
        inside = self.root.winfo_containing(x, y)
        if inside is None or not self._is_target_or_descendant(inside, widget):
            return f"obscured within the application by {inside!r}"
        top_hwnd = self.win32.window_from_point(x, y)
        if not top_hwnd or self.win32.root_of(top_hwnd) != window:
            return f"obscured by another window (hwnd {top_hwnd})"
        return None

    @staticmethod
    def _is_target_or_descendant(found: tk.Misc, widget: tk.Misc) -> bool:
        node: tk.Misc | None = found
        while node is not None:
            if node is widget or str(node) == str(widget):
                return True
            node = getattr(node, "master", None)
        return False

    def _center(self, widget: tk.Misc, dx: float = 0.5, dy: float = 0.5) -> tuple[int, int]:
        return (
            int(widget.winfo_rootx() + widget.winfo_width() * dx),
            int(widget.winfo_rooty() + widget.winfo_height() * dy),
        )

    def _scroll_container(self, widget: tk.Misc) -> tk.Canvas | None:
        node = getattr(widget, "master", None)
        while node is not None:
            if isinstance(node, tk.Canvas) and node.cget("yscrollcommand"):
                try:
                    first, last = node.yview()
                    if first > 0.0 or last < 1.0:
                        return node
                except tk.TclError:
                    pass
            node = getattr(node, "master", None)
        return None

    _SELF_SCROLLING = ("combobox", "listbox", "spinbox", "text", "treeview")

    def _wheel_point(self, container: tk.Canvas, *, skip: int = 0) -> tuple[int, int]:
        """A point over the scrolling page that is not a self-scrolling widget (the app routes the wheel away from those)."""

        left, top = container.winfo_rootx(), container.winfo_rooty()
        width, height = container.winfo_width(), container.winfo_height()
        candidates = []
        for fy in (0.5, 0.15, 0.85, 0.3, 0.7, 0.05, 0.95):
            for fx in (0.5, 0.1, 0.9, 0.3, 0.7):
                candidates.append((int(left + width * fx), int(top + height * fy)))
        usable = []
        for x, y in candidates:
            found = self.root.winfo_containing(x, y)
            if found is None or not self._is_target_or_descendant(
                found, container.master or container
            ):
                continue
            if any(name in str(found.winfo_class()).lower() for name in self._SELF_SCROLLING):
                continue
            usable.append((x, y))
        pool = usable or candidates
        return pool[skip % len(pool)]

    def _settled(self, widget: tk.Misc, point: tuple[float, float]) -> bool:
        """True once the control's screen position has stopped changing (smooth scrolling, deferred layout)."""

        last = self._center(widget, *point)
        stable_since = time.monotonic()
        deadline = stable_since + 1.5
        while time.monotonic() < deadline:
            self.pump(0.06)
            now = self._center(widget, *point)
            if now != last:
                last, stable_since = now, time.monotonic()
            elif time.monotonic() - stable_since >= 0.25:
                return True
        return False

    def reach(
        self,
        widget: tk.Misc,
        *,
        label: str,
        point: tuple[float, float] = (0.5, 0.5),
        max_scrolls: int = 60,
        patience: float = 5.0,
    ) -> tuple[int, int]:
        """Return a clickable screen point, wheel-scrolling the enclosing canvas as a person would."""

        self.ensure_foreground(widget)
        scrolls = 0
        stalled = 0
        started = time.monotonic()
        waited_for = ""
        while True:
            self.pump(0.02)
            x, y = self._center(widget, *point)
            reason = self.diagnose(widget, x, y)
            if reason is None:
                waited = time.monotonic() - started
                if waited_for and waited >= 0.5:
                    self.trace.record(
                        "waited_for_state", label=label, state=waited_for, seconds=round(waited, 2)
                    )
                if scrolls and not self._settled(widget, point):
                    continue  # the page is still moving after the wheel: look again before pressing
                if scrolls:
                    self.trace.record("scrolled_into_view", label=label, wheel_notches=scrolls)
                return x, y
            if reason.startswith(("hidden", "disabled")) and time.monotonic() - started < patience:
                waited_for = reason.split(" ")[0]
                continue  # the view may still be switching or a gate still resolving; a person would wait a moment
            scrollable = ("obscured within", "outside", "off-screen")
            container = (
                self._scroll_container(widget) if any(k in reason for k in scrollable) else None
            )
            if container is None or scrolls >= max_scrolls:
                if not self.responsive(1.0):
                    raise ControlUnreachable(
                        label, "unresponsive", "the Tk event loop did not answer"
                    )
                raise ControlUnreachable(label, reason, f"after {scrolls} wheel notches")
            above = widget.winfo_rooty() < container.winfo_rooty()
            before = container.yview()
            cx, cy = self._wheel_point(container, skip=stalled)
            self.win32.wheel(cx, cy, 3 if above else -3)
            scrolls += 3
            self.pump(0.06)
            stalled = stalled + 1 if container.yview() == before else 0
            if stalled >= 6:
                raise ControlUnreachable(
                    label, reason, f"the wheel did not move the page after {scrolls} notches"
                )

    def click(
        self,
        widget: tk.Misc,
        *,
        label: str,
        point: tuple[float, float] = (0.5, 0.5),
        double: bool = False,
    ) -> None:
        x, y = self.reach(widget, label=label, point=point)

        def settle() -> tuple[int, int] | None:
            self.pump(
                0.2
            )  # let focus handling and any reveal-scroll finish while the button is down
            try:
                return self._center(widget, *point) if widget.winfo_exists() else None
            except tk.TclError:
                return None

        released = self.win32.click(x, y, double=double, settle=settle)
        if released != (x, y):
            self.trace.record(
                "pointer_followed_control", label=label, pressed=(x, y), released=released
            )
        self.trace.record(
            "click",
            label=label,
            x=x,
            y=y,
            widget=str(widget),
            rect=(
                widget.winfo_rootx(),
                widget.winfo_rooty(),
                widget.winfo_width(),
                widget.winfo_height(),
            ),
        )
        self.pump(0.1)
        try:
            after = (widget.winfo_rootx(), widget.winfo_rooty())
        except tk.TclError:  # the click closed or rebuilt the control
            after = None
        self.trace.entries[-1]["rect_after_click"] = after
        if not self.responsive():
            raise ControlUnreachable(
                label, "unresponsive", "event loop stopped answering after the click"
            )

    # -- operator actions (physical) ------------------------------------------------------------
    def invoke(self, button: tk.Misc, *, label: str) -> None:
        self.click(button, label=label)

    def select_tab(self, notebook: ttk.Notebook, title: str) -> None:
        """Open a notebook page the way an operator does.

        The application hides the native tab strip and navigates through its task bar (a group button, then the
        page's button), so the physical clicks go there; the notebook is only read to confirm the result.  A
        notebook whose strip is still visible is clicked on its tab.
        """

        wanted = title.strip().lower()
        titles = [str(notebook.tab(t, "text")).strip().lower() for t in notebook.tabs()]
        if wanted not in titles:
            raise WidgetNotFound(f"tab {title!r} not in notebook tabs {titles}")
        index = titles.index(wanted)
        self.ensure_foreground()
        if notebook.index("current") == index:
            self.trace.record("select_tab", title=title, already_selected=True)
            return
        bar = self._task_bar()
        if bar is not None:
            self._select_through_task_bar(bar, notebook, index, title)
        else:
            self._click_native_tab(notebook, index, title)
        self.pump(0.3)
        if notebook.index("current") != index:
            raise ControlUnreachable(f"tab {title}", "did not respond to the click")

    def _task_bar(self) -> Any:
        from src.gui.widgets.task_navigation_bar_v2 import TaskNavigationBar

        return next(
            (
                w
                for w in iter_widgets(self.root)
                if isinstance(w, TaskNavigationBar) and w.winfo_ismapped()
            ),
            None,
        )

    def _select_through_task_bar(
        self, bar: Any, notebook: ttk.Notebook, index: int, title: str
    ) -> None:
        from src.gui.view_contracts.task_navigation_contract import get_destination

        shell = getattr(
            bar._on_select, "__self__", None
        )  # the main window that owns the page registry
        registry = dict(getattr(shell, "_tab_registry", {}))
        page = notebook.tabs()[index]
        tab_id = next((tid for tid, widget in registry.items() if str(widget) == str(page)), None)
        destination = get_destination(tab_id) if tab_id else None
        if destination is None:
            raise ControlUnreachable(
                f"tab {title}",
                "has no task-navigation destination",
                f"registry ids {sorted(registry)}",
            )
        if tab_id not in bar.visible_destination_ids():
            self.click(bar.group_button(destination.group_id), label=f"nav group for {title}")
            self.pump(0.2)
        self.click(bar.destination_button(tab_id), label=f"nav {destination.display_label}")

    def _click_native_tab(self, notebook: ttk.Notebook, index: int, title: str) -> None:
        try:
            bx, by, bw, bh = (int(v) for v in notebook.bbox(index))
        except (tk.TclError, ValueError, TypeError):
            bx = by = bw = bh = 0
        if bw < 6 or bh < 6 or bx + bw > notebook.winfo_width() + 1:
            raise ControlUnreachable(
                f"tab {title}",
                "not visible in the tab strip",
                f"tab bbox {(bx, by, bw, bh)}, notebook {notebook.winfo_width()}x{notebook.winfo_height()}; "
                "the window may be too narrow to show it",
            )
        x = notebook.winfo_rootx() + bx + bw // 2
        y = notebook.winfo_rooty() + by + bh // 2
        reason = self.diagnose(notebook, x, y)
        if reason:
            raise ControlUnreachable(f"tab {title}", reason)
        self.win32.click(x, y)
        self.trace.record("select_tab", title=title, index=index, x=x, y=y)

    @staticmethod
    def _field_text(widget: tk.Misc) -> str:
        try:
            if isinstance(widget, tk.Text):
                return str(widget.get("1.0", "end-1c"))
            return str(widget.get())  # type: ignore[attr-defined]
        except tk.TclError:
            return ""

    def _settled_text(self, widget: tk.Misc, *, quiet: float = 0.4, limit: float = 8.0) -> str:
        """The field's text once it has stopped changing (Tk may still be working through queued keystrokes)."""

        shown = self._field_text(widget)
        stable_since = time.monotonic()
        deadline = stable_since + limit
        while time.monotonic() < deadline:
            self.pump(0.05)
            now = self._field_text(widget)
            if now != shown:
                shown, stable_since = now, time.monotonic()
            elif time.monotonic() - stable_since >= quiet:
                break
        return shown

    def _clear_and_type(self, widget: tk.Misc, value: str, *, label: str, multiline: bool) -> None:
        """Replace a field's content as a person would, and read the field back to confirm it took.

        Some fields rewrite their own text on every keystroke or coerce an empty value, so a single recipe is not
        enough: strategies are tried in order until the field shows exactly ``value``; the strategy used and any
        wrong intermediate text are recorded.
        """

        w = self.win32
        ctrl = (VK_CONTROL,) if multiline else ()

        def home() -> None:
            w.press(VK_HOME, *ctrl)

        def end() -> None:
            w.press(VK_END, *ctrl)

        def select_to_end() -> None:
            w.press(VK_END, *ctrl, VK_SHIFT)

        def select_all() -> None:
            home()
            select_to_end()

        def type_first_then_trim() -> None:
            home()
            if value:
                w.type_text(value)
            select_to_end()
            w.press(VK_DELETE)

        def type_over_selection() -> None:
            select_all()
            w.type_text(value) if value else w.press(VK_DELETE)

        def backspace_then_type() -> None:
            end()
            for _ in range(len(self._field_text(widget)) + 3):
                w.press(0x08)  # VK_BACK
            if value:
                w.type_text(value)

        wrong: list[str] = []
        for name, recipe in (
            ("type-then-trim", type_first_then_trim),
            ("type-over-selection", type_over_selection),
            ("backspace-then-type", backspace_then_type),
        ):
            self.click(widget, label=label)
            recipe()
            shown = self._settled_text(widget)
            if shown == value:
                if wrong:
                    self.trace.record(
                        "typing_retried", label=label, strategy=name, earlier_results=wrong
                    )
                return
            wrong.append(f"{name}: {shown!r}")
        raise ControlUnreachable(
            label, "the field did not accept the typed value", f"wanted {value!r}; tried {wrong}"
        )

    def type_in_entry(self, entry: tk.Entry | ttk.Entry, value: str, *, label: str) -> None:
        self._clear_and_type(entry, value, label=label, multiline=False)
        self.win32.press(VK_TAB)
        self.trace.record("type_in_entry", label=label, value=value)
        self.pump(0.05)

    def type_in_text(self, widget: tk.Text, value: str, *, label: str) -> None:
        self._clear_and_type(widget, value, label=label, multiline=True)
        self.trace.record("type_in_text", label=label, value=value)
        self.pump(0.05)

    def select_combobox(self, combo: ttk.Combobox, value: str, *, label: str) -> None:
        allowed = [str(v) for v in combo.cget("values")]
        if value not in allowed:
            raise WidgetNotFound(f"{label}: {value!r} not among combobox values {allowed[:12]}")
        call = combo.tk.call
        listbox = (
            f"{call('ttk::combobox::PopdownWindow', str(combo))}.f.l"  # the Tcl-side drop-down list
        )
        for attempt in range(
            1, 4
        ):  # the press can focus the field and scroll it away; a person clicks again
            self.click(combo, label=f"{label} (open list)", point=(0.94, 0.5))
            try:
                self.wait_until(
                    lambda: bool(int(call("winfo", "viewable", listbox))),
                    timeout=1.5,
                    description=f"{label} list opens",
                )
                break
            except JourneyTimeout:
                if attempt == 3:
                    raise
                self.trace.record(
                    "reclick_after_no_effect", label=f"{label} (open list)", attempt=attempt
                )
        index = allowed.index(value)
        call(listbox, "see", index)
        self.pump(0.05)
        bbox = [int(n) for n in call(listbox, "bbox", index)]
        if len(bbox) != 4:
            raise ControlUnreachable(label, "list item not visible", value)
        x = int(call("winfo", "rootx", listbox)) + bbox[0] + bbox[2] // 2
        y = int(call("winfo", "rooty", listbox)) + bbox[1] + bbox[3] // 2
        top_hwnd = self.win32.window_from_point(x, y)
        if not top_hwnd or self.win32.root_of(top_hwnd) == 0:
            raise ControlUnreachable(label, "list item obscured", value)
        self.win32.click(x, y)
        self.pump(0.15)
        if combo.get() != value:
            raise ControlUnreachable(label, "selection did not apply", f"shows {combo.get()!r}")
        self.trace.record("select_combobox", label=label, value=value)

    def _control_for_variable(self, variable: tk.Variable) -> tk.Misc:
        """The visible control bound to ``variable``; a control hidden in a collapsed section is revealed the way a
        person does it, by clicking the section header."""

        from src.gui.widgets.disclosure_section_v2 import DisclosureSection

        hidden: tk.Misc | None = None
        for widget in iter_widgets(self.root):
            try:
                bound = (
                    str(widget.cget("textvariable")) == str(variable)
                    if "textvariable" in widget.keys()
                    else False
                )  # type: ignore[attr-defined]
                bound = bound or (
                    str(widget.cget("variable")) == str(variable)
                    if "variable" in widget.keys()
                    else False
                )  # type: ignore[attr-defined]
            except tk.TclError:
                continue
            if not bound:
                continue
            if widget.winfo_viewable():
                return widget
            hidden = hidden or widget
        if hidden is not None:
            node: tk.Misc | None = hidden
            while node is not None:
                if isinstance(node, DisclosureSection) and not node.is_expanded():
                    self.click(
                        node.toggle_button, label=f"expand section {getattr(node, '_title', '')}"
                    )
                    self.pump(0.3)
                    if hidden.winfo_viewable():
                        return hidden
                node = getattr(node, "master", None)
        raise ControlUnreachable(f"variable {variable}", "not bound to any visible control")

    def set_variable(self, variable: tk.Variable, value: Any, *, label: str) -> None:
        widget = self._control_for_variable(variable)
        if isinstance(widget, ttk.Combobox):
            self.select_combobox(widget, str(value), label=label)
        elif isinstance(widget, (ttk.Checkbutton, tk.Checkbutton)):
            if bool(variable.get()) != bool(value):
                self.click(widget, label=label)
        else:
            self.type_in_entry(widget, str(value), label=label)  # type: ignore[arg-type]
        self.trace.record("set_variable", label=label, value=value)

    def select_tree_row(self, tree: ttk.Treeview, iid: str, *, label: str) -> None:
        if iid not in tree.get_children():
            raise WidgetNotFound(f"{label}: row {iid!r} is not in the tree")
        tree.see(iid)
        self.pump(0.05)
        bbox = tree.bbox(iid)
        if not bbox:
            raise ControlUnreachable(label, "row not visible")
        x, y = (
            tree.winfo_rootx() + bbox[0] + min(bbox[2] // 2, 60),
            tree.winfo_rooty() + bbox[1] + bbox[3] // 2,
        )
        self._require_reachable(tree, x, y, label)
        self.win32.click(x, y)
        self.trace.record("select_tree_row", label=label, row=iid, x=x, y=y)
        self.pump(0.15)

    def _require_reachable(self, widget: tk.Misc, x: int, y: int, label: str) -> None:
        """Wait briefly for a transient state to clear, then fail when a person could not click the point."""

        deadline = time.monotonic() + 5.0
        while True:
            reason = self.diagnose(widget, x, y)
            if reason is None:
                return
            if not reason.startswith(("hidden", "disabled")) or time.monotonic() > deadline:
                raise ControlUnreachable(label, reason)
            self.pump(0.1)

    def drag_sash(self, paned: ttk.Panedwindow, index: int, *, delta: int, label: str) -> None:
        """Drag a pane divider by ``delta`` pixels (negative = up/left) with the real mouse."""

        vertical = str(paned.cget("orient")) == "vertical"
        before = int(paned.sashpos(index))
        target = max(30, before + delta)
        for grip in (
            2,
            1,
            3,
            0,
            4,
        ):  # the sash is a few pixels thick: find where it takes the press
            if vertical:
                x = paned.winfo_rootx() + max(20, paned.winfo_width() // 3)
                y = paned.winfo_rooty() + before + grip
                x2, y2 = x, paned.winfo_rooty() + target + grip
            else:
                x = paned.winfo_rootx() + before + grip
                y = paned.winfo_rooty() + max(20, paned.winfo_height() // 3)
                x2, y2 = paned.winfo_rootx() + target + grip, y
            self._require_reachable(paned, x, y, label)
            self.win32.drag(x, y, x2, y2, pump=self.pump)
            self.pump(0.2)
            if int(paned.sashpos(index)) != before:
                self.trace.record(
                    "drag_sash",
                    label=label,
                    index=index,
                    before=before,
                    after=int(paned.sashpos(index)),
                    x=x,
                    y=y,
                )
                return
        raise ControlUnreachable(label, "the divider did not move when dragged")

    def select_listbox_row(self, listbox: tk.Listbox, index: int, *, label: str) -> None:
        listbox.see(index)
        self.pump(0.05)
        bbox = listbox.bbox(index)
        if not bbox:
            raise ControlUnreachable(label, "row not visible")
        x, y = (
            listbox.winfo_rootx() + bbox[0] + bbox[2] // 2,
            listbox.winfo_rooty() + bbox[1] + bbox[3] // 2,
        )
        self._require_reachable(listbox, x, y, label)
        self.win32.click(x, y)
        self.trace.record("select_listbox_row", label=label, index=index, x=x, y=y)
        self.pump(0.1)

    def screenshot(self, directory: Path, name: str) -> str:
        """Capture the StableNew window as displayed (evidence of what the operator saw)."""

        path = self.win32.screenshot(directory / f"{name}.png", bbox=self.win32.rect(self.hwnd))
        self.screenshots.append(str(path))
        self.trace.record("screenshot", name=name, path=str(path))
        return str(path)

    def close_via_window_manager(self) -> None:
        """The system close command (what the title-bar X sends); the application's own handler runs."""

        # Move the pointer off the controls first: a pending tooltip timer firing during teardown re-enters the
        # application's own shutdown (observed as an access violation), and a person closing a window is not hovering.
        left, top, right, _bottom = self.win32.rect(self.hwnd)
        self.win32.move(left + (right - left) // 2, top + 12)
        self.pump(0.6)
        self.trace.record("close_window", method="WM_SYSCOMMAND/SC_CLOSE")
        self.win32.post_close(self.hwnd)


class NativeDialogResponder:
    """Answers native Windows dialogs (message boxes and common file dialogs) of this process from a helper thread.

    A modal native dialog blocks the Tk thread that opened it, so the answer must come from another thread.  Each
    scripted answer is ``("button", "Yes")`` or ``("file", "C:/path/file.png")``; every dialog seen is recorded.
    """

    def __init__(self, win32: Win32, pid: int, *, default_button: str = "yes") -> None:
        self.win32, self.pid, self.default_button = win32, pid, default_button.lower()
        self.script: list[tuple[str, str]] = []
        self.seen: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._handled: set[int] = set()
        self._thread = threading.Thread(target=self._run, name="dialog-responder", daemon=True)

    def __enter__(self) -> NativeDialogResponder:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join(timeout=3)

    def queue(self, kind: str, value: str) -> None:
        self.script.append((kind, value))

    def _run(self) -> None:
        while not self._stop.is_set():
            for hwnd in self.win32.dialogs_of(self.pid):
                if hwnd in self._handled:
                    continue
                kids = self.win32.children_of(hwnd)
                self._handled.add(hwnd)
                title = self.win32.text(hwnd)
                texts = [t for (_h, c, t) in kids if c == "Static" and t]
                edits = [h for (h, c, _t) in kids if c == "Edit"]
                buttons = [
                    (h, t.replace("&", "").lower()) for (h, c, t) in kids if c == "Button" and t
                ]
                wanted = self.script.pop(0) if self.script else None
                record: dict[str, Any] = {
                    "title": title,
                    "text": " ".join(texts)[:300],
                    "buttons": [t for _h, t in buttons],
                    "answer": None,
                }
                if wanted and wanted[0] == "file" and edits:
                    self.win32.set_text(edits[0], wanted[1])
                    ok = next(
                        (h for h, t in buttons if t in {"open", "save", "ok", "select folder"}),
                        None,
                    )
                    if ok:
                        self.win32.click_button(ok)
                    record["answer"] = f"file:{wanted[1]}"
                else:
                    choice = wanted[1].lower() if wanted else self.default_button
                    target = next((h for h, t in buttons if t == choice), None) or (
                        buttons[0][0] if buttons else None
                    )
                    if target:
                        self.win32.click_button(target)
                        record["answer"] = choice
                self.seen.append(record)
            time.sleep(0.1)
