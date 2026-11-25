"""Local consent and connection status for the optional phone connector."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from src.app.site_phone_connector import PhoneConnectorError, PhoneEnrollment, SitePhoneConnector

DEFAULT_NATIVE_REVIEW = True


def pairing_permissions(rating: bool, native_review: bool, queue_submit: bool = False) -> str:
    gallery = (
        "Browse Output, save gallery and video ratings, and refresh eval reports in shared Output"
        if rating
        else "Browse Output"
    )
    review = (
        "Write native Review evidence with ratings, Retain, and Mark for rework"
        if native_review
        else "Native Review evidence permission off"
    )
    queue = (
        "Preview and submit saved PromptPacks, images marked for rework, video jobs, and video evaluations"
        if queue_submit
        else "Phone queue submission permission off"
    )
    return f"• {gallery}\n• {review}\n• {queue}"


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
        ttk.Checkbutton(panel, text="Allow ratings and eval report refresh", variable=rating).pack(
            anchor="w"
        )
        native_review = tk.BooleanVar(master=dialog, value=DEFAULT_NATIVE_REVIEW)
        ttk.Checkbutton(
            panel, text="Allow writing native Review evidence", variable=native_review
        ).pack(anchor="w")
        ttk.Label(
            panel, text="Native Review ratings, Retain, and Mark for rework", wraplength=370
        ).pack(anchor="w", padx=18)
        queue_submit = tk.BooleanVar(master=dialog, value=False)
        ttk.Checkbutton(
            panel, text="Allow phone Preview and queue submission", variable=queue_submit
        ).pack(anchor="w")
        ttk.Label(
            panel, text="Saved PromptPacks, marked rework, and video plans", wraplength=370
        ).pack(anchor="w", padx=18)
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
            can_review = native_review.get()
            can_submit = queue_submit.get()
            if messagebox.askyesno(
                "Approve phone review?",
                f"Approve {enrollment.name} for up to 30 days?\n\n{folder}\n\n"
                f"{pairing_permissions(can_rate, can_review, can_submit)}",
                parent=dialog,
                default=messagebox.NO,
            ):
                self._watch(
                    dialog,
                    self._connector.enroll(
                        enrollment,
                        Path(folder),
                        can_rate,
                        native_review=can_review,
                        queue_submit=can_submit,
                    ),
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

        def change_output() -> None:
            folder = filedialog.askdirectory(
                parent=dialog,
                title="Choose the Output folder to share with the approved phone",
                mustexist=True,
            )
            if folder and messagebox.askyesno(
                "Change phone Output?",
                f"Share this folder with the approved phone using its existing permissions?\n\n{folder}",
                parent=dialog,
                default=messagebox.NO,
            ):
                self._watch(
                    dialog,
                    self._connector.change_folder(Path(folder)),
                    lambda _: feedback.configure(
                        text="The phone's shared Output folder was updated."
                    ),
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
        ttk.Button(panel, text="Change shared Output…", command=change_output).pack(anchor="w")
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
