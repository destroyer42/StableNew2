"""Output settings panel for GUI V2."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, ttk

from src.config import app_config
from src.gui.theme_v2 import HEADING_LABEL_STYLE, MUTED_LABEL_STYLE
from src.gui.widgets.flow_row_v2 import FlowRow
from src.gui.widgets.responsive_wrap_v2 import bind_wraplength
from src.state.output_routing import OUTPUT_ROUTE_AUTO, OUTPUT_ROUTE_PIPELINE, OUTPUT_ROUTE_TESTING


class OutputSettingsPanelV2(ttk.Frame):
    """Expose output directory/profile, filename pattern, batch size, image format, seed mode.

    When embed_mode=True, widgets are built directly into the master frame
    without creating additional frame structure.
    """

    FORMATS = ("png", "jpg", "webp")
    SEED_MODES = ("fixed", "increment", "random")
    OUTPUT_ROUTES = (OUTPUT_ROUTE_AUTO, OUTPUT_ROUTE_PIPELINE, OUTPUT_ROUTE_TESTING)

    NOTE = (
        "These values are saved into a PromptPack by Apply to PromptPack and are loaded from a pack by Load Pack "
        "Settings. They do not change the jobs in the current Preview. The default output folder for new jobs is "
        "set in Engine Settings."
    )

    def __init__(
        self, master: tk.Misc, *, embed_mode: bool = False, default_output_dir: str | None = None
    ) -> None:
        super().__init__(master, style="Panel.TFrame", padding=0 if embed_mode else 8)
        self._embed_mode = embed_mode
        self._default_output_dir = default_output_dir
        self._build_widgets(self)

    def _build_widgets(self, parent: tk.Misc) -> None:
        """Build all widgets into the specified parent frame."""
        ttk.Label(parent, text="", style=HEADING_LABEL_STYLE).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6)
        )

        # Convert default output dir to absolute path for display
        default_output = self._default_output_dir or app_config.output_dir_default()
        abs_output = os.path.abspath(default_output)

        self.output_dir_var = tk.StringVar(value=abs_output)
        self.filename_pattern_var = tk.StringVar(value=app_config.filename_pattern_default())
        self.image_format_var = tk.StringVar(value=app_config.image_format_default())
        self.batch_size_var = tk.StringVar(value=str(app_config.batch_size_default()))
        self.seed_mode_var = tk.StringVar(value=app_config.seed_mode_default())
        self.output_route_var = tk.StringVar(value=OUTPUT_ROUTE_AUTO)

        # Build output dir row with browse button
        self._build_dir_row(parent, "Output Dir", self.output_dir_var, 1, 0)

        # Format, Batch Size, Seed Mode and Route wrap onto further rows when the column is narrow (GUI-COMPLETE-760);
        # a single packed row left the trailing pairs unmapped, so Seed Mode / Route could not be reached.
        controls_row = FlowRow(parent, gap=16)
        controls_row.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(0, 4))
        self.controls_row = controls_row

        def _pair(label: str) -> ttk.Frame:
            pair = ttk.Frame(controls_row)
            ttk.Label(pair, text=label, style="TLabel").pack(side="left", padx=(0, 4))
            controls_row.add(pair)
            return pair

        format_combo = ttk.Combobox(
            _pair("Format:"),
            textvariable=self.image_format_var,
            values=self.FORMATS,
            state="readonly",
            width=8,
            style="Dark.TCombobox",
        )
        format_combo.pack(side="left")

        batch_spin = ttk.Spinbox(
            _pair("Batch Size:"),
            from_=1,
            to=99,
            increment=1,
            textvariable=self.batch_size_var,
            width=6,
            style="Dark.TSpinbox",
        )
        batch_spin.pack(side="left")
        self._create_tooltip(batch_spin, "Number of images to generate per prompt")

        seed_combo = ttk.Combobox(
            _pair("Seed Mode:"),
            textvariable=self.seed_mode_var,
            values=self.SEED_MODES,
            state="readonly",
            width=10,
            style="Dark.TCombobox",
        )
        seed_combo.pack(side="left")

        route_combo = ttk.Combobox(
            _pair("Route:"),
            textvariable=self.output_route_var,
            values=self.OUTPUT_ROUTES,
            state="readonly",
            width=10,
            style="Dark.TCombobox",
        )
        route_combo.pack(side="left")
        self._create_tooltip(
            route_combo,
            "Auto keeps route-based defaults. Use Testing to isolate debug output in output\\Testing.",
        )

        note = ttk.Label(
            parent, text=self.NOTE, style=MUTED_LABEL_STYLE, wraplength=380, justify="left"
        )
        note.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(2, 0))
        bind_wraplength(note, maximum=420)
        parent.columnconfigure(1, weight=1)

    def _build_dir_row(
        self, parent: tk.Misc, label: str, variable: tk.StringVar, row_idx: int, col_idx: int
    ) -> None:
        """Build a row with entry field and browse button for directory selection."""
        label_widget = ttk.Label(parent, text=label, style="TLabel")
        label_widget.grid(row=row_idx, column=col_idx, sticky="w", padx=(0, 8), pady=(0, 4))

        # Container frame for entry + browse button
        container = ttk.Frame(parent)
        container.grid(row=row_idx, column=col_idx + 1, sticky="ew", pady=(0, 4))
        container.columnconfigure(0, weight=1)

        entry = ttk.Entry(container, textvariable=variable)
        entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        browse_btn = ttk.Button(
            container, text="Browse...", command=self._on_browse_output_dir, style="Dark.TButton"
        )
        browse_btn.grid(row=0, column=1, sticky="e")

    def _on_browse_output_dir(self) -> None:
        """Open folder browser dialog to select output directory."""
        current_dir = self.output_dir_var.get()
        initial_dir = current_dir if current_dir and os.path.isdir(current_dir) else os.getcwd()

        selected = filedialog.askdirectory(
            title="Select Output Directory", initialdir=initial_dir, mustexist=False
        )

        if selected:
            # Convert to absolute path and update variable
            abs_path = os.path.abspath(selected)
            self.output_dir_var.set(abs_path)

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
            "seed_mode": self.seed_mode_var.get().strip(),
            "output_route": self.output_route_var.get().strip() or OUTPUT_ROUTE_AUTO,
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
        seed = overrides.get("seed_mode")
        if seed:
            self.seed_mode_var.set(str(seed))
        route = overrides.get("output_route")
        if route:
            route_name = str(route)
            if route_name in self.OUTPUT_ROUTES:
                self.output_route_var.set(route_name)

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
                pady=3,
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
