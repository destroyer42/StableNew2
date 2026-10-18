from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # anchor to the repository, not the working directory

ADAPTER_FILES = [
    ROOT / "src/gui_v2/adapters/__init__.py",
    ROOT / "src/gui_v2/adapters/randomizer_adapter_v2.py",
    ROOT / "src/gui_v2/adapters/learning_adapter_v2.py",
]


def test_adapters_do_not_import_tk() -> None:
    forbidden_tokens = {"tkinter", "from tkinter", "tk.", "ttk", "src.gui"}
    for file_path in ADAPTER_FILES:
        assert file_path.exists(), f"Adapter file missing: {file_path}"
        content = file_path.read_text(encoding="utf-8").lower()
        for token in forbidden_tokens:
            assert token not in content, f"{file_path} unexpectedly references {token}"
