"""Tk "Batches" view inside the Queue/History operator workflow (PR-BATCH-OPS-201).

A thin renderer over ``BatchOperationsSession``: it owns widgets and dialogs, never state or queue/repository
access. All repository reads and operations run off the Tk thread through the session; this module only draws
the latest derived projection, keeps the operator's selection across refreshes and routes hand-offs to the
existing Review / Movie Clips / folder seams.
"""

from __future__ import annotations

import time
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk
from typing import Any

from src.gui.batch_retry_dialog import BatchRetryDialog
from src.gui.tooltip import attach_tooltip
from src.gui.ui_dispatcher import TkUiDispatcher
from src.gui.view_contracts.batch_operations_contract import BatchOperationsSession, BatchViewHooks
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.queue.batch_membership import BatchKey
from src.queue.failure_triage import CATEGORY_LABELS
from src.queue.job_model import JobStatus
from src.utils.thread_registry import get_thread_registry

ALL_STATUSES = "All statuses"
ALL_CATEGORIES = "All failure categories"
_STATUS_CHOICES = {status.value.upper(): status for status in JobStatus}
_CATEGORY_CHOICES = {label: category for category, label in CATEGORY_LABELS.items()}
# The right column is ~400px wide: triage-critical columns come first and the rest scroll horizontally.
_BATCH_COLUMNS = (
    ("kind", "Kind", 100), ("id", "ID", 66), ("state", "State", 150),
    ("progress", "Finished", 84), ("jobs", "Jobs / sources", 130),
)
_JOB_COLUMNS = (
    ("pos", "#", 30), ("source", "Source", 120), ("status", "Status", 98), ("failure", "Failure", 150),
    ("model", "Model / workflow", 110), ("priority", "Priority", 58), ("outputs", "Outputs", 74),
    ("retry", "Retried as", 90),
)


