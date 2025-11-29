from __future__ import annotations

from pathlib import Path


def test_randomizer_adapter_no_tk_imports():
    path = Path("src/gui_v2/adapters/randomizer_adapter_v2.py")
    text = path.read_text(encoding="utf-8").lower()
    for token in ("tkinter", "ttk", "from tkinter"):
        assert token not in text, f"Unexpected tk import in {path}"
