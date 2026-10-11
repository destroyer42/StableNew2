"""Transient whole-selection review; confirmation admits the exact prepared NJRs."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from src.controller.review_batch_service import ReviewBatchPreview


class ReviewBatchDialog(tk.Toplevel):
    def __init__(self, parent: Any, preview: ReviewBatchPreview, *, submit: Any,
                 repreview: Any, visibility: Any) -> None:
        super().__init__(parent)
        self.title("Review batch preview")
        self.geometry("1000x540")
        self.transient(parent.winfo_toplevel())
        self.preview, self._submit, self._repreview, self._visibility = preview, submit, repreview, visibility
        self._attempted = False
        self._inflight = False
        self.protocol("WM_DELETE_WINDOW", lambda: None if self._inflight else self.destroy())
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        summary = (f"{len(preview.items)} sources · {len(preview.jobs)} compiled jobs · "
                   f"{len(preview.blocked)} blocked · "
                   f"Order: {'model/profile groups' if preview.group_by_model else 'source order'}")
        ttk.Label(frame, text=summary).pack(anchor="w")
        ttk.Label(frame, text=f"Batch: {preview.batch_id}").pack(anchor="w", pady=(4, 8))
        self.rows = ttk.Treeview(frame, columns=("source", "model", "prompt", "metadata", "order", "status"),
                                 show="headings", selectmode="browse")
        for key, label, width in (("source", "Source", 160), ("model", "Checkpoint", 150),
                                  ("prompt", "Final positive prompt", 230), ("metadata", "Baseline", 120),
                                  ("order", "Job order", 65), ("status", "Status / action", 250)):
            self.rows.heading(key, text=label)
            self.rows.column(key, width=width)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.rows.yview)
        scroll.pack(side="right", fill="y")
        self.rows.configure(yscrollcommand=scroll.set)
        self.rows.pack(fill="both", expand=True)
        order = {path: index + 1 for index, job in enumerate(preview.jobs) for path in job.input_image_paths}
        for item in preview.items:
            subject = {"positive_prompt": item.prompt, "name": Path(item.path).name}
            self.rows.insert("", "end", values=(Path(item.path).name, item.model or "n/a",
                visibility.redact_text(item.prompt, item=subject), item.metadata_source,
                order.get(item.path, "—"), item.error or "Compiled"))
        self.details = tk.Text(frame, height=5, wrap="word")
        self.details.pack(fill="x", pady=8)
        self.rows.bind("<<TreeviewSelect>>", lambda _: self._show_details())
        ttk.Label(frame, text="No sources are omitted automatically. Cancel before confirmation leaves the queue unchanged.").pack(anchor="w")
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(8, 0))
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self.destroy)
        self.cancel_button.pack(side="right")
        self.exclude_button = ttk.Button(actions, text="Exclude blocked and re-preview", command=self._exclude)
        self.exclude_button.pack(side="left")
        self.exclude_button.state(["!disabled"] if preview.blocked and preview.jobs else ["disabled"])
        self.repreview_button = ttk.Button(actions, text="Re-preview all", command=self._preview_all)
        self.repreview_button.pack(side="left", padx=8)
        self.submit_button = ttk.Button(actions, text=f"Add {len(preview.jobs)} jobs to Queue", command=self._confirm)
        self.submit_button.pack(side="right", padx=8)
        if preview.blocked or not preview.jobs:
            self.submit_button.state(["disabled"])
        first = self.rows.get_children()
        if first:
            self.rows.selection_set(first[0])
            self._show_details()

    def _show_details(self) -> None:
        selected = self.rows.selection()
        if not selected:
            return
        values = self.rows.item(selected[0], "values")
        index = self.rows.index(selected[0])
        item = self.preview.items[index]
        job = next((job for job in self.preview.jobs if item.path in job.input_image_paths), None)
        detail = f"Source: {item.path}\nCheckpoint: {values[1]}\nPositive prompt: {values[2]}\n{values[5]}"
        if job is not None:
            negative = self._visibility.redact_text(job.negative_prompt, item={"positive_prompt": job.positive_prompt})
            settings = "\n".join(
                f"{stage.stage_type}: sampler={stage.sampler_name}, scheduler={stage.scheduler}, "
                f"steps={stage.steps}, CFG={stage.cfg_scale}, denoise={stage.denoising_strength}"
                for stage in job.stage_chain if stage.enabled
            )
            detail += (f"\nNegative prompt: {negative}\n{settings}\nBackend/profile: {job.backend_options}"
                       f"\nOutput directory: {job.output_plan.base_output_dir}\nJob: {job.job_id}"
                       f"\nParent job: {job.source.parent_job_id or 'unavailable'}"
                       f"\nSource artifact: {job.source.parent_artifact_id}")
        self.details.delete("1.0", tk.END)
        self.details.insert("1.0", detail)

    def _preview_all(self) -> None:
        if self._inflight:
            return
        paths = [item.path for item in self.preview.items]
        self.destroy()
        self._repreview(paths)

    def _exclude(self) -> None:
        if self._inflight or not self.preview.blocked:
            return
        paths = [item.path for item in self.preview.items if not item.error]
        self.destroy()
        self._repreview(paths)

    def _confirm(self) -> None:
        if self._attempted or self.preview.blocked or not self.preview.jobs:
            return
        self._attempted = True
        self._inflight = True
        self.submit_button.state(["disabled"])
        for button in (self.cancel_button, self.repreview_button, self.exclude_button):
            button.state(["disabled"])
        try:
            self._submit(self.preview, on_submitted=self._submitted, on_error=self._failed)
        except Exception as exc:
            self._failed(exc)

    def _failed(self, exc: Exception) -> None:
        self._inflight = False
        if not self.winfo_exists():
            return
        self.cancel_button.state(["!disabled"])
        self.repreview_button.state(["!disabled"])
        messagebox.showerror("Review batch not submitted", str(exc), parent=self)

    def _submitted(self, count: int) -> None:
        self._inflight = False
        if not self.winfo_exists():
            return
        messagebox.showinfo("Submitted", f"Submitted {count} jobs. Batch: {self.preview.batch_id}", parent=self)
        self.destroy()
