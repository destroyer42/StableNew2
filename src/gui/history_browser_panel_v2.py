"""Searchable, paged browser over the whole job history (every row, not only the newest few).

It reuses ``JobHistoryPanelV2`` for the result table and its Open Folder / Replay actions, and adds a filter bar and
"Load more". Searches run on one worker thread and come back through a ``Future`` the GUI thread polls, so a slow
disk never blocks Tk. Results are never mirrored into ``AppState``, so the hand-offs that look entries up there (SVD,
Video Workflow, Movie Clips, Explain) are not offered here; Replay goes through the controller by job id.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from tkinter import ttk
from typing import Any

from src.gui import theme_v2 as theme_mod
from src.gui.job_history_panel_v2 import HistoryActionState, JobHistoryPanelV2
from src.gui_v2.history_browser_model import (
    ANY_STATUS,
    STATUS_CHOICES,
    HistoryFilterError,
    HistoryFilters,
    describe_page,
)
from src.queue.history_query import DEFAULT_PAGE_SIZE, HistoryPage, HistoryQuery
from src.queue.job_history_store import JobHistoryEntry

SearchFn = Callable[[HistoryQuery], HistoryPage]
_POLL_MS = 50


def resolve_history_search(controller: Any | None) -> SearchFn | None:
    """The repository's ``query_history`` reached the way the main window reaches the repository, or ``None``."""

    job_service = getattr(controller, "job_service", None)
    repository = getattr(job_service, "history_store", None)
    search = getattr(repository, "query_history", None)
    return search if callable(search) else None


