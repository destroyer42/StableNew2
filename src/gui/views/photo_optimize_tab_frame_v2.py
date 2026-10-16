from __future__ import annotations

import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from tkinter import filedialog, messagebox, ttk
from typing import Any

from src.controller.content_visibility_resolver import ContentVisibilityResolver
from src.gui.controllers.review_workflow_adapter import ReviewWorkflowAdapter
from src.photo_optimize import PhotoOptimizeAsset, PhotoOptimizeBaseline, get_photo_optimize_store
from src.photo_optimize.settings import (
    normalize_settings,
    resolve_geometry,
    validate_settings,
)

from .photo_optimize_layout import PhotoOptimizeLayoutMixin
from .photo_optimize_results import PhotoOptimizeResultsMixin
from .photo_optimize_scope import PhotoOptimizeScopeMixin


class PhotoOptimizeTabFrameV2(PhotoOptimizeResultsMixin, PhotoOptimizeScopeMixin, PhotoOptimizeLayoutMixin, ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        app_controller: Any = None,
        app_state: Any = None,
        store: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self.app_controller = app_controller
        self.app_state = None
        manager = getattr(app_controller, "_config_manager", None)
        loader = getattr(manager, "load_settings", None)
        settings = loader() if callable(loader) else {}
        output_root = settings.get("output_dir") if isinstance(settings, dict) else None
        self.store = store
        self._workspace_executor = None
        self._workspace_future = None
        self._workspace_poll_id = None
        self._operation_executor = None
        self._operation_future = None
        self._operation_poll_id = None
        self._workflow_adapter = ReviewWorkflowAdapter()
        self._asset_index_by_row: list[str] = []
        self._current_asset_id: str | None = None
        self._current_asset: PhotoOptimizeAsset | None = None
        self._restored_asset_id: str | None = None
        self._restored_asset_ids: list[str] | None = None
        self._result_candidates = []
        self._result_preview_executor = None
        self._result_preview_future = None
        self._result_preview_poll_id = None
        self._result_preview_token = 0
        self._suspend_asset_persist = False
        self._app_state_resource_listener: Any = None
        self._app_state_visibility_listener: Any = None
        self._model_name_map: dict[str, str] = {}
        self._vae_name_map: dict[str, str] = {"Automatic": ""}
        self._content_visibility_mode = "nsfw"
        self._pending_asset_refresh_target: str | None = None
        self._pending_resources_payload: dict[str, list[Any]] | None = None
        self._pending_visibility_refresh = False

        self.prompt_mode_var = tk.StringVar(value="append")
        self.negative_mode_var = tk.StringVar(value="append")
        self._prompt_prev_mode = "append"
        self._negative_prev_mode = "append"
        self._prompt_mode_edits: dict[str, str] = {"append": "", "replace": "", "modify": ""}
        self._negative_mode_edits: dict[str, str] = {"append": "", "replace": "", "modify": ""}

        self.model_var = tk.StringVar()
        self.vae_var = tk.StringVar()
        self.tags_var = tk.StringVar()
        self.stage_img2img_var = tk.BooleanVar(value=True)
        self.stage_adetailer_var = tk.BooleanVar(value=False)
        self.stage_upscale_var = tk.BooleanVar(value=False)
        self.batch_size_var = tk.IntVar(value=1)
        self.img2img_sampler_var = tk.StringVar()
        self.img2img_scheduler_var = tk.StringVar(value="normal")
        self.show_image_previews_var = tk.BooleanVar(value=True)
        self.result_status_var = tk.StringVar()
        self.promotion_mode_var = tk.StringVar(value="image_only")
        self.edit_scope_var = tk.StringVar(value="Single Photo")
        self.img2img_steps_var = tk.IntVar(value=20)
        self.img2img_cfg_var = tk.DoubleVar(value=7.0)
        self.img2img_denoise_var = tk.DoubleVar(value=0.3)
        self.img2img_width_var = tk.IntVar(value=0)
        self.img2img_height_var = tk.IntVar(value=0)
        self.geometry_mode_var = tk.StringVar(value="auto")
        self.show_archived_var = tk.BooleanVar(value=False)
        self.settings_error_var = tk.StringVar()
        self.submission_summary_var = tk.StringVar(value="Select photos; each retains its own target settings.")
        self.migration_status_var = tk.StringVar(value="")
        self.adetailer_model_var = tk.StringVar()
        self.adetailer_confidence_var = tk.DoubleVar(value=0.35)
        self.adetailer_steps_var = tk.IntVar(value=28)
        self.adetailer_cfg_var = tk.DoubleVar(value=7.0)
        self.adetailer_denoise_var = tk.DoubleVar(value=0.4)
        self.adetailer_sampler_var = tk.StringVar()
        self.adetailer_scheduler_var = tk.StringVar(value="Use sampler default")
        self.upscale_upscaler_var = tk.StringVar()
        self.upscale_factor_var = tk.DoubleVar(value=2.0)
        self.upscale_steps_var = tk.IntVar(value=20)
        self.upscale_denoise_var = tk.DoubleVar(value=0.35)
        self.upscale_sampler_var = tk.StringVar(value="Euler a")
        self.upscale_scheduler_var = tk.StringVar(value="normal")
        self.upscale_tile_size_var = tk.IntVar(value=0)
        self.upscale_face_restore_var = tk.BooleanVar(value=False)
        self.upscale_face_restore_method_var = tk.StringVar(value="CodeFormer")

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_header()
        self._build_body()
        self.bind("<Map>", self._on_map, add="+")

        self.prompt_mode_var.trace_add("write", lambda *_: self._on_prompt_mode_changed())
        self.negative_mode_var.trace_add("write", lambda *_: self._on_negative_mode_changed())
        for variable in (
            self.model_var,
            self.vae_var,
            self.tags_var,
            self.stage_img2img_var,
            self.stage_adetailer_var,
            self.stage_upscale_var,
            self.img2img_sampler_var,
            self.img2img_scheduler_var,
            self.img2img_steps_var,
            self.img2img_cfg_var,
            self.img2img_denoise_var,
            self.img2img_width_var,
            self.img2img_height_var,
            self.geometry_mode_var,
            self.adetailer_model_var,
            self.adetailer_confidence_var,
            self.adetailer_steps_var,
            self.adetailer_cfg_var,
            self.adetailer_denoise_var,
            self.adetailer_sampler_var,
            self.adetailer_scheduler_var,
            self.upscale_upscaler_var,
            self.upscale_factor_var,
            self.upscale_steps_var,
            self.upscale_denoise_var,
            self.upscale_sampler_var,
            self.upscale_scheduler_var,
            self.upscale_tile_size_var,
            self.upscale_face_restore_var,
            self.upscale_face_restore_method_var,
        ):
            variable.trace_add("write", lambda *_: self._persist_current_asset_baseline())

        self.baseline_prompt_text.bind(
            "<KeyRelease>", lambda _e: self._persist_current_asset_baseline()
        )
        self.baseline_prompt_text.bind(
            "<FocusOut>", lambda _e: self._persist_current_asset_baseline()
        )
        self.baseline_negative_text.bind(
            "<KeyRelease>", lambda _e: self._persist_current_asset_baseline()
        )
        self.baseline_negative_text.bind(
            "<FocusOut>", lambda _e: self._persist_current_asset_baseline()
        )
        self.notes_text.bind("<KeyRelease>", lambda _e: self._persist_current_asset_baseline())
        self.notes_text.bind("<FocusOut>", lambda _e: self._persist_current_asset_baseline())
        self.prompt_delta_text.bind("<KeyRelease>", lambda _e: self._refresh_prompt_diff())
        self.negative_delta_text.bind("<KeyRelease>", lambda _e: self._refresh_prompt_diff())

        self.bind_app_state(app_state)
        self._apply_content_visibility_mode()
        self._refresh_assets()
        self._render_migration_report()
        if self.store is None:
            self.submission_summary_var.set("Loading and verifying Photo Optimize workspace…")
            self._workspace_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="photo-workspace")
            self._workspace_future = self._workspace_executor.submit(get_photo_optimize_store, output_root=output_root)
            self._workspace_poll_id = self.after(50, self._poll_workspace)

    def _poll_workspace(self) -> None:
        self._workspace_poll_id = None
        if not self._workspace_future.done():
            self._workspace_poll_id = self.after(50, self._poll_workspace)
            return
        try:
            self.store = self._workspace_future.result()
            self.submission_summary_var.set("Workspace ready. Select photos; each retains its own target settings.")
            self._render_migration_report()
            self._refresh_assets(select_asset_id=self._restored_asset_id)
        except Exception as exc:
            self.submission_summary_var.set(f"Workspace unavailable: {exc}")
            messagebox.showerror("Photo workspace unavailable", str(exc))
        finally:
            self._workspace_executor.shutdown(wait=False)

    def _workspace_ready(self) -> bool:
        if self.store is not None:
            return True
        messagebox.showwarning("Workspace unavailable", self.submission_summary_var.get())
        return False

    def _render_migration_report(self) -> None:
        variable = self.__dict__.get("migration_status_var")
        if variable is not None and self.store is not None:
            variable.set(self.store.migration_report.summary())

    def _show_migration_details(self) -> None:
        if self._workspace_ready():
            messagebox.showinfo("Legacy photo migration", self.store.migration_report.details())

    def _retry_legacy_migration(self) -> None:
        if not self._workspace_ready():
            return

        def completed(_report):
            self._render_migration_report()
            self._refresh_assets()

        self._run_photo_operation(self.store.retry_migration, completed)

    def _run_photo_operation(self, operation, completed) -> None:
        if self._operation_future is not None:
            messagebox.showwarning("Photo operation pending", "Wait for the current photo operation to finish.")
            return
        self._operation_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="photo-intent")
        self._operation_future = self._operation_executor.submit(operation)
        future = self._operation_future
        executor = self._operation_executor
        def poll():
            self._operation_poll_id = None
            if not future.done():
                self._operation_poll_id = self.after(50, poll)
                return
            try:
                completed(future.result())
            except Exception as exc:
                messagebox.showerror("Photo operation failed", str(exc))
            finally:
                executor.shutdown(wait=False)
                self._operation_future = None
        self._operation_poll_id = self.after(50, poll)



    def _on_import_photos(self) -> None:
        if not self._workspace_ready():
            return
        files = filedialog.askopenfilenames(
            title="Import photos for Photo Optomize",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.webp"),
                ("All files", "*.*"),
            ],
        )
        if not files:
            return
        defaults = self._build_import_defaults()
        def import_files():
            imported_ids, errors = [], []
            for file_path in files:
                try:
                    asset = self.store.import_photo(file_path, baseline_defaults=defaults)
                    imported_ids.append(asset.asset_id)
                except (OSError, ValueError) as exc:
                    errors.append(str(exc))
            return imported_ids, errors
        def imported(result):
            ids, errors = result
            self._refresh_assets(select_asset_id=ids[0] if ids else None)
            if errors:
                messagebox.showerror("Import failed", "\n".join(errors))
        self._run_photo_operation(import_files, imported)

    def _build_import_defaults(self) -> dict[str, Any]:
        controller = self.app_controller
        builder = getattr(controller, "build_photo_optimize_defaults", None)
        if callable(builder):
            try:
                defaults = builder()
                if isinstance(defaults, dict):
                    return defaults
            except Exception:
                pass
        return {
            "prompt": "",
            "negative_prompt": "",
            "model": "",
            "vae": "",
            "stage_defaults": {"img2img": True, "adetailer": False, "upscale": False},
            "config": {},
            "source": "manual",
        }


    def _refresh_assets(self, select_asset_id: str | None = None) -> None:
        if self.store is None:
            return
        had_assets = bool(self._asset_index_by_row)
        selected = self._selected_asset_ids(batch_all=False)
        assets = self.store.list_assets(include_archived=self.show_archived_var.get())
        self.assets_list.delete(0, tk.END)
        self._asset_index_by_row = []
        for asset in assets:
            label = asset.source_filename
            if asset.archived:
                label = f"[Archived] {label}"
            if asset.history:
                label = f"{label} ({len(asset.history)})"
            self.assets_list.insert(tk.END, label)
            self._asset_index_by_row.append(asset.asset_id)
        self.selection_label.config(text=f"{len(assets)} asset(s)")
        self.active_photo_combo.configure(values=[
            f"{asset.source_filename} [{asset.asset_id}]" for asset in assets
        ])

        target_asset_id = select_asset_id or self._restored_asset_id or self._current_asset_id
        if self._restored_asset_ids is not None:
            restored = [asset_id for asset_id in self._restored_asset_ids
                        if asset_id in self._asset_index_by_row]
            self._restored_asset_ids = None
            for asset_id in restored:
                self.assets_list.selection_set(self._asset_index_by_row.index(asset_id))
            if target_asset_id in self._asset_index_by_row:
                self._show_asset(target_asset_id)
            elif restored:
                self._show_asset(restored[0])
            else:
                self._clear_selection()
            self._restored_asset_id = None
            return
        retained = [asset_id for asset_id in selected if asset_id in self._asset_index_by_row]
        if retained and select_asset_id is None:
            for asset_id in retained:
                self.assets_list.selection_set(self._asset_index_by_row.index(asset_id))
            self._show_asset(target_asset_id if target_asset_id in self._asset_index_by_row else retained[0])
            return
        if had_assets and not retained and select_asset_id is None:
            if target_asset_id in self._asset_index_by_row:
                self._show_asset(target_asset_id)
            else:
                self._clear_selection()
            return
        if target_asset_id and target_asset_id in self._asset_index_by_row:
            index = self._asset_index_by_row.index(target_asset_id)
            self.assets_list.selection_clear(0, tk.END)
            self.assets_list.selection_set(index)
            self.assets_list.activate(index)
            self._show_asset(target_asset_id)
            self._restored_asset_id = None
            return
        if self._asset_index_by_row:
            self.assets_list.selection_clear(0, tk.END)
            self.assets_list.selection_set(0)
            self._show_asset(self._asset_index_by_row[0])
        else:
            self._clear_selection()

    def _archive_assets(self, *, clear_all: bool) -> None:
        if not self._workspace_ready():
            return
        ids = self._selected_asset_ids(batch_all=clear_all)
        try:
            self.store.archive_assets(ids)
            self._refresh_assets()
        except (OSError, ValueError) as exc:
            messagebox.showerror("Archive failed", str(exc))

    def _restore_assets(self) -> None:
        if not self._workspace_ready():
            return
        try:
            self.store.restore_assets(self._selected_asset_ids(batch_all=False))
            self._refresh_assets()
        except (OSError, ValueError) as exc:
            messagebox.showerror("Restore failed", str(exc))

    def _clear_selection(self) -> None:
        self._current_asset_id = None
        self._current_asset = None
        self.active_photo_combo.set("")
        self._refresh_scope_selection()
        self._clear_result_preview()
        self.meta_label.config(text="Metadata: n/a")
        self.history_list.delete(0, tk.END)
        self._result_candidates = []
        self._set_text(self.baseline_prompt_text, "")
        self._set_text(self.baseline_negative_text, "")
        self._set_text(self.notes_text, "")
        self.model_var.set("")
        self.vae_var.set("")
        self.tags_var.set("")
        self._load_baseline_config_form({})
        self._apply_content_visibility_mode()
        self._refresh_prompt_diff()

    def _on_asset_select(self, _event: tk.Event) -> None:
        idxs = list(self.assets_list.curselection())
        if not idxs:
            self._refresh_scope_selection()
            if self._current_asset is not None:
                self._refresh_preview(self._current_asset)
            return
        idx = int(idxs[0])
        if self._current_asset_id in self._asset_index_by_row:
            idx = self._asset_index_by_row.index(self._current_asset_id)
        if idx < 0 or idx >= len(self._asset_index_by_row):
            return
        self._show_asset(self._asset_index_by_row[idx])

    def _on_active_photo_choice(self, _event: tk.Event) -> None:
        index = self.active_photo_combo.current()
        if 0 <= index < len(self._asset_index_by_row):
            self._show_asset(self._asset_index_by_row[index])

    def _show_asset(self, asset_id: str) -> None:
        asset = self.store.get_asset(asset_id)
        if asset is None:
            return
        self._current_asset_id = asset.asset_id
        self._current_asset = asset
        if asset_id in self._asset_index_by_row:
            self.active_photo_combo.current(self._asset_index_by_row.index(asset_id))
        self._refresh_scope_selection()
        self._suspend_asset_persist = True
        try:
            self._refresh_resource_options()
            self._set_text(self.baseline_prompt_text, asset.baseline.prompt)
            self._set_text(self.baseline_negative_text, asset.baseline.negative_prompt)
            self._set_text(self.notes_text, asset.notes)
            self.model_var.set(
                self._display_for_internal(asset.baseline.model, self._model_name_map)
                or asset.baseline.model
            )
            self.vae_var.set(
                self._display_for_internal(asset.baseline.vae, self._vae_name_map)
                or ("Automatic" if not asset.baseline.vae else asset.baseline.vae)
            )
            self.tags_var.set(", ".join(asset.tags))
            self.geometry_mode_var.set(asset.baseline.geometry_policy)
            self._update_geometry_controls()
            self.stage_img2img_var.set(bool(asset.baseline.stage_defaults.get("img2img", True)))
            self.stage_adetailer_var.set(
                bool(asset.baseline.stage_defaults.get("adetailer", False))
            )
            self.stage_upscale_var.set(bool(asset.baseline.stage_defaults.get("upscale", False)))
            try:
                displayed_config = resolve_geometry(asset.baseline, asset.current_input_path)
                self.settings_error_var.set("")
            except ValueError as exc:
                displayed_config = asset.baseline.config
                self.settings_error_var.set(str(exc))
            self._load_baseline_config_form(displayed_config)
            self._apply_content_visibility_mode()
            self._populate_history(asset)
            self._refresh_preview(asset)
            self._refresh_prompt_diff()
        finally:
            self._suspend_asset_persist = False




    def _selected_asset_ids(self, *, batch_all: bool) -> list[str]:
        if batch_all:
            return list(self._asset_index_by_row)
        idxs = list(self.assets_list.curselection())
        asset_ids: list[str] = []
        for idx in idxs:
            if 0 <= int(idx) < len(self._asset_index_by_row):
                asset_ids.append(self._asset_index_by_row[int(idx)])
        return asset_ids

    def _selected_stages(self) -> list[str]:
        stages: list[str] = []
        if self.stage_img2img_var.get():
            stages.append("img2img")
        if self.stage_adetailer_var.get():
            stages.append("adetailer")
        if self.stage_upscale_var.get():
            stages.append("upscale")
        return stages



    def _show_interrogate_unavailable(self) -> None:
        messagebox.showinfo(
            "Interrogate unavailable",
            "Prompt interrogation is not wired in this MVP. Set the baseline prompt manually.",
        )



    def _show_batch_logic_help(self) -> None:
        messagebox.showinfo(
            "Batch Logic",
            "How Photo Optimize batching works:\n\n"
            "- The editor changes the active photo only; selection controls submission and Pipeline copy.\n"
            "- Each photo uses its own stages, Auto/Custom geometry, model, VAE and config.\n"
            "- Jobs group only identical full workloads, including prompts, stages and dimensions.\n"
            "- Batch is the maximum photos per compatible job; all jobs preflight together.\n"
            "- Compatible assets can share one queue job.\n"
            "- Incompatible assets are split into separate queue jobs automatically.\n"
            "- After completion, each asset still gets its own copied output and history entry.",
        )

    def _persist_current_asset_baseline(self) -> bool:
        if self._suspend_asset_persist or self._current_asset is None:
            return True
        asset = self.store.get_asset(self._current_asset.asset_id)
        if asset is None:
            return False
        baseline = PhotoOptimizeBaseline.from_dict(asset.baseline.to_dict())
        self._update_geometry_controls()
        baseline.prompt = self._get_text(self.baseline_prompt_text)
        baseline.negative_prompt = self._get_text(self.baseline_negative_text)
        baseline.model = self._internal_for_display(self.model_var.get(), self._model_name_map)
        baseline.vae = self._internal_for_display(self.vae_var.get(), self._vae_name_map)
        baseline.stage_defaults = {
            "img2img": bool(self.stage_img2img_var.get()),
            "adetailer": bool(self.stage_adetailer_var.get()),
            "upscale": bool(self.stage_upscale_var.get()),
        }
        try:
            baseline.geometry_policy = self.geometry_mode_var.get()
            baseline.config = self._merge_nested_dicts(
                baseline.config if isinstance(baseline.config, dict) else {},
                self._collect_baseline_config_from_form(),
            )
            baseline.config = resolve_geometry(baseline, asset.current_input_path)
            validate_settings(baseline.config)
        except (ValueError, TypeError, tk.TclError) as exc:
            self.settings_error_var.set(str(exc))
            return False
        if not baseline.working_image_path:
            baseline.working_image_path = asset.managed_original_path
        updated = self.store.update_asset_fields(
            asset.asset_id,
            notes=self._get_text(self.notes_text),
            tags=[item.strip() for item in self.tags_var.get().split(",") if item.strip()],
            baseline=baseline,
        )
        self._current_asset = updated
        if baseline.geometry_policy == "auto":
            suspended = self._suspend_asset_persist
            self._suspend_asset_persist = True
            try:
                self.img2img_width_var.set(baseline.config["img2img"]["width"])
                self.img2img_height_var.set(baseline.config["img2img"]["height"])
            finally:
                self._suspend_asset_persist = suspended
        self._apply_content_visibility_mode()
        self._refresh_prompt_diff()
        self._refresh_preview(updated)
        self.settings_error_var.set("")
        return True

    def _update_geometry_controls(self) -> None:
        mode = "normal" if self.geometry_mode_var.get() == "custom" else "disabled"
        self.geometry_width_entry.configure(state=mode)
        self.geometry_height_entry.configure(state=mode)

    def show_submission_summary(self, summary: str) -> None:
        lines = summary.splitlines()
        concise = "\n".join(lines[:5])
        if len(lines) > 5:
            concise += f"\n{len(lines) - 5} more job targets; see Operator Log for all settings."
        self.submission_summary_var.set(concise)

    def _interrogate_current_asset(self) -> None:
        if self._current_asset is None:
            messagebox.showwarning("No asset", "Select an asset first.")
            return
        controller = self.app_controller
        interrogate = getattr(controller, "interrogate_photo_path", None)
        if not callable(interrogate):
            messagebox.showerror("Controller missing", "Photo interrogation is not connected.")
            return
        try:
            caption = str(interrogate(str(self._current_asset.current_input_path)) or "").strip()
            if not caption:
                raise RuntimeError("Interrogate returned an empty caption")
            asset = self.store.get_asset(self._current_asset.asset_id)
            if asset is None:
                raise RuntimeError("Selected asset could not be reloaded")
            baseline = PhotoOptimizeBaseline.from_dict(asset.baseline.to_dict())
            baseline.prompt = caption
            baseline.source = "interrogated"
            self.store.update_asset_fields(
                asset.asset_id,
                notes=asset.notes,
                tags=list(asset.tags),
                baseline=baseline,
            )
            self._show_asset(asset.asset_id)
        except Exception as exc:
            messagebox.showerror("Interrogate failed", str(exc))

    def _sync_edit_box_to_mode(self, which: str) -> None:
        if which == "prompt":
            mode = self.prompt_mode_var.get() or "append"
            text = self._prompt_mode_edits.get(mode, "")
            self._set_text(self.prompt_delta_text, text)
        else:
            mode = self.negative_mode_var.get() or "append"
            text = self._negative_mode_edits.get(mode, "")
            self._set_text(self.negative_delta_text, text)
        self._refresh_prompt_diff()

    def _on_prompt_mode_changed(self) -> None:
        self._prompt_mode_edits[self._prompt_prev_mode] = self._get_text(self.prompt_delta_text)
        self._prompt_prev_mode = self.prompt_mode_var.get() or "append"
        self._sync_edit_box_to_mode("prompt")

    def _on_negative_mode_changed(self) -> None:
        self._negative_mode_edits[self._negative_prev_mode] = self._get_text(
            self.negative_delta_text
        )
        self._negative_prev_mode = self.negative_mode_var.get() or "append"
        self._sync_edit_box_to_mode("negative")

    def _refresh_prompt_diff(self) -> None:
        asset = self._current_asset
        base_prompt = asset.baseline.prompt if asset is not None else ""
        base_negative = asset.baseline.negative_prompt if asset is not None else ""
        diff = self._workflow_adapter.build_prompt_diff(
            base_prompt=base_prompt,
            base_negative_prompt=base_negative,
            prompt_delta=self._get_text(self.prompt_delta_text),
            negative_prompt_delta=self._get_text(self.negative_delta_text),
            prompt_mode=self.prompt_mode_var.get(),
            negative_prompt_mode=self.negative_mode_var.get(),
        )
        resolver = self._visibility_resolver()
        subject = self._current_visibility_subject()
        self.diff_before_label.config(text=resolver.redact_text(diff.before_text, item=subject))
        self.diff_after_label.config(text=resolver.redact_text(diff.after_text, item=subject))

    def _set_readonly_text(self, widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value or "")
        widget.configure(state="disabled")

    def _visibility_resolver(self) -> ContentVisibilityResolver:
        return ContentVisibilityResolver(self._content_visibility_mode)

    def _current_visibility_subject(self) -> dict[str, str]:
        asset = self._current_asset
        if asset is None:
            return {"positive_prompt": "", "negative_prompt": "", "name": ""}
        return {
            "positive_prompt": asset.baseline.prompt,
            "negative_prompt": asset.baseline.negative_prompt,
            "name": asset.source_filename,
        }

    def _apply_content_visibility_mode(self) -> None:
        resolver = self._visibility_resolver()
        subject = self._current_visibility_subject()
        prompt_value = resolver.redact_text(subject.get("positive_prompt", ""), item=subject)
        negative_value = resolver.redact_text(subject.get("negative_prompt", ""), item=subject)
        self._set_readonly_text(self.current_prompt_text, prompt_value)
        self._set_readonly_text(self.current_negative_text, negative_value)
        self.visibility_banner.config(text="")

    def on_content_visibility_mode_changed(self, mode: str | None = None) -> None:
        self._content_visibility_mode = str(
            mode
            or getattr(getattr(self, "app_state", None), "content_visibility_mode", "nsfw")
            or "nsfw"
        )
        self._pending_visibility_refresh = False
        self._apply_content_visibility_mode()
        self._refresh_prompt_diff()
        if self._current_asset is not None:
            self._refresh_preview(self._current_asset)

    def _on_content_visibility_mode_changed(self) -> None:
        mode = str(
            getattr(getattr(self, "app_state", None), "content_visibility_mode", "nsfw") or "nsfw"
        )
        self._content_visibility_mode = mode
        if not bool(self.winfo_ismapped()):
            self._pending_visibility_refresh = True
            return
        self.on_content_visibility_mode_changed(mode)

    def _set_text(self, widget: tk.Text, value: str) -> None:
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value or "")

    def _get_text(self, widget: tk.Text) -> str:
        return widget.get("1.0", tk.END).strip()

    def _load_baseline_config_form(self, config: dict[str, Any] | None) -> None:
        suspended = self._suspend_asset_persist
        self._suspend_asset_persist = True
        try:
            data = normalize_settings(config or {})
            fields = {
                "img2img": {"sampler": "sampler_name", "scheduler": "scheduler", "steps": "steps", "cfg": "cfg_scale",
                           "denoise": "denoising_strength", "width": "width", "height": "height"},
                "adetailer": {"model": "adetailer_model", "confidence": "adetailer_confidence",
                             "steps": "adetailer_steps", "cfg": "adetailer_cfg",
                             "denoise": "adetailer_denoise", "sampler": "adetailer_sampler",
                             "scheduler": "scheduler"},
                "upscale": {"upscaler": "upscaler", "factor": "upscaling_resize", "steps": "steps",
                           "denoise": "denoising_strength", "sampler": "sampler_name",
                           "scheduler": "scheduler", "tile_size": "tile_size",
                           "face_restore": "face_restore", "face_restore_method": "face_restore_method"},
            }
            for stage, mapping in fields.items():
                for name, key in mapping.items():
                    getattr(self, f"{stage}_{name}_var").set(data[stage][key])
        finally:
            self._suspend_asset_persist = suspended

    def _collect_baseline_config_from_form(self) -> dict[str, Any]:
        img2img_cfg: dict[str, Any] = {
            "sampler_name": self.img2img_sampler_var.get().strip(),
            "scheduler": self.img2img_scheduler_var.get().strip(),
            "steps": self._safe_int(self.img2img_steps_var.get(), 20),
            "cfg_scale": self._safe_float(self.img2img_cfg_var.get(), 7.0),
            "denoising_strength": self._safe_float(self.img2img_denoise_var.get(), 0.3),
        }
        width = self._safe_int(self.img2img_width_var.get(), 0)
        height = self._safe_int(self.img2img_height_var.get(), 0)
        img2img_cfg["width"] = width
        img2img_cfg["height"] = height

        adetailer_cfg: dict[str, Any] = {
            "adetailer_model": self.adetailer_model_var.get().strip(),
            "ad_model": self.adetailer_model_var.get().strip(),
            "adetailer_confidence": self._safe_float(self.adetailer_confidence_var.get(), 0.35),
            "ad_confidence": self._safe_float(self.adetailer_confidence_var.get(), 0.35),
            "adetailer_steps": self._safe_int(self.adetailer_steps_var.get(), 28),
            "ad_steps": self._safe_int(self.adetailer_steps_var.get(), 28),
            "adetailer_cfg": self._safe_float(self.adetailer_cfg_var.get(), 7.0),
            "ad_cfg_scale": self._safe_float(self.adetailer_cfg_var.get(), 7.0),
            "adetailer_denoise": self._safe_float(self.adetailer_denoise_var.get(), 0.4),
            "ad_denoising_strength": self._safe_float(self.adetailer_denoise_var.get(), 0.4),
            "adetailer_sampler": self.adetailer_sampler_var.get().strip(),
            "ad_sampler": self.adetailer_sampler_var.get().strip(),
            "scheduler": self.adetailer_scheduler_var.get().strip() or "Use sampler default",
            "ad_scheduler": self.adetailer_scheduler_var.get().strip() or "Use sampler default",
        }

        upscale_cfg: dict[str, Any] = {
            "upscaler": self.upscale_upscaler_var.get().strip(),
            "upscaling_resize": self._safe_float(self.upscale_factor_var.get(), 2.0),
            "upscale_factor": self._safe_float(self.upscale_factor_var.get(), 2.0),
            "steps": self._safe_int(self.upscale_steps_var.get(), 20),
            "denoising_strength": self._safe_float(self.upscale_denoise_var.get(), 0.35),
            "sampler_name": self.upscale_sampler_var.get().strip(),
            "scheduler": self.upscale_scheduler_var.get().strip() or "normal",
            "tile_size": self._safe_int(self.upscale_tile_size_var.get(), 0),
            "face_restore": bool(self.upscale_face_restore_var.get()),
            "face_restore_method": self.upscale_face_restore_method_var.get().strip()
            or "CodeFormer",
        }

        config: dict[str, Any] = {
            "img2img": img2img_cfg,
            "img2img_sampler_name": img2img_cfg["sampler_name"],
            "img2img_steps": img2img_cfg["steps"],
            "img2img_cfg_scale": img2img_cfg["cfg_scale"],
            "img2img_denoising_strength": img2img_cfg["denoising_strength"],
            "adetailer": adetailer_cfg,
            "adetailer_steps": adetailer_cfg["adetailer_steps"],
            "adetailer_cfg_scale": adetailer_cfg["adetailer_cfg"],
            "adetailer_sampler_name": adetailer_cfg["adetailer_sampler"],
            "adetailer_denoising_strength": adetailer_cfg["adetailer_denoise"],
            "upscale": upscale_cfg,
            "upscale_steps": upscale_cfg["steps"],
            "upscale_sampler_name": upscale_cfg["sampler_name"],
            "upscale_denoising_strength": upscale_cfg["denoising_strength"],
            "upscale_factor": upscale_cfg["upscale_factor"],
            "upscaler": upscale_cfg["upscaler"],
            "steps": img2img_cfg["steps"],
            "cfg_scale": img2img_cfg["cfg_scale"],
            "sampler_name": img2img_cfg["sampler_name"],
        }
        return config

    def _refresh_resource_options(self, resources: dict[str, list[Any]] | None = None) -> None:
        suspended = self._suspend_asset_persist
        self._suspend_asset_persist = True
        try:
            self._project_resource_options(resources)
        finally:
            self._suspend_asset_persist = suspended

    def _project_resource_options(self, resources: dict[str, list[Any]] | None = None) -> None:
        resource_map = resources
        if resource_map is None:
            resource_map = (
                getattr(self.app_state, "resources", {}) if self.app_state is not None else {}
            )
        model_values, model_map = self._normalize_dropdown_entries(
            self._resource_entries(resource_map, "models")
        )
        vae_values, vae_map = self._normalize_dropdown_entries(
            self._resource_entries(resource_map, "vaes"),
            include_automatic=True,
        )
        self._model_name_map = model_map
        self._vae_name_map = vae_map
        self._set_combobox_values(self.model_combo, self.model_var, model_values)
        self._set_combobox_values(self.vae_combo, self.vae_var, vae_values)

        samplers = self._resource_values("samplers")
        schedulers = self._resource_values("schedulers")
        upscalers = self._resource_values("upscalers", fallback=["Latent", "R-ESRGAN 4x+"])
        adetailer_models = self._resource_values(
            "adetailer_models",
            fallback=["face_yolov8n.pt", "hand_yolov8n.pt", "mediapipe_face_full"],
        )
        self._set_combobox_values(self.img2img_sampler_combo, self.img2img_sampler_var, samplers)
        self._set_combobox_values(self.img2img_scheduler_combo, self.img2img_scheduler_var, schedulers)
        editor = self.__dict__.get("batch_editor")
        if editor is not None:
            editor.resources({kind: [self._resource_internal_name(item) for item in
                                    self._resource_entries(resource_map, kind)]
                              for kind in ("models", "vaes", "samplers", "schedulers", "upscalers", "adetailer_models")})
        self._set_combobox_values(
            self.adetailer_sampler_combo, self.adetailer_sampler_var, samplers
        )
        self._set_combobox_values(self.upscale_sampler_combo, self.upscale_sampler_var, samplers)
        self._set_combobox_values(
            self.adetailer_scheduler_combo,
            self.adetailer_scheduler_var,
            ["Use sampler default"] + schedulers,
        )
        self._set_combobox_values(
            self.upscale_scheduler_combo, self.upscale_scheduler_var, schedulers
        )
        self._set_combobox_values(self.upscale_upscaler_combo, self.upscale_upscaler_var, upscalers)
        self._set_combobox_values(
            self.adetailer_model_combo, self.adetailer_model_var, adetailer_models
        )

    @staticmethod
    def _resource_entries(
        resources: dict[str, list[Any]] | None,
        key: str,
    ) -> list[Any]:
        if not isinstance(resources, dict):
            return []
        return list(resources.get(key) or [])

    def _resource_values(self, key: str, *, fallback: list[str] | None = None) -> list[str]:
        resources = getattr(self.app_state, "resources", {}) if self.app_state is not None else {}
        entries = resources.get(key) if isinstance(resources, dict) else []
        values: list[str] = []
        for entry in entries or []:
            value = self._resource_entry_name(entry)
            if value:
                values.append(value)
        for item in fallback or []:
            if item and item not in values:
                values.append(item)
        return values

    @staticmethod
    def _resource_entry_name(entry: Any) -> str:
        if isinstance(entry, str):
            return entry.strip()
        if isinstance(entry, dict):
            for key in ("title", "model_name", "name", "label"):
                value = entry.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return ""
        for attr in ("display_name", "name", "title", "model_name"):
            value = getattr(entry, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @classmethod
    def _normalize_dropdown_entries(
        cls,
        entries: list[Any],
        *,
        include_automatic: bool = False,
    ) -> tuple[list[str], dict[str, str]]:
        seen: set[str] = set()
        values: list[str] = []
        mapping: dict[str, str] = {}
        if include_automatic:
            values.append("Automatic")
            mapping["Automatic"] = ""
            seen.add("Automatic")
        for entry in entries:
            display = cls._resource_entry_name(entry)
            if not display or display in seen:
                continue
            internal = cls._resource_internal_name(entry) or display
            seen.add(display)
            values.append(display)
            mapping[display] = internal
        return values, mapping

    @staticmethod
    def _resource_internal_name(entry: Any) -> str:
        if isinstance(entry, str):
            return entry.strip()
        if isinstance(entry, dict):
            for key in ("name", "model_name", "title", "label"):
                value = entry.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return ""
        for attr in ("name", "model_name", "title", "display_name"):
            value = getattr(entry, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _display_for_internal(internal: str | None, mapping: dict[str, str]) -> str:
        target = str(internal or "").strip()
        if not target:
            return "Automatic" if mapping.get("Automatic", None) == "" else ""
        for display, name in mapping.items():
            if name == target:
                return display
        return target

    @staticmethod
    def _internal_for_display(display: str | None, mapping: dict[str, str]) -> str:
        text = str(display or "").strip()
        if not text:
            return ""
        return str(mapping.get(text, text)).strip()

    @staticmethod
    def _set_combobox_values(combo: ttk.Combobox, var: tk.StringVar, values: list[str]) -> None:
        current = (var.get() or "").strip()
        unique_values: list[str] = []
        for value in values:
            item = str(value or "").strip()
            if item and item not in unique_values:
                unique_values.append(item)
        if current and current not in unique_values:
            unique_values.append(current)
        combo["values"] = unique_values

    @staticmethod
    def _merge_nested_dicts(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(base or {})
        for key, value in (update or {}).items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = PhotoOptimizeTabFrameV2._merge_nested_dicts(
                    merged.get(key, {}), value
                )
            else:
                merged[key] = deepcopy(value)
        return merged

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        number = float(value)
        if not number.is_integer():
            raise ValueError("Setting must be an integer")
        return int(number)

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        return float(value)

    def get_photo_optimize_state(self) -> dict[str, Any]:
        return {
            "selected_asset_id": self._current_asset_id,
            "selected_asset_ids": self._selected_asset_ids(batch_all=False),
            "show_archived": self.show_archived_var.get(),
            "show_image_previews": self.show_image_previews_var.get(),
            "editing_scope": self.edit_scope_var.get(),
        }

    def _on_app_state_resources_changed(
        self, resources: dict[str, list[Any]] | None = None
    ) -> None:
        resource_map = resources if isinstance(resources, dict) else None
        if not bool(self.winfo_ismapped()):
            self._pending_resources_payload = resource_map
            return
        self._pending_resources_payload = None
        self._refresh_resource_options(resource_map)

    def bind_app_state(self, app_state: Any) -> None:
        if self.app_state is app_state:
            return
        old_state = self.app_state
        old_listener = self._app_state_resource_listener
        old_visibility_listener = self._app_state_visibility_listener
        if old_state is not None and old_listener is not None and hasattr(old_state, "unsubscribe"):
            try:
                old_state.unsubscribe("resources", old_listener)
            except Exception:
                pass
        if (
            old_state is not None
            and old_visibility_listener is not None
            and hasattr(old_state, "unsubscribe")
        ):
            try:
                old_state.unsubscribe("content_visibility_mode", old_visibility_listener)
            except Exception:
                pass
        self.app_state = app_state
        self._app_state_resource_listener = None
        self._app_state_visibility_listener = None
        if self.app_state is not None and hasattr(self.app_state, "subscribe"):
            self._app_state_resource_listener = lambda: self._on_app_state_resources_changed(
                getattr(self.app_state, "resources", None)
            )
            try:
                self.app_state.subscribe("resources", self._app_state_resource_listener)
            except Exception:
                self._app_state_resource_listener = None
            self._app_state_visibility_listener = self._on_content_visibility_mode_changed
            try:
                self.app_state.subscribe(
                    "content_visibility_mode",
                    self._app_state_visibility_listener,
                )
            except Exception:
                self._app_state_visibility_listener = None
        self._on_app_state_resources_changed(
            getattr(self.app_state, "resources", None) if self.app_state is not None else None
        )
        self.on_content_visibility_mode_changed()

    def restore_photo_optimize_state(self, payload: dict[str, Any] | None) -> bool:
        if not isinstance(payload, dict):
            return False
        selected_asset_id = payload.get("selected_asset_id")
        if "selected_asset_ids" in payload:
            self._restored_asset_ids = [str(asset_id) for asset_id in payload["selected_asset_ids"]]
        self.show_archived_var.set(bool(payload.get("show_archived", False)))
        self.show_image_previews_var.set(bool(payload.get("show_image_previews", True)))
        scope = "Batch Edit" if payload.get("editing_scope") == "Batch Edit" else "Single Photo"
        self.edit_workspaces.select(self.batch_workspace if scope == "Batch Edit" else self.single_workspace)
        self.edit_scope_var.set(scope)
        if selected_asset_id:
            self._restored_asset_id = str(selected_asset_id)
            self._refresh_assets(select_asset_id=self._restored_asset_id)
            return True
        self._refresh_assets()
        return False

    def on_assets_updated(self, asset_ids: list[str] | None = None) -> None:
        target = self._current_asset_id
        if not bool(self.winfo_ismapped()):
            self._pending_asset_refresh_target = target or ""
            return
        self._pending_asset_refresh_target = None
        self._refresh_assets()

    def _on_map(self, _event: Any = None) -> None:
        if self._pending_resources_payload is not None:
            resources = self._pending_resources_payload
            self._pending_resources_payload = None
            self.after_idle(lambda resources=resources: self._refresh_resource_options(resources))
        if self._pending_asset_refresh_target is not None:
            self._pending_asset_refresh_target = None
            self.after_idle(self._refresh_assets)
        if self._pending_visibility_refresh:
            self.after_idle(
                lambda: self.on_content_visibility_mode_changed(self._content_visibility_mode)
            )

    def destroy(self) -> None:
        self._dispose_result_preview()
        if self._operation_poll_id is not None:
            self.after_cancel(self._operation_poll_id)
        if self._operation_executor is not None:
            self._operation_executor.shutdown(wait=False, cancel_futures=True)
        if self._workspace_poll_id is not None:
            self.after_cancel(self._workspace_poll_id)
        if self._workspace_executor is not None:
            self._workspace_executor.shutdown(wait=False, cancel_futures=True)
        if (
            self.app_state is not None
            and self._app_state_resource_listener is not None
            and hasattr(self.app_state, "unsubscribe")
        ):
            try:
                self.app_state.unsubscribe("resources", self._app_state_resource_listener)
            except Exception:
                pass
        if (
            self.app_state is not None
            and self._app_state_visibility_listener is not None
            and hasattr(self.app_state, "unsubscribe")
        ):
            try:
                self.app_state.unsubscribe(
                    "content_visibility_mode", self._app_state_visibility_listener
                )
            except Exception:
                pass
        self._app_state_resource_listener = None
        self._app_state_visibility_listener = None
        super().destroy()


PhotoOptimizeTabFrame = PhotoOptimizeTabFrameV2
