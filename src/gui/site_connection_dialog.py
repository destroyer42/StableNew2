"""Native consent and frozen Preview attachment for the StableNew operator Site."""

from __future__ import annotations

import logging
import secrets
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, cast

from src.app.site_queue_bridge import (
    PreviewJob,
    PreviewView,
    SiteListener,
    SiteSession,
    SubmissionReceipt,
)
from src.controller.app_controller_services.run_submission_service import (
    PreviewWitness,
    same_preview,
)
from src.pipeline.job_models_v2 import WorkloadKind

log = logging.getLogger(__name__)
_MAX_PREVIEW_JOBS = 250
_RECEIPT_SECONDS = 20


class PreviewQueueConnection:
    """All methods run on the existing UI thread. The listener never touches the GUI or queue."""

    def __init__(self, app: Any, session: SiteSession, confirm: Any) -> None:
        self.app = app
        self.session = session
        self.confirm = confirm
        self.witness: PreviewWitness | None = None
        self.preview_id: str | None = None
        self.pending: tuple[SubmissionReceipt, tuple[str, ...], float] | None = None
        self.uncertain: PreviewWitness | None = None

    def _publish_current(self) -> None:
        current = self.app.app_state.snapshot_accepted_preview()
        records = current[1]
        if not records:
            self.session.publish(None, "open_an_image_preview")
        elif len(records) > _MAX_PREVIEW_JOBS:
            self.session.publish(None, "preview_too_large")
        elif any(record.workload_kind != WorkloadKind.IMAGE for record in records):
            self.session.publish(None, "image_preview_required")
        elif self.uncertain is not None and same_preview(self.uncertain, current):
            self.session.publish(None, "check_native_queue")
        else:
            if self.witness is None or not same_preview(self.witness, current):
                self.preview_id = secrets.token_hex(16)
            assert self.preview_id is not None
            self.witness = current
            self.session.publish(
                PreviewView(
                    self.preview_id,
                    tuple(
                        PreviewJob(record.job_id, tuple(record.stage_chain_labels))
                        for record in records
                    ),
                )
            )
            return
        self.witness = None
        self.preview_id = None

    def _finish(
        self, receipt: SubmissionReceipt, state: str, job_ids: tuple[str, ...] = ()
    ) -> None:
        self.session.finish(receipt, state, job_ids)
        self.pending = None
        self.witness = None
        self.preview_id = None

    def _committed(self, job_ids: tuple[str, ...]) -> tuple[str, ...]:
        repository = self.app.job_service.history_store
        return tuple(job_id for job_id in job_ids if repository.get_job(job_id) is not None)

    def _check_receipt(self) -> None:
        if self.pending is None:
            return
        receipt, job_ids, timeout = self.pending
        try:
            committed = self._committed(job_ids)
        except Exception:  # noqa: BLE001 - job admission might already have committed
            log.exception("Unable to read the native queue receipt")
            self.uncertain = self.witness
            self._finish(receipt, "check_native_queue")
            return
        if committed == job_ids:
            self._finish(receipt, "queued", committed)
        elif time.monotonic() >= timeout or not self.app._queue_submit_in_progress:
            self.uncertain = self.witness
            self._finish(receipt, "check_native_queue")

    def _consume(self, receipt: SubmissionReceipt) -> None:
        witness = self.witness
        if witness is None or receipt.preview_id != self.preview_id:
            self._finish(receipt, "preview_changed")
            return
        job_ids = tuple(record.job_id for record in witness[1])
        if not self.confirm(len(job_ids)):
            self._finish(receipt, "declined")
            return
        if self.session.expired or self.app._is_shutting_down:
            self._finish(receipt, "connection_closed")
            return
        if not same_preview(witness, self.app.app_state.snapshot_accepted_preview()):
            self._finish(receipt, "preview_changed")
            return
        try:
            if self._committed(job_ids):
                self.uncertain = witness
                self._finish(receipt, "check_native_queue")
                return
            if not self.app.submit_frozen_site_preview(witness):
                self._finish(receipt, "native_queue_refused")
                return
        except Exception:  # noqa: BLE001 - never retry uncertain queue admission
            log.exception("Failed to observe the native queue handoff")
            self.uncertain = witness
            self._finish(receipt, "check_native_queue")
            return
        self.session.finish(receipt, "submitting")
        self.pending = (receipt, job_ids, time.monotonic() + _RECEIPT_SECONDS)

    def tick(self) -> None:
        if self.session.expired or self.app._is_shutting_down:
            return
        self._check_receipt()
        if self.pending is not None:
            return
        self._publish_current()
        receipt = self.session.take_request()
        if receipt is not None:
            self._consume(receipt)


