"""Small operator-level helpers shared by the golden journeys (visible controls only)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from tools.operator_journey.golden.session import GoldenRun, JourneyAbort
from tools.operator_journey.tk_driver import JourneyTimeout, iter_widgets


def set_toggle(run: GoldenRun, parent: tk.Misc, text: str, wanted: bool) -> None:
    """Click a checkbutton only if it is not already in the wanted state."""

    d = run.driver
    button = d.find(parent, (ttk.Checkbutton, tk.Checkbutton), text=text)
    if bool(int(d.root.getvar(str(button.cget("variable"))))) != wanted:  # type: ignore[attr-defined]
        d.invoke(button, label=f"toggle {text}")


def combo_for(run: GoldenRun, parent: tk.Misc, variable: tk.Variable) -> ttk.Combobox:
    return run.driver.find(parent, ttk.Combobox, textvariable=variable)  # type: ignore[return-value]


def visible_text(root: tk.Misc, *, contains: str) -> str | None:
    """The first visible label/text whose content contains ``contains`` (what the operator can read)."""

    for widget in iter_widgets(root):
        try:
            if not widget.winfo_viewable():
                continue
            if isinstance(widget, (ttk.Label, tk.Label)):
                text = str(widget.cget("text"))
            elif isinstance(widget, tk.Text):
                text = widget.get("1.0", "end-1c")
            else:
                continue
        except tk.TclError:
            continue
        if contains in text:
            return text
    return None


def wait_text(
    run: GoldenRun, root: tk.Misc, needle: str, *, description: str, timeout: float = 20
) -> str:
    try:
        return run.driver.wait_until(
            lambda: visible_text(root, contains=needle), timeout=timeout, description=description
        )
    except JourneyTimeout as exc:
        raise JourneyAbort(str(exc)) from exc


def select_history_row(run: GoldenRun, job_id: str) -> Any:
    """Open the pipeline History list and click the row for ``job_id`` like an operator."""

    panel = run.window.pipeline_tab.history_panel
    run.driver.invoke(panel.refresh_btn, label="Refresh History")

    def row() -> str | None:
        return next((item for item, job in panel._item_to_job.items() if job == job_id), None)

    iid = run.driver.wait_until(row, timeout=20, description=f"History lists job {job_id}")
    run.driver.select_tree_row(panel.history_tree, iid, label=f"History row {job_id}")
    return panel
