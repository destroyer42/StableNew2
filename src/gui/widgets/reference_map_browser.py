"""Searchable reference-map list with a bounded thumbnail (PR-GUI-UX-550).

A presentation widget for the one ``<WebUI root>/models/OpenPose`` library. It lists the identities it is given (the
registry-backed scan stays with the owner), filters them with ``filter_entries``, reports the operator's pick through
``on_select`` and shows a thumbnail made by the existing bounded library reader (``read_library_image`` and
``thumbnail_png``). It never scans, hashes, writes or decides execution, and a thumbnail is an inspection aid, not
evidence that the compiler or Forge will admit the map.

Image reads run on a tracked worker and come back through a polled queue; a newer selection, a hidden (redacted) name
or a destroyed widget makes a late result a no-op. Nothing is read until the widget is first shown (``lazy``).
"""

from __future__ import annotations

import base64
import queue
import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import ttk
from typing import Any

from src.conditioning.openpose_catalog import LibraryEntry, filter_entries
from src.conditioning.openpose_library import (
    OpenPoseInputError,
    library_root,
    read_library_image,
    thumbnail_png,
)
from src.controller.content_visibility_resolver import REDACTED_TEXT

#: ``work`` runs off the Tk thread; ``done(result, error)`` runs on it.
Runner = Callable[[Callable[[], Any], Callable[[Any, Exception | None], None]], None]

THUMB_EDGE = 160
_POLL_MS = 40


