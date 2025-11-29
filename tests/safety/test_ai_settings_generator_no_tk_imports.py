from __future__ import annotations

from pathlib import Path


FILES = [
    Path("src/ai/settings_generator_contract.py"),
    Path("src/ai/settings_generator_driver.py"),
    Path("src/ai/settings_generator_adapter.py"),
    Path("src/controller/settings_suggestion_controller.py"),
]


def test_ai_settings_generator_no_tk_imports() -> None:
    forbidden_tokens = {"tkinter", "from tkinter", "ttk", "src.gui"}
    for file_path in FILES:
        assert file_path.exists(), f"Missing file: {file_path}"
        text = file_path.read_text(encoding="utf-8").lower()
        for token in forbidden_tokens:
            assert token not in text, f"{file_path} unexpectedly references {token}"
