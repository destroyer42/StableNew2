"""Randomizer panel for GUI v2 - Full plan builder UI."""
# Phase 3+/4 GUI extras:
# Not required for Phase 1 stability; used by future adetailer/randomizer/job history workflows only.

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from dataclasses import dataclass
from typing import Any

from . import theme as theme_mod
from src.gui_v2.adapters.randomizer_adapter_v2 import (
    RiskBand,
    build_randomizer_plan,
    compute_variant_stats,
    preview_variants,
)

DEFAULT_MAX_VARIANTS = 512


@dataclass
class MatrixRow:
    """Represents a single matrix dimension row in the UI."""
    key: str
    label_var: tk.StringVar
    value_var: tk.StringVar
    enabled_var: tk.BooleanVar


class RandomizerPanelV2(ttk.Frame):
    """Full-featured Randomizer card for the Pipeline tab with plan builder UI."""

    def __init__(self, master: tk.Misc, *, controller=None, theme=None, **kwargs) -> None:
        style_name = getattr(theme, "SURFACE_FRAME_STYLE", theme_mod.SURFACE_FRAME_STYLE)
        super().__init__(master, style=style_name, padding=theme_mod.PADDING_MD, **kwargs)
        self._controller = controller
        self.controller = controller  # alias for legacy compatibility
        self.theme = theme

        # Header
        header_style = getattr(theme, "STATUS_STRONG_LABEL_STYLE", theme_mod.STATUS_STRONG_LABEL_STYLE)
        header_frame = ttk.Frame(self, style="Dark.TFrame")
        header_frame.pack(fill=tk.X, pady=(0, 4))
        self.header_label = ttk.Label(header_frame, text="Randomizer", style=header_style)
        self.header_label.pack(side=tk.LEFT)
        self._risk_badge_var = tk.StringVar(value="")
        self._risk_badge = ttk.Label(header_frame, textvariable=self._risk_badge_var, style="Dark.TLabel")
        self._risk_badge.pack(side=tk.RIGHT, padx=(8, 0))

        # Body container
        body_style = getattr(theme, "SURFACE_FRAME_STYLE", theme_mod.SURFACE_FRAME_STYLE)
        self.body = ttk.Frame(self, style=body_style)
        self.body.pack(fill=tk.BOTH, expand=True)

        # Core control variables
        self.randomization_enabled_var = tk.BooleanVar(value=False)
        self.variant_mode_var = tk.StringVar(value="fanout")
        self.fanout_var = tk.StringVar(value="1")
        self.max_variants_var = tk.IntVar(value=8)

        # Seed control variables
        self.seed_mode_var = tk.StringVar(value="none")  # "none", "fixed", "per_variant"
        self.base_seed_var = tk.StringVar(value="")  # empty -> None

        # Stats display variables
        self.variant_count_var = tk.StringVar(value="Variants: 0")
        self.variant_explainer_var = tk.StringVar(value="Randomizer is OFF. Enable to see variant count.")
        self._variant_count = 0
        self._change_callback = None
        self._risk_threshold = 128

        # Matrix state
        self._rows: list[MatrixRow] = []
        self.matrix_vars: dict[str, tk.StringVar] = {}

        # UI widget references
        self._mode_combobox: ttk.Combobox | None = None
        self._fanout_spinbox: ttk.Spinbox | None = None
        self._max_variants_spinbox: ttk.Spinbox | None = None
        self._seed_mode_combobox: ttk.Combobox | None = None
        self._base_seed_entry: ttk.Entry | None = None
        self._matrix_frame: ttk.Frame | None = None
        self._preview_frame: ttk.LabelFrame | None = None
        self._preview_list: ttk.Treeview | None = None

        self._build_controls()

    def _build_controls(self) -> None:
        """Build all UI controls for the randomizer card."""
        # === Row 0: Enable toggle ===
        enable_frame = ttk.Frame(self.body, style="Dark.TFrame")
        enable_frame.grid(row=0, column=0, columnspan=4, sticky=tk.W, pady=(0, 6))

        enable_cb = ttk.Checkbutton(
            enable_frame,
            text="Enable randomization",
            variable=self.randomization_enabled_var,
            command=self._on_randomizer_toggle,
            style="Dark.TCheckbutton",
        )
        enable_cb.pack(side=tk.LEFT)

        # === Row 1: Mode, Fanout, Max Variants ===
        controls_frame = ttk.Frame(self.body, style="Dark.TFrame")
        controls_frame.grid(row=1, column=0, columnspan=4, sticky=tk.EW, pady=(0, 6))

        # Variant mode
        ttk.Label(controls_frame, text="Mode:", style="Dark.TLabel").pack(side=tk.LEFT)
        self._mode_combobox = ttk.Combobox(
            controls_frame,
            textvariable=self.variant_mode_var,
            state="readonly",
            values=["fanout", "rotate", "sequential", "random"],
            width=10,
        )
        self._mode_combobox.pack(side=tk.LEFT, padx=(4, 12))
        self._mode_combobox.set("fanout")
        self.variant_mode_var.trace_add("write", self._handle_var_change)

        # Fanout per variant
        ttk.Label(controls_frame, text="Fanout:", style="Dark.TLabel").pack(side=tk.LEFT)
        self._fanout_spinbox = ttk.Spinbox(
            controls_frame,
            from_=1,
            to=99,
            textvariable=self.fanout_var,
            width=4,
            command=self._on_fanout_change,
        )
        self._fanout_spinbox.pack(side=tk.LEFT, padx=(4, 12))
        self.fanout_var.trace_add("write", self._handle_var_change)

        # Max variants
        ttk.Label(controls_frame, text="Max variants:", style="Dark.TLabel").pack(side=tk.LEFT)
        self._max_variants_spinbox = ttk.Spinbox(
            controls_frame,
            from_=1,
            to=DEFAULT_MAX_VARIANTS,
            textvariable=self.max_variants_var,
            width=5,
            command=self._on_max_variants_change,
        )
        self._max_variants_spinbox.pack(side=tk.LEFT, padx=(4, 0))
        self._max_variants_spinbox.bind("<FocusOut>", lambda _e: self._on_max_variants_change())
        self.max_variants_var.trace_add("write", self._handle_var_change)

        # === Row 1.5: Seed controls ===
        seed_frame = ttk.Frame(self.body, style="Dark.TFrame")
        seed_frame.grid(row=2, column=0, columnspan=4, sticky=tk.EW, pady=(0, 6))

        # Seed mode
        ttk.Label(seed_frame, text="Seed mode:", style="Dark.TLabel").pack(side=tk.LEFT)
        self._seed_mode_combobox = ttk.Combobox(
            seed_frame,
            textvariable=self.seed_mode_var,
            state="readonly",
            values=["none", "fixed", "per_variant"],
            width=10,
        )
        self._seed_mode_combobox.pack(side=tk.LEFT, padx=(4, 12))
        self._seed_mode_combobox.set("none")
        self.seed_mode_var.trace_add("write", self._on_seed_settings_changed)

        # Base seed
        ttk.Label(seed_frame, text="Base seed:", style="Dark.TLabel").pack(side=tk.LEFT)
        self._base_seed_entry = ttk.Entry(
            seed_frame,
            textvariable=self.base_seed_var,
            width=10,
        )
        self._base_seed_entry.pack(side=tk.LEFT, padx=(4, 0))
        self._base_seed_entry.bind("<FocusOut>", lambda _e: self._on_seed_settings_changed())
        self.base_seed_var.trace_add("write", self._on_seed_settings_changed)

        # === Row 3: Stats display ===
        stats_frame = ttk.Frame(self.body, style="Dark.TFrame")
        stats_frame.grid(row=3, column=0, columnspan=4, sticky=tk.EW, pady=(0, 6))

        ttk.Label(stats_frame, textvariable=self.variant_count_var, style="Dark.TLabel").pack(side=tk.LEFT)
        ttk.Label(stats_frame, textvariable=self.variant_explainer_var, style="Dark.TLabel").pack(
            side=tk.LEFT, padx=(12, 0)
        )

        # === Row 4: Matrix rows container ===
        matrix_label = ttk.Label(self.body, text="Matrix Dimensions:", style="Dark.TLabel")
        matrix_label.grid(row=4, column=0, columnspan=4, sticky=tk.W, pady=(4, 2))

        self._matrix_frame = ttk.Frame(self.body, style="Dark.TFrame")
        self._matrix_frame.grid(row=5, column=0, columnspan=4, sticky=tk.EW, pady=(0, 4))
        self._matrix_frame.columnconfigure(2, weight=1)

        # === Row 6: Add row button ===
        btn_frame = ttk.Frame(self.body, style="Dark.TFrame")
        btn_frame.grid(row=6, column=0, columnspan=4, sticky=tk.W, pady=(0, 6))
        add_btn = ttk.Button(btn_frame, text="+ Add dimension", command=lambda: self._add_matrix_row())
        add_btn.pack(side=tk.LEFT)

        # === Row 7: Preview area ===
        self._preview_frame = ttk.LabelFrame(
            self.body,
            text="Variant Preview",
            padding=4,
            style="Dark.TLabelframe",
        )
        self._preview_frame.grid(row=7, column=0, columnspan=4, sticky=tk.EW, pady=(4, 0))

        self._preview_list = ttk.Treeview(
            self._preview_frame,
            columns=("idx", "summary"),
            show="headings",
            height=5,
        )
        self._preview_list.heading("idx", text="#")
        self._preview_list.heading("summary", text="Configuration")
        self._preview_list.column("idx", width=30, anchor=tk.W)
        self._preview_list.column("summary", width=450, anchor=tk.W)
        self._preview_list.pack(fill=tk.BOTH, expand=True)

        self.body.columnconfigure(0, weight=0)
        self.body.columnconfigure(1, weight=0)
        self.body.columnconfigure(2, weight=1)
        self.body.columnconfigure(3, weight=0)

        # Seed default matrix rows
        self._add_matrix_row(label="Model matrix entries", key="model")
        self._add_matrix_row(label="Hypernetworks (name[:strength])", key="hypernetwork")

        # Initial state update
        self._update_controls_state()
        self._refresh_plan_and_stats()

    # =========================================================================
    # Matrix Row Management
    # =========================================================================

    def _add_matrix_row(
        self, label: str = "", values: str = "", enabled: bool = True, key: str | None = None
    ) -> None:
        """Add a new matrix dimension row."""
        if self._matrix_frame is None:
            return
        label_var = tk.StringVar(value=label)
        value_var = tk.StringVar(value=values)
        enabled_var = tk.BooleanVar(value=enabled)
        row_key = key or f"custom_{len(self._rows)}"
        row = MatrixRow(row_key, label_var, value_var, enabled_var)
        self._rows.append(row)
        if key:
            self.matrix_vars[key] = value_var
        self._rebuild_matrix_ui_from_model()

    def _clone_matrix_row(self, index: int) -> None:
        """Clone a matrix row at the given index."""
        if index < 0 or index >= len(self._rows):
            return
        src = self._rows[index]
        self._add_matrix_row(
            label=src.label_var.get(),
            values=src.value_var.get(),
            enabled=src.enabled_var.get(),
            key=None,
        )

    def _delete_matrix_row(self, index: int) -> None:
        """Delete a matrix row at the given index."""
        if index < 0 or index >= len(self._rows):
            return
        self._rows.pop(index)
        self._rebuild_matrix_ui_from_model()

    def _rebuild_matrix_ui_from_model(self) -> None:
        """Rebuild matrix UI from internal row model."""
        if self._matrix_frame is None:
            return
        for child in list(self._matrix_frame.winfo_children()):
            child.destroy()

        for idx, row in enumerate(self._rows):
            # Enabled checkbox
            enabled_cb = ttk.Checkbutton(
                self._matrix_frame,
                variable=row.enabled_var,
                command=self._handle_var_change,
                style="Dark.TCheckbutton",
            )
            enabled_cb.grid(row=idx, column=0, padx=(0, 4), sticky=tk.W)

            # Label entry
            label_entry = ttk.Entry(self._matrix_frame, textvariable=row.label_var, width=22)
            label_entry.grid(row=idx, column=1, padx=(0, 4), sticky=tk.EW)

            # Values entry
            value_entry = ttk.Entry(self._matrix_frame, textvariable=row.value_var, width=40)
            value_entry.grid(row=idx, column=2, padx=(0, 4), sticky=tk.EW)

            # Clone button
            clone_btn = ttk.Button(
                self._matrix_frame,
                text="Clone",
                width=6,
                command=lambda i=idx: self._clone_matrix_row(i),
            )
            clone_btn.grid(row=idx, column=3, padx=(0, 2))

            # Delete button
            del_btn = ttk.Button(
                self._matrix_frame,
                text="Del",
                width=4,
                command=lambda i=idx: self._delete_matrix_row(i),
            )
            del_btn.grid(row=idx, column=4, padx=(0, 0))

            # Attach change traces
            row.value_var.trace_add("write", self._handle_var_change)
            row.label_var.trace_add("write", self._handle_var_change)

    # =========================================================================
    # Control State Management
    # =========================================================================

    def _update_controls_state(self) -> None:
        """Enable/disable controls based on randomization_enabled state."""
        enabled = self.randomization_enabled_var.get()
        state = "normal" if enabled else "disabled"

        if self._mode_combobox:
            self._mode_combobox.configure(state="readonly" if enabled else "disabled")
        if self._fanout_spinbox:
            self._fanout_spinbox.configure(state=state)
        if self._max_variants_spinbox:
            self._max_variants_spinbox.configure(state=state)
        if self._seed_mode_combobox:
            self._seed_mode_combobox.configure(state="readonly" if enabled else "disabled")
        if self._base_seed_entry:
            self._base_seed_entry.configure(state=state)

    # =========================================================================
    # Event Handlers
    # =========================================================================

    def _on_randomizer_toggle(self) -> None:
        """Handle randomization enable/disable toggle."""
        enabled = bool(self.randomization_enabled_var.get())
        self._update_controls_state()

        if self._controller and hasattr(self._controller, "on_randomization_toggled"):
            try:
                self._controller.on_randomization_toggled(enabled)
            except Exception:
                pass

        self._refresh_plan_and_stats()

        if self._change_callback:
            try:
                self._change_callback()
            except Exception:
                pass

    def _on_max_variants_change(self, *_args: object) -> None:
        """Handle max variants spinbox change."""
        value = self._parse_positive_int(self.max_variants_var.get(), default=8)
        value = max(1, min(value, DEFAULT_MAX_VARIANTS))
        self.max_variants_var.set(value)

        if self._controller and hasattr(self._controller, "on_randomizer_max_variants_changed"):
            try:
                self._controller.on_randomizer_max_variants_changed(value)
            except Exception:
                pass

        self._refresh_plan_and_stats()

    def _on_fanout_change(self, *_args: object) -> None:
        """Handle fanout spinbox change."""
        value = self._parse_positive_int(self.fanout_var.get(), default=1)
        value = max(1, min(value, 99))
        self.fanout_var.set(str(value))
        self._refresh_plan_and_stats()

    def _on_seed_settings_changed(self, *_args: object) -> None:
        """Handle seed mode or base seed change."""
        mode = (self.seed_mode_var.get() or "none").lower()
        if mode in ("fixed", "per_variant"):
            # Normalize base_seed to a positive integer if possible
            raw = (self.base_seed_var.get() or "").strip()
            if raw:
                seed = self._parse_seed_value(raw)
                if seed is not None:
                    self.base_seed_var.set(str(seed))
                else:
                    # Keep empty if invalid
                    self.base_seed_var.set("")
        self._refresh_plan_and_stats()
        if self._change_callback:
            try:
                self._change_callback()
            except Exception:
                pass

    def _handle_var_change(self, *_args: object) -> None:
        """Generic handler for any control variable change."""
        self._refresh_plan_and_stats()
        if self._change_callback:
            try:
                self._change_callback()
            except Exception:
                pass

    # =========================================================================
    # Plan Building & Stats
    # =========================================================================

    def _refresh_plan_and_stats(self) -> None:
        """Refresh variant stats and preview using the adapter."""
        enabled = self.randomization_enabled_var.get()

        if not enabled:
            self.variant_count_var.set("Variants: 0")
            self.variant_explainer_var.set("Randomizer is OFF. Enable to see variant count.")
            self._risk_badge_var.set("")
            self._clear_preview()
            self._variant_count = 0
            return

        base_config = self._current_randomizer_base_config()
        options = self.get_randomizer_config()

        stats = compute_variant_stats(base_config, options, threshold=self._risk_threshold)
        total = stats.get("total_variants", 0)
        matrix_combos = stats.get("matrix_combos", 0)
        fanout = stats.get("fanout", 1)
        risk_band = stats.get("risk_band", RiskBand.LOW)
        max_variants = options.get("max_variants", DEFAULT_MAX_VARIANTS)

        effective = min(total, max_variants)
        self._variant_count = effective

        # Update stats display
        self.variant_count_var.set(f"Variants: {effective}")
        # Build explainer with seed info
        seed_mode = stats.get("seed_mode", "none")
        base_seed = stats.get("base_seed")
        seed_text = self._format_seed_text(seed_mode, base_seed)
        self.variant_explainer_var.set(f"{matrix_combos} combos × fanout {fanout} | {seed_text}")

        # Update risk badge
        if risk_band == RiskBand.HIGH:
            self._risk_badge_var.set("Risk: High")
        elif risk_band == RiskBand.MEDIUM:
            self._risk_badge_var.set("Risk: Medium")
        else:
            self._risk_badge_var.set("Risk: Low")

        # Update preview
        self._refresh_preview(base_config, options)

    def _refresh_preview(self, base_config: dict, options: dict) -> None:
        """Refresh the variant preview list."""
        if self._preview_list is None:
            return

        self._clear_preview()

        previews = preview_variants(base_config, options, limit=8)
        for idx, cfg in enumerate(previews):
            summary = self._format_variant_summary(cfg)
            self._preview_list.insert("", "end", values=(idx + 1, summary))

    def _clear_preview(self) -> None:
        """Clear all items from the preview list."""
        if self._preview_list is None:
            return
        for item in self._preview_list.get_children():
            self._preview_list.delete(item)

    def _format_variant_summary(self, cfg: dict) -> str:
        """Format a variant config as a short summary string."""
        parts: list[str] = []

        # Check for model in various locations
        model = (
            cfg.get("txt2img", {}).get("model")
            or cfg.get("pipeline", {}).get("model")
            or cfg.get("model")
        )
        if model:
            parts.append(f"model={model}")

        # Check for sampler
        sampler = (
            cfg.get("txt2img", {}).get("sampler_name")
            or cfg.get("pipeline", {}).get("sampler")
        )
        if sampler:
            parts.append(f"sampler={sampler}")

        # Check for hypernetwork
        hyper = cfg.get("pipeline", {}).get("hypernetwork") or cfg.get("hypernetwork")
        if isinstance(hyper, dict):
            hyper_name = hyper.get("name")
            if hyper_name:
                parts.append(f"hypernet={hyper_name}")
        elif hyper:
            parts.append(f"hypernet={hyper}")

        # Check for variant mode
        mode = cfg.get("pipeline", {}).get("variant_mode")
        if mode and not parts:
            parts.append(f"mode={mode}")

        return ", ".join(parts) if parts else "(base config)"

    def _current_randomizer_base_config(self) -> dict:
        """Get the current base config from the controller if available."""
        try:
            if self._controller and hasattr(self._controller, "get_current_config"):
                return self._controller.get_current_config() or {}
            if self._controller and hasattr(self._controller, "current_config"):
                return self._controller.current_config or {}
        except Exception:
            pass
        return {}

    # =========================================================================
    # Config Interface
    # =========================================================================

    def get_randomizer_config(self) -> dict[str, Any]:
        """Return the full randomizer configuration for controller/pipeline use."""
        enabled = bool(self.randomization_enabled_var.get())
        max_variants = self._parse_positive_int(self.max_variants_var.get(), default=8)
        max_variants = max(1, min(max_variants, DEFAULT_MAX_VARIANTS))
        mode = (self.variant_mode_var.get() or "fanout").strip().lower()
        fanout = self._parse_positive_int(self.fanout_var.get(), default=1)

        # Parse seed settings
        seed_mode = (self.seed_mode_var.get() or "none").strip().lower()
        if seed_mode not in ("none", "fixed", "per_variant"):
            seed_mode = "none"
        raw_seed = (self.base_seed_var.get() or "").strip()
        base_seed: int | None = self._parse_seed_value(raw_seed)

        config: dict[str, Any] = {
            "randomization_enabled": enabled,
            "max_variants": max_variants,
            "variant_mode": mode,
            "variant_fanout": fanout,
            "seed_mode": seed_mode,
            "base_seed": base_seed,
        }

        # Build matrix payload
        matrix_payload = self._build_matrix_payload()
        if matrix_payload:
            config["matrix"] = matrix_payload

        # Extract model_matrix and hypernetworks for legacy compatibility
        model_entries = self._get_model_matrix_entries()
        if model_entries:
            config["model_matrix"] = model_entries

        hyper_entries = self._get_hypernetwork_entries()
        if hyper_entries:
            config["hypernetworks"] = hyper_entries

        return config

    def get_randomizer_options(self) -> dict[str, Any]:
        """Alias for get_randomizer_config for legacy compatibility."""
        return self.get_randomizer_config()

    def _build_matrix_payload(self) -> dict[str, Any]:
        """Build the matrix payload from all enabled rows."""
        payload: dict[str, Any] = {}
        for row in self._rows:
            if not row.enabled_var.get():
                continue
            label = row.label_var.get().strip().lower()
            key = row.key

            if key == "model":
                entries = self._parse_simple_entries(row.value_var.get())
                if entries:
                    payload["model"] = entries
            elif key == "hypernetwork":
                entries = self._parse_hyper_entries(row.value_var.get())
                if entries:
                    payload["hypernetwork"] = entries
            else:
                entries = self._parse_simple_entries(row.value_var.get())
                if entries:
                    payload[label or key] = entries

        return payload

    def _get_model_matrix_entries(self) -> list[str]:
        """Get model matrix entries from the model row."""
        for row in self._rows:
            if row.key == "model" and row.enabled_var.get():
                return self._parse_simple_entries(row.value_var.get())
        return []

    def _get_hypernetwork_entries(self) -> list[dict]:
        """Get hypernetwork entries from the hypernetwork row."""
        for row in self._rows:
            if row.key == "hypernetwork" and row.enabled_var.get():
                return self._parse_hyper_entries(row.value_var.get())
        return []

    def load_from_config(self, config: dict | None) -> None:
        """Load panel state from a configuration dict."""
        if not config:
            return

        # Load top-level randomizer settings
        enabled = bool(config.get("randomization_enabled", False))
        self.randomization_enabled_var.set(enabled)

        max_variants = self._parse_positive_int(config.get("max_variants"), default=8)
        self.max_variants_var.set(max(1, min(max_variants, DEFAULT_MAX_VARIANTS)))

        # Load from pipeline section
        pipeline_cfg = config.get("pipeline") or {}
        mode = pipeline_cfg.get("variant_mode", "fanout") or "fanout"
        self.variant_mode_var.set(str(mode).lower())

        fanout = self._parse_positive_int(pipeline_cfg.get("variant_fanout"), default=1)
        self.fanout_var.set(str(fanout))

        # Load model matrix
        model_values = pipeline_cfg.get("model_matrix") or config.get("model_matrix") or []
        if self._rows and len(self._rows) > 0:
            self._rows[0].value_var.set(", ".join(str(entry) for entry in model_values if entry))

        # Load hypernetworks
        hyper_entries = pipeline_cfg.get("hypernetworks") or config.get("hypernetworks") or []
        hyper_texts: list[str] = []
        for entry in hyper_entries:
            if isinstance(entry, dict):
                name = entry.get("name")
                strength = entry.get("strength")
            else:
                name = entry
                strength = None
            if not name:
                continue
            name_text = str(name).strip()
            if not name_text:
                continue
            if strength is None or strength == "":
                hyper_texts.append(name_text)
            else:
                hyper_texts.append(f"{name_text}:{strength}")
        if len(self._rows) > 1:
            self._rows[1].value_var.set(", ".join(hyper_texts))

        # Load seed settings
        seed_mode = config.get("seed_mode", "none") or "none"
        if seed_mode not in ("none", "fixed", "per_variant"):
            seed_mode = "none"
        self.seed_mode_var.set(seed_mode)

        base_seed = config.get("base_seed")
        if base_seed is not None:
            self.base_seed_var.set(str(base_seed))
        else:
            self.base_seed_var.set("")

        # Update UI state
        self._update_controls_state()
        self._refresh_plan_and_stats()

    def build_variant_plan(self, base_config: dict | None):
        """Build and return a variant plan result."""
        return build_randomizer_plan(base_config, self.get_randomizer_config())

    def set_change_callback(self, callback) -> None:
        """Set the callback to be called on any control change."""
        self._change_callback = callback

    def update_variant_count(self, count: int) -> None:
        """Update the displayed variant count (legacy interface)."""
        safe_count = max(0, int(count)) if isinstance(count, int) else 0
        if safe_count != self._variant_count:
            self._variant_count = safe_count
        self._refresh_plan_and_stats()

    def get_variant_count(self) -> int:
        """Get the current effective variant count."""
        return self._variant_count

    # =========================================================================
    # Utility Methods
    # =========================================================================

    @staticmethod
    def _parse_positive_int(value: Any, default: int = 1) -> int:
        """Parse a value as a positive integer, returning default if invalid."""
        try:
            parsed = int(value)
            return parsed if parsed > 0 else default
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_seed_value(raw: str) -> int | None:
        """Parse a seed value string, returning None if invalid or empty."""
        if not raw:
            return None
        raw = raw.strip()
        if not raw:
            return None
        try:
            value = int(raw)
            return value if value >= 0 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_seed_text(seed_mode: str, base_seed: int | None) -> str:
        """Format seed settings as a short display string."""
        if seed_mode == "none" or not seed_mode:
            return "Seed: none"
        elif seed_mode == "fixed":
            if base_seed is not None:
                return f"Seed: fixed @ {base_seed}"
            return "Seed: fixed"
        elif seed_mode == "per_variant":
            if base_seed is not None:
                return f"Seed: per_variant from {base_seed}"
            return "Seed: per_variant"
        return "Seed: none"

    @staticmethod
    def _parse_simple_entries(text: str) -> list[str]:
        """Parse comma-separated text into a list of trimmed entries."""
        if not text:
            return []
        parts = [segment.strip() for segment in text.replace("\n", ",").split(",")]
        return [part for part in parts if part]

    @staticmethod
    def _parse_hyper_entries(text: str) -> list[dict]:
        """Parse hypernetwork entries in 'name[:strength]' format."""
        if not text:
            return []
        entries: list[dict] = []
        for raw_entry in text.replace("\n", ",").split(","):
            cleaned = raw_entry.strip()
            if not cleaned:
                continue
            if ":" in cleaned:
                name, strength_text = cleaned.split(":", 1)
            else:
                name, strength_text = cleaned, ""
            name = name.strip()
            if not name:
                continue
            strength_value = None
            if strength_text.strip():
                try:
                    strength_value = float(strength_text.strip())
                except (TypeError, ValueError):
                    strength_value = None
            entries.append({"name": name, "strength": strength_value})
        return entries
