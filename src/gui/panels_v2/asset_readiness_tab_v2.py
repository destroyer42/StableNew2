"""Read-only asset readiness tab for the Debug Hub (PR-ASSET-130).

Presentation only: the projection is ``src/assets/resource_readiness`` over the one ``AssetRegistry``, and the session in
``src/gui_v2/asset_readiness_view`` owns latest-wins delivery. Nothing is read or hashed until an operator presses a
button, and no button downloads, installs, selects a model or enqueues work.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from src.gui.ui_dispatcher import TkUiDispatcher
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.gui_v2.asset_readiness_view import ReadinessSession, headline, project_rows
from src.utils.thread_registry import get_thread_registry


def produce_report(refresh: bool, cancelled: Callable[[], bool]) -> dict[str, Any]:
    """Worker-side: one report from the application's registry (``refresh`` streams SHA-256 of two folders)."""

    from src.assets.registry import AssetRegistry
    from src.assets.resource_catalog import load_catalog
    from src.assets.resource_readiness import build_report, collect_installed_evidence

    catalog = load_catalog()
    evidence = collect_installed_evidence(
        AssetRegistry(), catalog, refresh=refresh, cancelled=cancelled
    )
    return build_report(catalog, evidence)


class AssetReadinessTab(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        runner: BackgroundWorkRunner | None = None,
        producer: Callable[[bool, Callable[[], bool]], dict[str, Any]] = produce_report,
    ) -> None:
        super().__init__(master)
        bar = ttk.Frame(self)
        bar.pack(fill=tk.X, pady=(0, 4))
        self._status = tk.StringVar(
            value="Press a button to check. Nothing is scanned or hashed until you do; nothing is downloaded."
        )
        self._cached_button = ttk.Button(
            bar, text="Check (cached)", command=lambda: self._request(False)
        )
        self._cached_button.pack(side=tk.LEFT)
        self._refresh_button = ttk.Button(
            bar, text="Refresh (hash files)", command=lambda: self._request(True)
        )
        self._refresh_button.pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(self, textvariable=self._status, wraplength=880, anchor="w").pack(fill=tk.X)
        self._text = tk.Text(self, wrap=tk.WORD, state=tk.DISABLED)
        self._text.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self._runner = runner or BackgroundWorkRunner(
            spawn=lambda name, target: get_thread_registry().spawn(
                target=target, name=name, daemon=False, purpose="Asset readiness check"
            ),
            dispatch=TkUiDispatcher(self.winfo_toplevel()).invoke,
        )
        self.session = ReadinessSession(
            self._runner, producer, self._show_report, self._show_error, self._set_busy
        )
        self.bind(
            "<Destroy>",
            lambda event: self.session.close() if event.widget is self else None,
            add="+",
        )

    def _request(self, refresh: bool) -> None:
        self._status.set("Hashing files…" if refresh else "Reading the cached inventory…")
        self.session.request(refresh=refresh)

    def _set_busy(self, busy: bool) -> None:
        state = ["disabled"] if busy else ["!disabled"]
        self._cached_button.state(state)
        self._refresh_button.state(state)

    def _show_error(self, message: str) -> None:
        self._status.set(f"Readiness check failed: {message}")

    def _show_report(self, report: dict[str, Any]) -> None:
        self._status.set(headline(report))
        lines: list[str] = []
        for row in project_rows(report):
            lines.append(f"{row.title} - {row.status_label}")
            lines.append(f"  {row.detail}")
            lines.extend(f"  {step}" for step in row.steps)
            lines.append("")
        self._text.config(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        self._text.insert(tk.END, "\n".join(lines))
        self._text.config(state=tk.DISABLED)