class SiteConnectionDialog:
    def __init__(self, root: tk.Tk, app: Any) -> None:
        self.root = root
        self.app = app
        self.dialog: tk.Toplevel | None = None
        self.listener: SiteListener | None = None
        self.connection: PreviewQueueConnection | None = None
        self._timer: str | None = None

    def open(self) -> None:
        if self.dialog is not None:
            self.dialog.lift()
            return
        if self.app._is_shutting_down:
            return
        session = SiteSession()
        try:
            self.listener = SiteListener(session)
        except OSError:
            messagebox.showerror(
                "StableNew Site connection",
                "The local connection could not open. Close another Site connection using this port and try again.",
                parent=self.root,
            )
            return

        self.dialog = dialog = tk.Toplevel(self.root)
        dialog.title("StableNew Site connection")
        dialog.transient(self.root)
        dialog.protocol("WM_DELETE_WINDOW", self.close)
        dialog.bind("<Destroy>", self._destroyed, add="+")
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame, text="Pair the private StableNew Site", font=("TkDefaultFont", 12, "bold")
        ).pack(anchor="w")
        ttk.Label(
            frame,
            text="Paste this code into Connect StableNew on the Site. This connection expires in 15 minutes.",
            wraplength=370,
        ).pack(anchor="w", pady=(5, 12))
        code = ttk.Entry(frame, width=48)
        code.insert(0, session.code)
        code.configure(state="readonly")
        code.pack(fill="x")
        ttk.Button(frame, text="Copy pairing code", command=lambda: self._copy(session.code)).pack(
            anchor="w", pady=6
        )
        ttk.Label(
            frame,
            text="Keep this window open. Queue requests ask for confirmation in StableNew.",
            wraplength=370,
        ).pack(anchor="w", pady=(4, 8))
        ttk.Button(frame, text="Disconnect", command=self.close).pack(anchor="e")
        self.connection = PreviewQueueConnection(self.app, session, self._confirm)
        self._tick()

    def _copy(self, code: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(code)

    def _confirm(self, count: int) -> bool:
        dialog = self.dialog
        if dialog is None:
            return False
        return messagebox.askyesno(
            "Queue image Preview from the StableNew Site?",
            f"Add the {count} currently previewed image job(s) to the existing StableNew queue? "
            "The normal queue dispatch policy applies.",
            parent=dialog,
            default=messagebox.NO,
        )

    def _tick(self) -> None:
        self._timer = None
        connection = self.connection
        if connection is None:
            return
        if connection.session.expired or self.app._is_shutting_down:
            self.close()
            return
        connection.tick()
        if self.dialog is not None and connection is self.connection:
            self._timer = self.root.after(150, self._tick)

    def _destroyed(self, event: tk.Event[Any]) -> None:
        if event.widget is self.dialog:
            self._disconnect()

    def _disconnect(self) -> None:
        self.dialog = None
        self.connection = None
        if self._timer is not None:
            self.root.after_cancel(self._timer)
            self._timer = None
        if self.listener is not None:
            self.listener.close()
            self.listener = None

    def close(self) -> None:
        dialog = self.dialog
        self._disconnect()
        if dialog is not None:
            dialog.destroy()


def install_site_connection_menu(root: tk.Tk, app: Any) -> None:
    """Add the local opt-in entry at desktop composition. No socket is opened here."""
    connection = SiteConnectionDialog(root, app)
    menu_path = root.cget("menu")
    menu = cast(tk.Menu, root.nametowidget(menu_path)) if menu_path else tk.Menu(root)
    if not menu_path:
        root.configure(menu=menu)
    site = tk.Menu(menu, tearoff=False)
    site.add_command(label="Connect Operator Site", command=connection.open)
    menu.add_cascade(label="Operator Site", menu=site)
