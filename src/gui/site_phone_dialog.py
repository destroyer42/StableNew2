"""Local consent and connection status for the optional phone connector."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from src.app.site_phone_connector import PhoneConnectorError, PhoneEnrollment, SitePhoneConnector


class PhoneReviewDialog:
    def __init__(self, root: tk.Tk, connector: SitePhoneConnector) -> None:
        self._root = root
        self._connector = connector
        self._dialog: tk.Toplevel | None = None

    def open(self) -> None:
        if self._dialog is not None and self._dialog.winfo_exists():
            self._dialog.lift()
            return
        dialog = self._dialog = tk.Toplevel(self._root)
        dialog.title("StableNew phone review")
        dialog.transient(self._root)
        panel = ttk.Frame(dialog, padding=16)
        panel.pack(fill="both", expand=True)
        ttk.Label(
            panel,
            text="Sign in to the private Site on your phone. Under Connect StableNew, request a phone pairing code.",
            wraplength=370,
        ).pack(anchor="w", pady=(0, 12))
        ttk.Label(panel, text="Site service credential").pack(anchor="w")
        credential = ttk.Entry(panel, show="*", width=50)
        credential.pack(fill="x", pady=(0, 8))
        ttk.Label(panel, text="Phone pairing code").pack(anchor="w")
        code = ttk.Entry(panel, show="*", width=50)
        code.pack(fill="x", pady=(0, 8))
        rating = tk.BooleanVar(master=dialog)
        ttk.Checkbutton(panel, text="Also allow saving ratings", variable=rating).pack(anchor="w")
        status = ttk.Label(panel, wraplength=370)
        status.pack(anchor="w", pady=(10, 4))
        feedback = ttk.Label(panel, wraplength=370)
        feedback.pack(anchor="w")

        def approve(enrollment: PhoneEnrollment) -> None:
            credential.delete(0, "end")
            code.delete(0, "end")
            folder = filedialog.askdirectory(
                parent=dialog,
                title="Choose the Output folder to share with this phone",
                mustexist=True,
            )
            if not folder:
                return
            can_rate = rating.get()
            access = "browse and rate" if can_rate else "browse"
            if messagebox.askyesno(
                "Approve phone review?",
                f"Allow {enrollment.name} to {access} this folder for up to 30 days?\n\n{folder}",
                parent=dialog,
                default=messagebox.NO,
            ):
                self._watch(
                    dialog,
                    self._connector.enroll(enrollment, Path(folder), can_rate),
                    lambda _: feedback.configure(text="Pairing approved on this PC."),
                    feedback,
                )

        def inspect() -> None:
            feedback.configure(text="Checking the phone pairing code…")
            self._watch(
                dialog,
                self._connector.inspect(credential.get().strip(), code.get().strip().lower()),
                approve,
                feedback,
            )

        def revoke() -> None:
            if messagebox.askyesno(
                "Revoke phone review?",
                "Block this phone's access to Output on this PC?",
                parent=dialog,
                default=messagebox.NO,
            ):
                feedback.configure(text="Revocation requested.")
                self._connector.revoke()

        def update_credential() -> None:
            self._watch(
                dialog,
                self._connector.update_site_credential(credential.get().strip()),
                lambda _: credential.delete(0, "end"),
                feedback,
            )

        def update_status() -> None:
            if dialog.winfo_exists():
                status.configure(text=self._connector.status)
                dialog.after(500, update_status)

        buttons = ttk.Frame(panel)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Review pairing…", command=inspect).pack(side="left")
        ttk.Button(buttons, text="Update credential", command=update_credential).pack(
            side="left", padx=8
        )
        ttk.Button(buttons, text="Revoke phone", command=revoke).pack(side="right")
        update_status()

    def _watch[T](
        self,
        dialog: tk.Toplevel,
        future: Future[T],
        complete: Callable[[T], object],
        feedback: ttk.Label,
    ) -> None:
        if not dialog.winfo_exists():
            return
        if not future.done():
            dialog.after(100, self._watch, dialog, future, complete, feedback)
            return
        try:
            feedback.configure(text="")
            complete(future.result())
        except PhoneConnectorError as error:
            feedback.configure(text=str(error))
