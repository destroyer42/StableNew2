"""A word-wrapped, multi-line text field that mirrors a ``StringVar`` (Storyboard Continue prompts). Presentation only.

A single-line ``ttk.Entry`` scrolls sideways and crawls on a long prompt. This field wraps instead, is a few lines tall
at rest and grows while it has focus, so a long prompt can be read and edited without scrolling. The variable stays the
single source of truth for everything else: it is updated as the text is edited and updates the text when it is set
(``set_rows``, a restore), so consumers keep reading and writing the same ``StringVar``.

A prompt is one logical line, as the Continue service expects, so Enter inserts nothing and pasted line breaks become
spaces. Tab and Shift+Tab move focus rather than inserting a tab character.
"""

from __future__ import annotations

import tkinter as tk
from typing import Any

from src.gui import theme_v2
from src.gui.widgets.scrollable_frame_v2 import forward_wheel

REST_LINES = 3
FOCUS_LINES = 8
#: A grown field shrinks this long after losing focus, not at once: a click on a control in the next row would
#: otherwise find that row moved out from under the pointer between button press and release.
FOCUS_SHRINK_MS = 250


class MirroredText(tk.Text):
    def __init__(
        self,
        master: tk.Misc,
        variable: tk.StringVar,
        *,
        rest_lines: int = REST_LINES,
        focus_lines: int = FOCUS_LINES,
        **kwargs: Any,
    ) -> None:
        options: dict[str, Any] = {"wrap": "word", "width": 20, "height": rest_lines, "undo": True}
        options.update(kwargs)
        super().__init__(master, **options)
        theme_v2.style_text_widget(self)
        self._variable = variable
        self._rest_lines = rest_lines
        self._focus_lines = focus_lines
        self._busy = False
        self._shrink_after: str | None = None
        self._trace_id: str | None = variable.trace_add("write", self._from_variable)
        self._from_variable()
        self.bind("<<Modified>>", self._on_modified)
        for sequence in ("<Return>", "<KP_Enter>"):
            self.bind(sequence, lambda _event: "break")
        self.bind("<Tab>", lambda event: self._move_focus(event, backwards=False))
        for sequence in ("<Shift-Tab>", "<ISO_Left_Tab>"):
            self.bind(sequence, lambda event: self._move_focus(event, backwards=True))
        self.bind("<Control-a>", self._select_all)
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind(sequence, self._on_wheel)
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self.bind("<Destroy>", self._on_destroy, add="+")

    # ------------------------------------------------------------------ text <-> variable

    def _from_variable(self, *_args: object) -> None:
        if self._busy:
            return
        value = self._variable.get()
        if value == self.get("1.0", "end-1c"):
            return
        self._replace(value)
        self.edit_modified(False)

    def _replace(self, value: str) -> None:
        self._busy = True
        try:
            self.delete("1.0", "end")
            self.insert("1.0", value)
        finally:
            self._busy = False

    def _on_modified(self, _event: tk.Event) -> None:
        if not self.edit_modified():
            return
        self.edit_modified(False)
        text = self.get("1.0", "end-1c")
        flat = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
        if flat != text:
            self._replace(flat)
            self.edit_modified(False)
            self.mark_set("insert", "end-1c")
        if self._variable.get() != flat:
            self._busy = True
            try:
                self._variable.set(flat)
            finally:
                self._busy = False

    # ------------------------------------------------------------------ keys

    def _move_focus(self, event: tk.Event, *, backwards: bool) -> str:
        target = event.widget.tk_focusPrev() if backwards else event.widget.tk_focusNext()
        if target is not None:
            target.focus_set()
        return "break"

    def _select_all(self, _event: tk.Event) -> str:
        self.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _on_wheel(self, event: tk.Event) -> str | None:
        """A field whose text fits has nothing to scroll, so the wheel goes to the panel around it (else its own)."""

        if self.yview() != (0.0, 1.0):
            return None
        return forward_wheel(self, event)

    # ------------------------------------------------------------------ growing with focus

    def _on_focus_in(self, _event: tk.Event) -> None:
        self._cancel_shrink()
        self.configure(height=self._focus_lines)

    def _on_focus_out(self, _event: tk.Event) -> None:
        self._cancel_shrink()
        self._shrink_after = self.after(FOCUS_SHRINK_MS, self._shrink)

    def _shrink(self) -> None:
        self._shrink_after = None
        if self.winfo_exists():
            self.configure(height=self._rest_lines)

    def _cancel_shrink(self) -> None:
        if self._shrink_after is not None:
            self.after_cancel(self._shrink_after)
            self._shrink_after = None

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        self._cancel_shrink()
        if self._trace_id is not None:
            try:
                self._variable.trace_remove("write", self._trace_id)
            except tk.TclError:
                pass
            self._trace_id = None


__all__ = ["FOCUS_LINES", "FOCUS_SHRINK_MS", "REST_LINES", "MirroredText"]
