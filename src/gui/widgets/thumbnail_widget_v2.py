"""Thumbnail display widget for GUI V2."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from PIL import Image, ImageTk

from src.gui.theme_v2 import BACKGROUND_ELEVATED, TEXT_MUTED


class ThumbnailWidget(ttk.Frame):
    """Widget displaying a thumbnail image with placeholder support."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        width: int = 150,
        height: int = 150,
        placeholder_text: str = "No Preview",
        background: str = BACKGROUND_ELEVATED,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)

        self._width = width
        self._height = height
        self._placeholder_text = placeholder_text
        self._background = background
        self._photo_image: "ImageTk.PhotoImage | None" = None
        self._load_thread: threading.Thread | None = None

        # Create canvas for image display
        self._canvas = tk.Canvas(
            self,
            width=width,
            height=height,
            bg=background,
            highlightthickness=1,
            highlightbackground="#3a3a3a",
        )
        self._canvas.pack(fill="both", expand=True)

        # Show initial placeholder
        self._show_placeholder()

    def _show_placeholder(self, text: str | None = None) -> None:
        """Display placeholder text."""
        self._canvas.delete("all")
        display_text = text or self._placeholder_text
        self._canvas.create_text(
            self._width // 2,
            self._height // 2,
            text=display_text,
            fill=TEXT_MUTED,
            font=("Segoe UI", 9),
            anchor="center",
        )

    def set_image(self, image: "Image.Image | None") -> None:
        """Set the displayed thumbnail from a PIL Image."""
        if image is None:
            self.clear()
            return

        try:
            from PIL import ImageTk

            # Keep reference to prevent garbage collection
            self._photo_image = ImageTk.PhotoImage(image)

            self._canvas.delete("all")
            self._canvas.create_image(
                self._width // 2,
                self._height // 2,
                image=self._photo_image,
                anchor="center",
            )
        except Exception:
            self._show_placeholder("Image error")

    def set_image_from_path(self, path: Path | str) -> None:
        """Load and display thumbnail from file path (async)."""
        self.set_loading()

        def _load() -> None:
            from src.utils.image_utils import load_image_thumbnail

            thumb = load_image_thumbnail(path, (self._width, self._height))

            # Schedule UI update on main thread
            if self.winfo_exists():
                self.after(0, lambda: self._on_image_loaded(thumb))

        self._load_thread = threading.Thread(target=_load, daemon=True)
        self._load_thread.start()

    def _on_image_loaded(self, image: "Image.Image | None") -> None:
        """Handle async image load completion."""
        if image is None:
            self._show_placeholder("Not found")
        else:
            self.set_image(image)

    def set_image_from_base64(self, data: str) -> None:
        """Load and display thumbnail from base64 string."""
        import base64
        import io

        try:
            from PIL import Image as PILImage

            from src.utils.image_utils import generate_thumbnail

            # Decode base64
            if data.startswith("data:"):
                data = data.split(",", 1)[1]

            image_data = base64.b64decode(data)
            img = PILImage.open(io.BytesIO(image_data))
            thumb = generate_thumbnail(img, (self._width, self._height))
            self.set_image(thumb)

        except Exception:
            self._show_placeholder("Decode error")

    def clear(self) -> None:
        """Clear the thumbnail and show placeholder."""
        self._photo_image = None
        self._show_placeholder()

    def set_loading(self) -> None:
        """Show loading indicator."""
        self._show_placeholder("Loading...")
