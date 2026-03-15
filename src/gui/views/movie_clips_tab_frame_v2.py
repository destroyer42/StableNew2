"""Movie Clips tab frame for StableNew v2.6.

PR-GUI-VIDEO-001: Tab shell, source selection, ordered image list,
clip settings, and UI-state persistence.
"""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any

from src.gui.ui_tokens import TOKENS
from src.gui.view_contracts.movie_clips_contract import (
    DEFAULT_CODEC,
    DEFAULT_FPS,
    DEFAULT_MODE,
    DEFAULT_QUALITY,
    CODEC_OPTIONS,
    MODE_OPTIONS,
    QUALITY_OPTIONS,
    SOURCE_MODE_FOLDER,
    SOURCE_MODE_MANUAL,
    build_clip_settings_summary,
    format_image_list_summary,
    format_source_mode_label,
    sort_image_names,
)

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
        self._build_status: str = ""

        # Tk variables
        self.source_mode_var = tk.StringVar(value=SOURCE_MODE_FOLDER)
        self.folder_var = tk.StringVar()
        self.fps_var = tk.IntVar(value=DEFAULT_FPS)
        self.codec_var = tk.StringVar(value=DEFAULT_CODEC)
        self.quality_var = tk.StringVar(value=DEFAULT_QUALITY)
        self.mode_var = tk.StringVar(value=DEFAULT_MODE)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_header()
        self._build_body()

        # Trace source mode toggle
        self.source_mode_var.trace_add("write", lambda *_: self._on_source_mode_changed())

    # ------------------------------------------------------------------
    # Layout construction
    # ------------------------------------------------------------------

    def _build_header(self) -> None:
        header = ttk.Frame(self, style="Panel.TFrame", padding=8)
        header.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 4))
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
            text="Browse…",
            style="Dark.TButton",
            command=self._on_browse_folder,
        )
        self.browse_btn.grid(row=0, column=4, sticky="w", padx=(0, 6))

        self.load_btn = ttk.Button(
            header,
            text="Load Images",
            style="Dark.TButton",
            command=self._on_load_images,
        )
        self.load_btn.grid(row=0, column=5, sticky="w")

        self.status_label = ttk.Label(
            header,
            text="",
            style="Dark.TLabel",
        )
        self.status_label.grid(row=0, column=6, sticky="e", padx=(8, 0))

    def _build_body(self) -> None:
        body = ttk.Frame(self, style="Panel.TFrame")
        body.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=0)
        body.rowconfigure(0, weight=1)

        # Left: ordered image list
        list_frame = ttk.LabelFrame(
            body,
            text="Selected Images (ordered)",
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
        self.image_list.grid(row=0, column=0, sticky="nsew")
        _sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.image_list.yview)
        _sb.grid(row=0, column=1, sticky="ns")
        self.image_list.configure(yscrollcommand=_sb.set)

        # List action buttons
        btn_row = ttk.Frame(list_frame, style="Panel.TFrame")
        btn_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        self.add_images_btn = ttk.Button(
            btn_row,
            text="Add Images…",
            style="Dark.TButton",
            command=self._on_add_images,
        )
        self.add_images_btn.pack(side="left", padx=(0, 6))

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

        self.list_summary_label = ttk.Label(
            btn_row,
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
        settings_frame.columnconfigure(1, weight=1)

        _lbl_cfg = {"style": "Dark.TLabel", "anchor": "w"}

        ttk.Label(settings_frame, text="FPS", **_lbl_cfg).grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 6)
        )
        ttk.Spinbox(
            settings_frame,
            from_=1,
            to=120,
            increment=1,
            textvariable=self.fps_var,
            width=6,
            style="Dark.TSpinbox",
        ).grid(row=0, column=1, sticky="ew", pady=(0, 6))

        ttk.Label(settings_frame, text="Codec", **_lbl_cfg).grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=(0, 6)
        )
        ttk.Combobox(
            settings_frame,
            textvariable=self.codec_var,
            values=CODEC_OPTIONS,
            state="readonly",
            style="Dark.TCombobox",
            width=14,
        ).grid(row=1, column=1, sticky="ew", pady=(0, 6))

        ttk.Label(settings_frame, text="Quality", **_lbl_cfg).grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=(0, 6)
        )
        ttk.Combobox(
            settings_frame,
            textvariable=self.quality_var,
            values=QUALITY_OPTIONS,
            state="readonly",
            style="Dark.TCombobox",
            width=14,
        ).grid(row=2, column=1, sticky="ew", pady=(0, 6))

        ttk.Label(settings_frame, text="Mode", **_lbl_cfg).grid(
            row=3, column=0, sticky="w", padx=(0, 8), pady=(0, 12)
        )
        ttk.Combobox(
            settings_frame,
            textvariable=self.mode_var,
            values=MODE_OPTIONS,
            state="readonly",
            style="Dark.TCombobox",
            width=14,
        ).grid(row=3, column=1, sticky="ew", pady=(0, 12))

        ttk.Separator(settings_frame, orient="horizontal").grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=(0, 10)
        )

        self.build_btn = ttk.Button(
            settings_frame,
            text="Build Clip",
            style="Primary.TButton",
            command=self._on_build_clip,
        )
        self.build_btn.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        self.build_status_label = ttk.Label(
            settings_frame,
            text="",
            style="Dark.TLabel",
            wraplength=160,
            justify="center",
        )
        self.build_status_label.grid(row=6, column=0, columnspan=2, sticky="ew")

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
        images = sorted(
            [p for p in folder.iterdir() if p.suffix.lower() in _IMAGE_EXTENSIONS],
            key=lambda p: p.name,
        )
        if not images:
            self._set_status("No images found in folder.")
            return
        self._set_image_list(images)
        self._set_status(f"Loaded {len(images)} images from folder.")

    def _on_add_images(self) -> None:
        files = filedialog.askopenfilenames(
            title="Select Images",
            filetypes=[
                ("Image Files", "*.png *.jpg *.jpeg *.webp *.bmp *.tiff *.tif"),
                ("All Files", "*.*"),
            ],
        )
        if not files:
            return
        new_paths = [Path(f) for f in files if Path(f).suffix.lower() in _IMAGE_EXTENSIONS]
        # Merge keeping deterministic order, dedupe by resolved path
        existing_resolved = {p.resolve() for p in self._image_paths}
        added = [p for p in new_paths if p.resolve() not in existing_resolved]
        if added:
            self._set_image_list(
                sorted(self._image_paths + added, key=lambda p: p.name)
            )
            self._set_status(f"Added {len(added)} image(s).")
        else:
            self._set_status("No new images added.")

    def _on_remove_selected(self) -> None:
        selected = list(self.image_list.curselection())
        if not selected:
            return
        selected_set = set(selected)
        self._image_paths = [
            p for i, p in enumerate(self._image_paths) if i not in selected_set
        ]
        self._refresh_list_widget()
        self._update_summary()

    def _on_clear_all(self) -> None:
        self._image_paths = []
        self._refresh_list_widget()
        self._update_summary()
        self._set_status("")

    def _on_build_clip(self) -> None:
        """Delegate clip build to controller (wired in PR-VIDEO-002)."""
        controller = self.app_controller
        handler = getattr(controller, "on_build_movie_clip", None)
        if not callable(handler):
            self._set_build_status("Controller not connected.")
            return
        if not self._image_paths:
            self._set_build_status("No images selected.")
            return
        settings = self._collect_settings()
        self._set_build_status("Building…")
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

    def _on_build_complete(self, output_path: str) -> None:
        self._set_build_status(f"Done: {Path(output_path).name}")

    def _on_build_error(self, reason: str) -> None:
        self._set_build_status(f"Error: {reason}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_image_list(self, paths: list[Path]) -> None:
        self._image_paths = paths
        self._refresh_list_widget()
        self._update_summary()

    def _refresh_list_widget(self) -> None:
        try:
            self.image_list.delete(0, tk.END)
            for p in self._image_paths:
                self.image_list.insert(tk.END, p.name)
        except Exception:
            pass

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

    def _set_build_status(self, msg: str) -> None:
        self._build_status = msg
        try:
            self.build_status_label.configure(text=msg)
        except Exception:
            pass

    def _collect_settings(self) -> dict[str, Any]:
        return {
            "fps": self.fps_var.get(),
            "codec": self.codec_var.get(),
            "quality": self.quality_var.get(),
            "mode": self.mode_var.get(),
        }

    # ------------------------------------------------------------------
    # State persistence (called by MainWindowV2)
    # ------------------------------------------------------------------

    def get_movie_clips_state(self) -> dict[str, Any]:
        """Return serialisable state for ui_state_store."""
        return {
            "source_mode": self.source_mode_var.get(),
            "last_folder": self._last_folder,
            "fps": self.fps_var.get(),
            "codec": self.codec_var.get(),
            "quality": self.quality_var.get(),
            "mode": self.mode_var.get(),
        }

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
            return True
        except Exception as exc:
            logger.warning(f"Failed to restore movie clips state: {exc}")
            return False
