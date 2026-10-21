"""Movie Clips tab frame for StableNew v2.6.

PR-GUI-VIDEO-001: Tab shell, source selection, ordered image list,
clip settings, and UI-state persistence. PR-VID-ASM-332: images and videos in
the operator's order (Move Up/Down), per-still durations, resolution,
crossfade and music track; Build queues an assembly job.
"""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any

from src.gui.help_text.stage_setting_help_v2 import MOVIE_CLIPS_SETTING_HELP
from src.gui.help_text.workflow_guidance_v2 import build_movie_clips_guidance
from src.gui.layout_v2 import configure_grid_columns
from src.gui.theme_v2 import style_listbox_widget
from src.gui.tooltip import attach_tooltip
from src.gui.ui_tokens import TOKENS
from src.gui.view_contracts.movie_clips_contract import (
    AUDIO_FILE_TYPES,
    CODEC_OPTIONS,
    DEFAULT_CLIP_NAME,
    DEFAULT_CODEC,
    DEFAULT_FADE_OUT_SECONDS,
    DEFAULT_FPS,
    DEFAULT_MODE,
    DEFAULT_QUALITY,
    DEFAULT_RESOLUTION,
    DEFAULT_STILL_SECONDS,
    DEFAULT_TRANSITION_SECONDS,
    MODE_OPTIONS,
    QUALITY_OPTIONS,
    RESOLUTION_OPTIONS,
    SOURCE_FILE_TYPES,
    SOURCE_MODE_FOLDER,
    SOURCE_MODE_MANUAL,
    build_clip_settings_summary,
    extract_source_paths_from_bundle,
    format_canonical_source_summary,
    format_clip_entry,
    format_image_list_summary,
    format_source_mode_label,
    is_media_path,
    is_video_path,
    move_items,
)
from src.gui.view_contracts.pipeline_layout_contract import (
    PRIMARY_CONTROL_MIN_WIDTH,
    get_two_pane_workspace_column_specs,
)
from src.gui.view_contracts.video_workspace_contract import summarize_movie_clips_source
from src.gui.widgets.action_explainer_panel_v2 import ActionExplainerPanel
from src.gui.widgets.tab_overview_panel_v2 import TabOverviewPanel, get_tab_overview_content

logger = logging.getLogger(__name__)

# Supported image file extensions
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}


