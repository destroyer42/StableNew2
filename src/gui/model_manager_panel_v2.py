"""Model and VAE selector panel for GUI V2."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Iterable
from tkinter import ttk

from src.config import app_config
from src.gui.model_list_adapter_v2 import ModelListAdapterV2


class ModelManagerPanelV2(ttk.Frame):
    """Expose checkpoint and VAE selectors with a refresh hook."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        adapter: ModelListAdapterV2 | None = None,
        models: Iterable[str] | None = None,
        vaes: Iterable[str] | None = None,
    ) -> None:
        super().__init__(master, style="Panel.TFrame", padding=8)
        self.adapter = adapter or ModelListAdapterV2()

        self.model_var = tk.StringVar(value=app_config.get_core_model_name())
        self.vae_var = tk.StringVar(value=app_config.get_core_vae_name())

        # Removed redundant "Model Manager" label (card already titled)

        self.model_combo = self._build_combo(self.model_var, models or [])
        self._build_row("Model", self.model_combo)

        self.vae_combo = self._build_combo(self.vae_var, vaes or [])
        self._build_row("VAE", self.vae_combo)

        refresh_btn = ttk.Button(
            self, text="Refresh", command=self.refresh_lists, style="Primary.TButton"
        )
        # Place the button in the next available row, right-aligned
        row_idx = getattr(self, "_row_idx", 0)
        refresh_btn.grid(row=row_idx, column=1, sticky="e", pady=(4, 0))
        self._row_idx = row_idx + 1

    def _build_row(self, label: str, widget: tk.Widget) -> None:
        row_idx = getattr(self, "_row_idx", 0)
        label_widget = ttk.Label(self, text=label, style="TLabel")
        label_widget.grid(row=row_idx, column=0, sticky="w", padx=(0, 8), pady=(0, 4))
        if isinstance(widget, ttk.Combobox):
            widget.config(width=12)
        widget.grid(row=row_idx, column=1, sticky="ew", pady=(0, 4))
        self.columnconfigure(1, weight=1)
        self._row_idx = row_idx + 1

    def _build_combo(self, variable: tk.StringVar, values: Iterable[str]) -> ttk.Combobox:
        combo = ttk.Combobox(
            self,
            textvariable=variable,
            values=tuple(values),
            state="normal",
            style="Dark.TCombobox",
        )
        return combo

    def refresh_lists(self) -> None:
        """Reload model/vae names from the adapter and keep current selections if possible."""

        if self.adapter:
            try:
                models = self.adapter.get_model_names()
                if models:
                    self.model_combo["values"] = tuple(models)
            except Exception:
                pass
            try:
                vaes = self.adapter.get_vae_names()
                if vaes:
                    self.vae_combo["values"] = tuple(vaes)
            except Exception:
                pass

    def get_selections(self) -> dict[str, str]:
        return {
            "model_name": self.model_var.get().strip(),
            "vae_name": self.vae_var.get().strip(),
        }

    def set_selections(self, model_name: str | None = None, vae_name: str | None = None) -> None:
        if model_name is not None:
            self.model_var.set(str(model_name))
        if vae_name is not None:
            self.vae_var.set(str(vae_name))


__all__ = ["ModelManagerPanelV2"]