class BatchOperationsPanelV2(ttk.Frame):
    REFRESH_MIN_INTERVAL_S = 2.0

    def __init__(
        self,
        master: tk.Misc,
        *,
        service: Any,
        main_window_provider: Callable[[], Any] | None = None,
        folder_opener: Callable[[str], None] | None = None,
        runner: BackgroundWorkRunner | None = None,
        clock: Callable[[], float] = time.monotonic,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self._main_window_provider = main_window_provider or (lambda: None)
        self._folder_opener = folder_opener
        self._clock = clock
        self._last_refresh = float("-inf")
        self._destroyed = False
        self._rendering = False
        self._last_batches: tuple[Any, ...] | None = None
        self._last_jobs: tuple[Any, ...] | None = None
        self._last_detail = ""
        self.columnconfigure(0, weight=1)
        self.session: BatchOperationsSession | None = None
        if service is None:
            ttk.Label(self, text="Batch operations are unavailable: no job service is attached.").grid(
                row=0, column=0, sticky="w", padx=8, pady=8)
            return
        self._build()
        self.session = BatchOperationsSession(
            service=service,
            runner=runner or self._default_runner(),
            hooks=BatchViewHooks(
                confirm_cancel=self._confirm_cancel,
                review_retry=self._review_retry,
                open_in_review=self._open_in_review,
                open_folder=self._open_folder,
                open_movie_clips=self._open_movie_clips,
            ),
            on_change=self._render,
        )
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.bind("<Map>", lambda _event: self.request_refresh_if_visible(), add="+")
        self.bind("<Configure>", self._on_resize, add="+")

    # -- construction ----------------------------------------------------------------------------------------

    def _default_runner(self) -> BackgroundWorkRunner:
        dispatcher = TkUiDispatcher(self.winfo_toplevel())
        return BackgroundWorkRunner(
            spawn=lambda name, target: get_thread_registry().spawn(
                target=target, name=name, daemon=False, purpose="batch operations"),
            dispatch=dispatcher.invoke,
        )

    def _build(self) -> None:
        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        bar.columnconfigure(1, weight=1)
        self.refresh_button = ttk.Button(bar, text="Refresh", command=self.refresh)
        self.refresh_button.grid(row=0, column=0, padx=(0, 8))
        self.status_var = tk.StringVar(value="Expand to load batches.")
        self.status_label = ttk.Label(bar, textvariable=self.status_var, wraplength=280, justify="left")
        self.status_label.grid(row=0, column=1, sticky="ew")

        self.batch_tree = self._tree(1, _BATCH_COLUMNS, height=4, mode="browse")
        self.batch_tree.bind("<<TreeviewSelect>>", self._on_batch_selected, add="+")

        self.summary_var = tk.StringVar()
        self.summary_label = ttk.Label(self, textvariable=self.summary_var, justify="left", wraplength=360)
        self.summary_label.grid(row=2, column=0, sticky="ew", pady=(6, 2))

        filters = ttk.Frame(self)
        filters.grid(row=3, column=0, sticky="ew", pady=(2, 2))
        ttk.Label(filters, text="Status:").grid(row=0, column=0, padx=(0, 4))
        self.status_filter = ttk.Combobox(
            filters, state="readonly", width=12, values=[ALL_STATUSES, *_STATUS_CHOICES])
        self.status_filter.set(ALL_STATUSES)
        self.status_filter.grid(row=0, column=1, padx=(0, 12))
        ttk.Label(filters, text="Failure:").grid(row=0, column=2, padx=(0, 4))
        self.category_filter = ttk.Combobox(
            filters, state="readonly", width=24, values=[ALL_CATEGORIES, *_CATEGORY_CHOICES])
        self.category_filter.set(ALL_CATEGORIES)
        self.category_filter.grid(row=0, column=3)
        for box in (self.status_filter, self.category_filter):
            box.bind("<<ComboboxSelected>>", self._on_filter_changed, add="+")

        self.job_tree = self._tree(4, _JOB_COLUMNS, height=8, mode="extended")
        self.job_tree.bind("<<TreeviewSelect>>", self._on_job_selected, add="+")

        details = ttk.Frame(self)
        details.grid(row=5, column=0, sticky="nsew", pady=(6, 0))
        details.columnconfigure(0, weight=1)
        self.detail_text = tk.Text(details, height=7, wrap="word", state="disabled")
        scroll = ttk.Scrollbar(details, orient="vertical", command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=scroll.set)
        self.detail_text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        actions = ttk.Frame(self)
        actions.grid(row=6, column=0, sticky="ew", pady=(6, 0))
        specs = (
            ("cancel_button", "Cancel Remaining", self.cancel_remaining),
            ("retry_button", "Retry Selected Failed", self.retry_selected),
            ("folder_button", "Open Output Folder", lambda: self._open("folder")),
            ("review_button", "Open in Review", lambda: self._open("review")),
            ("clips_button", "Movie Clips", lambda: self._open("movie_clips")),
        )
        for index, (name, text, command) in enumerate(specs):
            button = ttk.Button(actions, text=text, command=command, state="disabled")
            button.grid(row=index // 3, column=index % 3, padx=(0, 6), pady=(0, 4), sticky="w")
            attach_tooltip(button, text)
            setattr(self, name, button)
        self.hint_var = tk.StringVar()
        self.hint_label = ttk.Label(self, textvariable=self.hint_var, justify="left", wraplength=360)
        self.hint_label.grid(row=7, column=0, sticky="ew", pady=(4, 0))
        self.rowconfigure(4, weight=1)
        for widget in (self.batch_tree, self.job_tree, self.refresh_button, self.status_filter, self.category_filter):
            widget.bind("<F5>", lambda _event: self.refresh(), add="+")  # F5 refreshes from anywhere in the view

    def _tree(
        self, row: int, columns: tuple[tuple[str, str, int], ...], *, height: int, mode: str
    ) -> ttk.Treeview:
        frame = ttk.Frame(self)
        frame.grid(row=row, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        tree = ttk.Treeview(
            frame, columns=[c[0] for c in columns], show="headings", height=height, selectmode=mode)
        for name, title, width in columns:
            tree.heading(name, text=title)
            tree.column(name, width=width, minwidth=28, stretch=name in {"source", "state", "failure"})
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        across = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=scroll.set, xscrollcommand=across.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        across.grid(row=1, column=0, sticky="ew")
        return tree

    # -- public ------------------------------------------------------------------------------------------------

    def refresh(self) -> None:
        if self.session is not None and self.session.refresh():
            self._last_refresh = self._clock()

    def request_refresh_if_visible(self) -> None:
        """Debounced automatic refresh; only while this view is actually on screen."""

        if self.session is None or self._destroyed:
            return
        try:
            visible = bool(self.winfo_ismapped())
        except tk.TclError:
            return
        if visible and self._clock() - self._last_refresh >= self.REFRESH_MIN_INTERVAL_S:
            self.refresh()

    def cancel_remaining(self) -> None:
        if self.session is not None:
            self.session.cancel_remaining()

    def retry_selected(self) -> None:
        if self.session is not None:
            self.session.retry_selected()

    def _open(self, target: str) -> None:
        if self.session is not None:
            self.session.open_outputs(target)

    # -- events -------------------------------------------------------------------------------------------------

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is self and self.session is not None:
            self._destroyed = True
            self.session.close()

    def _on_resize(self, event: tk.Event) -> None:
        if event.widget is self:
            wrap = max(180, int(event.width) - 24)
            for label in (self.status_label, self.summary_label, self.hint_label):
                label.configure(wraplength=wrap)

    def _on_batch_selected(self, _event: tk.Event) -> None:
        if self._rendering or self.session is None:
            return
        selection = self.batch_tree.selection()
        self.session.select_batch(BatchKey.from_token(selection[0]) if selection else None)

    def _on_job_selected(self, _event: tk.Event) -> None:
        if self._rendering or self.session is None:
            return
        self.session.set_job_selection(self.job_tree.selection())

    def _on_filter_changed(self, _event: tk.Event) -> None:
        if self.session is not None:
            self.session.set_filters(
                _STATUS_CHOICES.get(self.status_filter.get()),
                _CATEGORY_CHOICES.get(self.category_filter.get()),
            )

    # -- rendering ----------------------------------------------------------------------------------------------

    def _render(self) -> None:
        session = self.session
        if session is None or self._destroyed:
            return
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        self._rendering = True
        try:
            self._render_batches(session)
            self._render_jobs(session)
            self.summary_var.set(session.summary_text())
            self._render_detail(session)
            self._render_actions(session)
        finally:
            self._rendering = False

    def _replace_rows(self, tree: ttk.Treeview, rows: list[tuple[str, tuple[Any, ...]]], keep: tuple[str, ...]) -> None:
        tree.delete(*tree.get_children())
        for iid, values in rows:
            tree.insert("", "end", iid=iid, values=values)
        present = [iid for iid in keep if tree.exists(iid)]
        if present:
            tree.selection_set(present)
            tree.see(present[0])

    def _render_batches(self, session: BatchOperationsSession) -> None:
        rows = session.batch_rows()
        keep = (session.selected_key.to_token(),) if session.selected_key else ()
        if rows != self._last_batches:
            self._last_batches = rows
            self._replace_rows(
                self.batch_tree,
                [
                    (r.token, (r.kind, r.short_id, f"{r.state} ({r.note})" if r.note else r.state, r.progress, r.jobs))
                    for r in rows
                ],
                keep,
            )
        elif keep and tuple(self.batch_tree.selection()) != keep and self.batch_tree.exists(keep[0]):
            self.batch_tree.selection_set(keep)

    def _render_jobs(self, session: BatchOperationsSession) -> None:
        rows = session.job_rows()
        if rows != self._last_jobs:
            self._last_jobs = rows
            self._replace_rows(
                self.job_tree,
                [
                    (r.job_id, (r.position, r.source, r.status, r.failure, r.model, r.priority, r.outputs, r.retry))
                    for r in rows
                ],
                session.selected_ids,
            )

    def _render_detail(self, session: BatchOperationsSession) -> None:
        text = session.detail_text()
        if text != self._last_detail:
            self._last_detail = text
            self.detail_text.configure(state="normal")
            self.detail_text.delete("1.0", "end")
            self.detail_text.insert("1.0", text)
            self.detail_text.configure(state="disabled")

    def _render_actions(self, session: BatchOperationsSession) -> None:
        states = (
            (self.cancel_button, session.cancel_state()),
            (self.retry_button, session.retry_state()),
            (self.folder_button, session.folder_state()),
            (self.review_button, session.review_state()),
            (self.clips_button, session.movie_clips_state()),
        )
        for button, state in states:
            button.configure(state="normal" if state.enabled else "disabled")
            tooltip = getattr(button, "tooltip", None)
            if tooltip is not None:
                tooltip.text = state.reason
        self.refresh_button.configure(state="disabled" if session.busy else "normal")
        blocked = []
        if session.detail is not None and not session.busy:
            for name, state in (
                ("Cancel Remaining", session.cancel_state()),
                ("Retry Selected Failed", session.retry_state()),
            ):
                if not state.enabled:
                    blocked.append(f"{name}: {state.reason}")
        self.hint_var.set(" | ".join(blocked))
        if session.busy:
            self.status_var.set(f"Working ({session.busy.lower()})...")
        elif session.loading:
            self.status_var.set("Loading batches...")
        else:
            self.status_var.set(session.message or self._idle_text(session))

    @staticmethod
    def _idle_text(session: BatchOperationsSession) -> str:
        if session.snapshot is None:
            return "Expand to load batches."
        count = len(session.snapshot.catalog.summaries)
        return f"{count} batch(es)." if count else "No Review or Video Workflow batches found."

    # -- hooks (Tk thread) --------------------------------------------------------------------------------------

    def _confirm_cancel(self, plan: Any) -> bool:
        return bool(messagebox.askyesno(
            "Cancel remaining jobs",
            f"Cancel the {len(plan.target_job_ids)} job(s) of {plan.key.label} that are still queued?\n\n"
            f"{plan.untouched_count} other job(s) are running, finished or already cancelled and will not be "
            "touched. A job that starts before it is cancelled keeps running.",
            parent=self.winfo_toplevel(),
        ))

    def _review_retry(self, plan: Any) -> tuple[str, ...] | None:
        return BatchRetryDialog(self, plan).show()

    def _open_in_review(self, paths: tuple[str, ...]) -> int:
        from src.gui.controllers.video_workspace_handoff import route_images_to_review

        main_window = self._main_window_provider()
        if main_window is None:
            raise RuntimeError("The main window is not available")
        return len(route_images_to_review(
            main_window=main_window, image_paths=list(paths),
            status_message=f"Opened {len(paths)} batch output image(s) from Queue/History."))

    def _open_movie_clips(self, bundle: dict[str, Any]) -> None:
        from src.gui.controllers.video_workspace_handoff import route_bundle_to_movie_clips

        main_window = self._main_window_provider()
        if main_window is None:
            raise RuntimeError("The main window is not available")
        route_bundle_to_movie_clips(
            main_window=main_window, bundle=bundle, status_message="Loaded batch output into Movie Clips.")

    def _open_folder(self, path: str) -> None:
        opener = self._folder_opener
        if opener is None:
            from src.gui.job_history_panel_v2 import JobHistoryPanelV2

            opener = JobHistoryPanelV2._default_open_folder
        opener(path)


__all__ = ["BatchOperationsPanelV2"]
