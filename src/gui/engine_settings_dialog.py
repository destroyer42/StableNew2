"""Modern engine settings dialog for GUI V2."""

from __future__ import annotations

from typing import Any, Callable

import tkinter as tk
from tkinter import messagebox, ttk

from src.utils.config import ConfigManager


class EngineSettingsDialog(ttk.Frame):
    """Dialog content that edits persisted engine settings."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        config_manager: ConfigManager,
        on_save: Callable[[dict[str, Any]], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        status_text: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self.config_manager = config_manager
        self._on_save = on_save
        self._on_cancel = on_cancel

        self._webui_base_url_var = tk.StringVar()
        self._webui_workdir_var = tk.StringVar()
        self._webui_autostart_var = tk.BooleanVar()
        self._webui_initial_timeout_var = tk.DoubleVar()
        self._webui_retry_count_var = tk.IntVar()
        self._webui_retry_interval_var = tk.DoubleVar()
        self._webui_total_timeout_var = tk.DoubleVar()
        self._output_dir_var = tk.StringVar()
        self._model_dir_var = tk.StringVar()

        self._field_vars: dict[str, tk.Variable] = {
            "webui_base_url": self._webui_base_url_var,
            "webui_workdir": self._webui_workdir_var,
            "webui_autostart_enabled": self._webui_autostart_var,
            "webui_health_initial_timeout_seconds": self._webui_initial_timeout_var,
            "webui_health_retry_count": self._webui_retry_count_var,
            "webui_health_retry_interval_seconds": self._webui_retry_interval_var,
            "webui_health_total_timeout_seconds": self._webui_total_timeout_var,
            "output_dir": self._output_dir_var,
            "model_dir": self._model_dir_var,
        }

        self.columnconfigure(0, weight=1)
        if status_text:
            ttk.Label(
                self,
                text=f"WebUI status: {status_text}",
                style="Muted.TLabel",
            ).grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))

        self._build_sections()
        self._apply_settings()
        self._build_actions()

    def _build_sections(self) -> None:
        webui_frame = ttk.LabelFrame(self, text="WebUI", padding=8)
        paths_frame = ttk.LabelFrame(self, text="Paths", padding=8)
        health_frame = ttk.LabelFrame(self, text="Health Checks", padding=8)

        webui_frame.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        paths_frame.grid(row=2, column=0, sticky="ew", padx=8, pady=4)
        health_frame.grid(row=3, column=0, sticky="ew", padx=8, pady=4)

        webui_frame.columnconfigure(1, weight=1)
        paths_frame.columnconfigure(1, weight=1)
        health_frame.columnconfigure(1, weight=1)

        self._add_label_entry(webui_frame, "API URL:", self._webui_base_url_var, row=0)
        self._add_label_entry(webui_frame, "WebUI workdir:", self._webui_workdir_var, row=1)
        ttk.Checkbutton(
            webui_frame,
            text="Autostart WebUI",
            variable=self._webui_autostart_var,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self._add_label_entry(paths_frame, "Output directory:", self._output_dir_var, row=0)
        self._add_label_entry(paths_frame, "Model directory:", self._model_dir_var, row=1)

        self._add_label_entry(
            health_frame,
            "Initial timeout (s):",
            self._webui_initial_timeout_var,
            row=0,
            var_type="float",
        )
        self._add_label_entry(
            health_frame,
            "Retry count:",
            self._webui_retry_count_var,
            row=1,
            var_type="int",
        )
        self._add_label_entry(
            health_frame,
            "Retry interval (s):",
            self._webui_retry_interval_var,
            row=2,
            var_type="float",
        )
        self._add_label_entry(
            health_frame,
            "Total timeout (s):",
            self._webui_total_timeout_var,
            row=3,
            var_type="float",
        )

    def _build_actions(self) -> None:
        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=4, column=0, sticky="ew", padx=8, pady=(8, 8))
        btn_frame.columnconfigure((0, 1, 2), weight=1)

        restore_btn = ttk.Button(btn_frame, text="Restore Defaults", command=self.restore_defaults)
        restore_btn.grid(row=0, column=0, sticky="ew")
        cancel_btn = ttk.Button(btn_frame, text="Cancel", command=self._handle_cancel)
        cancel_btn.grid(row=0, column=1, sticky="ew", padx=4)
        save_btn = ttk.Button(btn_frame, text="Save & Close", command=self._handle_save)
        save_btn.grid(row=0, column=2, sticky="ew")

    def _add_label_entry(
        self,
        parent: ttk.Frame,
        label: str,
        var: tk.Variable,
        *,
        row: int,
        var_type: str | None = None,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
        if isinstance(var, tk.BooleanVar):
            chk = ttk.Checkbutton(parent, variable=var)
            chk.grid(row=row, column=1, sticky="w", pady=2)
            return

        entry = ttk.Entry(parent, textvariable=var)
        entry.grid(row=row, column=1, sticky="ew", pady=2, padx=(4, 0))
        if var_type == "int":
            entry.configure(validate="key", validatecommand=(entry.register(self._validate_int), "%P"))
        elif var_type == "float":
            entry.configure(validate="key", validatecommand=(entry.register(self._validate_float), "%P"))

    def _validate_int(self, value: str) -> bool:
        if value == "":
            return True
        try:
            int(value)
            return True
        except ValueError:
            return False

    def _validate_float(self, value: str) -> bool:
        if value == "":
            return True
        try:
            float(value)
            return True
        except ValueError:
            return False

    def _apply_settings(self) -> None:
        settings = self.config_manager.load_settings()
        defaults = self.config_manager.get_default_engine_settings()
        for key, var in self._field_vars.items():
            value = settings.get(key, defaults.get(key))
            if isinstance(var, tk.BooleanVar):
                var.set(bool(value))
            elif isinstance(var, tk.IntVar):
                var.set(int(value or 0))
            elif isinstance(var, tk.DoubleVar):
                var.set(float(value or 0.0))
            else:
                var.set(str(value or ""))

    def collect_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for key, var in self._field_vars.items():
            if isinstance(var, tk.BooleanVar):
                values[key] = bool(var.get())
            elif isinstance(var, tk.IntVar):
                values[key] = int(var.get())
            elif isinstance(var, tk.DoubleVar):
                values[key] = float(var.get())
            else:
                values[key] = str(var.get()).strip()
        return values

    def _validate(self, values: dict[str, Any]) -> bool:
        base_url = str(values.get("webui_base_url") or "").strip()
        if not base_url:
            messagebox.showwarning("Settings", "WebUI API URL must be provided.")
            return False
        return True

    def _handle_save(self) -> None:
        values = self.collect_values()
        if not self._validate(values):
            return
        if callable(self._on_save):
            try:
                self._on_save(values)
            except Exception:
                pass
        self.master.destroy()

    def _handle_cancel(self) -> None:
        if callable(self._on_cancel):
            try:
                self._on_cancel()
            except Exception:
                pass
        self.master.destroy()

    def restore_defaults(self) -> None:
        defaults = self.config_manager.get_default_engine_settings()
        for key, var in self._field_vars.items():
            value = defaults.get(key)
            if isinstance(var, tk.BooleanVar):
                var.set(bool(value))
            elif isinstance(var, tk.IntVar):
                var.set(int(value or 0))
            elif isinstance(var, tk.DoubleVar):
                var.set(float(value or 0.0))
            else:
                var.set(str(value or ""))
