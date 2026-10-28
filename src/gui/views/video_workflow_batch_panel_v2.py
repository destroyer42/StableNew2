"""Tk rendering of the Video Workflow multi-source batch section (PR-VID-BATCH-200).

Presentation only: the state machine lives in ``VideoBatchSession``.  Previewing prepares source
images and builds NJRs and queueing re-verifies frozen files, so both run on a worker owned by the
existing ``ThreadRegistry``; every widget read happens before the worker starts and every widget
update is marshalled back to the Tk thread through ``TkUiDispatcher``.  This module builds no
payload, calls no backend and branches on no workflow or model.

The compact source controls (one row) live in the tab header (never scrolled away) and the primary
Preview / Queue buttons are packed into the header's action bar by this panel; the taller source
table and preview text live in the scrolled body.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any

from src.gui.theme_v2 import style_text_widget
from src.gui.ui_dispatcher import tk_dispatcher_for
from src.gui.view_contracts.video_batch_contract import (
    MAX_BATCH_SOURCES,
    BatchPreviewWork,
    BatchQueueWork,
    FolderScanWork,
    VideoBatchSession,
)
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.gui.widgets.responsive_wrap_v2 import bind_wraplength
from src.utils.thread_registry import get_thread_registry

_IMAGE_FILETYPES = [
    ("Image files", "*.png *.jpg *.jpeg *.webp *.bmp *.tiff *.tif"),
    ("All files", "*.*"),
]
_STATUS_LABELS = {
    "pending": "not checked",
    "ready": "ready",
    "frozen": "frozen",
    "blocked": "BLOCKED",
}


class WorkflowBatchPanel(ttk.Frame):
    """Compact header strip for multi-source selection plus a body panel with the per-source
    preview.  The strip and the Preview / Queue buttons stay in the fixed header; the (taller)
    source table and preview live in ``details_parent`` (the tab's scrolled body)."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        details_parent: tk.Misc,
        session: VideoBatchSession,
        read_form: Callable[[], dict[str, Any]],
        action_parent: tk.Misc,
        action_before: tk.Widget | None = None,
        on_queued: Callable[[list[str]], None] | None = None,
        on_mode_change: Callable[[bool], None] | None = None,
        on_status: Callable[[str], None] | None = None,
        runner: BackgroundWorkRunner | None = None,
    ) -> None:
        super().__init__(master, style="Panel.TFrame")
        self._session = session
        self._read_form = read_form
        self._on_queued = on_queued
        self._on_mode_change = on_mode_change
        self._on_status = on_status
        self._runner = runner
        self._closed = False
        self._last_dir = ""
        self._mode_active: bool | None = None
        self._details_visible: bool | None = None
        self._last_status = ""
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.columnconfigure(0, weight=1)

        self.source_var = tk.StringVar(value="")
        self.message_var = tk.StringVar(value="")
        self.recursive_var = tk.BooleanVar(value=True)

        # Header strip: one row of controls (plus one summary line only while a batch exists).
        buttons = ttk.Frame(self, style="Panel.TFrame")
        buttons.grid(row=0, column=0, sticky="ew")
        ttk.Label(buttons, text="Multiple images", style="Dark.TLabel").pack(
            side="left", padx=(0, 8)
        )
        self.select_images_button = ttk.Button(
            buttons, text="Select Images...", style="Dark.TButton", command=self._on_select_images
        )
        self.select_images_button.pack(side="left")
        self.select_folder_button = ttk.Button(
            buttons, text="Select Folder...", style="Dark.TButton", command=self._on_select_folder
        )
        self.select_folder_button.pack(side="left", padx=(6, 0))
        self.recursive_check = ttk.Checkbutton(
            buttons,
            text="Include subfolders",
            variable=self.recursive_var,
            style="Dark.TCheckbutton",
        )
        self.recursive_check.pack(side="left", padx=(6, 0))
        self.clear_button = ttk.Button(
            buttons, text="Clear Sources", style="Dark.TButton", command=self._on_clear
        )
        self.clear_button.pack(side="left", padx=(6, 0))
        self.source_label = ttk.Label(
            self, textvariable=self.source_var, style="Muted.TLabel", justify="left"
        )
        self.source_label.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        self.source_label.grid_remove()
        bind_wraplength(self.source_label)

        # Details (in the scrolled body): source table, exclusion actions and the preview text.
        self.details = ttk.LabelFrame(details_parent, text="Batch sources and preview", padding=8)
        self.details.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            self.details,
            columns=("file", "status", "detail"),
            show="headings",
            height=8,
            selectmode="extended",
        )
        self.tree.heading("file", text="Source")
        self.tree.heading("status", text="Status")
        self.tree.heading("detail", text="Details")
        self.tree.column("file", width=190, anchor="w")
        self.tree.column("status", width=90, anchor="w")
        self.tree.column("detail", width=520, anchor="w")
        self.tree.grid(row=0, column=0, sticky="ew")
        scroll = ttk.Scrollbar(self.details, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        exclusions = ttk.Frame(self.details, style="Panel.TFrame")
        exclusions.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.exclude_button = ttk.Button(
            exclusions, text="Exclude Selected", style="Dark.TButton", command=self._on_exclude
        )
        self.exclude_button.pack(side="left")
        self.exclude_blocked_button = ttk.Button(
            exclusions,
            text="Exclude Blocked",
            style="Dark.TButton",
            command=self._on_exclude_blocked,
        )
        self.exclude_blocked_button.pack(side="left", padx=(6, 0))
        self.preview_text = tk.Text(self.details, height=10, wrap="word", state="disabled")
        style_text_widget(self.preview_text, elevated=True)
        self.preview_text.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        message = ttk.Label(
            self.details, textvariable=self.message_var, style="Muted.TLabel", justify="left"
        )
        message.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        bind_wraplength(message)

        # The primary actions share the header's fixed action bar so they never scroll away.
        self.preview_button = ttk.Button(
            action_parent, text="Preview Batch", style="Dark.TButton", command=self._on_preview
        )
        self.queue_button = ttk.Button(
            action_parent, text="Queue Batch", style="Primary.TButton", command=self._on_queue
        )
        self._action_before = action_before
        self.refresh()

    def place_details(self, **grid_options: Any) -> None:
        """Grid the details panel once (the tab owns its container); visibility is then managed."""

        self.details.grid(**grid_options)
        self._details_visible = None  # force the next refresh to apply the current visibility
        self.refresh()

    # ------------------------------------------------------------------ rendering

    def refresh(self) -> None:
        """Re-render source summary, rows, preview, status and button states."""

        session = self._session
        active = session.active
        busy = session.busy is not None
        self.source_var.set(session.source_text)
        status = session.status_text
        self.message_var.set(status)
        if status and status != self._last_status and self._on_status is not None:
            self._on_status(status)  # the header's status line is always visible
        self._last_status = status
        idle = "disabled" if busy else "normal"
        self.select_images_button.configure(state=idle)
        self.select_folder_button.configure(state=idle)
        self.clear_button.configure(state="normal" if active and not busy else "disabled")
        self.exclude_button.configure(state="normal" if active and not busy else "disabled")
        blocked = bool(session.preview and session.preview.blocked_indices)
        self.exclude_blocked_button.configure(
            state="normal" if blocked and not busy else "disabled"
        )
        if active:
            self.source_label.grid()
        else:
            self.source_label.grid_remove()
        if self._details_visible is not active:
            self._details_visible = active
            if active:
                self.details.grid()
            else:
                self.details.grid_remove()
        self._render_rows()
        self._render_preview()
        self._sync_action_buttons(active, busy)

    def _sync_action_buttons(self, active: bool, busy: bool) -> None:
        if active:
            if not self.preview_button.winfo_ismapped():
                options: dict[str, Any] = {"side": "left", "padx": (8, 0)}
                if self._action_before is not None:
                    options["before"] = self._action_before
                self.preview_button.pack(**options)
                self.queue_button.pack(**options)
        else:
            self.preview_button.pack_forget()
            self.queue_button.pack_forget()
        count = self._session.count
        self.queue_button.configure(
            text=f"Queue {count} Videos" if active and count else "Queue Batch",
            state="normal" if self._session.preview_valid and not busy else "disabled",
        )
        refused = self._session.over_limit or count == 0
        self.preview_button.configure(state="disabled" if busy or refused else "normal")
        if self._mode_active is not active:
            self._mode_active = active
            if self._on_mode_change is not None:
                self._on_mode_change(active)

    def _render_rows(self) -> None:
        session = self._session
        self.tree.delete(*self.tree.get_children())
        if session.preview is not None and len(session.preview.rows) == session.count:
            for row in session.preview.rows:
                self.tree.insert(
                    "",
                    "end",
                    iid=str(row.index),
                    values=(
                        f"{row.index + 1:02d}  {row.name}",
                        _STATUS_LABELS.get(row.status, row.status),
                        row.detail,
                    ),
                )
            return
        for index, source in enumerate(session.sources):
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    f"{index + 1:02d}  {Path(str(source.path)).name}",
                    _STATUS_LABELS["pending"],
                    str(source.path),
                ),
            )

    def _render_preview(self) -> None:
        view = self._session.preview
        lines: list[str] = []
        if view is not None:
            lines.append(view.headline)
            lines.append("")
            lines.extend(f"{label}: {value}" for label, value in view.summary)
            if view.problems:
                lines.append("")
                lines.append("Problems:")
                lines.extend(f"  - {text}" for text in view.problems)
            if view.warnings:
                lines.append("")
                lines.append("Warnings:")
                lines.extend(f"  - {text}" for text in view.warnings)
            if view.notes:
                lines.append("")
                lines.extend(f"* {text}" for text in view.notes)
        elif self._session.active:
            lines.append(
                f"Press Preview Batch to check every source (1 to {MAX_BATCH_SOURCES}). "
                "Preview prepares StableNew-owned source images and freezes seeds; it does not queue."
            )
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", "\n".join(lines))
        self.preview_text.configure(state="disabled")

    def invalidate_if_changed(self) -> None:
        session = self._session
        if not session.active:
            return
        try:
            form = self._read_form()
        except Exception:
            return
        if session.invalidate_if_changed(form):
            self.refresh()

    # ------------------------------------------------------------------ selection handlers

    def _on_select_images(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Choose source images",
            filetypes=_IMAGE_FILETYPES,
            initialdir=self._last_dir or None,
        )
        if paths:
            self._last_dir = str(Path(paths[0]).parent)
            self._session.choose_files([str(p) for p in paths])
        self.refresh()

    def _on_select_folder(self) -> None:
        folder = filedialog.askdirectory(
            title="Choose folder of source images", initialdir=self._last_dir or None
        )
        if not folder:
            self.refresh()
            return
        self._last_dir = folder
        # Walking a large tree can take seconds; it runs on a worker, never on the Tk thread.
        work = self._session.begin_scan(folder, recursive=bool(self.recursive_var.get()))
        self.refresh()
        if work is None:
            return
        self._work_runner().start(
            f"VideoBatch-Scan-{id(self)}",
            lambda: self._session.run_scan(work),
            lambda outcome: self._deliver(lambda: self._finish_scan(work, outcome)),
        )

    def _finish_scan(self, work: FolderScanWork, outcome: WorkOutcome) -> None:
        self._session.finish_scan(work, outcome)
        self.refresh()

    def set_review_selection(self, paths: list[str], lineage: dict[str, dict[str, str]]) -> bool:
        """Review handoff entry point: transfers intent only; nothing is queued."""

        accepted = self._session.choose_review(paths, lineage)
        self.refresh()
        return accepted

    def _on_exclude(self) -> None:
        indices = [int(item) for item in self.tree.selection()]
        if not indices:
            self._session._set_message("Select the rows to exclude first.")
        else:
            self._session.exclude(indices)
        self.refresh()

    def _on_exclude_blocked(self) -> None:
        self._session.exclude_blocked()
        self.refresh()

    def _on_clear(self) -> None:
        self._session.clear()
        self.refresh()

    # ------------------------------------------------------------------ off-thread work

    def _work_runner(self) -> BackgroundWorkRunner:
        if self._runner is None:
            dispatcher = tk_dispatcher_for(self)
            self._runner = BackgroundWorkRunner(
                spawn=lambda name, target: get_thread_registry().spawn(
                    target=target,
                    name=name,
                    daemon=False,
                    purpose="Prepare, hash and build a multi-source Video Workflow batch "
                    "without blocking Tk",
                ),
                dispatch=dispatcher.invoke,
            )
        return self._runner

    def _deliver(self, finish: Callable[[], None]) -> None:
        """Run ``finish`` on the Tk thread unless the panel was torn down meanwhile."""

        if self._closed:
            return
        try:
            if not self.winfo_exists():
                return
            finish()
        except tk.TclError:
            pass  # the widget tree is going away; there is nothing left to update

    def _on_destroy(self, event: Any = None) -> None:
        if event is None or event.widget is self:
            self._closed = True

    def _current_form(self) -> dict[str, Any]:
        try:
            return self._read_form()
        except Exception:
            return {"__unreadable__": object()}  # cannot match the snapshot: treated as stale

    def _on_preview(self) -> None:
        form = self._read_form()  # Tk reads happen here, before the worker starts
        work = self._session.begin_preview(form)
        self.refresh()
        if work is None:
            return
        self._work_runner().start(
            f"VideoBatch-Preview-{id(self)}",
            lambda: self._session.run_preview(work),
            lambda outcome: self._deliver(lambda: self._finish_preview(work, outcome)),
        )

    def _finish_preview(self, work: BatchPreviewWork, outcome: WorkOutcome) -> None:
        self._session.finish_preview(work, outcome, self._current_form())
        self.refresh()

    def _on_queue(self) -> None:
        form = self._read_form()
        work = self._session.begin_queue(form)
        self.refresh()
        if work is None:
            return
        self._work_runner().start(
            f"VideoBatch-Queue-{id(self)}",
            lambda: self._session.run_queue(work),
            lambda outcome: self._deliver(lambda: self._finish_queue(work, outcome)),
        )

    def _finish_queue(self, work: BatchQueueWork, outcome: WorkOutcome) -> None:
        job_ids = self._session.finish_queue(work, outcome)
        self.refresh()
        if self._on_queued is not None:
            self._on_queued(job_ids)  # also on refusal: queue state is re-read, never assumed


__all__ = ["WorkflowBatchPanel"]
