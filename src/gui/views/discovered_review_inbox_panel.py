# Subsystem: Learning / GUI
# Role: Inbox panel showing discovered-review groups by status.

"""DiscoveredReviewInboxPanel — lists discovered groups with status controls."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk
from typing import Any

from src.gui.theme_v2 import BODY_LABEL_STYLE, SURFACE_FRAME_STYLE
from src.learning.discovered_review_models import (
    STATUS_CLOSED,
    STATUS_IGNORED,
    STATUS_IN_REVIEW,
    STATUS_WAITING_REVIEW,
    DiscoveredReviewHandle,
)

_STATUS_LABELS = {
    STATUS_WAITING_REVIEW: "Waiting Review",
    STATUS_IN_REVIEW: "In Review",
    STATUS_CLOSED: "Closed",
    STATUS_IGNORED: "Ignored",
}


class DiscoveredReviewInboxPanel(ttk.Frame):
    """Inbox panel for discovered-review groups inside the Learning tab.

    Displays groups filtered by status with action buttons.

    Callbacks
    ---------
    on_open_group(group_id):
        Called when the user double-clicks or clicks Open on a group.
    on_close_group(group_id):
        Called when the user clicks Close on a group.
    on_ignore_group(group_id):
        Called when the user clicks Ignore on a group.
    on_rescan():
        Called when the user clicks Rescan.
    on_pick_scan_root():
        Called when the user clicks Scan Folder.
    on_reset_scan_root():
        Called when the user clicks Auto Root.
    """

    def __init__(
        self,
        master: tk.Misc,
        on_open_group: Callable[[str], None] | None = None,
        on_close_group: Callable[[str], None] | None = None,
        on_ignore_group: Callable[[str], None] | None = None,
        on_reopen_group: Callable[[str], None] | None = None,
        on_rescan: Callable[[], None] | None = None,
        on_pick_scan_root: Callable[[], None] | None = None,
        on_reset_scan_root: Callable[[], None] | None = None,
        on_prune_missing: Callable[[], None] | None = None,
        on_rebuild_scanned: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self._on_open_group = on_open_group
        self._on_close_group = on_close_group
        self._on_ignore_group = on_ignore_group
        self._on_reopen_group = on_reopen_group
        self._on_rescan = on_rescan
        self._on_pick_scan_root = on_pick_scan_root
        self._on_reset_scan_root = on_reset_scan_root
        self._on_prune_missing = on_prune_missing
        self._on_rebuild_scanned = on_rebuild_scanned
        self._handles: list[DiscoveredReviewHandle] = []
        self._status_filter_var = tk.StringVar(value="active")
        self._selected_group_id: str | None = None
        self._scanning_var = tk.BooleanVar(value=False)
        self._scan_root_var = tk.StringVar(value="Scan Root: Auto")

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # --- toolbar ---
        toolbar = ttk.Frame(self, style=SURFACE_FRAME_STYLE, padding=(4, 2))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(5, weight=1)

        ttk.Label(toolbar, text="Filter:", style=BODY_LABEL_STYLE).grid(
            row=0, column=0, padx=(0, 4)
        )
        for col, (label, value) in enumerate(
            [
                ("Active", "active"),
                ("Done", STATUS_CLOSED),
                ("Dismissed", STATUS_IGNORED),
                ("All", "all"),
            ],
            start=1,
        ):
            ttk.Radiobutton(
                toolbar,
                text=label,
                variable=self._status_filter_var,
                value=value,
                command=self._apply_filter,
            ).grid(row=0, column=col, padx=2)

        self._pick_scan_root_btn = ttk.Button(
            toolbar,
            text="Scan Folder",
            command=self._on_pick_scan_root_clicked,
        )
        self._pick_scan_root_btn.grid(row=0, column=5, padx=(8, 0), sticky="e")

        self._reset_scan_root_btn = ttk.Button(
            toolbar,
            text="Auto Root",
            command=self._on_reset_scan_root_clicked,
        )
        self._reset_scan_root_btn.grid(row=0, column=6, padx=(4, 0), sticky="e")

        self._scan_btn = ttk.Button(
            toolbar,
            text="Rescan",
            command=self._on_rescan_clicked,
        )
        self._scan_btn.grid(row=0, column=7, padx=(4, 0), sticky="e")

        self._prune_btn = ttk.Button(
            toolbar, text="Clean Missing References...", command=self._on_prune_clicked
        )
        self._prune_btn.grid(row=0, column=8, padx=(4, 0), sticky="e")
        self._rebuild_btn = ttk.Button(toolbar, text="Rebuild Scanned Inbox...", command=self._on_rebuild_clicked)
        self._rebuild_btn.grid(row=0, column=9, padx=(4, 0), sticky="e")

        self._scan_root_label = ttk.Label(
            toolbar,
            textvariable=self._scan_root_var,
            style=BODY_LABEL_STYLE,
            width=36,
        )
        self._scan_root_label.grid(row=1, column=0, columnspan=10, sticky="w", pady=(4, 0))

        self._scan_status_label = ttk.Label(toolbar, text="", style=BODY_LABEL_STYLE)
        self._scan_status_label.grid(row=2, column=0, columnspan=10, padx=4, sticky="w")

        # --- list frame ---
        list_frame = ttk.Frame(self, style=SURFACE_FRAME_STYLE, padding=4)
        list_frame.grid(row=1, column=0, sticky="nsew", padx=2, pady=2)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        columns = ("status", "count", "available", "missing", "stage", "varying")
        self._tree = ttk.Treeview(
            list_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        self._tree.heading("status", text="Status")
        self._tree.heading("count", text="Images")
        self._tree.heading("available", text="Available")
        self._tree.heading("missing", text="Missing")
        self._tree.heading("stage", text="Stage")
        self._tree.heading("varying", text="Varying Fields")
        self._tree.column("status", width=110, anchor="center")
        self._tree.column("count", width=60, anchor="center")
        self._tree.column("available", width=70, anchor="center")
        self._tree.column("missing", width=60, anchor="center")
        self._tree.column("stage", width=80, anchor="center")
        self._tree.column("varying", width=200, anchor="w")
        self._tree.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns")

        self._tree.bind("<Double-1>", self._on_tree_double_click)
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        # --- action bar ---
        action_bar = ttk.Frame(self, style=SURFACE_FRAME_STYLE, padding=(4, 2))
        action_bar.grid(row=2, column=0, sticky="ew")

        self._open_btn = ttk.Button(
            action_bar,
            text="Review",
            command=self._on_open_clicked,
            state="disabled",
        )
        self._open_btn.pack(side="left", padx=(0, 4))

        self._close_btn = ttk.Button(
            action_bar,
            text="Done",
            command=self._on_close_clicked,
            state="disabled",
        )
        self._close_btn.pack(side="left", padx=(0, 4))

        self._ignore_btn = ttk.Button(
            action_bar,
            text="Dismiss",
            command=self._on_ignore_clicked,
            state="disabled",
        )
        self._ignore_btn.pack(side="left")

        self._reopen_btn = ttk.Button(
            action_bar,
            text="Restore",
            command=self._on_reopen_clicked,
            state="disabled",
        )
        self._reopen_btn.pack(side="left", padx=(4, 0))

        self._group_info_label = ttk.Label(
            action_bar, text="No group selected", style=BODY_LABEL_STYLE
        )
        self._group_info_label.pack(side="right", padx=4)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_handles(self, handles: list[DiscoveredReviewHandle]) -> None:
        """Replace the displayed handles and refresh the list."""
        self._handles = list(handles)
        self._apply_filter()

    def set_scanning(self, scanning: bool) -> None:
        """Update the scan-in-progress indicator."""
        self._scanning_var.set(scanning)
        if scanning:
            self._scan_status_label.configure(text="Scanning…")
            self._scan_btn.configure(state="disabled")
        else:
            self._scan_status_label.configure(text="")
            self._scan_btn.configure(state="normal")

    def get_selected_group_id(self) -> str | None:
        return self._selected_group_id

    def set_scan_root(self, scan_root: str | None) -> None:
        """Update the displayed scan root override state."""
        if scan_root:
            display = str(Path(scan_root))
            if len(display) > 52:
                display = "..." + display[-49:]
            self._scan_root_var.set(f"Scan Root: {display}")
        else:
            self._scan_root_var.set("Scan Root: Auto")

    def set_scan_result(self, result: Any) -> None:
        """Expose success, no-result, and failure outcomes without ambiguity."""
        if not bool(getattr(result, "success", False)):
            self._scan_status_label.configure(
                text=f"Scan failed: {str(getattr(result, 'reason', '') or 'unknown error')[:90]}"
            )
            return
        new_count = int(getattr(result, "new_group_count", 0) or 0)
        record_count = int(getattr(result, "record_count", 0) or 0)
        message = "Scan succeeded: no new groups" if new_count == 0 else f"Scan succeeded: {new_count} new group(s)"
        self._scan_status_label.configure(text=f"{message} ({record_count} eligible artifact(s))")

    # ------------------------------------------------------------------
    # Filter and render
    # ------------------------------------------------------------------

    def _apply_filter(self) -> None:
        filt = self._status_filter_var.get()
        if filt == "active":
            visible = [
                h
                for h in self._handles
                if h.status in (STATUS_WAITING_REVIEW, STATUS_IN_REVIEW)
                and h.available_item_count > 0
            ]
        elif filt == STATUS_CLOSED:
            visible = [h for h in self._handles if h.status == STATUS_CLOSED]
        elif filt == STATUS_IGNORED:
            visible = [h for h in self._handles if h.status == STATUS_IGNORED]
        else:
            visible = list(self._handles)
        self._render_handles(visible)

    def _render_handles(self, handles: list[DiscoveredReviewHandle]) -> None:
        self._tree.delete(*self._tree.get_children())
        for h in handles:
            varying_text = ", ".join(h.varying_fields) or "—"
            status_label = _STATUS_LABELS.get(h.status, h.status)
            self._tree.insert(
                "",
                "end",
                iid=h.group_id,
                values=(
                    status_label,
                    h.item_count,
                    h.available_item_count,
                    h.missing_item_count,
                    h.stage,
                    varying_text,
                ),
                text=h.display_name,
            )
        self._update_action_buttons()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_tree_select(self, _event: Any = None) -> None:
        sel = self._tree.selection()
        self._selected_group_id = sel[0] if sel else None
        self._update_action_buttons()
        if self._selected_group_id:
            handle = self._find_handle(self._selected_group_id)
            if handle:
                info = (
                    f"{handle.display_name} ({handle.available_item_count} available, "
                    f"{handle.missing_item_count} missing)"
                )
                self._group_info_label.configure(text=info)

    def _on_prune_clicked(self) -> None:
        if self._on_prune_missing:
            self._on_prune_missing()

    def _on_rebuild_clicked(self) -> None:
        if self._on_rebuild_scanned:
            self._on_rebuild_scanned()

    def _on_reopen_clicked(self) -> None:
        if self._selected_group_id and self._on_reopen_group:
            self._on_reopen_group(self._selected_group_id)

    def _on_tree_double_click(self, _event: Any = None) -> None:
        if self._selected_group_id and self._on_open_group:
            self._on_open_group(self._selected_group_id)

    def _on_open_clicked(self) -> None:
        if self._selected_group_id and self._on_open_group:
            self._on_open_group(self._selected_group_id)

    def _on_close_clicked(self) -> None:
        if self._selected_group_id and self._on_close_group:
            self._on_close_group(self._selected_group_id)

    def _on_ignore_clicked(self) -> None:
        if self._selected_group_id and self._on_ignore_group:
            self._on_ignore_group(self._selected_group_id)

    def _on_rescan_clicked(self) -> None:
        if self._on_rescan:
            self._on_rescan()

    def _on_pick_scan_root_clicked(self) -> None:
        if self._on_pick_scan_root:
            self._on_pick_scan_root()

    def _on_reset_scan_root_clicked(self) -> None:
        if self._on_reset_scan_root:
            self._on_reset_scan_root()

    def _update_action_buttons(self) -> None:
        state = "normal" if self._selected_group_id else "disabled"
        handle = self._find_handle(self._selected_group_id or "")
        terminal = bool(handle and handle.status in (STATUS_CLOSED, STATUS_IGNORED))
        self._open_btn.configure(state=state if not terminal else "disabled")
        self._close_btn.configure(state=state if not terminal else "disabled")
        self._ignore_btn.configure(state=state if not terminal else "disabled")
        self._reopen_btn.configure(state=state if terminal else "disabled")

    def _find_handle(self, group_id: str) -> DiscoveredReviewHandle | None:
        return next((h for h in self._handles if h.group_id == group_id), None)
