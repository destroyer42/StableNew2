"""API Failure Visualizer for the Debug Hub."""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk

from src.utils.api_failure_store_v2 import ApiFailureRecord, get_api_failures


class ApiFailureVisualizerV2(ttk.Frame):
    """Visual definition of recent API failures."""

    def __init__(self, master: tk.Misc, *, limit: int = 5) -> None:
        super().__init__(master)
        self.limit = limit
        self._photo: tk.PhotoImage | None = None

        header = ttk.Frame(self)
        header.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(header, text="API Failure Visualizer").pack(side=tk.LEFT)
        ttk.Button(header, text="Refresh", command=self.refresh).pack(side=tk.RIGHT)

        body = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True)

        self._list_frame = ttk.Frame(body)
        self._list_frame.columnconfigure(0, weight=1)
        body.add(self._list_frame, weight=1)

        self._detail_frame = ttk.Frame(body)
        self._detail_frame.columnconfigure(0, weight=1)
        body.add(self._detail_frame, weight=2)

        columns = ("stage", "endpoint", "status", "summary")
        self._tree = ttk.Treeview(self._list_frame, columns=columns, show="headings", height=8)
        for col, label in [
            ("stage", "Stage"),
            ("endpoint", "Endpoint"),
            ("status", "Status"),
            ("summary", "Summary"),
        ]:
            self._tree.heading(col, text=label)
            self._tree.column(col, anchor=tk.W, width=120)
        self._tree.pack(fill=tk.BOTH, expand=True)
        self._tree.bind("<<TreeviewSelect>>", lambda *_: self._show_selected())

        detail_header = ttk.Frame(self._detail_frame)
        detail_header.pack(fill=tk.X)
        self._detail_label = ttk.Label(detail_header, text="Select a failure to inspect.")
        self._detail_label.pack(anchor=tk.W)

        self._response_text = tk.Text(self._detail_frame, height=6, wrap=tk.WORD)
        self._response_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._response_text.configure(state=tk.DISABLED)

        self._payload_text = tk.Text(self._detail_frame, height=6, wrap=tk.WORD)
        self._payload_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._payload_text.configure(state=tk.DISABLED)

        self._image_label = ttk.Label(self._detail_frame, text="Image preview")
        self._image_label.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self._records: list[ApiFailureRecord] = []
        self.refresh()

    def refresh(self) -> None:
        """Reload the failure list."""
        self._records = get_api_failures(limit=self.limit)
        self._tree.delete(*self._tree.get_children())
        for idx, record in enumerate(self._records):
            status = str(record.status_code) if record.status_code else "-"
            summary = record.error_message[:60]
            self._tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    record.stage or "api",
                    record.endpoint,
                    status,
                    summary,
                ),
            )
        self._detail_label.config(text="Select a failure to inspect.")
        self._clear_detail()

    def _show_selected(self) -> None:
        selection = self._tree.selection()
        if not selection:
            return
        record = self._records[int(selection[0])]
        self._detail_label.config(
            text=f"{record.method} {record.endpoint} ({record.status_code or 'n/a'})"
        )
        self._populate_text_widget(self._response_text, record.response_text or "No response body")
        payload_str = "<missing payload>"
        if record.payload:
            payload_str = json.dumps(record.payload, indent=2, ensure_ascii=False)
        self._populate_text_widget(self._payload_text, payload_str)
        self._update_image(record)

    def _populate_text_widget(self, widget: tk.Text, text: str) -> None:
        widget.config(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, text)
        widget.config(state=tk.DISABLED)

    def _update_image(self, record: ApiFailureRecord) -> None:
        data = record.image_base64
        if not data:
            self._image_label.config(text="Image preview unavailable")
            self._photo = None
            self._image_label.config(image="")
            return
        try:
            photo = tk.PhotoImage(data=data, format="png")
            self._photo = photo
            self._image_label.config(image=photo, text="")
        except Exception:
            self._image_label.config(text="Image preview failed to decode")
            self._photo = None

    def _clear_detail(self) -> None:
        self._populate_text_widget(self._response_text, "")
        self._populate_text_widget(self._payload_text, "")
        self._image_label.config(image="", text="Image preview")
        self._photo = None
