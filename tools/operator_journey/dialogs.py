"""Scripted answers for native Tk message boxes (a bounded semantic test seam).

Native ``messagebox`` dialogs block a Tk event loop that a journey pumps itself.
The seam answers each yes/no prompt as the operator would and records the exact
prompt text, so the journey can assert what the UI told the operator before
confirming.  Only the dialog boundary is replaced; the button command that opens
the dialog, and everything it does afterwards, is the production code.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from tkinter import messagebox


@dataclass
class DialogRecord:
    kind: str
    title: str
    message: str
    answer: bool | None = None


@dataclass
class DialogSeam:
    answers: list[bool] = field(default_factory=list)
    default: bool = True
    calls: list[DialogRecord] = field(default_factory=list)

    def script(self, *answers: bool) -> None:
        self.answers = list(answers)

    def _answer(self) -> bool:
        return self.answers.pop(0) if self.answers else self.default

    def askyesno(self, title: str = "", message: str = "", **_: object) -> bool:
        answer = self._answer()
        self.calls.append(DialogRecord("askyesno", str(title), str(message), answer))
        return answer

    def info(self, kind: str) -> object:
        def record(title: str = "", message: str = "", **_: object) -> str:
            self.calls.append(DialogRecord(kind, str(title), str(message)))
            return "ok"

        return record


@contextmanager
def scripted_dialogs(seam: DialogSeam) -> Iterator[DialogSeam]:
    saved = (messagebox.askyesno, messagebox.showinfo, messagebox.showwarning, messagebox.showerror)
    messagebox.askyesno = seam.askyesno  # type: ignore[assignment]
    messagebox.showinfo = seam.info("showinfo")  # type: ignore[assignment]
    messagebox.showwarning = seam.info("showwarning")  # type: ignore[assignment]
    messagebox.showerror = seam.info("showerror")  # type: ignore[assignment]
    try:
        yield seam
    finally:
        (
            messagebox.askyesno,
            messagebox.showinfo,
            messagebox.showwarning,
            messagebox.showerror,
        ) = saved