class MovieClipsTabFrameV2(ttk.Frame):
    """Top-level Movie Clips tab: source selection, image list, clip settings.

    No clip assembly logic lives here. Assembly is delegated to the controller
    when wired (PR-VIDEO-002).
    """

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

        # Internal state
        self._source_mode: str = SOURCE_MODE_FOLDER
        self._last_folder: str = ""
        self._image_paths: list[Path] = []
        #: Per-item still duration in slideshow mode (``None``: the Still (s) default), parallel to ``_image_paths``.
        self._clip_durations: list[float | None] = []
        self._source_bundle: dict[str, Any] | None = None
        self._build_status: str = ""
        self._setting_tooltips: dict[str, Any] = {}
        self._pending_visibility_refresh = False

        # Tk variables
        self.source_mode_var = tk.StringVar(value=SOURCE_MODE_FOLDER)
        self.folder_var = tk.StringVar()
        self.fps_var = tk.IntVar(value=DEFAULT_FPS)
        self.codec_var = tk.StringVar(value=DEFAULT_CODEC)
        self.quality_var = tk.StringVar(value=DEFAULT_QUALITY)
        self.mode_var = tk.StringVar(value=DEFAULT_MODE)
        self.resolution_var = tk.StringVar(value=DEFAULT_RESOLUTION)
        self.transition_var = tk.DoubleVar(value=DEFAULT_TRANSITION_SECONDS)
        self.still_seconds_var = tk.DoubleVar(value=DEFAULT_STILL_SECONDS)
        self.audio_path_var = tk.StringVar()
        self.fade_out_var = tk.DoubleVar(value=DEFAULT_FADE_OUT_SECONDS)
        self.clip_name_var = tk.StringVar(value=DEFAULT_CLIP_NAME)
        self.source_summary_var = tk.StringVar(value=summarize_movie_clips_source().empty_state)
        self.effective_settings_var = tk.StringVar(value="Effective settings: defaults loaded")

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=0)
        self.rowconfigure(1, weight=0)
        self.rowconfigure(2, weight=1)

        self.overview_panel = TabOverviewPanel(
            self,
            content=get_tab_overview_content("movie_clips"),
            app_state=self.app_state,
        )
        self.overview_panel.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 0))

        self._build_header()
        self._build_body()
        self.bind("<Map>", self._on_map, add="+")
        for variable in (self.fps_var, self.codec_var, self.quality_var, self.mode_var):
            variable.trace_add("write", lambda *_: self._update_effective_settings_summary())
        # Slideshow rows show each still's duration; a frame sequence shows plain names.
        self.mode_var.trace_add("write", lambda *_: self._refresh_list_widget(keep_selection=True))
        self._update_effective_settings_summary()
        if self.app_state is not None and hasattr(self.app_state, "subscribe"):
            try:
                self.app_state.subscribe(
                    "content_visibility_mode",
                    self._on_content_visibility_mode_changed,
                )
            except Exception:
                pass
        self.on_content_visibility_mode_changed()

        # Trace source mode toggle
        self.source_mode_var.trace_add("write", lambda *_: self._on_source_mode_changed())

    # ------------------------------------------------------------------
    # Layout construction
    # ------------------------------------------------------------------

    def _build_header(self) -> None:
        header = ttk.Frame(self, style="Panel.TFrame", padding=8)
        header.grid(row=1, column=0, sticky="ew", padx=6, pady=(6, 4))
        header.columnconfigure(6, weight=1)

        ttk.Label(header, text="Source:", style="Dark.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        ttk.Radiobutton(
            header,
            text=format_source_mode_label(SOURCE_MODE_FOLDER),
            variable=self.source_mode_var,
            value=SOURCE_MODE_FOLDER,
            style="Dark.TRadiobutton",
        ).grid(row=0, column=1, sticky="w", padx=(0, 8))
        ttk.Radiobutton(
            header,
            text=format_source_mode_label(SOURCE_MODE_MANUAL),
            variable=self.source_mode_var,
            value=SOURCE_MODE_MANUAL,
            style="Dark.TRadiobutton",
        ).grid(row=0, column=2, sticky="w", padx=(0, 12))

        self.folder_entry = ttk.Entry(
            header,
            textvariable=self.folder_var,
            style="Dark.TEntry",
            width=42,
        )
        self.folder_entry.grid(row=0, column=3, sticky="ew", padx=(0, 6))

        self.browse_btn = ttk.Button(
            header,
            text="Browse...",
            style="Dark.TButton",
            command=self._on_browse_folder,
        )
        self.browse_btn.grid(row=0, column=4, sticky="w", padx=(0, 6))

        self.load_btn = ttk.Button(
            header,
            text="Load Folder",
            style="Dark.TButton",
            command=self._on_load_images,
        )
        self.load_btn.grid(row=0, column=5, sticky="w")
        self.latest_video_btn = ttk.Button(
            header,
            text="Use Latest Video Output",
            style="Dark.TButton",
            command=self._on_use_latest_video_output,
        )
        self.latest_video_btn.grid(row=0, column=6, sticky="w", padx=(6, 0))
        self.latest_video_tooltip = attach_tooltip(
            self.latest_video_btn,
            "Pull the most recent compatible video-output bundle into Movie Clips so you can assemble its frames without browsing manually.",
        )

        self.status_label = ttk.Label(
            header,
            text="",
            style="Dark.TLabel",
        )
        self.status_label.grid(row=0, column=7, sticky="e", padx=(8, 0))
        self.visibility_banner = ttk.Label(header, text="", style="Muted.TLabel")
        ttk.Label(
            header,
            textvariable=self.source_summary_var,
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=8, sticky="w", pady=(6, 0))
        ttk.Label(
            header,
            textvariable=self.effective_settings_var,
            style="Muted.TLabel",
        ).grid(row=2, column=0, columnspan=8, sticky="w", pady=(2, 0))

    def _build_body(self) -> None:
        body = ttk.Frame(self, style="Panel.TFrame")
        body.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 6))
        configure_grid_columns(
            body,
            get_two_pane_workspace_column_specs(
                left_weight=3,
                right_weight=2,
                left_min_width=420,
                right_min_width=320,
            ),
        )
        body.rowconfigure(0, weight=1)
        self._body_frame = body

        # Left: ordered image list
        list_frame = ttk.LabelFrame(
            body,
            text="Clips (in movie order)",
            style="Dark.TLabelframe",
            padding=6,
        )
        list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.image_list = tk.Listbox(
            list_frame,
            bg=TOKENS.colors.surface_secondary,
            fg=TOKENS.colors.text_primary,
            selectbackground=TOKENS.colors.accent_primary,
            selectforeground=TOKENS.colors.text_primary,
            selectmode=tk.EXTENDED,
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=TOKENS.colors.border_subtle,
            exportselection=False,
        )
        style_listbox_widget(self.image_list)
        self.image_list.grid(row=0, column=0, sticky="nsew")
        _sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.image_list.yview)
        _sb.grid(row=0, column=1, sticky="ns")
        self.image_list.configure(yscrollcommand=_sb.set)

        # List action buttons
        btn_row = ttk.Frame(list_frame, style="Panel.TFrame")
        btn_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        self.add_images_btn = ttk.Button(
            btn_row,
            text="Add Files...",
            style="Dark.TButton",
            command=self._on_add_images,
        )
        self.add_images_btn.pack(side="left", padx=(0, 6))

        self.move_up_btn = ttk.Button(
            btn_row, text="Move Up", style="Dark.TButton", command=lambda: self._on_move(-1)
        )
        self.move_up_btn.pack(side="left", padx=(0, 6))
        self.move_down_btn = ttk.Button(
            btn_row, text="Move Down", style="Dark.TButton", command=lambda: self._on_move(1)
        )
        self.move_down_btn.pack(side="left", padx=(0, 6))

        self.remove_selected_btn = ttk.Button(
            btn_row,
            text="Remove Selected",
            style="Dark.TButton",
            command=self._on_remove_selected,
        )
        self.remove_selected_btn.pack(side="left", padx=(0, 6))

        self.clear_all_btn = ttk.Button(
            btn_row,
            text="Clear All",
            style="Dark.TButton",
            command=self._on_clear_all,
        )
        self.clear_all_btn.pack(side="left")

        duration_row = ttk.Frame(list_frame, style="Panel.TFrame")
        duration_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        still_label = ttk.Label(duration_row, text="Still (s)", style="Dark.TLabel")
        still_label.pack(side="left", padx=(0, 6))
        self.still_seconds_spin = ttk.Spinbox(
            duration_row,
            from_=0.1,
            to=300.0,
            increment=0.5,
            textvariable=self.still_seconds_var,
            width=6,
            style="Dark.TSpinbox",
        )
        self.still_seconds_spin.pack(side="left", padx=(0, 6))
        self.apply_duration_btn = ttk.Button(
            duration_row,
            text="Set for Selected",
            style="Dark.TButton",
            command=self._on_apply_duration,
        )
        self.apply_duration_btn.pack(side="left")
        self._attach_setting_help(
            "still_seconds",
            MOVIE_CLIPS_SETTING_HELP["still_seconds"],
            still_label,
            self.still_seconds_spin,
            self.apply_duration_btn,
        )

        self.list_summary_label = ttk.Label(
            duration_row,
            text=format_image_list_summary(0),
            style="Dark.TLabel",
        )
        self.list_summary_label.pack(side="right", padx=(8, 0))

        # Right: clip settings + build action
        settings_frame = ttk.LabelFrame(
            body,
            text="Clip Settings",
            style="Dark.TLabelframe",
            padding=8,
        )
        settings_frame.grid(row=0, column=1, sticky="ns")
        settings_frame.columnconfigure(1, weight=1, minsize=PRIMARY_CONTROL_MIN_WIDTH)
        self._settings_frame = settings_frame

        self.workflow_help_panel = ActionExplainerPanel(
            settings_frame,
            content=build_movie_clips_guidance(),
            app_state=self.app_state,
            wraplength=240,
        )
        self.workflow_help_panel.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        fps_label = ttk.Label(settings_frame, text="FPS", style="Dark.TLabel", anchor="w")
        fps_label.grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(0, 6))
        self.fps_spin = ttk.Spinbox(
            settings_frame,
            from_=1,
            to=120,
            increment=1,
            textvariable=self.fps_var,
            width=6,
            style="Dark.TSpinbox",
        )
        self.fps_spin.grid(row=1, column=1, sticky="ew", pady=(0, 6))
        self._attach_setting_help("fps", MOVIE_CLIPS_SETTING_HELP["fps"], fps_label, self.fps_spin)

        codec_label = ttk.Label(settings_frame, text="Codec", style="Dark.TLabel", anchor="w")
        codec_label.grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(0, 6))
        self.codec_combo = ttk.Combobox(
            settings_frame,
            textvariable=self.codec_var,
            values=CODEC_OPTIONS,
            state="readonly",
            style="Dark.TCombobox",
            width=14,
        )
        self.codec_combo.grid(row=2, column=1, sticky="ew", pady=(0, 6))
        self._attach_setting_help(
            "codec",
            MOVIE_CLIPS_SETTING_HELP["codec"],
            codec_label,
            self.codec_combo,
        )

        quality_label = ttk.Label(settings_frame, text="Quality", style="Dark.TLabel", anchor="w")
        quality_label.grid(row=3, column=0, sticky="w", padx=(0, 8), pady=(0, 6))
        self.quality_combo = ttk.Combobox(
            settings_frame,
            textvariable=self.quality_var,
            values=QUALITY_OPTIONS,
            state="readonly",
            style="Dark.TCombobox",
            width=14,
        )
        self.quality_combo.grid(row=3, column=1, sticky="ew", pady=(0, 6))
        self._attach_setting_help(
            "quality",
            MOVIE_CLIPS_SETTING_HELP["quality"],
            quality_label,
            self.quality_combo,
        )

        mode_label = ttk.Label(settings_frame, text="Mode", style="Dark.TLabel", anchor="w")
        mode_label.grid(row=4, column=0, sticky="w", padx=(0, 8), pady=(0, 6))
        self.mode_combo = ttk.Combobox(
            settings_frame,
            textvariable=self.mode_var,
            values=MODE_OPTIONS,
            state="readonly",
            style="Dark.TCombobox",
            width=14,
        )
        self.mode_combo.grid(row=4, column=1, sticky="ew", pady=(0, 6))
        self._attach_setting_help(
            "mode",
            MOVIE_CLIPS_SETTING_HELP["mode"],
            mode_label,
            self.mode_combo,
        )

        self.resolution_combo = ttk.Combobox(
            settings_frame,
            textvariable=self.resolution_var,
            values=RESOLUTION_OPTIONS,
            style="Dark.TCombobox",
            width=14,
        )
        self._add_setting_row(5, "Resolution", "resolution", self.resolution_combo)
        self.transition_spin = ttk.Spinbox(
            settings_frame,
            from_=0.0,
            to=5.0,
            increment=0.25,
            textvariable=self.transition_var,
            width=6,
            style="Dark.TSpinbox",
        )
        self._add_setting_row(6, "Transition (s)", "transition", self.transition_spin)
        self.clip_name_entry = ttk.Entry(
            settings_frame, textvariable=self.clip_name_var, style="Dark.TEntry", width=16
        )
        self._add_setting_row(7, "Clip name", "clip_name", self.clip_name_entry)

        audio_frame = ttk.Frame(settings_frame, style="Panel.TFrame")
        audio_frame.columnconfigure(0, weight=1)
        self.audio_entry = ttk.Entry(
            audio_frame, textvariable=self.audio_path_var, style="Dark.TEntry", width=12
        )
        self.audio_entry.grid(row=0, column=0, sticky="ew")
        self.audio_browse_btn = ttk.Button(
            audio_frame, text="...", width=3, style="Dark.TButton", command=self._on_browse_audio
        )
        self.audio_browse_btn.grid(row=0, column=1, padx=(4, 0))
        self.audio_clear_btn = ttk.Button(
            audio_frame,
            text="x",
            width=2,
            style="Dark.TButton",
            command=lambda: self.audio_path_var.set(""),
        )
        self.audio_clear_btn.grid(row=0, column=2, padx=(4, 0))
        self._add_setting_row(8, "Music", "audio", audio_frame)
        self.fade_out_spin = ttk.Spinbox(
            settings_frame,
            from_=0.0,
            to=10.0,
            increment=0.5,
            textvariable=self.fade_out_var,
            width=6,
            style="Dark.TSpinbox",
        )
        self._add_setting_row(9, "Fade out (s)", "audio", self.fade_out_spin, bottom=12)

        ttk.Separator(settings_frame, orient="horizontal").grid(
            row=10, column=0, columnspan=2, sticky="ew", pady=(0, 10)
        )

        self.build_btn = ttk.Button(
            settings_frame,
            text="Queue Assembly",
            style="Primary.TButton",
            command=self._on_build_clip,
        )
        self.build_btn.grid(row=11, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        self.build_tooltip = attach_tooltip(
            self.build_btn,
            "Assemble the currently ordered image list (stills and videos) into one movie with the settings shown "
            "here. The job is queued: follow it in the Queue, cancel it there, and find the movie in History.",
        )

        self.build_status_label = ttk.Label(
            settings_frame,
            text="",
            style="Dark.TLabel",
            wraplength=160,
            justify="center",
        )
        self.build_status_label.grid(row=12, column=0, columnspan=2, sticky="ew")

    def _add_setting_row(
        self, row: int, text: str, help_key: str, widget: tk.Widget, *, bottom: int = 6
    ) -> None:
        label = ttk.Label(self._settings_frame, text=text, style="Dark.TLabel", anchor="w")
        label.grid(row=row, column=0, sticky="w", padx=(0, 8), pady=(0, bottom))
        widget.grid(row=row, column=1, sticky="ew", pady=(0, bottom))
        self._attach_setting_help(help_key, MOVIE_CLIPS_SETTING_HELP[help_key], label, widget)

    def _attach_setting_help(self, key: str, text: str, *widgets: tk.Widget | None) -> None:
        live_widgets = [widget for widget in widgets if widget is not None]
        if not live_widgets:
            return
        primary = live_widgets[0]
        self._setting_tooltips[key] = attach_tooltip(primary, text)
        for widget in live_widgets[1:]:
            attach_tooltip(widget, text)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_source_mode_changed(self) -> None:
        mode = self.source_mode_var.get()
        self._source_mode = mode
        is_folder = mode == SOURCE_MODE_FOLDER
        state = "normal" if is_folder else "disabled"
        try:
            self.folder_entry.configure(state=state)
            self.browse_btn.configure(state=state)
            self.load_btn.configure(state=state)
            # Manual mode: add_images enabled; folder mode: disabled
            add_state = "disabled" if is_folder else "normal"
            self.add_images_btn.configure(state=add_state)
        except Exception:
            pass

    def _on_browse_folder(self) -> None:
        initial = self._last_folder or ""
        folder = filedialog.askdirectory(
            title="Select Run Output Folder",
            initialdir=initial or None,
        )
        if folder:
            self.folder_var.set(folder)
            self._last_folder = folder

    def _on_load_images(self) -> None:
        folder_str = self.folder_var.get().strip()
        if not folder_str:
            self._set_status("No folder selected.")
            return
        folder = Path(folder_str)
        if not folder.is_dir():
            self._set_status("Folder not found.")
            return
        # Name order is only the starting order; Move Up/Down changes it and nothing re-sorts it later.
        media = sorted([p for p in folder.iterdir() if is_media_path(p)], key=lambda p: p.name)
        if not media:
            self._set_status("No images or videos found in folder.")
            return
        self._source_bundle = None
        self._set_image_list(media)
        self._switch_to_slideshow_for_videos()
        self._set_status(f"Loaded {len(media)} file(s) from folder.")

    def _on_add_images(self) -> None:
        files = filedialog.askopenfilenames(
            title="Select Images or Videos", filetypes=SOURCE_FILE_TYPES
        )
        if not files:
            return
        self.add_files([Path(f) for f in files])

    def add_files(self, paths: list[Path]) -> None:
        """Append images and videos at the end of the list, in the given order (a file may appear twice)."""

        added = [path for path in paths if is_media_path(path)]
        if not added:
            self._set_status("No images or videos added.")
            return
        self._source_bundle = None
        self._set_image_list(self._image_paths + added, self._clip_durations + [None] * len(added))
        switched = self._switch_to_slideshow_for_videos()
        note = " Mode switched to slideshow for the videos." if switched else ""
        self._set_status(f"Added {len(added)} file(s).{note}")

    def _switch_to_slideshow_for_videos(self) -> bool:
        """A frame sequence takes images only: a list with a video switches to slideshow."""

        if self.mode_var.get() != "slideshow" and any(is_video_path(p) for p in self._image_paths):
            self.mode_var.set("slideshow")
            return True
        return False

    def _on_move(self, delta: int) -> None:
        selected = self._selected_indices()
        if not selected:
            return
        self._sync_durations()
        pairs, positions = move_items(
            list(zip(self._image_paths, self._clip_durations, strict=True)), selected, delta
        )
        self._image_paths = [path for path, _ in pairs]
        self._clip_durations = [duration for _, duration in pairs]
        self._source_bundle = None
        self._refresh_list_widget(selection=positions)

    def _on_apply_duration(self) -> None:
        self._sync_durations()
        selected = [i for i in self._selected_indices() if not is_video_path(self._image_paths[i])]
        seconds = self._read_float(self.still_seconds_var, DEFAULT_STILL_SECONDS)
        if not selected:
            self._set_status(f"Stills without their own duration show for {seconds:g} s.")
            self._refresh_list_widget(keep_selection=True)
            return
        for index in selected:
            self._clip_durations[index] = seconds
        self._refresh_list_widget(selection=self._selected_indices())
        self._set_status(f"{len(selected)} still(s) now show for {seconds:g} s.")

    def _on_browse_audio(self) -> None:
        path = filedialog.askopenfilename(title="Select Music Track", filetypes=AUDIO_FILE_TYPES)
        if path:
            self.audio_path_var.set(path)

    def _on_remove_selected(self) -> None:
        selected = self._selected_indices()
        if not selected:
            return
        selected_set = set(selected)
        self._image_paths = [p for i, p in enumerate(self._image_paths) if i not in selected_set]
        self._clip_durations = [
            d for i, d in enumerate(self._clip_durations) if i not in selected_set
        ]
        self._source_bundle = None
        self._refresh_list_widget()
        self._update_summary()

    def _on_clear_all(self) -> None:
        self._image_paths = []
        self._clip_durations = []
        self._source_bundle = None
        self._refresh_list_widget()
        self._update_summary()
        self._update_source_summary()
        self._set_status("")

    def _on_use_latest_video_output(self) -> None:
        controller = self.app_controller
        getter = getattr(controller, "get_latest_video_output_bundle", None)
        if not callable(getter):
            self._set_status("Latest video lookup is not connected.")
            return
        try:
            bundle = getter()
        except Exception as exc:
            self._set_status(f"Video lookup failed: {exc}")
            return
        if not isinstance(bundle, dict) or not bundle:
            self._set_status("No recent video output available.")
            return
        self.set_source_bundle(bundle, status_message="Loaded latest video output.")

    def _on_build_clip(self) -> None:
        """Ask the controller to queue the assembly (PR-VID-ASM-332); the queue does the work."""
        controller = self.app_controller
        handler = getattr(controller, "on_build_movie_clip", None)
        if not callable(handler):
            self._set_build_status("Controller not connected.")
            return
        if not self._image_paths:
            self._set_build_status("No images or videos selected.")
            return
        settings = self._collect_settings()
        self._set_build_status("Checking and queueing...")
        try:
            handler(
                image_paths=list(self._image_paths),
                settings=settings,
                on_complete=self._on_build_complete,
                on_error=self._on_build_error,
            )
        except Exception as exc:
            logger.exception("Error calling on_build_movie_clip")
            self._on_build_error(str(exc))

    # ------------------------------------------------------------------
    # Controller callbacks
    # ------------------------------------------------------------------

    def _on_build_complete(self, job_id: str) -> None:
        self._set_build_status(
            f"Queued assembly job {str(job_id)[:8]}. Follow it in the Queue; the movie appears in History."
        )

    def _on_build_error(self, reason: str) -> None:
        self._set_build_status(f"Error: {reason}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_image_list(
        self, paths: list[Path], durations: list[float | None] | None = None
    ) -> None:
        self._image_paths = list(paths)
        self._clip_durations = list(durations) if durations is not None else [None] * len(paths)
        self._refresh_list_widget()
        self._update_summary()
        self._update_source_summary()

    def _refresh_list_widget(
        self, *, selection: list[int] | None = None, keep_selection: bool = False
    ) -> None:
        if keep_selection:
            selection = self._selected_indices()
        self._sync_durations()
        mode = self.mode_var.get()
        default_seconds = self._read_float(self.still_seconds_var, DEFAULT_STILL_SECONDS)
        try:
            self.image_list.delete(0, tk.END)
            for path, duration in zip(self._image_paths, self._clip_durations, strict=True):
                self.image_list.insert(
                    tk.END,
                    format_clip_entry(
                        path, mode=mode, duration_seconds=duration, default_seconds=default_seconds
                    ),
                )
            for index in selection or []:
                self.image_list.selection_set(index)
        except tk.TclError:
            logger.debug("Movie Clips list refresh skipped", exc_info=True)

    def _sync_durations(self) -> None:
        """Keep one duration slot per list item, whoever last replaced ``_image_paths``."""

        count = len(self._image_paths)
        self._clip_durations = (list(self._clip_durations) + [None] * count)[:count]

    def _selected_indices(self) -> list[int]:
        selection = self.image_list.curselection()  # type: ignore[no-untyped-call]
        return [int(index) for index in selection]

    @staticmethod
    def _read_float(variable: tk.DoubleVar, default: float) -> float:
        try:
            return float(variable.get())
        except (tk.TclError, TypeError, ValueError):
            return default

    def _update_summary(self) -> None:
        try:
            self.list_summary_label.configure(
                text=format_image_list_summary(len(self._image_paths))
            )
        except Exception:
            pass

    def _set_status(self, msg: str) -> None:
        try:
            self.status_label.configure(text=msg)
        except Exception:
            pass

    def _update_source_summary(self) -> None:
        summary = summarize_movie_clips_source(
            image_paths=[str(path) for path in self._image_paths],
            bundle=self._source_bundle,
        )
        text = summary.headline
        if summary.detail:
            text = f"{text} | {summary.detail}"
        if not self._image_paths and not self._source_bundle:
            text = summary.empty_state
        self.source_summary_var.set(text)

    def _update_effective_settings_summary(self) -> None:
        summary = build_clip_settings_summary(
            self.fps_var.get(),
            self.codec_var.get(),
            self.quality_var.get(),
            self.mode_var.get(),
        )
        bits = [
            f"fps={summary.fps} [{'default' if summary.fps == DEFAULT_FPS else 'selected here'}]",
            f"codec={summary.codec} [{'default' if summary.codec == DEFAULT_CODEC else 'selected here'}]",
            f"quality={summary.quality} [{'default' if summary.quality == DEFAULT_QUALITY else 'selected here'}]",
            f"mode={summary.mode} [{'default' if summary.mode == DEFAULT_MODE else 'selected here'}]",
        ]
        self.effective_settings_var.set("Effective settings: " + " | ".join(bits))

    def _set_build_status(self, msg: str) -> None:
        self._build_status = msg
        try:
            self.build_status_label.configure(text=msg)
        except Exception:
            pass

    def on_content_visibility_mode_changed(self, mode: str | None = None) -> None:
        self._pending_visibility_refresh = False
        self.visibility_banner.configure(text="")

    def _on_content_visibility_mode_changed(self) -> None:
        if not bool(self.winfo_ismapped()):
            self._pending_visibility_refresh = True
            return
        self.on_content_visibility_mode_changed()

    def _on_map(self, _event=None) -> None:
        if not self._pending_visibility_refresh:
            return
        self.after_idle(self.on_content_visibility_mode_changed)

    def _collect_settings(self) -> dict[str, Any]:
        self._sync_durations()
        return {
            "fps": self.fps_var.get(),
            "codec": self.codec_var.get(),
            "quality": self.quality_var.get(),
            "mode": self.mode_var.get(),
            "resolution": self.resolution_var.get().strip() or DEFAULT_RESOLUTION,
            "still_seconds": self._read_float(self.still_seconds_var, DEFAULT_STILL_SECONDS),
            "clip_durations": list(self._clip_durations),
            "transition_seconds": self._read_float(self.transition_var, DEFAULT_TRANSITION_SECONDS),
            "audio_path": self.audio_path_var.get().strip(),
            "audio_fade_out_seconds": self._read_float(self.fade_out_var, DEFAULT_FADE_OUT_SECONDS),
            "clip_name": self.clip_name_var.get().strip() or DEFAULT_CLIP_NAME,
        }

    # ------------------------------------------------------------------
    # State persistence (called by MainWindowV2)
    # ------------------------------------------------------------------

    def get_movie_clips_state(self) -> dict[str, Any]:
        """Return serialisable state for ui_state_store."""
        return {
            "source_mode": self.source_mode_var.get(),
            "last_folder": self._last_folder,
            "source_bundle_kind": (
                self._source_bundle.get("stage") if isinstance(self._source_bundle, dict) else ""
            ),
            "fps": self.fps_var.get(),
            "codec": self.codec_var.get(),
            "quality": self.quality_var.get(),
            "mode": self.mode_var.get(),
            "resolution": self.resolution_var.get(),
            "still_seconds": self._read_float(self.still_seconds_var, DEFAULT_STILL_SECONDS),
            "transition_seconds": self._read_float(self.transition_var, DEFAULT_TRANSITION_SECONDS),
            "audio_fade_out_seconds": self._read_float(self.fade_out_var, DEFAULT_FADE_OUT_SECONDS),
        }

    def set_source_frame_paths(
        self,
        paths: list[str],
        *,
        status_message: str | None = None,
    ) -> None:
        """Accept a list of frame paths from a video-artifact handoff bundle (PR-VIDEO-215).

        Switches to manual source mode and populates the image list so the user
        can immediately build a clip from workflow-video frame outputs.
        """
        resolved = [Path(p) for p in paths if p]
        valid = [p for p in resolved if p.suffix.lower() in _IMAGE_EXTENSIONS]
        if not valid:
            self._set_status(status_message or "No valid frame images in bundle.")
            return
        self._source_bundle = None
        self.source_mode_var.set(SOURCE_MODE_MANUAL)
        self._set_image_list(valid)
        self._set_status(status_message or f"Loaded {len(valid)} frame(s) from video output.")

    def set_source_bundle(
        self,
        bundle: dict[str, Any],
        *,
        status_message: str | None = None,
    ) -> None:
        """Accept a canonical sequence or assembled-video bundle.

        This keeps Movie Clips on the existing controller callback path: the tab
        resolves the bundle into concrete source paths and passes those paths to
        the controller when the user builds the clip.
        """
        source_paths = [Path(item) for item in extract_source_paths_from_bundle(bundle)]
        if not source_paths:
            self._source_bundle = None
            self._set_status(status_message or format_canonical_source_summary(bundle))
            return
        self._source_bundle = dict(bundle)
        self.source_mode_var.set(SOURCE_MODE_MANUAL)
        self._set_image_list(source_paths)
        self._switch_to_slideshow_for_videos()
        self._set_status(status_message or format_canonical_source_summary(bundle))

    def restore_movie_clips_state(self, payload: dict[str, Any] | None) -> bool:
        """Restore persisted state. Returns True if anything was applied."""
        if not isinstance(payload, dict):
            return False
        try:
            mode = payload.get("source_mode", SOURCE_MODE_FOLDER)
            self.source_mode_var.set(mode)
            folder = payload.get("last_folder", "")
            if folder:
                self._last_folder = folder
                self.folder_var.set(folder)
            fps = payload.get("fps", DEFAULT_FPS)
            self.fps_var.set(int(fps))
            codec = payload.get("codec", DEFAULT_CODEC)
            if codec in CODEC_OPTIONS:
                self.codec_var.set(codec)
            quality = payload.get("quality", DEFAULT_QUALITY)
            if quality in QUALITY_OPTIONS:
                self.quality_var.set(quality)
            clip_mode = payload.get("mode", DEFAULT_MODE)
            if clip_mode in ("sequence", "slideshow"):
                self.mode_var.set(clip_mode)
            resolution = payload.get("resolution")
            if isinstance(resolution, str) and resolution.strip():
                self.resolution_var.set(resolution.strip())
            for key, variable in (
                ("still_seconds", self.still_seconds_var),
                ("transition_seconds", self.transition_var),
                ("audio_fade_out_seconds", self.fade_out_var),
            ):
                if isinstance(payload.get(key), (int, float)):
                    variable.set(float(payload[key]))
            return True
        except Exception as exc:
            logger.warning(f"Failed to restore movie clips state: {exc}")
            return False
