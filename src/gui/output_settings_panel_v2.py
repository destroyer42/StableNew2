"""Output settings panel for GUI V2."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.config import app_config
from src.gui.theme_v2 import HEADING_LABEL_STYLE


class OutputSettingsPanelV2(ttk.Frame):
    """Expose output directory/profile, filename pattern, batch size, image format, seed mode.

    When embed_mode=True, widgets are built directly into the master frame
    without creating additional frame structure.
    """

    FORMATS = ("png", "jpg", "webp")
    SEED_MODES = ("fixed", "increment", "random")

    def __init__(self, master: tk.Misc, *, embed_mode: bool = False) -> None:
        super().__init__(master, style="Panel.TFrame", padding=0 if embed_mode else 8)
        self._embed_mode = embed_mode
        self._build_widgets(self)

    def _build_widgets(self, parent: tk.Misc) -> None:
        """Build all widgets into the specified parent frame."""
        ttk.Label(parent, text="", style=HEADING_LABEL_STYLE).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6)
        )
        self.output_dir_var = tk.StringVar(value=app_config.output_dir_default())
        self.filename_pattern_var = tk.StringVar(value=app_config.filename_pattern_default())
        self.image_format_var = tk.StringVar(value=app_config.image_format_default())
        self.batch_size_var = tk.StringVar(value=str(app_config.batch_size_default()))
        self.n_iter_var = tk.StringVar(value=str(app_config.n_iter_default()))
        self.seed_mode_var = tk.StringVar(value=app_config.seed_mode_default())

        self._build_row(
            parent, "Output Dir", ttk.Entry(parent, textvariable=self.output_dir_var), 1, 0
        )
        self._build_row(
            parent, "Filename", ttk.Entry(parent, textvariable=self.filename_pattern_var), 2, 0
        )
        self._build_row(
            parent,
            "Format",
            ttk.Combobox(
                parent,
                textvariable=self.image_format_var,
                values=self.FORMATS,
                state="readonly",
                width=8,
            ),
            3,
            0,
        )
        batch_spin = ttk.Spinbox(
            parent, from_=1, to=99, increment=1, textvariable=self.batch_size_var, width=6
        )
        self._build_row(parent, "Batch Size", batch_spin, 3, 2)
        self._create_tooltip(batch_spin, "Parallel images per generation (rendered simultaneously)")
        
        loops_spin = ttk.Spinbox(
            parent, from_=1, to=20, increment=1, textvariable=self.n_iter_var, width=6
        )
        self._build_row(parent, "Loops", loops_spin, 4, 0)
        self._create_tooltip(loops_spin, "Sequential generation passes (iterations, one after another)")
        
        self._build_row(
            parent,
            "Seed Mode",
            ttk.Combobox(
                parent,
                textvariable=self.seed_mode_var,
                values=self.SEED_MODES,
                state="readonly",
                width=10,
            ),
            4,
            2,
        )

        parent.columnconfigure(1, weight=1)

    def _build_row(
        self, parent: tk.Misc, label: str, widget: tk.Widget, row_idx: int, col_idx: int
    ) -> None:
        label_widget = ttk.Label(parent, text=label, style="TLabel")
        label_widget.grid(row=row_idx, column=col_idx, sticky="w", padx=(0, 8), pady=(0, 4))
        widget.grid(row=row_idx, column=col_idx + 1, sticky="ew", pady=(0, 4))

    def get_output_overrides(self) -> dict[str, object]:
        return {
            "output_dir": self.output_dir_var.get().strip(),
            "filename_pattern": self.filename_pattern_var.get().strip(),
            "image_format": self.image_format_var.get().strip(),
            "batch_size": self._safe_int(
                self.batch_size_var.get(), app_config.batch_size_default()
            ),
            "n_iter": self._safe_int(
                self.n_iter_var.get(), app_config.n_iter_default()
            ),
            "seed_mode": self.seed_mode_var.get().strip(),
        }

    def apply_from_overrides(self, overrides: dict[str, object]) -> None:
        if not overrides:
            return
        self.output_dir_var.set(str(overrides.get("output_dir", self.output_dir_var.get())))
        self.filename_pattern_var.set(
            str(overrides.get("filename_pattern", self.filename_pattern_var.get()))
        )
        fmt = overrides.get("image_format")
        if fmt:
            self.image_format_var.set(str(fmt))
        batch = overrides.get("batch_size")
        if batch is not None:
            try:
                self.batch_size_var.set(str(int(float(str(batch)))))
            except Exception:
                pass
        n_iter = overrides.get("n_iter")
        if n_iter is not None:
            try:
                self.n_iter_var.set(str(int(float(str(n_iter)))))
            except Exception:
                pass
        seed = overrides.get("seed_mode")
        if seed:
            self.seed_mode_var.set(str(seed))

    @staticmethod
    def _safe_int(value: object, default: int) -> int:
        try:
            return int(float(str(value)))
        except Exception:
            return default
    
    def _create_tooltip(self, widget: tk.Widget, text: str) -> None:
        """Create a simple tooltip for a widget."""
        def on_enter(event):
            tooltip = tk.Toplevel()
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{event.x_root + 10}+{event.y_root + 10}")
            label = tk.Label(
                tooltip, 
                text=text, 
                background="#ffffe0", 
                relief="solid", 
                borderwidth=1, 
                padx=5, 
                pady=3
            )
            label.pack()
            widget._tooltip = tooltip
        
        def on_leave(event):
            if hasattr(widget, "_tooltip"):
                widget._tooltip.destroy()
                delattr(widget, "_tooltip")
        
        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)


__all__ = ["OutputSettingsPanelV2"]
