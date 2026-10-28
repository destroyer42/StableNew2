from __future__ import annotations

import threading
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field

from src.controller.ports.ui_dispatcher import ImmediateUiDispatcher, UiDispatcher
from src.gui.gui_invoker import TkInvoker


@dataclass
class TkUiDispatcher:
    """Tk implementation of the toolkit-neutral UiDispatcher contract.

    One dispatcher owns one Tk pump. Code obtains the dispatcher for a Tk root through
    :func:`tk_dispatcher_for` so a root never has more than one; direct construction is reserved for
    that registry and for tests that drive a fake root.
    """

    root: object
    _invoker: TkInvoker | None = field(init=False, default=None, repr=False)
    _ui_thread_id: int = field(init=False, repr=False)
    _disposed: bool = field(init=False, default=False, repr=False)

    def __post_init__(self) -> None:
        self._ui_thread_id = threading.get_ident()
        try:
            self._invoker = TkInvoker(self.root)  # type: ignore[arg-type]
        except Exception:
            self._invoker = None

    @property
    def disposed(self) -> bool:
        return self._disposed

    def schedule(self, fn: Callable[[], None]) -> None:
        if self._disposed:
            return
        invoker = self._invoker
        if invoker is not None:
            invoker.schedule(fn)
            return
        if not self._after(0, fn):
            fn()

    def _after(self, delay_ms: int, fn: Callable[[], None]) -> bool:
        after = getattr(self.root, "after", None)
        if not callable(after):
            return False
        try:
            after(max(0, int(delay_ms)), fn)
        except Exception:
            return False
        return True

    def invoke(self, fn: Callable[[], None]) -> None:
        """Backward-compatible name for :meth:`schedule`."""
        self.schedule(fn)

    def invoke_later(self, delay_ms: int, fn: Callable[[], None]) -> None:
        if self._disposed:
            return
        invoker = self._invoker
        if invoker is not None:
            invoker.invoke_later(delay_ms, fn)
            return
        if not self._after(delay_ms, fn):
            fn()

    def run_on_ui_thread(self, fn: Callable[[], None]) -> None:
        if self._disposed:
            return
        invoker = self._invoker
        if invoker is not None:
            invoker.run_on_ui_thread(fn)
            return
        if threading.get_ident() == self._ui_thread_id:
            fn()
            return
        self.schedule(fn)

    def dispose(self) -> None:
        """Stop the pump, drop queued work and cancel delayed work. Idempotent."""
        self._disposed = True
        invoker = self._invoker
        if invoker is not None:
            invoker.dispose()


_root_dispatchers: weakref.WeakKeyDictionary[object, TkUiDispatcher] = weakref.WeakKeyDictionary()
_root_dispatchers_lock = threading.Lock()


def _tk_root_of(widget_or_root: object) -> object:
    """Resolve the Tk root for a widget; a root (or a test double) resolves to itself."""
    resolver = getattr(widget_or_root, "_root", None)
    return resolver() if callable(resolver) else widget_or_root


def tk_dispatcher_for(widget_or_root: object) -> TkUiDispatcher:
    """Return the single dispatcher that owns the pump for this widget's Tk root.

    The composition path creates it for the production root; standalone windows and widgets reach the
    same instance, so a root never gains a second pump.
    """
    root = _tk_root_of(widget_or_root)
    with _root_dispatchers_lock:
        dispatcher = _root_dispatchers.get(root)
        if dispatcher is None:
            # A disposed dispatcher stays registered so a closing root is never given a fresh pump.
            dispatcher = TkUiDispatcher(root)
            _root_dispatchers[root] = dispatcher
        return dispatcher


def release_tk_dispatcher(widget_or_root: object) -> None:
    """Dispose the root's dispatcher and forget it, so a later window on the same root gets a fresh one.

    Only a standalone window (one that was not handed a dispatcher by the composition path) calls this;
    the production dispatcher stays registered once disposed so a closing root is never given a new pump.
    """
    root = _tk_root_of(widget_or_root)
    with _root_dispatchers_lock:
        dispatcher = _root_dispatchers.pop(root, None)
    if dispatcher is not None:
        dispatcher.dispose()


__all__ = [
    "ImmediateUiDispatcher",
    "TkUiDispatcher",
    "UiDispatcher",
    "release_tk_dispatcher",
    "tk_dispatcher_for",
]
