"""LEARN-JOIN: one read-only window showing keep and favourite rates by recipe.

It reads on a worker and shows; it changes no setting, record or job and offers no action that would.
"""

from __future__ import annotations

import logging
import queue
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from src.gui.theme_v2 import apply_toplevel_theme
from src.learning.decision_rates import (
    FACTOR_BATCH,
    FACTOR_MODEL,
    MIN_IMAGES_PER_SIDE,
    OptionRow,
    Report,
    percent,
    summary_lines,
    tag_text,
)
from src.utils.thread_registry import get_thread_registry

log = logging.getLogger(__name__)

_COLUMNS = (
    ("decided", "Decided", 70),
    ("kept", "Kept", 60),
    ("favorites", "Favourite", 75),
    ("tags", "Reason tags", 190),
    ("difference", "Compared with the rest", 330),
)
_NOTE = (
    "Observed, not controlled: packs, models and days are mixed, so a difference shows what you kept, not why. "
    f"A difference appears only with at least {MIN_IMAGES_PER_SIDE} images on each side and a 95% interval "
    "(corrected for the number of options) that excludes zero; telling 85% from 80% takes about 900 each. "
    "Nothing here changes a setting or a recommendation."
)


class KeepRatesWindow(tk.Toplevel):
    """``load`` is blocking and returns a :class:`Report`; it runs on a worker."""

    def __init__(self, master: tk.Misc, load: Callable[[], Report]) -> None:
        super().__init__(master)
        self.title("What you keep")
        self.geometry(
            f"{min(1100, self.winfo_screenwidth() - 24)}x{min(620, self.winfo_screenheight() - 96)}"
        )
        apply_toplevel_theme(self)
        self._load = load
        self._report: Report | None = None
        self._results: queue.Queue[tuple[Report | None, str]] = queue.Queue()
        self._poll_id: str | None = None
        self._loading = False

        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        self.summary_var = tk.StringVar(value="Reading your decisions...")
        ttk.Label(top, textvariable=self.summary_var, wraplength=1060, justify="left").pack(
            anchor="w"
        )

        picker = ttk.Frame(self, padding=(8, 0))
        picker.pack(fill="x")
        ttk.Label(picker, text="Show").pack(side="left")
        self.factor_var = tk.StringVar(value=FACTOR_MODEL)
        self.factor_box = ttk.Combobox(
            picker, textvariable=self.factor_var, state="readonly", width=28
        )
        self.factor_box.pack(side="left", padx=(6, 12))
        ttk.Label(picker, text="Model").pack(side="left")
        self.model_var = tk.StringVar(value="")
        self.model_box = ttk.Combobox(
            picker, textvariable=self.model_var, state="disabled", width=52
        )
        self.model_box.pack(side="left", padx=(6, 12))
        self.refresh_button = ttk.Button(picker, text="Refresh", command=self.reload)
        self.refresh_button.pack(side="right")
        self.factor_box.bind("<<ComboboxSelected>>", lambda _event: self._factor_chosen())
        self.model_box.bind("<<ComboboxSelected>>", lambda _event: self._model_chosen())

        table = ttk.Frame(self, padding=8)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=[key for key, _title, _width in _COLUMNS])
        self.tree.heading("#0", text="Option")
        self.tree.column("#0", width=260, stretch=True)
        for key, title, width in _COLUMNS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, stretch=key == "difference")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        ttk.Label(self, text=_NOTE, wraplength=1060, justify="left", padding=(8, 0, 8, 8)).pack(
            anchor="w", fill="x"
        )
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.reload()

    # -- loading ------------------------------------------------------------------------------------------------

    def reload(self) -> None:
        if self._loading:
            return
        self._loading = True
        self.refresh_button.configure(state="disabled")
        self.summary_var.set("Reading your decisions...")
        load, results = self._load, self._results

        def work() -> None:
            try:
                results.put((load(), ""))
            except Exception as exc:  # noqa: BLE001 - shown in the window
                log.warning("The keep-rates report could not be read", exc_info=True)
                results.put((None, type(exc).__name__))

        get_thread_registry().spawn(
            target=work, name="learning-keep-rates", purpose="read keep rates"
        )
        self._poll_id = self.after(75, self._poll)

    def _poll(self) -> None:
        self._poll_id = None
        try:
            report, error = self._results.get_nowait()
        except queue.Empty:
            self._poll_id = self.after(75, self._poll)
            return
        self._loading = False
        self.refresh_button.configure(state="normal")
        if report is None:
            self.summary_var.set(f"The report could not be read ({error}). See the log.")
            return
        self.show(report)

    def _on_destroy(self, event: Any) -> None:
        if event.widget is self and self._poll_id is not None:
            self.after_cancel(self._poll_id)
            self._poll_id = None

    # -- showing ------------------------------------------------------------------------------------------------

    def show(self, report: Report) -> None:
        self._report = report
        self.summary_var.set("\n".join(summary_lines(report)))
        factors = sorted({factor for groups in report.by_model.values() for factor in groups})
        self.factor_box.configure(values=[FACTOR_MODEL, *factors, FACTOR_BATCH])
        if self.factor_var.get() not in (FACTOR_MODEL, FACTOR_BATCH, *factors):
            self.factor_var.set(FACTOR_MODEL)
        self._factor_chosen()

    def _factor_chosen(self) -> None:
        report = self._report
        if report is None:
            return
        factor = self.factor_var.get()
        if factor in (FACTOR_MODEL, FACTOR_BATCH):
            self.model_box.configure(state="disabled", values=[])
            self.model_var.set("")
        else:
            # Most-decided model first; only models that have this factor.
            models = [
                row.option for row in report.models if factor in report.by_model.get(row.option, {})
            ]
            self.model_box.configure(state="readonly", values=models)
            if self.model_var.get() not in models:
                self.model_var.set(models[0] if models else "")
        self._model_chosen()

    def _rows(self) -> tuple[OptionRow, ...]:
        report = self._report
        if report is None:
            return ()
        factor = self.factor_var.get()
        if factor == FACTOR_MODEL:
            return report.models
        if factor == FACTOR_BATCH:
            return report.batches
        return report.by_model.get(self.model_var.get(), {}).get(factor, ())

    def _model_chosen(self) -> None:
        self.tree.delete(*self.tree.get_children())
        rows = self._rows()
        for row in rows:
            counts = row.counts
            self.tree.insert(
                "",
                "end",
                text=row.option,
                values=(
                    counts.decided,
                    percent(counts.kept, counts.decided),
                    percent(counts.favorites, counts.decided),
                    tag_text(counts),
                    row.difference,
                ),
            )
        if not rows and self._report is not None:
            empty = (
                "No decided images from a named batch yet."
                if self.factor_var.get() == FACTOR_BATCH
                else "Nothing to show yet."
            )
            self.tree.insert("", "end", text=empty)


def open_keep_rates(owner: Any) -> KeepRatesWindow:
    """Open (or raise) the window for the Learning tab ``owner``."""

    from src.gui.controllers.keep_rates_loader import load_keep_rates
    from src.learning.learning_paths import get_learning_records_path
    from src.review.review_lineage import repository_of
    from src.state.workspace_paths import workspace_paths

    existing = getattr(owner, "_keep_rates_window", None)
    if existing is not None and existing.winfo_exists():
        existing.lift()
        existing.reload()
        return existing
    writer = getattr(owner, "learning_record_writer", None)
    records = getattr(writer, "records_path", None) or get_learning_records_path(
        create_parent=False
    )
    repository = repository_of(getattr(owner, "app_controller", None))
    database = getattr(repository, "path", None) or workspace_paths.job_repository()
    window = KeepRatesWindow(owner, lambda: load_keep_rates(records, database))
    owner._keep_rates_window = window
    return window
