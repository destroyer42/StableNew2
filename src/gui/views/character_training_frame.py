from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any


_DEFAULTS = {
    "character_name": "",
    "image_dir": "",
    "output_dir": str(Path("data") / "embeddings"),
    "epochs": 100,
    "learning_rate": 0.0001,
    "base_model": "",
    "trigger_phrase": "",
    "rank": 16,
    "network_alpha": 16,
    "trainer_command": "",
}


class CharacterTrainingFrame(ttk.Frame):
    """Thin GUI surface for queueing canonical train_lora jobs."""

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

        self.character_name_var = tk.StringVar()
        self.image_dir_var = tk.StringVar()
        self.output_dir_var = tk.StringVar()
        self.epochs_var = tk.StringVar()
        self.learning_rate_var = tk.StringVar()
        self.base_model_var = tk.StringVar()
        self.trigger_phrase_var = tk.StringVar()
        self.rank_var = tk.StringVar()
        self.network_alpha_var = tk.StringVar()
        self.trainer_command_var = tk.StringVar()

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self._build_layout()
        self.apply_controller_defaults()

    def apply_controller_defaults(self) -> None:
        defaults = dict(_DEFAULTS)
        builder = getattr(self.app_controller, "build_character_training_defaults", None)
        if callable(builder):
            try:
                loaded = builder() or {}
            except Exception:
                loaded = {}
            if isinstance(loaded, dict):
                defaults.update(loaded)
        self._apply_defaults(defaults)

    def _build_layout(self) -> None:
        container = ttk.Frame(self, style="Panel.TFrame", padding=12)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(1, weight=1)

        ttk.Label(
            container,
            text="Queue a character LoRA training job through the normal StableNew queue and runner path.",
            justify="left",
            wraplength=720,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        self._add_entry_row(container, 1, "Character Name", self.character_name_var)
        self._add_path_row(container, 2, "Image Directory", self.image_dir_var, self._browse_image_dir)
        self._add_path_row(container, 3, "Output Directory", self.output_dir_var, self._browse_output_dir)
        self._add_entry_row(container, 4, "Epochs", self.epochs_var)
        self._add_entry_row(container, 5, "Learning Rate", self.learning_rate_var)
        self._add_entry_row(container, 6, "Base Model", self.base_model_var)
        self._add_entry_row(container, 7, "Trigger Phrase", self.trigger_phrase_var)
        self._add_entry_row(container, 8, "Rank", self.rank_var)
        self._add_entry_row(container, 9, "Network Alpha", self.network_alpha_var)
        self._add_entry_row(container, 10, "Trainer Command", self.trainer_command_var)

        self.submit_button = ttk.Button(
            container,
            text="Queue Training Job",
            command=self._on_submit,
            style="Primary.TButton",
        )
        self.submit_button.grid(row=11, column=0, sticky="w", pady=(10, 0))

        self.status_label = ttk.Label(container, text="", justify="left")
        self.status_label.grid(row=12, column=0, columnspan=3, sticky="w", pady=(8, 0))

    @staticmethod
    def _add_entry_row(
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=4)

    @staticmethod
    def _add_path_row(
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        command,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Button(parent, text="Browse...", command=command).grid(row=row, column=2, sticky="w", padx=(8, 0), pady=4)

    def _apply_defaults(self, defaults: dict[str, Any]) -> None:
        self.character_name_var.set(str(defaults.get("character_name") or ""))
        self.image_dir_var.set(str(defaults.get("image_dir") or ""))
        self.output_dir_var.set(str(defaults.get("output_dir") or _DEFAULTS["output_dir"]))
        self.epochs_var.set(str(defaults.get("epochs") or _DEFAULTS["epochs"]))
        self.learning_rate_var.set(str(defaults.get("learning_rate") or _DEFAULTS["learning_rate"]))
        self.base_model_var.set(str(defaults.get("base_model") or ""))
        self.trigger_phrase_var.set(str(defaults.get("trigger_phrase") or ""))
        self.rank_var.set(str(defaults.get("rank") or _DEFAULTS["rank"]))
        self.network_alpha_var.set(str(defaults.get("network_alpha") or _DEFAULTS["network_alpha"]))
        trainer_command = defaults.get("trainer_command") or ""
        if isinstance(trainer_command, (list, tuple)):
            trainer_command = " ".join(str(item) for item in trainer_command if str(item).strip())
        self.trainer_command_var.set(str(trainer_command))

    def _browse_image_dir(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.image_dir_var.get() or ".")
        if selected:
            self.image_dir_var.set(selected)

    def _browse_output_dir(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_dir_var.get() or str(Path("data") / "embeddings"))
        if selected:
            self.output_dir_var.set(selected)

    def _collect_form_data(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "character_name": self.character_name_var.get().strip(),
            "image_dir": self.image_dir_var.get().strip(),
            "output_dir": self.output_dir_var.get().strip(),
            "epochs": int(self.epochs_var.get().strip()),
            "learning_rate": float(self.learning_rate_var.get().strip()),
        }
        optional_string_fields = {
            "base_model": self.base_model_var.get().strip(),
            "trigger_phrase": self.trigger_phrase_var.get().strip(),
            "trainer_command": self.trainer_command_var.get().strip(),
        }
        for key, value in optional_string_fields.items():
            if value:
                payload[key] = value
        rank = self.rank_var.get().strip()
        if rank:
            payload["rank"] = int(rank)
        network_alpha = self.network_alpha_var.get().strip()
        if network_alpha:
            payload["network_alpha"] = int(network_alpha)
        return payload

    def _validate_form_data(self) -> str | None:
        if not self.character_name_var.get().strip():
            return "Character name is required."
        image_dir = Path(self.image_dir_var.get().strip()).expanduser()
        if not str(image_dir):
            return "Image directory is required."
        if not image_dir.exists() or not image_dir.is_dir():
            return "Image directory must exist."
        if not self.output_dir_var.get().strip():
            return "Output directory is required."
        try:
            if int(self.epochs_var.get().strip()) <= 0:
                return "Epochs must be greater than zero."
        except ValueError:
            return "Epochs must be an integer."
        try:
            if float(self.learning_rate_var.get().strip()) <= 0:
                return "Learning rate must be greater than zero."
        except ValueError:
            return "Learning rate must be a number."
        for label, raw_value in (
            ("Rank", self.rank_var.get().strip()),
            ("Network Alpha", self.network_alpha_var.get().strip()),
        ):
            if not raw_value:
                continue
            try:
                if int(raw_value) <= 0:
                    return f"{label} must be greater than zero."
            except ValueError:
                return f"{label} must be an integer."
        return None

    def _set_status(self, message: str) -> None:
        self.status_label.config(text=message)

    def _on_submit(self) -> None:
        validation_error = self._validate_form_data()
        if validation_error:
            self._set_status(validation_error)
            messagebox.showerror("Character Training", validation_error)
            return

        submit = getattr(self.app_controller, "submit_character_training_job", None)
        if not callable(submit):
            error = "Character training is unavailable because the AppController entrypoint is missing."
            self._set_status(error)
            messagebox.showerror("Character Training", error)
            return

        form_data = self._collect_form_data()
        try:
            job_id = submit(form_data)
        except Exception as exc:
            error = str(exc) or "Failed to queue character training job."
            self._set_status(error)
            messagebox.showerror("Character Training", error)
            return

        success_message = f"Queued character training job {job_id}."
        self._set_status(success_message)
        messagebox.showinfo("Character Training", success_message)