class HistoryBrowserPanelV2(JobHistoryPanelV2):
    """``JobHistoryPanelV2`` driven by filter-bar searches instead of ``AppState.history_items``."""

    page_size = DEFAULT_PAGE_SIZE

    def __init__(
        self,
        master: tk.Misc,
        *,
        search: SearchFn,
        controller: Any | None = None,
        folder_opener: Callable[[str], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            master,
            controller=controller,
            app_state=None,
            folder_opener=folder_opener,
            manage_app_state_subscriptions=False,
            **kwargs,
        )
        self._search = search
        self._executor: ThreadPoolExecutor | None = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="history-browser"
        )
        self._pending: tuple[Future[HistoryPage], bool] | None = None
        self._poll_after: str | None = None
        self._shown: list[JobHistoryEntry] = []
        self._last_page: HistoryPage | None = None
        self._last_filters = HistoryFilters()
        self._build_filter_bar()
        self._build_footer()
        self.refresh_btn.configure(text="Search Again", command=self._on_refresh)
        self.empty_state_var.set("")
        self.after(0, self._on_search)

    # --- construction -------------------------------------------------------------------------

    def _build_filter_bar(self) -> None:
        style_name = theme_mod.SURFACE_FRAME_STYLE
        bar = ttk.Frame(self, style=style_name)
        bar.pack(fill=tk.X, pady=(0, 4), before=self.refresh_btn.master)
        self._text_var = tk.StringVar()
        self._status_var = tk.StringVar(value=ANY_STATUS)
        self._pack_var = tk.StringVar()
        self._from_var = tk.StringVar()
        self._to_var = tk.StringVar()

        def field(label: str, widget: tk.Widget, *, left: int = 0) -> None:
            ttk.Label(bar, text=label, style=theme_mod.MUTED_LABEL_STYLE).pack(
                side=tk.LEFT, padx=(left, 2)
            )
            widget.pack(side=tk.LEFT)

        self.text_entry = ttk.Entry(bar, textvariable=self._text_var, width=24)
        field("Prompt/model", self.text_entry)
        self.status_box = ttk.Combobox(
            bar,
            textvariable=self._status_var,
            values=list(STATUS_CHOICES),
            width=10,
            state="readonly",
        )
        field("Status", self.status_box, left=8)
        self.pack_entry = ttk.Entry(bar, textvariable=self._pack_var, width=14)
        field("Pack", self.pack_entry, left=8)
        self.from_entry = ttk.Entry(bar, textvariable=self._from_var, width=11)
        field("From", self.from_entry, left=8)
        self.to_entry = ttk.Entry(bar, textvariable=self._to_var, width=11)
        field("To", self.to_entry, left=8)
        self.search_btn = ttk.Button(bar, text="Search", command=self._on_search)
        self.search_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.clear_btn = ttk.Button(bar, text="Clear", command=self._on_clear)
        self.clear_btn.pack(side=tk.LEFT, padx=(4, 0))
        for entry in (self.text_entry, self.pack_entry, self.from_entry, self.to_entry):
            entry.bind("<Return>", lambda _event: self._on_search())

    def _build_footer(self) -> None:
        footer = ttk.Frame(self, style=theme_mod.SURFACE_FRAME_STYLE)
        footer.pack(fill=tk.X, pady=(4, 0))
        self.summary_var = tk.StringVar(value="")
        ttk.Label(footer, textvariable=self.summary_var, style=theme_mod.MUTED_LABEL_STYLE).pack(
            side=tk.LEFT
        )
        self.more_btn = ttk.Button(
            footer, text="Load more", command=self._on_load_more, state=tk.DISABLED
        )
        self.more_btn.pack(side=tk.RIGHT)

    # --- actions the table must not offer here ------------------------------------------------

    def _history_action_state(self, entry: JobHistoryEntry | None) -> HistoryActionState:
        base = super()._history_action_state(entry)
        return HistoryActionState(
            open_folder=base.open_folder,
            replay=base.replay,
            svd=False,
            video_workflow=False,
            movie_clips=False,
            explain=False,
        )

    # --- searching ----------------------------------------------------------------------------

    def _on_refresh(self) -> None:
        self._on_search()

    def _on_clear(self) -> None:
        self._text_var.set("")
        self._status_var.set(ANY_STATUS)
        self._pack_var.set("")
        self._from_var.set("")
        self._to_var.set("")
        self._on_search()

    def _current_filters(self) -> HistoryFilters:
        return HistoryFilters(
            text=self._text_var.get(),
            status_label=self._status_var.get(),
            pack=self._pack_var.get(),
            date_from=self._from_var.get(),
            date_to=self._to_var.get(),
        )

    def _on_search(self) -> None:
        """Start over from the newest job with the filter bar as it is now."""

        if self._pending is not None:
            return
        filters = self._current_filters()
        try:
            query = filters.to_query(limit=self.page_size)
        except HistoryFilterError as exc:
            self.summary_var.set(str(exc))
            return
        self._last_filters = filters
        self._submit(query, append=False)

    def _on_load_more(self) -> None:
        if self._pending is not None or self._last_page is None or self._last_page.exhausted:
            return
        query = self._last_filters.to_query(
            cursor=self._last_page.next_cursor, limit=self.page_size
        )
        self._submit(query, append=True)

    def _submit(self, query: HistoryQuery, *, append: bool) -> None:
        executor = self._executor
        if executor is None:
            return
        self.summary_var.set("Searching...")
        self._set_busy(True)
        self._pending = (executor.submit(self._search, query), append)
        self._poll_after = self.after(_POLL_MS, self._poll)

    def _poll(self) -> None:
        self._poll_after = None
        pending = self._pending
        if pending is None:
            return
        future, append = pending
        if not future.done():
            self._poll_after = self.after(_POLL_MS, self._poll)
            return
        self._pending = None
        self._set_busy(False)
        try:
            page = future.result()
        except Exception as exc:  # noqa: BLE001 - the user sees the reason; the next search retries
            self.summary_var.set(f"Search failed: {exc}")
            return
        self.show_page(page, append=append)

    def _set_busy(self, busy: bool) -> None:
        self.search_btn.configure(state=tk.DISABLED if busy else tk.NORMAL)
        if busy:
            self.more_btn.configure(state=tk.DISABLED)

    def show_page(self, page: HistoryPage, *, append: bool) -> None:
        """Show ``page`` (appended to the rows already listed when ``append``), then describe what remains."""

        self._shown = [*self._shown, *page.entries] if append else list(page.entries)
        self._last_page = page
        self._populate_history(self._shown)
        self.empty_state_var.set("" if self._shown else "No jobs match.")
        self.summary_var.set(describe_page(len(self._shown), page))
        self.more_btn.configure(state=tk.DISABLED if page.exhausted else tk.NORMAL)

    def destroy(self) -> None:
        if self._poll_after is not None:
            try:
                self.after_cancel(self._poll_after)
            except tk.TclError:
                pass
            self._poll_after = None
        executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        super().destroy()


__all__ = ["HistoryBrowserPanelV2", "resolve_history_search"]
