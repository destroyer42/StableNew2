"""DESK-QUICK: the batch builder's model list, with search and a status per model.

Search only changes which rows are shown; selected models always stay visible, so nothing is queued from a hidden
row. Status (completed txt2img jobs here, N1 warnings, missing files) is read once on a tracked worker when the list
first appears and polled from the Tk thread; it informs and never blocks a selection.
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from tkinter import ttk
from typing import Any

from src.image_backends.model_policy_warnings import shown_warning_for
from src.pipeline.policy_warnings import PolicyWarning
from src.services.model_file_health import ModelFileHealth
from src.utils.checkpoint_identity import checkpoint_key
from src.utils.thread_registry import get_thread_registry

logger = logging.getLogger(__name__)

_POLL_MS = 200


@dataclass(frozen=True)
class ModelStatusReport:
    #: Completed txt2img jobs per canonical checkpoint key (``None``: job history could not be read).
    run_counts: Mapping[str, int] | None = None
    health: ModelFileHealth = field(default_factory=ModelFileHealth)
    #: N1 warnings by internal model name, in addition to the ones the picker published.
    warnings: Mapping[str, PolicyWarning] = field(default_factory=dict)


#: ``(cancelled) -> report``; blocking, so it runs on a worker.
LoadModelStatus = Callable[[Callable[[], bool]], ModelStatusReport]


def model_status_loader(controller: Any) -> LoadModelStatus:
    """The application's status sources. Called on the Tk thread: it only captures in-memory references."""

    resources = getattr(getattr(controller, "app_state", None), "resources", None) or {}
    entries = tuple(resources.get("models") or ())
    root = getattr(getattr(controller, "resource_service", None), "root_path", None)

    def load(cancelled: Callable[[], bool]) -> ModelStatusReport:
        from src.history.observed_execution import installed_run_counts
        from src.services.model_file_health import collect_model_file_health

        try:
            counts = installed_run_counts(cancelled=cancelled)
        except Exception:  # noqa: BLE001 - history is optional context
            logger.warning("Run counts for the model list could not be read", exc_info=True)
            counts = None
        return ModelStatusReport(run_counts=counts, health=collect_model_file_health(entries, root))

    return load


class MissingFilesWindow(tk.Toplevel):
    def __init__(self, parent: Any, lines: Sequence[str]) -> None:
        super().__init__(parent)
        self.title("Models with missing files")
        self.geometry("760x420")
        self.body = tk.Text(self, wrap="word")
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.body.yview)
        scroll.pack(side="right", fill="y")
        self.body.pack(side="left", fill="both", expand=True)
        self.body.configure(yscrollcommand=scroll.set)
        self.body.insert("1.0", "\n".join(lines))
        self.body.configure(state="disabled")


