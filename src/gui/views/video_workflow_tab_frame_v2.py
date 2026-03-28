from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, cast

from src.gui.layout_v2 import configure_grid_columns
from src.gui.help_text.workflow_guidance_v2 import build_video_workflow_guidance
from src.gui.help_text.stage_setting_help_v2 import VIDEO_WORKFLOW_SETTING_HELP
from src.gui.theme_v2 import style_text_widget
from src.gui.tooltip import attach_tooltip
from src.gui.widgets.action_explainer_panel_v2 import ActionExplainerPanel
from src.state.output_routing import (
    OUTPUT_ROUTE_MOVIE_CLIPS,
    OUTPUT_ROUTE_REPROCESS,
    OUTPUT_ROUTE_TESTING,
)
from src.gui.widgets.tab_overview_panel_v2 import TabOverviewPanel, get_tab_overview_content
from src.gui.view_contracts.pipeline_layout_contract import build_form_column_specs
from src.gui.view_contracts.video_workspace_contract import (
    format_workflow_capability_label,
    summarize_video_workflow_source,
)

_IMAGE_FILETYPES = [
    ("PNG files", "*.png"),
    ("Image files", "*.png *.jpg *.jpeg *.webp *.bmp *.tiff *.tif"),
    ("All files", "*.*"),
]
_MOTION_PROFILES = ("gentle", "balanced", "dynamic")
_OUTPUT_ROUTES = (OUTPUT_ROUTE_REPROCESS, OUTPUT_ROUTE_MOVIE_CLIPS, OUTPUT_ROUTE_TESTING)


