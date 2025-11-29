"""Randomizer panel scaffold for GUI v2."""
# Phase 3+/4 GUI extras:
# Not required for Phase 1 stability; used by future adetailer/randomizer/job history workflows only.

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from dataclasses import dataclass

from . import theme as theme_mod
from src.gui_v2.adapters.randomizer_adapter_v2 import (
    RiskBand,
    build_randomizer_plan,
    compute_variant_stats,
    preview_variants,
)


@dataclass
class MatrixRow:
    key: str
    label_var: tk.StringVar
    value_var: tk.StringVar
    enabled_var: tk.BooleanVar


class RandomizerPanelV2(ttk.Frame):
    """Container for randomization controls (structure only)."""

    def __init__(self, master: tk.Misc, *, controller=None, theme=None, **kwargs) -> None:
        style_name = getattr(theme, "SURFACE_FRAME_STYLE", theme_mod.SURFACE_FRAME_STYLE)
        super().__init__(master, style=style_name, padding=theme_mod.PADDING_MD, **kwargs)
        self.controller = controller
        self.theme = theme

        header_style = getattr(theme, "STATUS_STRONG_LABEL_STYLE", theme_mod.STATUS_STRONG_LABEL_STYLE)
        self.header_label = ttk.Label(self, text="Randomizer", style=header_style)
        self.header_label.pack(anchor=tk.W, pady=(0, 4))

        body_style = getattr(theme, "SURFACE_FRAME_STYLE", theme_mod.SURFACE_FRAME_STYLE)
        self.body = ttk.Frame(self, style=body_style)
        self.body.pack(fill=tk.BOTH, expand=True)

        self.variant_mode_var = tk.StringVar(value="fanout")
        self.fanout_var = tk.StringVar(value="1")
        self.variant_count_var = tk.StringVar(value="Total variants: 1")
        self.variant_explainer_var = tk.StringVar(value="")
        self._variant_count = 1
        self._change_callback = None
        self._rows: list[MatrixRow] = []
        self._risk_threshold = 128
        self.matrix_vars: dict[str, tk.StringVar] = {}

        self._matrix_frame = None
        self._preview_frame = None
        self._preview_list: ttk.Treeview | None = None

        self._build_controls()

    def _build_controls(self) -> None:
        ttk.Label(self.body, text="Variant mode", style="Dark.TLabel").grid(
            row=0, column=0, sticky=tk.W, pady=2
        )
        mode_box = ttk.Combobox(
            self.body,
            textvariable=self.variant_mode_var,
            state="readonly",
            values=("off", "fanout", "rotate"),
            width=14,
        )
        mode_box.grid(row=0, column=1, sticky=tk.W, pady=2)
        mode_box.set("fanout")
        self.variant_mode_var.trace_add("write", self._handle_var_change)

        ttk.Label(self.body, text="Fanout per variant", style="Dark.TLabel").grid(
            row=1, column=0, sticky=tk.W, pady=2
        )
        fanout_spin = ttk.Spinbox(
            self.body,
            from_=1,
            to=999,
            textvariable=self.fanout_var,
            width=6,
        )
        fanout_spin.grid(row=1, column=1, sticky=tk.W, pady=2)
        self.fanout_var.trace_add("write", self._handle_var_change)

        ttk.Label(self.body, textvariable=self.variant_count_var, style="Dark.TLabel").grid(
            row=1, column=2, sticky=tk.W, padx=(10, 0)
        )
        ttk.Label(self.body, textvariable=self.variant_explainer_var, style="Dark.TLabel").grid(
            row=2, column=0, columnspan=3, sticky=tk.W
        )

        self.body.columnconfigure(1, weight=1)

        # Matrix rows container
        self._matrix_frame = ttk.Frame(self.body, style="Dark.TFrame")
        self._matrix_frame.grid(row=3, column=0, columnspan=3, sticky=tk.EW, pady=(6, 2))
        self._matrix_frame.columnconfigure(2, weight=1)

        # Buttons row
        btn_frame = ttk.Frame(self.body, style="Dark.TFrame")
        btn_frame.grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=(4, 6))
        add_btn = ttk.Button(btn_frame, text="Add row", command=lambda: self._add_matrix_row())
        add_btn.pack(side=tk.LEFT, padx=(0, 6))

        # Preview area
        self._preview_frame = ttk.LabelFrame(self.body, text="Variant preview", padding=4, style="Dark.TLabelframe")
        self._preview_frame.grid(row=5, column=0, columnspan=3, sticky=tk.EW, pady=(6, 0))
        self._preview_list = ttk.Treeview(
            self._preview_frame, columns=("idx", "summary"), show="headings", height=5
        )
        self._preview_list.heading("idx", text="#")
        self._preview_list.heading("summary", text="Summary")
        self._preview_list.column("idx", width=30, anchor=tk.W)
        self._preview_list.column("summary", width=400, anchor=tk.W)
        self._preview_list.pack(fill=tk.BOTH, expand=True)

        # Seed default rows
        self._add_matrix_row(label="Model matrix entries", key="model")
        self._add_matrix_row(label="Hypernetworks (name[:strength])", key="hypernetwork")

    def _add_matrix_row(self, label: str = "", values: str = "", enabled: bool = True, key: str | None = None) -> None:
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
        if index < 0 or index >= len(self._rows):
            return
        self._rows.pop(index)
        self._rebuild_matrix_ui_from_model()

    def _rebuild_matrix_ui_from_model(self) -> None:
        if self._matrix_frame is None:
            return
        for child in list(self._matrix_frame.winfo_children()):
            child.destroy()
        for idx, row in enumerate(self._rows):
            enabled_cb = ttk.Checkbutton(
                self._matrix_frame, variable=row.enabled_var, command=self._handle_var_change
            )
            enabled_cb.grid(row=idx, column=0, padx=(0, 4), sticky=tk.W)

            label_entry = ttk.Entry(self._matrix_frame, textvariable=row.label_var, width=18)
            label_entry.grid(row=idx, column=1, padx=(0, 4), sticky=tk.EW)

            value_entry = ttk.Entry(self._matrix_frame, textvariable=row.value_var, width=42)
            value_entry.grid(row=idx, column=2, padx=(0, 4), sticky=tk.EW)

            clone_btn = ttk.Button(
                self._matrix_frame,
                text="Clone",
                width=6,
                command=lambda i=idx: self._clone_matrix_row(i),
            )
            clone_btn.grid(row=idx, column=3, padx=(0, 2))

            del_btn = ttk.Button(
                self._matrix_frame,
                text="Del",
                width=4,
                command=lambda i=idx: self._delete_matrix_row(i),
            )
            del_btn.grid(row=idx, column=4, padx=(0, 2))

            row.value_var.trace_add("write", self._handle_var_change)
            row.label_var.trace_add("write", self._handle_var_change)
            row.enabled_var.trace_add("write", self._handle_var_change)

    def load_from_config(self, config: dict | None) -> None:
        pipeline_cfg = ((config or {}).get("pipeline") or {})
        mode = pipeline_cfg.get("variant_mode", "fanout") or "fanout"
        self.variant_mode_var.set(str(mode).lower())
        fanout = pipeline_cfg.get("variant_fanout") or 1
        self.fanout_var.set(str(fanout))

        model_values = pipeline_cfg.get("model_matrix") or []
        if self._rows:
            self._rows[0].value_var.set(", ".join(str(entry) for entry in model_values if entry))

        hyper_entries = pipeline_cfg.get("hypernetworks") or []
        hyper_texts = []
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

    def build_variant_plan(self, base_config: dict | None):
        return build_randomizer_plan(base_config, self.get_randomizer_options())

    def set_change_callback(self, callback) -> None:
        self._change_callback = callback

    def update_variant_count(self, count: int) -> None:
        safe_count = max(0, int(count)) if isinstance(count, int) else 0
        if safe_count != self._variant_count:
            self._variant_count = safe_count
        stats = compute_variant_stats(None, self.get_randomizer_options())
        matrix_combos = stats.get("matrix_combos", safe_count)
        fanout = stats.get("fanout", 1)
        band = stats.get("risk_band", RiskBand.LOW)
        banner = f"Total variants: {self._variant_count} ({matrix_combos} x fanout {fanout})"
        self.variant_count_var.set(banner)
        self.variant_explainer_var.set(stats.get("explanation", ""))
        if band == RiskBand.HIGH:
            self.variant_count_var.set(f"{banner} (High output)")

    def get_variant_count(self) -> int:
        return self._variant_count

    def _handle_var_change(self, *_args) -> None:
        self._refresh_preview()
        if self._change_callback:
            try:
                self._change_callback()
            except Exception:
                pass

    @staticmethod
    def _coerce_positive_int(value: str | int | None, default: int = 1) -> int:
        try:
            parsed = int(value)
            return parsed if parsed > 0 else default
        except (TypeError, ValueError):
            return default

    def _refresh_preview(self) -> None:
        base_config = self._current_randomizer_base_config()
        options = self.get_randomizer_options()
        stats = compute_variant_stats(base_config, options)
        self.update_variant_count(stats.get("total_variants", self._variant_count))
        if self._preview_list is None:
            return
        for item in self._preview_list.get_children():
            self._preview_list.delete(item)
        previews = preview_variants(base_config, options, limit=5)
        for idx, cfg in enumerate(previews):
            snippet = ", ".join(
                str(cfg.get("txt2img", {}).get("model", "")) or str(cfg.get("pipeline", {}).get("variant_mode", ""))
            )
            self._preview_list.insert("", "end", values=(idx + 1, snippet))

    def _current_randomizer_base_config(self) -> dict:
        # Try to use controller snapshot if available; fallback to empty dict
        try:
            if getattr(self, "controller", None) and hasattr(self.controller, "current_config"):
                return getattr(self.controller, "current_config") or {}
        except Exception:
            pass
        return {}

    @staticmethod
    def _parse_simple_entries(text: str) -> list[str]:
        if not text:
            return []
        parts = [segment.strip() for segment in text.replace("\n", ",").split(",")]
        return [part for part in parts if part]

    @staticmethod
    def _parse_hyper_entries(text: str) -> list[dict]:
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

    def get_randomizer_options(self) -> dict:
        selected_mode = (self.variant_mode_var.get() or "").strip().lower()
        active_mode = selected_mode if selected_mode not in {"", "off"} else ""
        fanout = self._coerce_positive_int(self.fanout_var.get(), default=1)

        options: dict[str, object] = {
            "mode": selected_mode or "fanout",
            "fanout": fanout,
        }
        if active_mode:
            options["variant_mode"] = active_mode
        matrix_payload: dict[str, object] = {}
        model_entries: list[str] = []
        hyper_entries: list[dict] = []

        for row in self._rows:
            if not row.enabled_var.get():
                continue
            label = row.label_var.get().strip().lower()
            values_raw = row.value_var.get()
            if row.key == "model":
                model_entries = self._parse_simple_entries(values_raw)
                if model_entries:
                    options["model_matrix"] = model_entries
                    matrix_payload["model"] = model_entries
            elif row.key == "hypernetwork":
                hyper_entries = self._parse_hyper_entries(values_raw)
                if hyper_entries:
                    options["hypernetworks"] = hyper_entries
                    matrix_payload["hypernetwork"] = hyper_entries
            else:
                parsed = self._parse_simple_entries(values_raw)
                if parsed:
                    matrix_payload[label or row.key] = parsed
        if matrix_payload:
            options["matrix"] = matrix_payload
        return options