class ModelListPicker(ttk.Frame):
    """Search box, extended-selection list, one detail line and the missing-files button."""

    def __init__(
        self,
        parent: Any,
        models: Sequence[tuple[str, str]],
        *,
        load_status: LoadModelStatus | None = None,
    ) -> None:
        super().__init__(parent)
        self._models = list(models)  # (display, internal)
        self._shown: list[tuple[str, str]] = []
        self._load_status = load_status
        self._report = ModelStatusReport()
        self._loaded = False
        self._result: ModelStatusReport | None = None
        self._cancel = threading.Event()
        self._poll_id: str | None = None
        self.worker: threading.Thread | None = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        search = ttk.Frame(self)
        search.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(search, text="Search").pack(side="left")
        self.search_var = tk.StringVar(master=self, value="")
        ttk.Entry(search, textvariable=self.search_var).pack(
            side="left", fill="x", expand=True, padx=(4, 0)
        )
        self.listbox = tk.Listbox(self, selectmode="extended", exportselection=False, height=8)
        self.listbox.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.listbox.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=scroll.set)
        footer = ttk.Frame(self)
        footer.grid(row=2, column=0, columnspan=2, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.detail_label = ttk.Label(footer, text="", wraplength=320, justify="left")
        self.detail_label.grid(row=0, column=0, sticky="w")
        self.missing_button = ttk.Button(
            footer, text="Missing files…", command=self.show_missing_files
        )
        self.missing_button.grid(row=0, column=1, sticky="ne")

        self.search_var.trace_add("write", lambda *_: self._render())
        self.listbox.bind("<ButtonRelease-1>", self._on_click, add="+")
        self.listbox.bind("<Map>", self._on_map, add="+")
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._render()

    # -- selection ---------------------------------------------------------------------------------------------

    def selected(self) -> list[str]:
        return [self._shown[index][1] for index in self.listbox.curselection()]  # type: ignore[no-untyped-call]

    def select(self, names: Sequence[str]) -> None:
        """Select models by display or internal name (rows hidden by the search are shown first)."""

        wanted = {name for name in names if name}
        keep = set(self.selected()) | {
            internal for display, internal in self._models if wanted & {display, internal}
        }
        self._render(keep)

    def set_models(self, models: Sequence[tuple[str, str]]) -> None:
        keep = set(self.selected())
        self._models = list(models)
        self._render(keep)

    # -- rows --------------------------------------------------------------------------------------------------

    def _render(self, keep: set[str] | None = None) -> None:
        selected = set(self.selected()) if keep is None else keep
        words = self.search_var.get().lower().split()
        self._shown = [
            (display, internal)
            for display, internal in self._models
            if internal in selected
            or all(word in f"{display} {internal}".lower() for word in words)
        ]
        top = self.listbox.yview()[0]
        self.listbox.delete(0, "end")
        for index, (display, internal) in enumerate(self._shown):
            self.listbox.insert("end", self._row(display, internal))
            if internal in selected:
                self.listbox.selection_set(index)
        self.listbox.yview_moveto(top)

    def _warning(self, internal: str) -> PolicyWarning | None:
        return self._report.warnings.get(internal) or shown_warning_for(internal)

    def _runs(self, internal: str) -> int:
        return int((self._report.run_counts or {}).get(checkpoint_key(internal), 0))

    def _row(self, display: str, internal: str) -> str:
        parts = [display]
        runs = self._runs(internal)
        if runs:
            parts.append(f"ran {runs} {'time' if runs == 1 else 'times'} here")
        if self._warning(internal) is not None:
            parts.append("warning")
        if self._report.health.missing_for(internal):
            parts.append("missing files")
        return "  · ".join(parts)

    def show_detail(self, index: int) -> None:
        if not 0 <= index < len(self._shown):
            return
        _display, internal = self._shown[index]
        lines = [f"Missing: {problem}" for problem in self._report.health.missing_for(internal)]
        warning = self._warning(internal)
        if warning is not None:
            lines.append(warning.text())
        self.detail_label.configure(text="\n".join(lines)[:600])

    def _on_click(self, event: Any) -> None:
        self.show_detail(int(self.listbox.nearest(event.y)))  # type: ignore[no-untyped-call]

    # -- status ------------------------------------------------------------------------------------------------

    def apply_status(self, report: ModelStatusReport) -> None:
        self._report, self._loaded = report, True
        self._render()

    def refresh_status(self) -> None:
        """Start one background read; a read already running is left to finish."""

        load = self._load_status
        if load is None or (self.worker is not None and self.worker.is_alive()):
            return
        registry = get_thread_registry()

        def cancelled() -> bool:
            return self._cancel.is_set() or registry.is_shutdown_requested()

        def work() -> None:
            try:
                self._result = load(cancelled)
            except InterruptedError:
                return
            except Exception:  # noqa: BLE001 - the list works without status
                logger.warning("Model status could not be read", exc_info=True)

        try:
            self.worker = registry.spawn(
                target=work, name="BatchModelStatus", purpose="Read-only batch model list status"
            )
        except Exception:  # noqa: BLE001 - no worker only means no status
            logger.warning("Model status worker could not start", exc_info=True)
            return
        self._schedule_poll()

    def _schedule_poll(self) -> None:
        if self._poll_id is None:
            self._poll_id = self.after(_POLL_MS, self.poll_status)

    def poll_status(self) -> None:
        """Tk thread: apply a finished read, or look again while one is running."""

        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
            self._poll_id = None
        result, self._result = self._result, None
        if result is not None:
            self.apply_status(result)
        elif self.worker is not None and self.worker.is_alive():
            self._schedule_poll()

    def show_missing_files(self) -> MissingFilesWindow:
        if self._loaded:
            lines = self._report.health.lines()
        else:
            self.refresh_status()
            lines = ["Still checking the model files. Close this and open it again in a moment."]
        return MissingFilesWindow(self, lines)

    def _on_map(self, _event: Any) -> None:
        if not self._loaded:
            self.refresh_status()

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        self._cancel.set()
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
            self._poll_id = None


__all__ = [
    "MissingFilesWindow",
    "ModelListPicker",
    "ModelStatusReport",
    "model_status_loader",
]
