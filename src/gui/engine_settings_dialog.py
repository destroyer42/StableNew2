"""Modern engine settings dialog for GUI V2."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk
from typing import Any

from src.api.webui_runtime_identity import (
    A1111_DEFAULT_BASE_URL,
    A1111_WEBUI_IDENTITY,
    FORGE_WEBUI_IDENTITY,
    default_webui_base_url,
    resolve_configured_webui_runtime_identity,
    resolve_effective_webui_base_url,
)
from src.config.prompting_defaults import DEFAULT_PROMPT_OPTIMIZER_SETTINGS
from src.gui.content_visibility import normalize_content_visibility_mode
from src.utils.config import ConfigManager

#: Runtime selector values. "default" is the product default (managed Forge); it persists a blank identity.
RUNTIME_DEFAULT = "default"
RUNTIME_A1111 = A1111_WEBUI_IDENTITY
_RUNTIME_IDENTITY = {RUNTIME_DEFAULT: FORGE_WEBUI_IDENTITY, RUNTIME_A1111: A1111_WEBUI_IDENTITY}
_RUNTIME_LABEL = {RUNTIME_DEFAULT: "Default \u2014 Managed Forge", RUNTIME_A1111: "A1111 Compatibility"}


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
        content_visibility_mode: str = "nsfw",
        on_content_visibility_mode_change: Callable[[str], None] | None = None,
        running_runtime_identity: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self.config_manager = config_manager
        self._running_identity = running_runtime_identity
        self._initial_runtime = ""
        self._initial_identity_raw = ""
        self._invalid_identity: str | None = None
        self._runtime_var = tk.StringVar()
        self._effective_endpoint_var = tk.StringVar()
        self._runtime_notice_var = tk.StringVar()
        self._on_save = on_save
        self._on_cancel = on_cancel
        self._on_content_visibility_mode_change = on_content_visibility_mode_change

        self._webui_base_url_var = tk.StringVar()
        self._webui_workdir_var = tk.StringVar()
        self._webui_autostart_var = tk.BooleanVar()
        self._webui_initial_timeout_var = tk.DoubleVar()
        self._webui_retry_count_var = tk.IntVar()
        self._webui_retry_interval_var = tk.DoubleVar()
        self._webui_total_timeout_var = tk.DoubleVar()
        self._output_dir_var = tk.StringVar()
        self._model_dir_var = tk.StringVar()
        self._content_visibility_mode_var = tk.StringVar(
            value=normalize_content_visibility_mode(content_visibility_mode).value
        )
        self._prompt_optimizer_vars: dict[str, tk.Variable] = {
            "enabled": tk.BooleanVar(),
            "optimize_positive": tk.BooleanVar(),
            "optimize_negative": tk.BooleanVar(),
            "dedupe_enabled": tk.BooleanVar(),
            "preserve_lora_relative_order": tk.BooleanVar(),
            "preserve_unknown_order": tk.BooleanVar(),
            "enable_score_based_classification": tk.BooleanVar(),
            "allow_subject_anchor_boost": tk.BooleanVar(),
            "log_before_after": tk.BooleanVar(),
            "log_bucket_assignments": tk.BooleanVar(),
            "large_chunk_warning_threshold": tk.IntVar(),
            "subject_anchor_boost_min_chunk_count": tk.IntVar(),
        }

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
        visibility_frame = ttk.LabelFrame(self, text="Content Visibility", padding=8)
        health_frame = ttk.LabelFrame(self, text="Health Checks", padding=8)
        optimizer_frame = ttk.LabelFrame(self, text="Prompt Optimizer", padding=8)

        webui_frame.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        paths_frame.grid(row=2, column=0, sticky="ew", padx=8, pady=4)
        visibility_frame.grid(row=3, column=0, sticky="ew", padx=8, pady=4)
        health_frame.grid(row=4, column=0, sticky="ew", padx=8, pady=4)
        optimizer_frame.grid(row=5, column=0, sticky="ew", padx=8, pady=4)

        webui_frame.columnconfigure(1, weight=1)
        paths_frame.columnconfigure(1, weight=1)
        visibility_frame.columnconfigure(0, weight=1)
        health_frame.columnconfigure(1, weight=1)
        optimizer_frame.columnconfigure(0, weight=1)
        optimizer_frame.columnconfigure(1, weight=1)

        ttk.Label(webui_frame, text="Runtime:").grid(row=0, column=0, sticky="nw", pady=2)
        runtime_frame = ttk.Frame(webui_frame)
        runtime_frame.grid(row=0, column=1, sticky="w")
        for index, choice in enumerate((RUNTIME_DEFAULT, RUNTIME_A1111)):
            ttk.Radiobutton(
                runtime_frame,
                text=_RUNTIME_LABEL[choice],
                value=choice,
                variable=self._runtime_var,
            ).grid(row=index, column=0, sticky="w")
        ttk.Label(
            webui_frame, textvariable=self._runtime_notice_var, style="Muted.TLabel", wraplength=420
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
        self._add_label_entry(webui_frame, "API URL:", self._webui_base_url_var, row=2)
        ttk.Label(webui_frame, textvariable=self._effective_endpoint_var, style="Muted.TLabel").grid(
            row=3, column=1, sticky="w", padx=(4, 0)
        )
        self._add_label_entry(webui_frame, "WebUI workdir:", self._webui_workdir_var, row=4)
        ttk.Checkbutton(
            webui_frame,
            text="Autostart WebUI",
            variable=self._webui_autostart_var,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self._add_label_entry(paths_frame, "Output directory:", self._output_dir_var, row=0)
        self._add_label_entry(paths_frame, "Model directory:", self._model_dir_var, row=1)

        ttk.Radiobutton(
            visibility_frame,
            text="NSFW: show all prompts and assets",
            value="nsfw",
            variable=self._content_visibility_mode_var,
        ).grid(row=0, column=0, sticky="w", pady=(0, 2))
        ttk.Radiobutton(
            visibility_frame,
            text="SFW: hide explicit prompts and assets",
            value="sfw",
            variable=self._content_visibility_mode_var,
        ).grid(row=1, column=0, sticky="w")

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
        optimizer_specs = [
            ("enabled", "Enable"),
            ("optimize_positive", "Optimize Positive"),
            ("optimize_negative", "Optimize Negative"),
            ("dedupe_enabled", "Enable Dedupe"),
            ("preserve_lora_relative_order", "Preserve LoRAs"),
            ("preserve_unknown_order", "Preserve Unknown"),
            ("enable_score_based_classification", "Score-Based"),
            ("allow_subject_anchor_boost", "Anchor Boost"),
            ("log_before_after", "Log Before/After"),
            ("log_bucket_assignments", "Log Buckets"),
        ]
        for index, (key, label) in enumerate(optimizer_specs):
            ttk.Checkbutton(
                optimizer_frame,
                text=label,
                variable=self._prompt_optimizer_vars[key],
            ).grid(row=index // 2, column=index % 2, sticky="w", pady=2)
        self._add_label_entry(
            optimizer_frame,
            "Chunk warning threshold:",
            self._prompt_optimizer_vars["large_chunk_warning_threshold"],
            row=5,
            var_type="int",
        )
        self._add_label_entry(
            optimizer_frame,
            "Anchor min chunk count:",
            self._prompt_optimizer_vars["subject_anchor_boost_min_chunk_count"],
            row=6,
            var_type="int",
        )

    def _build_actions(self) -> None:
        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=6, column=0, sticky="ew", padx=8, pady=(8, 8))
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
            entry.configure(
                validate="key", validatecommand=(entry.register(self._validate_int), "%P")
            )
        elif var_type == "float":
            entry.configure(
                validate="key", validatecommand=(entry.register(self._validate_float), "%P")
            )

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
        prompt_defaults = dict(DEFAULT_PROMPT_OPTIMIZER_SETTINGS)
        prompt_defaults.update(defaults.get("prompt_optimizer") or {})
        prompt_defaults.update(settings.get("prompt_optimizer") or {})
        for key, var in self._prompt_optimizer_vars.items():
            value = prompt_defaults.get(key)
            if isinstance(var, tk.BooleanVar):
                var.set(bool(value))
            else:
                var.set(int(value or 0))
        self._load_runtime_choice(settings)
        self._runtime_var.trace_add("write", self._on_runtime_changed)
        self._webui_base_url_var.trace_add("write", lambda *_a: self._refresh_runtime_labels())
        self._refresh_runtime_labels()

    # ---- runtime selection (application-level, restart-required) -----------------------------------------
    def _load_runtime_choice(self, settings: dict[str, Any]) -> None:
        self._initial_identity_raw = str(settings.get("webui_runtime_identity") or "").strip()
        try:
            effective = resolve_configured_webui_runtime_identity(settings)
        except ValueError:
            # Fail closed: an invalid persisted identity selects neither runtime until the operator chooses.
            self._invalid_identity = self._initial_identity_raw or "(from the environment)"
            self._initial_runtime = ""
            self._runtime_var.set("")
            return
        choice = RUNTIME_A1111 if effective == A1111_WEBUI_IDENTITY else RUNTIME_DEFAULT
        self._initial_runtime = choice
        self._runtime_var.set(choice)
        if self._running_identity is None:
            self._running_identity = effective

    def selected_runtime(self) -> str:
        return str(self._runtime_var.get() or "")

    def set_runtime(self, choice: str) -> None:
        self._runtime_var.set(choice)

    def _selected_identity(self) -> str | None:
        return _RUNTIME_IDENTITY.get(self.selected_runtime())

    def restart_required(self) -> bool:
        identity = self._selected_identity()
        return bool(identity and self._running_identity and identity != self._running_identity)

    def effective_endpoint_text(self) -> str:
        identity = self._selected_identity()
        if identity is None:
            return "Effective endpoint: choose a runtime"
        url = resolve_effective_webui_base_url(
            {"webui_base_url": self._webui_base_url_var.get()}, identity=identity
        )
        return f"Effective endpoint: {url} ({_RUNTIME_LABEL[self.selected_runtime()]})"

    def runtime_notice_text(self) -> str:
        if self._selected_identity() is None:
            return (
                f"Invalid webui_runtime_identity '{self._invalid_identity}'. Choose a runtime to repair it; "
                "no fallback is applied."
            )
        if self.restart_required():
            return (
                "Restart StableNew to switch runtimes. The running runtime is not stopped or changed; until "
                "you restart, new image jobs are rejected because it no longer matches this selection."
            )
        return ""

    def _on_runtime_changed(self, *_args: Any) -> None:
        identity = self._selected_identity()
        if identity is not None:
            known = {
                default_webui_base_url(FORGE_WEBUI_IDENTITY).rstrip("/"),
                default_webui_base_url(A1111_WEBUI_IDENTITY).rstrip("/"),
                "",
            }
            if self._webui_base_url_var.get().strip().rstrip("/") in known:
                self._webui_base_url_var.set(default_webui_base_url(identity))
        self._refresh_runtime_labels()

    def _refresh_runtime_labels(self) -> None:
        self._effective_endpoint_var.set(self.effective_endpoint_text())
        self._runtime_notice_var.set(self.runtime_notice_text())

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
        values["prompt_optimizer"] = {
            key: (bool(var.get()) if isinstance(var, tk.BooleanVar) else int(var.get()))
            for key, var in self._prompt_optimizer_vars.items()
        }
        values["prompt_optimizer"]["warn_on_large_chunk_count"] = True
        values["prompt_optimizer"]["opt_out_pipeline_names"] = []
        choice = self.selected_runtime()
        identity = self._selected_identity()
        if choice != self._initial_runtime:
            # Only a changed selection is written; an unchanged one never rewrites (or pins) what is persisted.
            values["webui_runtime_identity"] = A1111_WEBUI_IDENTITY if choice == RUNTIME_A1111 else ""
        if identity is not None:
            url = str(values.get("webui_base_url") or "").strip()
            if url.rstrip("/") == default_webui_base_url(identity).rstrip("/"):
                # An identity default is not operator intent: persist the neutral flat default so a later runtime
                # switch can never inherit the other runtime's endpoint.
                values["webui_base_url"] = A1111_DEFAULT_BASE_URL
        return values

    def _validate(self, values: dict[str, Any]) -> bool:
        if self._selected_identity() is None:
            messagebox.showwarning("Settings", "Choose a WebUI runtime before saving.")
            return False
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
        if self.restart_required():
            messagebox.showinfo("Settings", self.runtime_notice_text())
        if callable(self._on_content_visibility_mode_change):
            try:
                self._on_content_visibility_mode_change(
                    normalize_content_visibility_mode(self._content_visibility_mode_var.get()).value
                )
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
        self._runtime_var.set(RUNTIME_DEFAULT)
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
        prompt_defaults = dict(DEFAULT_PROMPT_OPTIMIZER_SETTINGS)
        prompt_defaults.update(defaults.get("prompt_optimizer") or {})
        for key, var in self._prompt_optimizer_vars.items():
            value = prompt_defaults.get(key)
            if isinstance(var, tk.BooleanVar):
                var.set(bool(value))
            else:
                var.set(int(value or 0))
