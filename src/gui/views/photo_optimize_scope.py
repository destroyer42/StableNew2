"""Photo editing/review orchestration in the existing view and worker seams."""

from __future__ import annotations

from copy import deepcopy
from tkinter import messagebox

from src.photo_optimize.editing import apply_edit, prepare_edit, selection_values
from src.photo_optimize.submission import describe_photo_plan

from .photo_optimize_editors import pipeline_copy_dialog, review_dialog


class PhotoOptimizeScopeMixin:
    def _edit_target_ids(self):
        scope = self.__dict__.get("edit_scope_var")
        if scope is not None and scope.get() == "Single Photo":
            return [self._current_asset_id] if self._current_asset_id else []
        return self._selected_asset_ids(batch_all=False)

    def _refresh_scope_selection(self):
        editor = self.__dict__.get("batch_editor")
        work = self.__dict__.get("_work")
        if editor is not None and self.store is not None and work is not None:
            ids = self._selected_asset_ids(batch_all=False)
            store = self.store

            def load():
                found = (store.get_asset(identity) for identity in ids)
                return [asset for asset in found if asset is not None]

            work.submit(
                "photo:scope-selection",
                load,
                on_result=lambda assets: editor.project_selection(
                    selection_values(assets), len(assets)
                ),
                name="photo-scope-selection",
                purpose="Read the selected photos' drafts for the Batch Edit summary without blocking Tk",
            )
        update_summary = getattr(self, "_update_selection_summary", None)
        if callable(update_summary):
            update_summary()

    def _on_workspace_changed(self, _event=None):
        self.edit_scope_var.set(self.edit_workspaces.tab(self.edit_workspaces.select(), "text"))
        self._refresh_scope_selection()

    def _review_edit(self, ids, mask, source):
        self._with_saved_baseline(
            lambda: self._review_saved_edit(ids, mask, source), action="Applying a batch edit"
        )

    def _review_saved_edit(self, ids, mask, source):
        def prepared(plan):
            def render(asset, value):
                subject = {
                    "positive_prompt": asset.baseline.prompt,
                    "negative_prompt": asset.baseline.negative_prompt,
                    "name": asset.source_filename,
                }
                subject["description"] = repr(value)
                return self._visibility_resolver().redact_text(repr(value), item=subject)

            if review_dialog(self, source, plan.describe(render), accept="Apply listed changes"):
                self.after_idle(
                    lambda: self._run_photo_operation(
                        lambda: apply_edit(self.store, plan), self._edit_completed
                    )
                )

        self._run_photo_operation(
            lambda: prepare_edit(self.store, ids, mask, source=source), prepared
        )

    def _edit_completed(self, result):
        self._refresh_assets()
        messagebox.showinfo("Photo edit results", result.describe())

    def _review_batch_edit(self):
        try:
            self._review_edit(
                self._selected_asset_ids(batch_all=False),
                self.batch_editor.collect_mask(),
                "Batch Edit saved baselines",
            )
        except (ValueError, OSError) as exc:
            messagebox.showerror("Cannot prepare batch edit", str(exc))

    def _use_current_pipeline_settings(self):
        ids = self._edit_target_ids()
        if not ids:
            messagebox.showwarning(
                "No assets", "Choose a photo in Single Photo or a selection in Batch Edit."
            )
            return
        try:
            source = getattr(self.app_controller, "build_photo_optimize_defaults", None)
            if not callable(source):
                raise ValueError("Pipeline settings source is unavailable; open Pipeline and retry")
            snapshot = deepcopy(source())
            if not isinstance(snapshot.get("config"), dict) or not snapshot["config"]:
                raise ValueError("Live Pipeline settings are unavailable; open Pipeline and retry")
            scope = self.__dict__.get("edit_scope_var")
            name = scope.get() if scope is not None else "selected photos"
            pipeline_copy_dialog(
                self,
                snapshot,
                f"{name}: {len(ids)} photo(s)",
                lambda mask: self._review_edit(ids, mask, "Live Pipeline copy"),
            )
        except (AttributeError, ValueError, RuntimeError) as exc:
            messagebox.showerror("Pipeline copy failed", str(exc))

    def _toggle_image_previews(self):
        if self._current_asset is not None:
            self._refresh_preview(self._current_asset)

    def _optimize(self, *, batch_all):
        if not self._workspace_ready():
            return
        self._with_saved_baseline(
            lambda: self._optimize_saved(batch_all=batch_all), action="Preparing a plan"
        )

    def _optimize_saved(self, *, batch_all):
        ids = self._selected_asset_ids(batch_all=batch_all)
        controller = self.app_controller
        store = self.store
        try:
            # Everything the Tk thread owns is captured now; the sidecars are read on the worker.
            captured = {
                "stages": self._selected_stages(),
                "prompt_delta": self._get_text(self.prompt_delta_text),
                "negative_prompt_delta": self._get_text(self.negative_delta_text),
                "prompt_mode": self.prompt_mode_var.get(),
                "negative_prompt_mode": self.negative_mode_var.get(),
                "batch_size": int(self.batch_size_var.get()),
                "pipeline_defaults_snapshot": controller.build_photo_optimize_defaults(),
            }
        except (AttributeError, ValueError, RuntimeError) as exc:
            messagebox.showerror("Optimize failed", str(exc))
            return

        def prepare():
            assets = [store.get_asset(i) for i in ids]
            if batch_all:
                assets = [a for a in assets if a is not None and not a.archived]
            if not assets or any(a is None for a in assets):
                return None
            arguments = {
                "assets": [
                    {
                        "asset_id": a.asset_id,
                        "managed_original_path": a.managed_original_path,
                        "input_image_path": str(a.current_input_path),
                        "baseline": a.baseline.to_dict(),
                        "archived": a.archived,
                    }
                    for a in assets
                ],
                **captured,
            }
            return len(assets), controller.prepare_photo_optimize_plan(**arguments)

        def prepared(result):
            if result is None:
                messagebox.showwarning("No assets", "Select available photos first.")
                return
            count, plan = result
            # Render every frozen per-photo setting; the confirmed plan is submitted without recompilation.
            lines = [describe_photo_plan(plan), "\nFrozen per-photo effective targets:"]
            for job in plan.jobs:
                for row in job.extra_metadata["photo_optimize"]["assets"]:
                    subject = {
                        "positive_prompt": row["effective_prompt"],
                        "negative_prompt": row["effective_negative_prompt"],
                    }
                    subject["description"] = str(row)
                    safe = self._visibility_resolver().redact_text(str(row), item=subject)
                    lines.append(safe)
            if review_dialog(
                self,
                "Review Photo Optimize → Queue",
                "\n".join(lines),
                accept="Queue these exact jobs",
            ):
                self.after_idle(
                    lambda: self._run_photo_operation(
                        lambda: controller.submit_prepared_photo_plan(plan),
                        lambda submitted: messagebox.showinfo(
                            "Submitted", f"Queued {submitted} job(s) for {count} photos."
                        ),
                    )
                )

        self._run_photo_operation(prepare, prepared)
