"""Managed Photo Set hand-offs for the Photo Optimize tab (PR-GUI-UX-580).

Two directions, both intent-only (nothing is queued, no job or pipeline state is touched):

* ``receive_review_handoff`` accepts existing image paths from Quick Edit (Review), plans the import on a worker,
  asks the operator to confirm exactly what would be copied, then imports on a worker and selects the result.
* ``_open_selected_in_quick_edit`` hands the selected photos' current working images to Review's selection; Review
  asks Replace/Cancel itself when it holds unsent work.

Paths are the only thing that crosses: Review's History/Staged-Curation lineage never reaches a managed asset.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from tkinter import messagebox
from typing import Any

from src.photo_optimize.managed_import import (
    EXISTING,
    IMPORT_COPY,
    OPEN_EXISTING,
    ManagedImportPlan,
    apply_managed_import,
    plan_managed_import,
)

#: ``confirm(plan) -> duplicates policy`` ("open_existing" / "import_copy") or ``None`` when the operator cancels.
ImportConfirm = Callable[[ManagedImportPlan], str | None]


def ask_import_confirmation(plan: ManagedImportPlan, *, parent: Any = None) -> str | None:
    """Default confirmation: show the plan; duplicates get an explicit open-existing vs. copy-again choice."""

    title = "Manage selected photos"
    body = plan.describe()
    has_duplicates = any(row.status == EXISTING for row in plan.rows)
    if has_duplicates:
        answer = messagebox.askyesnocancel(
            title,
            f"{body}\n\nYes: import the new images and open the already-managed ones.\n"
            "No: also import the already-managed ones as new, separate copies.\nCancel: do nothing.",
            parent=parent,
        )
        if answer is None:
            return None
        return OPEN_EXISTING if answer else IMPORT_COPY
    confirmed = messagebox.askokcancel(
        title, f"{body}\n\nCopy the new image(s) into the managed workspace?", parent=parent
    )
    return OPEN_EXISTING if confirmed else None


class PhotoOptimizeHandoffMixin:
    """Composed into ``PhotoOptimizeTabFrameV2``; relies on its ``_work`` runner, ``store`` and selection helpers."""

    _confirm_import_hook: ImportConfirm | None = None

    # -- Quick Edit -> Managed Photo Set -----------------------------------------------------------------------

    def receive_review_handoff(
        self,
        image_paths: Sequence[str],
        *,
        status_message: str | None = None,
    ) -> None:
        if not self._workspace_ready():  # type: ignore[attr-defined]
            return
        paths = [str(path) for path in image_paths if str(path).strip()]
        if not paths:
            return
        store = self.store  # type: ignore[attr-defined]
        self.submission_summary_var.set(  # type: ignore[attr-defined]
            status_message or f"Checking {len(paths)} image(s) from Quick Edit..."
        )
        self._work.submit(  # type: ignore[attr-defined]
            "photo:managed-import-plan",
            lambda: plan_managed_import(store, paths),
            on_result=self._offer_managed_import,
            on_error=lambda exc: self.submission_summary_var.set(  # type: ignore[attr-defined]
                f"Could not check the selected images: {type(exc).__name__}"
            ),
            name="photo-managed-import-plan",
            purpose="Hash and check Review-selected images against the managed workspace without blocking Tk",
        )

    def _offer_managed_import(self, plan: ManagedImportPlan) -> None:
        if not plan.importable:
            self.submission_summary_var.set("Nothing to import.\n" + plan.describe())  # type: ignore[attr-defined]
            messagebox.showinfo("Manage selected photos", plan.describe())
            return
        confirm = self._confirm_import_hook or (
            lambda value: ask_import_confirmation(value, parent=self)
        )
        duplicates = confirm(plan)
        if duplicates is None:
            self.submission_summary_var.set("Import cancelled; nothing was copied or queued.")  # type: ignore[attr-defined]
            return
        store = self.store  # type: ignore[attr-defined]
        defaults = self._build_import_defaults()  # type: ignore[attr-defined]
        self._work.submit(  # type: ignore[attr-defined]
            "photo:managed-import-apply",
            lambda: apply_managed_import(
                store, plan, baseline_defaults=defaults, duplicates=duplicates
            ),
            on_result=self._managed_import_done,
            on_error=lambda exc: messagebox.showerror(
                "Import failed", f"{type(exc).__name__}: {exc}"
            ),
            name="photo-managed-import-apply",
            purpose="Copy operator-confirmed images into the managed workspace without blocking Tk",
        )

    def _managed_import_done(self, result: Any) -> None:
        ids = result.asset_ids()
        self.submission_summary_var.set(result.describe())  # type: ignore[attr-defined]
        if ids:
            # The list restore path selects every id (not only the first) once the refreshed list is published.
            self._select_assets_after_refresh(list(ids))  # type: ignore[attr-defined]
        self._refresh_assets(select_asset_id=ids[0] if ids else None)  # type: ignore[attr-defined]
        if result.failed or result.warnings:
            messagebox.showwarning("Manage selected photos", result.describe())

    # -- Managed Photo Set -> Quick Edit -----------------------------------------------------------------------

    def _open_selected_in_quick_edit(self) -> None:
        if not self._workspace_ready():  # type: ignore[attr-defined]
            return
        ids = self._selected_asset_ids(batch_all=False)  # type: ignore[attr-defined]
        if not ids:
            messagebox.showwarning("No photos", "Select one or more photos to open in Quick Edit.")
            return
        store = self.store  # type: ignore[attr-defined]

        def resolve() -> list[str]:
            found = (store.get_asset(identity) for identity in ids)
            return [str(asset.current_input_path) for asset in found if asset is not None]

        self._work.submit(  # type: ignore[attr-defined]
            "photo:open-in-quick-edit",
            resolve,
            on_result=self._route_to_quick_edit,
            on_error=lambda exc: self.submission_summary_var.set(  # type: ignore[attr-defined]
                f"Could not read the selected photos: {type(exc).__name__}"
            ),
            name="photo-open-in-quick-edit",
            purpose="Resolve the selected photos' working images for Quick Edit without blocking Tk",
        )

    def _route_to_quick_edit(self, paths: list[str]) -> None:
        if not paths:
            self.submission_summary_var.set("The selected photos are no longer available.")  # type: ignore[attr-defined]
            return
        main_window = getattr(self.app_controller, "main_window", None)  # type: ignore[attr-defined]
        if main_window is None:
            messagebox.showerror("Quick Edit unavailable", "The main window is not connected.")
            return
        from src.gui.controllers.video_workspace_handoff import route_images_to_review

        try:
            routed = route_images_to_review(
                main_window=main_window,
                image_paths=paths,
                status_message=f"Opened {len(paths)} managed photo(s) from the Managed Photo Set.",
            )
        except (RuntimeError, ValueError) as exc:
            messagebox.showerror("Quick Edit unavailable", str(exc))
            return
        if not routed:
            self.submission_summary_var.set("Quick Edit kept its current work; nothing was opened.")  # type: ignore[attr-defined]


__all__ = ["ImportConfirm", "PhotoOptimizeHandoffMixin", "ask_import_confirmation"]
