"""Result browser and read-only thumbnail worker; the existing store owns promotion/revert."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from tkinter import messagebox

from PIL import Image

from src.photo_optimize.results import _recorded_baseline, list_candidates, validate_candidate

from .photo_optimize_editors import review_dialog


def _subject(asset, candidate):
    evidence = [asset.baseline.to_dict()]
    if asset.original_baseline is not None:
        evidence.append(asset.original_baseline.to_dict())
    if candidate.kind == "history":
        evidence.append(asset.history[candidate.history_index].to_dict())
    elif candidate.kind == "working" and candidate.path != asset.managed_original_path:
        # Conservative for migrated paths whose recorded identity may retain its legacy spelling.
        evidence.extend(entry.to_dict() for entry in asset.history)
    return {
        "name": f"{asset.source_filename} {Path(candidate.path).name}",
        "description": str(evidence),
    }


def _thumbnail(store, asset, candidate):
    path, _checksum, warning = validate_candidate(store, asset, candidate)
    with Image.open(path) as image:
        image.thumbnail((220, 220))
        return image.copy(), warning


class PhotoOptimizeResultsMixin:
    def _populate_history(self, asset):
        self.history_list.delete(0, "end")
        self._result_candidates = list_candidates(asset)
        for candidate in self._result_candidates:
            label = candidate.label()
            if candidate.kind == "history" and candidate.history_index == len(asset.history) - 1:
                label += " [Latest run; no quality ranking]"
            label = self._visibility_resolver().redact_text(label, item=_subject(asset, candidate))
            self.history_list.insert("end", label)
        self.history_list.selection_set(1)  # current working baseline, not an assumed best output

    def _selected_result(self):
        selected = self.history_list.curselection()
        if selected and int(selected[0]) < len(self._result_candidates):
            return self._result_candidates[int(selected[0])]
        return None

    def _on_history_select(self, _event=None):
        if self._current_asset is not None:
            self._refresh_preview(self._current_asset)

    def _clear_result_preview(self):
        self._result_preview_token += 1
        if self._result_preview_future is not None:
            self._result_preview_future.cancel()
        if self._result_preview_poll_id is not None:
            self.after_cancel(self._result_preview_poll_id)
            self._result_preview_poll_id = None
        self.original_preview.clear()
        self.latest_preview.clear()

    def _dispose_result_preview(self):
        self._clear_result_preview()
        if self._result_preview_executor is not None:
            self._result_preview_executor.shutdown(wait=False, cancel_futures=True)

    def _refresh_preview(self, asset):
        self._clear_result_preview()
        selected = self._selected_result()
        show = self.show_image_previews_var.get()
        self.image_previews_frame.grid() if show else self.image_previews_frame.grid_remove()
        working_name = Path(asset.current_input_path).name
        metadata = (
            f"Asset: {asset.source_filename}\nWorking baseline: {working_name}\n"
            f"Model: {asset.baseline.model or '(pipeline fallback)'} | VAE: {asset.baseline.vae or 'Automatic'}\n"
            f"Editing this photo only | {len(self._selected_asset_ids(batch_all=False))} selected\n"
            f"Geometry: {asset.baseline.geometry_policy} | {self.img2img_width_var.get()} x {self.img2img_height_var.get()}\n"
            f"History entries: {len(asset.history)} | Latest run: {asset.history[-1].run_id if asset.history else 'none'}"
        )
        self.meta_label.configure(
            text=self._visibility_resolver().redact_text(
                metadata, item=self._current_visibility_subject()
            )
        )
        if selected is None:
            self.result_status_var.set(
                "Choose an original, working baseline or recorded output to preview."
            )
            return
        subject = _subject(asset, selected)
        label = self._visibility_resolver().redact_text(selected.label(), item=subject)
        status = f"Selected candidate: {label}. Preview only; working baseline unchanged."
        try:
            _baseline, note = _recorded_baseline(asset, selected)
        except ValueError as exc:
            note = str(exc)
        self.result_status_var.set(status + " " + note)
        if not show:
            return
        resolver = self._visibility_resolver()
        original = self._result_candidates[0]
        allow_original = resolver.is_visible(_subject(asset, original))
        allow_selected = resolver.is_visible(subject)
        if not allow_selected:
            self.result_status_var.set(status + " Hidden by content visibility. " + note)
        snapshot = deepcopy(asset)
        token = self._result_preview_token

        def load():
            pictures, errors = [], []
            for candidate, allowed in ((original, allow_original), (selected, allow_selected)):
                try:
                    image, warning = (
                        _thumbnail(self.store, snapshot, candidate) if allowed else (None, "")
                    )
                    pictures.append(image)
                    errors.append(warning)
                except (ValueError, OSError, KeyError, TypeError) as exc:
                    pictures.append(None)
                    errors.append(f"Ineligible: {exc}")
            return pictures, errors

        if self._result_preview_executor is None:
            self._result_preview_executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="photo-result-preview"
            )
        future = self._result_preview_future = self._result_preview_executor.submit(load)

        def poll():
            self._result_preview_poll_id = None
            if token != self._result_preview_token:
                return
            if not future.done():
                self._result_preview_poll_id = self.after(30, poll)
                return
            pictures, warnings = future.result()
            if pictures[0] is not None:
                self.original_preview.set_image(pictures[0])
            if pictures[1] is not None:
                self.latest_preview.set_image(pictures[1])
            if warnings[1]:
                self.result_status_var.set(status + " " + warnings[1] + " " + note)

        self._result_preview_poll_id = self.after(30, poll)

    def _promote_selected_result(self):
        candidate = self._selected_result()
        if candidate is None or self._current_asset_id is None:
            messagebox.showwarning(
                "No candidate", "Select a recorded result or the original first."
            )
            return
        self._with_saved_baseline(
            lambda: self._promote_saved_result(candidate), action="Promoting a result"
        )

    def _promote_saved_result(self, candidate):
        asset_id, mode = self._current_asset_id, self.promotion_mode_var.get()

        def prepared(plan):
            if self._current_asset_id != asset_id:
                return
            text = plan.describe()
            subject = {"description": text}
            text = self._visibility_resolver().redact_text(text, item=subject)
            if review_dialog(
                self, "Use selected result as working baseline", text, accept="Use selected result"
            ):
                self.after_idle(
                    lambda: self._run_photo_operation(
                        lambda: self.store.apply_result_promotion(plan), self._promotion_completed
                    )
                )

        self._run_photo_operation(
            lambda: self.store.prepare_result_promotion(asset_id, candidate, mode=mode), prepared
        )

    def _promotion_completed(self, asset):
        if self._current_asset_id == asset.asset_id:
            self._show_asset(asset.asset_id)
        messagebox.showinfo(
            "Working baseline",
            f"Working baseline ready for {asset.asset_id}. Historical artifacts were preserved.",
        )

    def _revert_baseline(self):
        if self._current_asset_id is not None:
            self._with_saved_baseline(
                self._revert_saved_baseline, action="Restoring the previous baseline"
            )

    def _revert_saved_baseline(self):
        asset_id = self._current_asset_id
        if asset_id is not None:
            self._run_photo_operation(
                lambda: self.store.revert_baseline(asset_id), self._promotion_completed
            )