class ReferenceMapBrowser(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        on_select: Callable[[str], None],
        registry_factory: Callable[[], Any] | None = None,
        runner: Runner | None = None,
        lazy: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(parent, **kwargs)
        self._on_select = on_select
        self._registry_factory = registry_factory
        self._runner: Runner = runner or self._threaded_runner
        self._lazy = lazy
        self._entries: tuple[LibraryEntry, ...] = ()
        self._hidden: Callable[[str], bool] = lambda _identity: False
        self._visible: list[LibraryEntry] = []
        self._selected = ""
        self._wanted = ""
        self._pending = ""
        self._shown = ""
        self._request = 0
        self._photo: tk.PhotoImage | None = None
        self._destroyed = False
        self._after_ids: set[str] = set()
        self._suppress = False
        self.columnconfigure(0, weight=1)
        self.search_var = tk.StringVar(value="")
        self.search_entry = ttk.Entry(self, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=0, sticky="ew")
        self.search_var.trace_add("write", lambda *_: self._apply_filter())
        self.empty_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.empty_var, wraplength=420, justify="left").grid(
            row=1, column=0, columnspan=2, sticky="ew"
        )
        list_frame = ttk.Frame(self)
        list_frame.grid(row=2, column=0, sticky="nsew", pady=(4, 0))
        list_frame.columnconfigure(0, weight=1)
        self.listbox = tk.Listbox(list_frame, height=5, exportselection=False, activestyle="none")
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.listbox.bind("<<ListboxSelect>>", self._on_list_select)
        preview = ttk.Frame(self)
        preview.grid(row=2, column=1, sticky="n", padx=(8, 0), pady=(4, 0))
        self.thumbnail_label = ttk.Label(
            preview, text="No map selected", anchor="center", justify="center"
        )
        self.thumbnail_label.configure(width=22)
        self.thumbnail_label.grid(row=0, column=0)
        self.identity_var = tk.StringVar(value="")
        ttk.Label(
            preview, textvariable=self.identity_var, wraplength=THUMB_EDGE + 40, justify="center"
        ).grid(row=1, column=0, pady=(4, 0))
        self.facts_var = tk.StringVar(value="")
        ttk.Label(
            preview, textvariable=self.facts_var, wraplength=THUMB_EDGE + 40, justify="center"
        ).grid(row=2, column=0)
        self.bind("<Map>", lambda _event: self._maybe_load(), add="+")

    # ------------------------------------------------------------------ public API

    def set_entries(
        self,
        entries: Sequence[LibraryEntry],
        *,
        hidden: Callable[[str], bool] | None = None,
        empty_text: str = "",
    ) -> None:
        self._entries = tuple(entries)
        if hidden is not None:
            self._hidden = hidden
        self.empty_var.set("" if self._entries else empty_text)
        self._apply_filter()

    def set_enabled(self, enabled: bool) -> None:
        self.search_entry.configure(state="normal" if enabled else "disabled")
        self.listbox.configure(state="normal" if enabled else "disabled")

    def set_selection(self, identity: str) -> None:
        """Show ``identity`` as the current pick (never fires ``on_select``)."""

        self._selected = identity
        self._select_in_list(identity)
        if not identity:
            self._reset("No map selected", "")
            return
        if self._hidden(identity):
            self._reset(REDACTED_TEXT, REDACTED_TEXT)
            return
        self.identity_var.set(identity)
        if identity == self._wanted:
            return
        self._request += 1  # supersede anything in flight for the previous pick
        self._wanted, self._pending, self._shown = identity, "", ""
        self._photo = None
        self.facts_var.set("")
        self.thumbnail_label.configure(image="", text="Loading preview…")
        self._maybe_load()

    def visible_identities(self) -> list[str]:
        return [entry.identity for entry in self._visible]

    # ------------------------------------------------------------------ list

    def _apply_filter(self) -> None:
        shown = [entry for entry in self._entries if not self._hidden(entry.identity)]
        self._visible = filter_entries(shown, self.search_var.get())
        self._suppress = True
        try:
            self.listbox.delete(0, "end")
            for entry in self._visible:
                self.listbox.insert("end", entry.identity)
            self._select_in_list(self._selected)
        finally:
            self._suppress = False

    def _select_in_list(self, identity: str) -> None:
        self.listbox.selection_clear(0, "end")
        for index, entry in enumerate(self._visible):
            if entry.identity == identity:
                self.listbox.selection_set(index)
                self.listbox.see(index)
                return

    def _on_list_select(self, _event: object | None = None) -> None:
        if self._suppress:
            return
        picked = self.listbox.curselection()  # type: ignore[no-untyped-call]  # typeshed leaves it untyped
        if picked and picked[0] < len(self._visible):
            self._on_select(self._visible[picked[0]].identity)

    # ------------------------------------------------------------------ thumbnail

    def _reset(self, text: str, identity_text: str) -> None:
        self._request += 1
        self._wanted = self._pending = self._shown = ""
        self._photo = None
        self.identity_var.set(identity_text)
        self.facts_var.set("")
        self.thumbnail_label.configure(image="", text=text)

    def _maybe_load(self) -> None:
        wanted = self._wanted
        if not wanted or wanted in (self._pending, self._shown) or self._destroyed:
            return
        if self._lazy and not self._mapped():
            return
        request = self._request
        self._pending = wanted
        factory = self._registry_factory

        def work() -> tuple[bytes, dict[str, Any]]:
            from src.assets import AssetRegistry
            from src.conditioning.openpose_diagnostics import input_image_facts

            registry = factory() if factory is not None else AssetRegistry()
            _path, image = read_library_image(
                library_root(getattr(registry, "webui_root", None)), wanted
            )
            return thumbnail_png(image.data, THUMB_EDGE), input_image_facts(image.data)

        def done(result: Any, error: Exception | None) -> None:
            if not self._alive() or request != self._request:
                return  # a newer pick, a redaction or a closed editor owns the preview
            self._pending = ""
            if error is not None or result is None:
                text = (
                    "Missing or unreadable image"
                    if isinstance(error, OpenPoseInputError)
                    else "Preview unavailable"
                )
                self.thumbnail_label.configure(image="", text=text)
                self.facts_var.set("")
                return
            png, facts = result
            try:
                self._photo = tk.PhotoImage(data=base64.b64encode(png).decode("ascii"))
            except tk.TclError:
                self._photo = None
                self.thumbnail_label.configure(image="", text="Preview unavailable")
                return
            self._shown = wanted
            self.thumbnail_label.configure(image=self._photo, text="")
            note = f"{facts['width']}x{facts['height']} {facts['format'] or ''}".strip()
            if facts.get("has_transparency"):
                note += "; has transparent pixels"
            self.facts_var.set(note)

        self._runner(work, done)

    def _mapped(self) -> bool:
        try:
            return bool(self.winfo_ismapped())
        except tk.TclError:
            return False

    def _alive(self) -> bool:
        if self._destroyed:
            return False
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def _threaded_runner(
        self, work: Callable[[], Any], done: Callable[[Any, Exception | None], None]
    ) -> None:
        box: queue.Queue[tuple[Any, Exception | None]] = queue.Queue(maxsize=1)

        def target() -> None:
            try:
                box.put((work(), None))
            except Exception as exc:  # noqa: BLE001 - reported on Tk; a worker never raises into the thread registry
                box.put((None, exc))

        from src.utils.thread_registry import get_thread_registry

        get_thread_registry().spawn(
            target=target,
            name="ReferenceMap-Preview",
            daemon=False,
            purpose="Decode a bounded reference-map thumbnail",
        )
        self._poll(box, done)

    def _poll(
        self,
        box: queue.Queue[tuple[Any, Exception | None]],
        done: Callable[[Any, Exception | None], None],
    ) -> None:
        if not self._alive():
            return
        try:
            result, error = box.get_nowait()
        except queue.Empty:
            handle: list[str] = []

            def tick() -> None:
                self._after_ids.discard(handle[0])
                self._poll(box, done)

            handle.append(self.after(_POLL_MS, tick))
            self._after_ids.add(handle[0])
            return
        done(result, error)

    def destroy(self) -> None:
        self._destroyed = True
        for handle in self._after_ids:
            try:
                self.after_cancel(handle)
            except tk.TclError:
                pass
        super().destroy()


__all__ = ["ReferenceMapBrowser", "Runner"]
