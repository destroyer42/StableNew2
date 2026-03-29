from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import tkinter as tk

from src.gui.views.character_training_frame import CharacterTrainingFrame


def test_character_training_frame_applies_controller_defaults(tk_root: tk.Tk) -> None:
    controller = Mock()
    controller.build_character_training_defaults.return_value = {
        "character_name": "Ada",
        "output_dir": "C:/weights",
        "epochs": 42,
        "learning_rate": 0.0002,
        "trainer_command": "trainer.exe",
    }

    frame = CharacterTrainingFrame(tk_root, app_controller=controller)
    try:
        assert frame.character_name_var.get() == "Ada"
        assert frame.output_dir_var.get() == "C:/weights"
        assert frame.epochs_var.get() == "42"
        assert frame.learning_rate_var.get() == "0.0002"
        assert frame.trainer_command_var.get() == "trainer.exe"
    finally:
        frame.destroy()


def test_character_training_frame_submit_calls_controller(tk_root: tk.Tk, tmp_path: Path) -> None:
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    output_dir = tmp_path / "weights"
    controller = Mock()
    controller.submit_character_training_job.return_value = "job-train-123"

    frame = CharacterTrainingFrame(tk_root, app_controller=controller)
    try:
        frame.character_name_var.set("Ada")
        frame.image_dir_var.set(str(image_dir))
        frame.output_dir_var.set(str(output_dir))
        frame.epochs_var.set("25")
        frame.learning_rate_var.set("0.0003")
        frame.base_model_var.set("sdxl")
        frame.trigger_phrase_var.set("ada person")
        frame.rank_var.set("16")
        frame.network_alpha_var.set("16")
        frame.trainer_command_var.set("trainer.exe")

        with patch("src.gui.views.character_training_frame.messagebox.showinfo"):
            frame._on_submit()

        controller.submit_character_training_job.assert_called_once_with(
            {
                "character_name": "Ada",
                "image_dir": str(image_dir),
                "output_dir": str(output_dir),
                "epochs": 25,
                "learning_rate": 0.0003,
                "base_model": "sdxl",
                "trigger_phrase": "ada person",
                "trainer_command": "trainer.exe",
                "rank": 16,
                "network_alpha": 16,
            }
        )
        assert frame.status_label.cget("text") == "Queued character training job job-train-123."
    finally:
        frame.destroy()