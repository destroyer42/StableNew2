"""Modal review of a selected retry (PR-BATCH-OPS-201).

Shows every selected job - ineligible ones with their reasons, never silently omitted - and a specific, prominent
acknowledgement for each job whose previous request may have produced output. It performs no admission itself:
``result`` is the tuple of acknowledged job ids to submit, or ``None`` when the operator backed out.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any


class BatchRetryDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, plan: Any) -> None:
        super().__init__(master)
        self.plan = plan
        self.result: tuple[str, ...] | None = None
        self.title("Retry failed jobs")
        self.resizable(True, True)
        self.ack_vars: dict[str, tk.BooleanVar] = {}
        self.columnconfigure(0, weight=1)

        eligible = sum(1 for item in plan.items if item.eligible)
        ttk.Label(
            self,
            wraplength=560,
            justify="left",
            text=(
                f"Retry {len(plan.items)} selected job(s) from {plan.key.label} as NEW jobs.\n"
                "The original failed jobs stay unchanged, and the new jobs are not members of the "
                "original batch."
            ),
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))

        columns = ("source", "failure", "result")
        self.rows = ttk.Treeview(self, columns=columns, show="headings", height=min(10, len(plan.items)))
        for name, title, width in (("source", "Source", 180), ("failure", "Failure", 190), ("result", "Retry", 260)):
            self.rows.heading(name, text=title)
            self.rows.column(name, width=width, stretch=name == "result")
        for item in plan.items:
            verdict = "Ready" if item.eligible else "Cannot retry: " + " ".join(item.reasons)
            self.rows.insert("", "end", iid=item.job_id, values=(item.source_label, item.failure_label, verdict))
        self.rows.grid(row=1, column=0, sticky="nsew", padx=12)

        self.notice = ttk.Label(self, wraplength=560, justify="left", foreground="#a14a00")
        self.notice.grid(row=2, column=0, sticky="ew", padx=12, pady=(8, 0))
        if plan.ineligible:
            self.notice.configure(
                text="Some selected jobs cannot be retried. Close this window and revise the selection; "
                "nothing is submitted while any selected job is ineligible."
            )

        self.ack_frame = ttk.Frame(self)
        self.ack_frame.grid(row=3, column=0, sticky="ew", padx=12, pady=(6, 0))
        for item in plan.acknowledgements:
            variable = tk.BooleanVar(master=self, value=False)
            self.ack_vars[item.job_id] = variable
            ttk.Checkbutton(
                self.ack_frame,
                variable=variable,
                command=self._sync,
                text=f"{item.source_label}: {item.acknowledgement_text}",
            ).pack(anchor="w", pady=2)

        buttons = ttk.Frame(self)
        buttons.grid(row=4, column=0, sticky="e", padx=12, pady=12)
        self.submit_button = ttk.Button(
            buttons, text=f"Retry {eligible} job(s)", command=self.submit, state="disabled"
        )
        self.submit_button.pack(side="right", padx=(6, 0))
        self.cancel_button = ttk.Button(buttons, text="Close", command=self.cancel)
        self.cancel_button.pack(side="right")
        self.bind("<Escape>", lambda _event: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self._sync()

    def _sync(self) -> None:
        ready = self.plan.submittable and all(variable.get() for variable in self.ack_vars.values())
        self.submit_button.configure(state="normal" if ready else "disabled")
        if self.plan.submittable and self.ack_vars and not ready:
            self.notice.configure(
                text="Acknowledge each warning above to enable the retry. A new generation can duplicate "
                "output that may already exist."
            )
        elif self.plan.submittable:
            self.notice.configure(text="")

    def submit(self) -> None:
        if str(self.submit_button.cget("state")) == "disabled":
            return
        self.result = tuple(job_id for job_id, variable in self.ack_vars.items() if variable.get())
        self.destroy()

    def cancel(self) -> None:
        self.result = None
        self.destroy()

    def show(self) -> tuple[str, ...] | None:
        """Run modally; ``None`` unless the operator confirmed."""

        try:
            self.transient(self.master.winfo_toplevel())
            self.grab_set()
        except tk.TclError:
            pass
        self.wait_window(self)
        return self.result


__all__ = ["BatchRetryDialog"]