class VideoWorkflowTabFrameV2(ttk.Frame):
    """Dedicated queue-backed UI for workflow-driven video generation."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        app_controller: Any = None,
        app_state: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self.app_controller = app_controller
        self.app_state = app_state
        self._workflow_map: dict[str, dict[str, Any]] = {}
        self._last_folder = ""
        self._source_bundle: dict[str, Any] | None = None
        self._setting_tooltips: dict[str, Any] = {}

        defaults = self._load_defaults()
        self.workflow_var = tk.StringVar(value=str(defaults.get("workflow_id") or ""))
        self.source_image_var = tk.StringVar(value=str(defaults.get("source_image_path") or ""))
        self.end_anchor_var = tk.StringVar(value=str(defaults.get("end_anchor_path") or ""))
        self.mid_anchors_var = tk.StringVar(value="; ".join(defaults.get("mid_anchor_paths") or []))
        self.motion_profile_var = tk.StringVar(value=str(defaults.get("motion_profile") or "gentle"))
        self.output_route_var = tk.StringVar(value=str(defaults.get("output_route") or OUTPUT_ROUTE_REPROCESS))
        self.status_var = tk.StringVar(value="Ready to queue a workflow-driven video job.")
        self.workflow_detail_var = tk.StringVar(value="No workflow selected.")
        self.source_summary_var = tk.StringVar(value="Source: none selected")
        self.effective_settings_var = tk.StringVar(value="Effective settings: defaults loaded")
        self._defaults = dict(defaults)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=0)
        self.rowconfigure(1, weight=0)
        self.rowconfigure(2, weight=1)

        self.overview_panel = TabOverviewPanel(
            self,
            content=get_tab_overview_content("video_workflow"),
            app_state=self.app_state,
        )
        self.overview_panel.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 0))

        self._build_header()
        self._build_body()
        self._refresh_workflow_choices()
        self._set_text_value(self.prompt_text, str(defaults.get("prompt") or ""))
        self._set_text_value(self.negative_prompt_text, str(defaults.get("negative_prompt") or ""))
        if self.app_state is not None and hasattr(self.app_state, "subscribe"):
            try:
                self.app_state.subscribe(
                    "content_visibility_mode",
                    self._on_content_visibility_mode_changed,
                )
            except Exception:
                pass
        for variable in (
            self.workflow_var,
            self.source_image_var,
            self.end_anchor_var,
            self.mid_anchors_var,
            self.output_route_var,
        ):
            variable.trace_add("write", lambda *_args: self._refresh_workspace_summary())
        self._refresh_workspace_summary()
        self.on_content_visibility_mode_changed()

    def _load_defaults(self) -> dict[str, Any]:
        controller = getattr(self, "app_controller", None)
        builder = getattr(controller, "build_video_workflow_defaults", None)
        if callable(builder):
            try:
                return dict(builder() or {})
            except Exception:
                pass
        return {
            "workflow_id": "",
            "workflow_version": "",
            "source_image_path": "",
            "end_anchor_path": "",
            "mid_anchor_paths": [],
            "prompt": "",
            "negative_prompt": "",
            "motion_profile": "gentle",
            "output_route": OUTPUT_ROUTE_REPROCESS,
        }

    def _build_header(self) -> None:
        header = ttk.Frame(self, style="Panel.TFrame", padding=8)
        header.grid(row=1, column=0, sticky="ew", padx=6, pady=(6, 4))
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text="Source Image", style="Dark.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        ttk.Entry(header, textvariable=self.source_image_var, style="Dark.TEntry").grid(
            row=0, column=1, sticky="ew", padx=(0, 6)
        )
        ttk.Button(header, text="Browse...", style="Dark.TButton", command=self._on_browse_source).grid(
            row=0, column=2, sticky="ew", padx=(0, 6)
        )
        self.use_latest_output_button = ttk.Button(
            header,
            text="Use Latest Output",
            style="Dark.TButton",
            command=self._on_use_latest_output,
        )
        self.use_latest_output_button.grid(row=0, column=3, sticky="ew")
        self.use_latest_output_tooltip = attach_tooltip(
            self.use_latest_output_button,
            "Load the newest compatible image output into this workflow tab. This prepares the source input only; it does not queue the workflow yet.",
        )
        ttk.Label(header, textvariable=self.status_var, style="Dark.TLabel").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(6, 0)
        )
        self.visibility_banner = ttk.Label(header, text="", style="Dark.TLabel")
        self.visibility_banner.grid(row=1, column=4, sticky="e", pady=(6, 0))
        ttk.Label(header, textvariable=self.source_summary_var, style="Muted.TLabel").grid(
            row=2, column=0, columnspan=4, sticky="w", pady=(4, 0)
        )
        ttk.Label(header, textvariable=self.effective_settings_var, style="Muted.TLabel").grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(2, 0)
        )

    def _build_body(self) -> None:
        body = ttk.Frame(self, style="Panel.TFrame", padding=8)
        body.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 6))
        configure_grid_columns(
            body,
            build_form_column_specs(
                label_columns=(0,),
                primary_columns=(1,),
                secondary_columns=(2, 3),
                secondary_min_width=140,
                secondary_weight=1,
            ),
        )
        body.rowconfigure(6, weight=1)
        body.rowconfigure(7, weight=1)
        self._body_frame = body

        self.workflow_combo: ttk.Combobox = cast(
            ttk.Combobox,
            self._add_labeled_entry(
            body,
            0,
            "Workflow",
            combo=True,
            variable=self.workflow_var,
            help_key="workflow",
            ),
        )
        ttk.Label(body, textvariable=self.workflow_detail_var, style="Muted.TLabel", wraplength=640, justify="left").grid(
            row=0, column=3, sticky="w", padx=(8, 0), pady=(0, 6)
        )
        self._add_labeled_entry(
            body,
            1,
            "End Anchor",
            variable=self.end_anchor_var,
            help_key="end_anchor",
        )
        ttk.Button(body, text="Browse...", style="Dark.TButton", command=self._on_browse_end_anchor).grid(
            row=1, column=2, sticky="ew", padx=(6, 0)
        )

        self._add_labeled_entry(
            body,
            2,
            "Mid Anchors",
            variable=self.mid_anchors_var,
            width=60,
            helper="Optional, separated by ';'",
            help_key="mid_anchors",
        )
        ttk.Button(body, text="Browse...", style="Dark.TButton", command=self._on_browse_mid_anchors).grid(
            row=2, column=2, sticky="ew", padx=(6, 0)
        )

        self._add_labeled_entry(
            body,
            3,
            "Motion",
            combo=True,
            variable=self.motion_profile_var,
            values=_MOTION_PROFILES,
            help_key="motion",
        )
        self._add_labeled_entry(
            body,
            4,
            "Output Route",
            combo=True,
            variable=self.output_route_var,
            values=_OUTPUT_ROUTES,
            help_key="output_route",
        )
        self.workflow_help_panel = ActionExplainerPanel(
            body,
            content=build_video_workflow_guidance(),
            app_state=self.app_state,
            wraplength=900,
        )
        self.workflow_help_panel.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(8, 6))

        prompt_label = ttk.Label(body, text="Prompt", style="Dark.TLabel")
        prompt_label.grid(row=6, column=0, sticky="nw", padx=(0, 8), pady=(8, 6))
        self.prompt_text = tk.Text(
            body,
            height=5,
            wrap="word",
        )
        style_text_widget(self.prompt_text, elevated=True)
        self.prompt_text.grid(row=6, column=1, columnspan=3, sticky="nsew", pady=(8, 6))
        self._attach_setting_help(
            "prompt",
            VIDEO_WORKFLOW_SETTING_HELP["prompt"],
            prompt_label,
            self.prompt_text,
        )

        negative_label = ttk.Label(body, text="Negative", style="Dark.TLabel")
        negative_label.grid(row=7, column=0, sticky="nw", padx=(0, 8), pady=(0, 6))
        self.negative_prompt_text = tk.Text(
            body,
            height=4,
            wrap="word",
        )
        style_text_widget(self.negative_prompt_text, elevated=True)
        self.negative_prompt_text.grid(row=7, column=1, columnspan=3, sticky="nsew", pady=(0, 6))
        self._attach_setting_help(
            "negative",
            VIDEO_WORKFLOW_SETTING_HELP["negative"],
            negative_label,
            self.negative_prompt_text,
        )

        submit_frame = ttk.Frame(body, style="Panel.TFrame")
        submit_frame.grid(row=8, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        self.queue_workflow_button = ttk.Button(
            submit_frame,
            text="Queue Video Workflow",
            style="Primary.TButton",
            command=self._on_submit,
        )
        self.queue_workflow_button.pack(side="left")
        self.queue_workflow_tooltip = attach_tooltip(
            self.queue_workflow_button,
            "Queue a workflow-driven video job using the selected workflow, anchors, prompts, and route shown in this tab.",
        )

    def _add_labeled_entry(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        *,
        variable: tk.Variable,
        combo: bool = False,
        values: tuple[str, ...] | list[str] = (),
        width: int = 40,
        helper: str = "",
        help_key: str | None = None,
    ) -> ttk.Combobox | ttk.Entry:
        label_widget = ttk.Label(parent, text=label, style="Dark.TLabel")
        label_widget.grid(row=row, column=0, sticky="w", padx=(0, 8), pady=(0, 6))
        widget: ttk.Combobox | ttk.Entry
        if combo:
            widget = ttk.Combobox(
                parent,
                textvariable=variable,
                values=list(values),
                state="readonly",
                style="Dark.TCombobox",
                width=width,
            )
        else:
            widget = ttk.Entry(parent, textvariable=variable, style="Dark.TEntry", width=width)
        widget.grid(row=row, column=1, sticky="ew", pady=(0, 6))
        if help_key:
            self._attach_setting_help(help_key, VIDEO_WORKFLOW_SETTING_HELP[help_key], label_widget, widget)
        if helper:
            ttk.Label(parent, text=helper, style="Muted.TLabel").grid(
                row=row, column=3, sticky="w", padx=(8, 0), pady=(0, 6)
            )
        return widget

    def _attach_setting_help(self, key: str, text: str, *widgets: tk.Widget | None) -> None:
        live_widgets = [widget for widget in widgets if widget is not None]
        if not live_widgets:
            return
        primary = live_widgets[0]
        self._setting_tooltips[key] = attach_tooltip(primary, text)
        for widget in live_widgets[1:]:
            attach_tooltip(widget, text)

    def _refresh_workflow_choices(self) -> None:
        controller = getattr(self, "app_controller", None)
        loader = getattr(controller, "get_video_workflow_specs", None)
        specs = []
        if callable(loader):
            try:
                specs = list(loader() or [])
            except Exception:
                specs = []
        self._workflow_map = {
            str(item.get("workflow_id") or ""): dict(item)
            for item in specs
            if item.get("workflow_id")
        }
        values = list(self._workflow_map.keys())
        self.workflow_combo["values"] = values
        if not self.workflow_var.get() and values:
            self.workflow_var.set(values[0])
        self._refresh_workspace_summary()

    def set_source_image_path(self, image_path: str, *, status_message: str | None = None) -> None:
        self.source_image_var.set(str(image_path))
        self._source_bundle = None
        if status_message:
            self.status_var.set(status_message)
        self._refresh_workspace_summary()

    def set_source_bundle(
        self,
        bundle: dict[str, Any],
        *,
        status_message: str | None = None,
    ) -> None:
        """Accept a generic video-artifact handoff bundle (PR-VIDEO-215).

        Extracts the best source image for this workflow tab:
        thumbnail_path > source_image_path > first frame path.
        """
        from src.video.video_artifact_helpers import extract_source_image_for_handoff

        best_path = extract_source_image_for_handoff(bundle) if isinstance(bundle, dict) else None
        if best_path:
            self._source_bundle = dict(bundle)
            self.source_image_var.set(str(best_path))
            self.status_var.set(
                status_message
                or f"Loaded from video output: {best_path.rsplit('/', 1)[-1].rsplit(chr(92), 1)[-1]}"
            )
            self._refresh_workspace_summary()

    def get_video_workflow_state(self) -> dict[str, Any]:
        workflow_meta = self._workflow_map.get(self.workflow_var.get(), {})
        return {
            "workflow_id": self.workflow_var.get().strip(),
            "workflow_version": str(workflow_meta.get("workflow_version") or "").strip(),
            "source_image_path": self.source_image_var.get().strip(),
            "end_anchor_path": self.end_anchor_var.get().strip(),
            "mid_anchor_paths": [
                item.strip() for item in self.mid_anchors_var.get().split(";") if item.strip()
            ],
            "prompt": self.prompt_text.get("1.0", "end").strip(),
            "negative_prompt": self.negative_prompt_text.get("1.0", "end").strip(),
            "motion_profile": self.motion_profile_var.get().strip(),
            "output_route": self.output_route_var.get().strip(),
        }

    def restore_video_workflow_state(self, state: dict[str, Any] | None) -> None:
        if not isinstance(state, dict):
            return
        self._refresh_workflow_choices()
        self.workflow_var.set(str(state.get("workflow_id") or self.workflow_var.get()))
        self.source_image_var.set(str(state.get("source_image_path") or ""))
        self.end_anchor_var.set(str(state.get("end_anchor_path") or ""))
        mid_anchors = state.get("mid_anchor_paths") or []
        if isinstance(mid_anchors, str):
            text = mid_anchors
        else:
            text = "; ".join(str(item) for item in mid_anchors if item)
        self.mid_anchors_var.set(text)
        self.motion_profile_var.set(str(state.get("motion_profile") or self.motion_profile_var.get()))
        self.output_route_var.set(str(state.get("output_route") or self.output_route_var.get()))
        self._set_text_value(self.prompt_text, str(state.get("prompt") or ""))
        self._set_text_value(self.negative_prompt_text, str(state.get("negative_prompt") or ""))
        self._source_bundle = None
        self._refresh_workspace_summary()

    def _refresh_workspace_summary(self) -> None:
        workflow_meta = self._workflow_map.get(self.workflow_var.get(), {})
        self.workflow_detail_var.set(format_workflow_capability_label(workflow_meta))
        summary = summarize_video_workflow_source(
            source_image_path=self.source_image_var.get().strip(),
            workflow_spec=workflow_meta,
            end_anchor_path=self.end_anchor_var.get().strip(),
            mid_anchor_paths=self.mid_anchors_var.get(),
            bundle=self._source_bundle,
        )
        detail = summary.detail.strip()
        if detail:
            self.source_summary_var.set(f"{summary.headline} | {detail}")
        else:
            self.source_summary_var.set(summary.headline or summary.empty_state)
        workflow_value = self.workflow_var.get().strip() or "none"
        workflow_source = (
            "default"
            if workflow_value == str(self._defaults.get("workflow_id") or "").strip()
            else "selected here"
        )
        motion_value = self.motion_profile_var.get().strip() or "gentle"
        motion_source = (
            "default"
            if motion_value == str(self._defaults.get("motion_profile") or "gentle").strip()
            else "selected here"
        )
        output_value = self.output_route_var.get().strip() or OUTPUT_ROUTE_REPROCESS
        output_source = (
            "default"
            if output_value == str(self._defaults.get("output_route") or OUTPUT_ROUTE_REPROCESS).strip()
            else "selected here"
        )
        anchor_state = "explicit anchors" if (self.end_anchor_var.get().strip() or self.mid_anchors_var.get().strip()) else "source-only"
        self.effective_settings_var.set(
            f"Effective settings: workflow={workflow_value} [{workflow_source}] | motion={motion_value} [{motion_source}] | output={output_value} [{output_source}] | anchor plan={anchor_state}"
        )

    def _set_text_value(self, widget: tk.Text, value: str) -> None:
        widget.delete("1.0", "end")
        widget.insert("1.0", value)

    def on_content_visibility_mode_changed(self, mode: str | None = None) -> None:
        value = str(
            mode or getattr(getattr(self, "app_state", None), "content_visibility_mode", "nsfw") or "nsfw"
        ).lower()
        self.visibility_banner.configure(text="SFW mode active" if value == "sfw" else "")

    def _on_content_visibility_mode_changed(self) -> None:
        self.on_content_visibility_mode_changed()

    def _on_browse_source(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose source image",
            filetypes=_IMAGE_FILETYPES,
            initialdir=self._last_folder or None,
        )
        if path:
            self._last_folder = str(Path(path).parent)
            self.source_image_var.set(path)

    def _on_browse_end_anchor(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose end anchor image",
            filetypes=_IMAGE_FILETYPES,
            initialdir=self._last_folder or None,
        )
        if path:
            self._last_folder = str(Path(path).parent)
            self.end_anchor_var.set(path)

    def _on_browse_mid_anchors(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Choose mid anchor images",
            filetypes=_IMAGE_FILETYPES,
            initialdir=self._last_folder or None,
        )
        if paths:
            self._last_folder = str(Path(paths[0]).parent)
            self.mid_anchors_var.set("; ".join(str(path) for path in paths))

    def _on_use_latest_output(self) -> None:
        controller = getattr(self, "app_controller", None)
        getter = getattr(controller, "get_latest_output_image_path", None)
        latest = getter() if callable(getter) else None
        if latest:
            self._source_bundle = None
            self.source_image_var.set(str(latest))
            self.status_var.set(f"Loaded latest output: {Path(str(latest)).name}")
            self._refresh_workspace_summary()
        else:
            self.status_var.set("No recent image output available to route into Video Workflow.")

    def _on_submit(self) -> None:
        controller = getattr(self, "app_controller", None)
        handler = getattr(controller, "submit_video_workflow_job", None)
        if not callable(handler):
            messagebox.showerror("Video Workflow", "Video workflow submission is not available.")
            return
        source_image_path = self.source_image_var.get().strip()
        form_data = self.get_video_workflow_state()
        try:
            job_id = handler(source_image_path=source_image_path, form_data=form_data)
        except Exception as exc:
            messagebox.showerror("Video Workflow", str(exc))
            self.status_var.set(f"Video workflow queue failed: {exc}")
            return
        self.status_var.set(f"Queued video workflow job {job_id}")
        messagebox.showinfo("Video Workflow", f"Queued video workflow job {job_id}")
