"""Semantic Tk operator driver.

Every operation manipulates the real widget the way an operator would (select a
tab, edit a field, pick a combobox value and fire ``<<ComboboxSelected>>``,
invoke a button) so the application's own bound callbacks run.  The driver never
calls a controller submission method, JobService, runner, executor or backend.
"""

from __future__ import annotations

import time
import tkinter as tk
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from tkinter import ttk
from typing import Any, TypeVar

T = TypeVar("T")


class JourneyTimeout(AssertionError):
    """A bounded wait expired; the message carries the evidence needed to diagnose it."""


class WidgetNotFound(AssertionError):
    """The requested semantic widget does not exist or is not operable."""


@dataclass
class ActionTrace:
    """Ordered record of every semantic operator action."""

    entries: list[dict[str, Any]] = field(default_factory=list)
    _t0: float = field(default_factory=time.monotonic)

    def record(self, action: str, **details: Any) -> None:
        self.entries.append(
            {"t": round(time.monotonic() - self._t0, 3), "action": action, **details}
        )


def iter_widgets(parent: tk.Misc) -> Iterator[tk.Misc]:
    for child in parent.winfo_children():
        yield child
        yield from iter_widgets(child)


class TkDriver:
    """Drive a live Tk application from the UI thread by pumping its event loop."""

    def __init__(
        self, root: tk.Tk, trace: ActionTrace | None = None, *, use_mainloop: bool = False
    ) -> None:
        self.root = root
        self.trace = trace or ActionTrace()
        # Some production callbacks touch widgets from worker threads, which Tk only
        # marshals while ``mainloop`` runs (as it always does in the real app).
        self.use_mainloop = use_mainloop

    # -- event loop -----------------------------------------------------
    def pump(self, seconds: float = 0.0) -> None:
        """Process pending Tk events for at least ``seconds`` (0 = one pass)."""

        if self.use_mainloop:
            self._pump_mainloop(max(0.005, seconds))
            return
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            self.root.update_idletasks()
            self.root.update()
            if time.monotonic() >= deadline:
                return
            time.sleep(0.005)

    def _pump_mainloop(self, seconds: float) -> None:
        after_id = self.root.after(max(1, int(seconds * 1000)), self.root.quit)
        try:
            self.root.mainloop()
        finally:
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass

    def wait_until(
        self,
        predicate: Callable[[], T],
        *,
        timeout: float,
        description: str,
        evidence: Callable[[], Any] | None = None,
        poll: float = 0.05,
    ) -> T:
        """Poll ``predicate`` (pumping Tk) until truthy, else raise with evidence."""

        deadline = time.monotonic() + timeout
        last_error = ""
        while True:
            self.pump()
            try:
                value = predicate()
                if value:
                    self.trace.record("wait_satisfied", description=description)
                    return value
            except Exception as exc:  # predicate probes may race widget rebuilds
                last_error = f"{type(exc).__name__}: {exc}"
            if time.monotonic() >= deadline:
                snapshot = ""
                if evidence is not None:
                    try:
                        snapshot = f" evidence={evidence()!r}"
                    except Exception as exc:
                        snapshot = f" evidence-unavailable={exc!r}"
                self.trace.record("wait_timeout", description=description)
                raise JourneyTimeout(
                    f"timed out after {timeout:.1f}s waiting for: {description}"
                    f"{' (last probe error: ' + last_error + ')' if last_error else ''}{snapshot}"
                )
            time.sleep(poll)

    # -- lookup ---------------------------------------------------------
    def find(
        self,
        parent: tk.Misc,
        widget_class: type[tk.Misc] | tuple[type[tk.Misc], ...],
        *,
        text: str | None = None,
        textvariable: tk.Variable | None = None,
    ) -> tk.Misc:
        for widget in iter_widgets(parent):
            if not isinstance(widget, widget_class):
                continue
            if text is not None:
                try:
                    if str(widget.cget("text")) != text:
                        continue
                except tk.TclError:
                    continue
            if textvariable is not None:
                try:
                    if str(widget.cget("textvariable")) != str(textvariable):
                        continue
                except tk.TclError:
                    continue
            return widget
        raise WidgetNotFound(
            f"no {getattr(widget_class, '__name__', widget_class)} "
            f"text={text!r} textvariable={str(textvariable)!r}"
        )

    def find_button(self, parent: tk.Misc, text: str) -> tk.Misc:
        return self.find(parent, (ttk.Button, tk.Button), text=text)

    # -- operator actions -------------------------------------------------
    def select_tab(self, notebook: ttk.Notebook, title: str) -> None:
        for index, tab_id in enumerate(notebook.tabs()):
            if str(notebook.tab(tab_id, "text")).strip().lower() == title.strip().lower():
                notebook.select(tab_id)  # Tk itself emits <<NotebookTabChanged>>
                self.trace.record("select_tab", title=title, index=index)
                self.pump(0.05)
                return
        titles = [notebook.tab(t, "text") for t in notebook.tabs()]
        raise WidgetNotFound(f"tab {title!r} not in notebook tabs {titles}")

    def set_variable(self, variable: tk.Variable, value: Any, *, label: str) -> None:
        variable.set(value)
        self.trace.record("set_variable", label=label, value=value)
        self.pump(0.02)

    def type_in_entry(self, entry: tk.Entry | ttk.Entry, value: str, *, label: str) -> None:
        entry.focus_force()
        entry.delete(0, tk.END)
        entry.insert(0, value)
        entry.event_generate("<KeyRelease>")
        self.trace.record("type_in_entry", label=label, value=value)
        self.pump(0.02)

    def type_in_text(self, widget: tk.Text, value: str, *, label: str) -> None:
        widget.focus_force()
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)
        widget.event_generate("<KeyRelease>")
        self.trace.record("type_in_text", label=label, value=value)
        self.pump(0.02)

    def select_combobox(self, combo: ttk.Combobox, value: str, *, label: str) -> None:
        """Pick ``value`` exactly as a user selecting a list entry would."""

        allowed = [str(v) for v in combo.cget("values")]
        if value not in allowed:
            raise WidgetNotFound(f"{label}: {value!r} not among combobox values {allowed}")
        if str(combo.cget("state")) == "disabled":
            raise WidgetNotFound(f"{label}: combobox is disabled")
        combo.set(value)
        combo.event_generate("<<ComboboxSelected>>")
        self.trace.record("select_combobox", label=label, value=value)
        self.pump(0.05)

    def invoke(self, button: tk.Misc, *, label: str) -> None:
        """Click a Button/Radiobutton/Checkbutton via its own ``invoke``."""

        try:
            state = str(button.cget("state"))
        except tk.TclError:
            state = "normal"
        if state == "disabled":
            raise WidgetNotFound(f"{label}: control is disabled")
        button.invoke()  # type: ignore[attr-defined]
        self.trace.record("invoke", label=label)
        self.pump(0.05)

    def select_listbox_row(self, listbox: tk.Listbox, index: int, *, label: str) -> None:
        listbox.selection_clear(0, tk.END)
        listbox.selection_set(index)
        listbox.activate(index)
        listbox.event_generate("<<ListboxSelect>>")
        self.trace.record("select_listbox_row", label=label, index=index)
        self.pump(0.05)

    def select_tree_row(self, tree: ttk.Treeview, iid: str, *, label: str) -> None:
        """Click a Treeview row: select it and let the app's <<TreeviewSelect>> run."""

        if iid not in tree.get_children():
            raise WidgetNotFound(f"{label}: row {iid!r} is not in the tree")
        tree.selection_set(iid)
        tree.focus(iid)
        tree.event_generate("<<TreeviewSelect>>")
        self.trace.record("select_tree_row", label=label, row=iid)
        self.pump(0.1)

    def close_via_window_manager(self) -> None:
        """Trigger the same handler the window's close button runs."""

        handler = self.root.protocol("WM_DELETE_WINDOW")
        self.trace.record("close_window")
        if handler:
            self.root.tk.call(handler)
        else:  # pragma: no cover - MainWindowV2 always registers a handler
            self.root.destroy()
