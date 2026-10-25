"""Tk rendering of the Video Workflow "Recent outputs" section (PR-VID-UX-314). Presentation only.

Lists the newest finished clips from the canonical repository, previews the selected one in a bounded
looping widget, and offers Open, Reveal and Send to Movie Clips.  Everything that reads the repository or
the file system runs on a worker owned by the existing ``ThreadRegistry``; results return to the Tk thread
through ``TkUiDispatcher`` and are dropped when stale or after the panel is destroyed.  The panel builds no
job, calls no backend and never writes.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import ttk
from typing import Any

from src.gui.ui_dispatcher import TkUiDispatcher
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.gui.view_contracts.video_recent_outputs_contract import RecentOutputsSession
from src.gui.widgets.media_inspector import MediaInspector as VideoPreviewWidget
from src.utils.thread_registry import get_thread_registry
from src.video.recent_video_outputs import RecentVideoOutput

_COLUMNS = ("completed", "workflow", "length", "file")


def _format_time(output: RecentVideoOutput) -> str:
    stamp = output.completed_at
    return stamp.strftime("%Y-%m-%d %H:%M") if stamp is not None else "-"


class WorkflowRecentOutputsPanel(ttk.LabelFrame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        list_outputs: Callable[[], Sequence[RecentVideoOutput]],
        send_to_movie: Callable[[RecentVideoOutput], Any] | None = None,
        decode: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            master, text="Recent outputs", style="Dark.TLabelframe", padding=8, **kwargs
        )
        self._closed = False
        self._runner: BackgroundWorkRunner | None = None
        self._previewed: str = ""
        self.status_var = tk.StringVar(value="")
        self.columnconfigure(0, weight=1)

        actions = ttk.Frame(self, style="Panel.TFrame")
        actions.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        self.refresh_button = ttk.Button(
            actions, text="Refresh", style="Dark.TButton", command=self.request_refresh
        )
        self.open_button = ttk.Button(
            actions, text="Open", style="Dark.TButton", command=self._on_open, state="disabled"
        )
        self.reveal_button = ttk.Button(
            actions, text="Reveal", style="Dark.TButton", command=self._on_reveal, state="disabled"
        )
        self.movie_button = ttk.Button(
            actions,
            text="Send to Movie Clips",
            style="Dark.TButton",
            command=self._on_send_to_movie,
            state="disabled",
        )
        for button in (
            self.refresh_button,
            self.open_button,
            self.reveal_button,
            self.movie_button,
        ):
            button.pack(side="left", padx=(0, 6))

        tree_frame = ttk.Frame(self, style="Panel.TFrame")
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        tree_frame.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            tree_frame, columns=_COLUMNS, show="headings", height=6, selectmode="browse"
        )
        for column, heading, width in (
            ("completed", "Completed", 130),
            ("workflow", "Workflow", 190),
            ("length", "Length", 140),
            ("file", "File", 160),
        ):
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=width, stretch=column in {"workflow", "file"})
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-Button-1>", lambda _e: self._on_open())

        self.preview = VideoPreviewWidget(
            self, decode=decode, edge=256, scale=1, allow_original=False
        )
        self.preview.grid(row=1, column=1, sticky="n")
        ttk.Label(self, textvariable=self.status_var, style="Muted.TLabel", justify="left").grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0)
        )

        self.session = RecentOutputsSession(
            list_outputs=list_outputs,
            runner=self._work_runner(),
            on_change=self._render,
            send_to_movie=send_to_movie,
        )
        self.status_var.set(self.session.status)
        self.bind("<Destroy>", self._on_destroy, add="+")

    # ------------------------------------------------------------------ public

    def request_refresh(self) -> None:
        if not self._closed:
            self.session.refresh()

    # ------------------------------------------------------------------ background work

    def _work_runner(self) -> BackgroundWorkRunner:
        if self._runner is None:
            dispatcher = TkUiDispatcher(self.winfo_toplevel())
            self._runner = BackgroundWorkRunner(
                spawn=lambda name, target: get_thread_registry().spawn(
                    target=target,
                    name=name,
                    daemon=False,
                    purpose="Read recent finished video outputs without blocking Tk",
                ),
                dispatch=lambda fn: dispatcher.invoke(lambda: self._deliver(fn)),
            )
        return self._runner

    def _deliver(self, finish: Callable[[], None]) -> None:
        if self._closed:
            return
        try:
            if self.winfo_exists():
                finish()
        except tk.TclError:
            pass  # the widget tree is going away

    # ------------------------------------------------------------------ rendering

    def _render(self) -> None:
        if self._closed:
            return
        try:
            self._render_rows()
            selected = self.session.selected
            state = "normal" if selected is not None else "disabled"
            self.open_button.configure(state=state)
            self.reveal_button.configure(state=state)
            self.movie_button.configure(
                state="normal" if self.session.can_send_to_movie else "disabled"
            )
            self.refresh_button.configure(state="disabled" if self.session.busy else "normal")
            self.status_var.set(
                "Reading recent outputs..." if self.session.busy else self.session.status
            )
            target = selected.video_path if selected is not None else ""
            if target != self._previewed:
                self._previewed = target
                if target and selected is not None:
                    self.preview.set_media(
                        target, "video", subject=selected.visibility_subject or {"name": target}
                    )
                else:
                    self.preview.stop()
        except tk.TclError:
            pass

    def _render_rows(self) -> None:
        wanted = [output.job_id for output in self.session.outputs]
        if list(self.tree.get_children()) != wanted:
            self.tree.delete(*self.tree.get_children())
            for output in self.session.outputs:
                self.tree.insert(
                    "",
                    "end",
                    iid=output.job_id,
                    values=(
                        _format_time(output),
                        output.workflow_label or output.backend_id or "-",
                        output.length_text,
                        output.file_name,
                    ),
                )
        selected = self.session.selected_job_id
        if selected and self.tree.exists(selected) and self.tree.selection() != (selected,):
            self.tree.selection_set(selected)

    # ------------------------------------------------------------------ actions

    def _on_select(self, _event: Any = None) -> None:
        chosen = self.tree.selection()
        if chosen and chosen[0] != self.session.selected_job_id:
            self.session.select(chosen[0])

    def _on_open(self) -> None:
        self.session.open_selected()

    def _on_reveal(self) -> None:
        self.session.reveal_selected()

    def _on_send_to_movie(self) -> None:
        self.session.send_selected_to_movie()

    def _on_destroy(self, event: Any = None) -> None:
        if event is None or event.widget is self:
            self._closed = True
            self.session.close()


__all__ = ["WorkflowRecentOutputsPanel"]
