from __future__ import annotations

from pathlib import Path

import tkinter as tk

from src.gui.widgets.thumbnail_widget_v2 import ThumbnailWidget


def test_thumbnail_widget_open_target_uses_default_viewer(monkeypatch, tk_root: tk.Tk, tmp_path: Path) -> None:
    target = tmp_path / "clip.mp4"
    target.write_bytes(b"mp4")

    widget = ThumbnailWidget(tk_root)
    try:
        widget.set_open_target(target)

        opened: list[str] = []
        monkeypatch.setattr("os.startfile", lambda path: opened.append(path))

        widget._open_current_path()

        assert opened == [str(target)]
    finally:
        widget.destroy()
