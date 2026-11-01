"""Read-only "Compare with Parent" window (PR-HISTORY-610B): parent image left, child image right, typed differences.

The window owns presentation only. All repository, hashing and decode work runs on the keyed latest-wins background
runner; its callbacks are dropped once the window is closed or a newer request supersedes them. Images use the shared
``MediaInspector`` (bounded decode, zoom, content-visibility policy) with a decoder bound to the verified bytes, so a
file changed after verification is never displayed. Nothing here queues a job, edits a draft or writes a record.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import Any

from src.controller.content_visibility_resolver import (
    REDACTED_TEXT,
    ContentVisibilityResolver,
)
from src.gui import theme_v2 as theme_mod
from src.gui.controllers.history_compare_service import (
    Comparison,
    HistoryCompareService,
)
from src.gui.ui_dispatcher import tk_dispatcher_for
from src.gui.view_contracts.edit_work_runner import build_edit_work_runner
from src.gui.view_contracts.history_comparison_artifact import (
    VerifiedImage,
    decode_verified_image,
)
from src.gui.view_contracts.media_image_decode import InspectionImage
from src.gui.widgets.media_inspector import MediaInspector
from src.gui_v2.history_compare_model import (
    ComparisonRefused,
    DifferenceState,
    format_value,
)

_LOADING = "Verifying recorded lineage, both images and the stored settings…"
_COLUMNS = ("field", "state", "parent", "child")


class HistoryCompareDialog(tk.Toplevel):
    def __init__(
        self, master: tk.Misc, *, repository: Any, child_id: str, app_state: Any = None
    ) -> None:
        super().__init__(master)
        self.title("Compare with Parent")
        self.geometry("1180x820")
        self.minsize(760, 560)
        theme_mod.apply_toplevel_theme(self)
        self.app_state = app_state
        self._service = HistoryCompareService(repository)
        self._work = build_edit_work_runner(self)
        self._closed = False
        self._revision = 0
        self._child_id = child_id
        self.comparison: Comparison | None = None
        self._proofs: dict[str, VerifiedImage] = {}
        self._changes_only = tk.BooleanVar(master=self, value=False)
        self.status_var = tk.StringVar(master=self, value=_LOADING)
        self.identity_var = tk.StringVar(master=self, value="")
        self.parent_title_var = tk.StringVar(master=self, value="Parent")
        self.child_title_var = tk.StringVar(master=self, value="Child")
        self._build()
        self.bind("<Escape>", lambda _event: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        dispatcher = tk_dispatcher_for(self)
        self._policy_callback = lambda: dispatcher.invoke(self._policy_changed)
        if callable(getattr(app_state, "subscribe", None)):
            app_state.subscribe("content_visibility_mode", self._policy_callback)
        self.load(child_id)

    # --- layout -------------------------------------------------------------------------------

    def _build(self) -> None:
        surface = theme_mod.SURFACE_FRAME_STYLE
        body = ttk.Frame(self, style=surface, padding=theme_mod.PADDING_MD)
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=3)
        body.rowconfigure(3, weight=2)
        ttk.Label(
            body,
            textvariable=self.status_var,
            style=theme_mod.STATUS_STRONG_LABEL_STYLE,
            wraplength=1100,
            justify=tk.LEFT,
        ).grid(row=0, column=0, sticky="ew")
        ttk.Label(
            body,
            textvariable=self.identity_var,
            style=theme_mod.MUTED_LABEL_STYLE,
            wraplength=1100,
            justify=tk.LEFT,
        ).grid(row=1, column=0, sticky="ew", pady=(0, 6))

        images = ttk.Frame(body, style=surface)
        images.grid(row=2, column=0, sticky="nsew")
        images.columnconfigure((0, 1), weight=1, uniform="side")
        images.rowconfigure(1, weight=1)
        for column, title in ((0, self.parent_title_var), (1, self.child_title_var)):
            ttk.Label(images, textvariable=title, style=theme_mod.STATUS_STRONG_LABEL_STYLE).grid(
                row=0, column=column, sticky="w", padx=4
            )
        self.parent_view = MediaInspector(
            images,
            width=480,
            height=320,
            allow_original=False,
            image_decoder=self._decoder,
            follow_workspace=False,
        )
        self.child_view = MediaInspector(
            images,
            width=480,
            height=320,
            allow_original=False,
            image_decoder=self._decoder,
            follow_workspace=False,
        )
        self.parent_view.grid(row=1, column=0, sticky="nsew", padx=(0, 4))
        self.child_view.grid(row=1, column=1, sticky="nsew", padx=(4, 0))

        table = ttk.Frame(body, style=surface)
        table.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        table.columnconfigure(0, weight=1)
        table.rowconfigure(1, weight=1)
        ttk.Checkbutton(
            table,
            text="Show changes only",
            style="Dark.TCheckbutton",
            variable=self._changes_only,
            command=self._render,
        ).grid(row=0, column=0, sticky="w")
        self.tree = ttk.Treeview(table, columns=_COLUMNS, show="headings", height=8)
        for key, heading, width in (
            ("field", "Setting", 220), ("state", "State", 110),
            ("parent", "Parent", 320), ("child", "Child", 320),
        ):  # fmt: skip
            self.tree.heading(key, text=heading)
            self.tree.column(key, width=width, stretch=key in {"parent", "child"})
        vertical = ttk.Scrollbar(table, orient=tk.VERTICAL, command=self.tree.yview)
        horizontal = ttk.Scrollbar(table, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=1, column=0, sticky="nsew")
        vertical.grid(row=1, column=1, sticky="ns")
        horizontal.grid(row=2, column=0, sticky="ew")

        footer = ttk.Frame(body, style=surface)
        footer.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        footer.columnconfigure(0, weight=1)
        self.limits_var = tk.StringVar(master=self, value="")
        ttk.Label(
            footer,
            textvariable=self.limits_var,
            style=theme_mod.MUTED_LABEL_STYLE,
            wraplength=980,
            justify=tk.LEFT,
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            footer,
            text="Read-only: nothing is queued and neither job nor image is changed.",
            style=theme_mod.MUTED_LABEL_STYLE,
        ).grid(row=1, column=0, sticky="w")
        ttk.Button(footer, text="Close", command=self.destroy).grid(row=0, column=1, rowspan=2)

    # --- loading ------------------------------------------------------------------------------

    def _decoder(self, path: str, cancel: threading.Event) -> InspectionImage:
        proof = self._proofs.get(path)
        if proof is None:
            raise ValueError("Image is not part of the verified comparison")
        try:
            return decode_verified_image(proof, cancel)
        except ComparisonRefused as exc:
            raise ValueError(str(exc)) from exc

    def load(self, child_id: str) -> None:
        """Start (or restart) the comparison for ``child_id``; any older request's result is dropped."""

        if self._closed:
            return
        self._revision += 1
        revision = self._revision
        self._child_id = child_id
        self._clear()
        self.status_var.set(_LOADING)
        self._work.submit(
            "compare",
            lambda: self._service.prepare(child_id),
            on_result=lambda comparison: self._ready(revision, comparison),
            on_error=lambda error: self._failed(revision, error),
            name="history-compare",
            purpose="Verify lineage, images and settings for Compare with Parent without blocking Tk",
        )

    def _clear(self) -> None:
        self.comparison = None
        self._proofs = {}
        self.parent_view.clear()
        self.child_view.clear()
        self.parent_title_var.set("Parent")
        self.child_title_var.set("Child")
        self.identity_var.set("")
        self.limits_var.set("")
        self.tree.delete(*self.tree.get_children())

    def _failed(self, revision: int, error: Exception) -> None:
        if self._closed or revision != self._revision:
            return
        self._clear()
        self.status_var.set(
            str(error)
            if isinstance(error, ComparisonRefused)
            else "The stored comparison could not be read safely."
        )

    def _ready(self, revision: int, comparison: Comparison) -> None:
        if self._closed or revision != self._revision:
            return
        self.comparison = comparison
        self._proofs = {
            comparison.parent.image.path: comparison.parent.image,
            comparison.child.image.path: comparison.child.image,
        }
        for view, side in (
            (self.parent_view, comparison.parent),
            (self.child_view, comparison.child),
        ):
            view.set_media(side.image.path, "image", subject=side.visibility_subject)
        self.parent_title_var.set(f"Parent - job {comparison.parent.job.job_id}")
        self.child_title_var.set(f"Child - job {comparison.child.job.job_id}")
        self.status_var.set(
            f"{comparison.relationship}: left is the recorded parent, right is its child."
        )
        self.identity_var.set(comparison.identity_note)
        self.limits_var.set(" ".join(comparison.limitations))
        self._render()

    # --- difference table (re-rendered, never re-fetched, when visibility changes) -------------------

    def _mode(self) -> str:
        return str(getattr(self.app_state, "content_visibility_mode", None) or "nsfw")

    @staticmethod
    def _shown(value: Any, restricted: bool, resolver: ContentVisibilityResolver) -> str:
        text = format_value(value)
        if restricted:  # the whole side is restricted (classified once per render, not per cell)
            return REDACTED_TEXT if text.strip() else text
        return resolver.redact_text(text)  # restricted text on an otherwise clean side

    def _render(self) -> None:
        self.tree.delete(*self.tree.get_children())
        comparison = self.comparison
        if comparison is None or self._closed:
            return
        resolver = ContentVisibilityResolver(self._mode())
        restricted = (
            not resolver.is_visible(comparison.parent.visibility_subject),
            not resolver.is_visible(comparison.child.visibility_subject),
        )
        changes_only = self._changes_only.get()
        group = ""
        for row in comparison.differences:
            if changes_only and row.state in {
                DifferenceState.UNCHANGED,
                DifferenceState.NOT_RECORDED,
            }:
                continue
            if row.group != group:
                group = row.group
                self.tree.insert("", "end", values=(f"— {group} —", "", "", ""))
            label = row.field + (" (observed)" if row.evidence == "observed" else "")
            self.tree.insert(
                "",
                "end",
                values=(
                    label,
                    row.state.value,
                    self._shown(row.parent, restricted[0], resolver),
                    self._shown(row.child, restricted[1], resolver),
                ),
            )

    def _policy_changed(self) -> None:
        if not self._closed:
            self._render()

    # --- teardown -----------------------------------------------------------------------------

    def destroy(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._revision += 1
        self._work.close()
        self.comparison = None
        self._proofs = {}
        if callable(getattr(self.app_state, "unsubscribe", None)):
            self.app_state.unsubscribe("content_visibility_mode", self._policy_callback)
        super().destroy()


__all__ = ["HistoryCompareDialog"]
