"""Reusable image thumbnail widget for Tkinter."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any

# PIL is optional - graceful degradation
try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class ImageThumbnail(tk.Canvas):
    """Canvas widget that displays a resizable image thumbnail."""

    def __init__(
        self,
        master: tk.Misc,
        max_width: int = 300,
        max_height: int = 300,
        bg: str = "#1E1E1E",
        **kwargs: Any,
    ) -> None:
        super().__init__(master, bg=bg, highlightthickness=0, **kwargs)
        self.max_width = max_width
        self.max_height = max_height
        self._photo_image: Any = None  # Keep reference to prevent GC
        self._current_path: str | None = None

        # Bind resize event
        self.bind("<Configure>", self._on_resize)

    def load_image(self, path: str | None) -> bool:
        """Load and display an image from the given path.

        Returns True if successful, False otherwise.
        """
        self.delete("all")
        self._photo_image = None
        self._current_path = path

        if not path:
            self._show_placeholder("No image selected")
            return False

        if not PIL_AVAILABLE:
            self._show_placeholder("PIL not installed\n(pip install Pillow)")
            return False

        try:
            path_obj = Path(path)
            if not path_obj.exists():
                self._show_placeholder(f"File not found:\n{path_obj.name}")
                return False

            # Load and resize image
            img = Image.open(path_obj)
            img = self._resize_to_fit(img)

            self._photo_image = ImageTk.PhotoImage(img)

            # Center image on canvas
            canvas_width = self.winfo_width() or self.max_width
            canvas_height = self.winfo_height() or self.max_height
            x = canvas_width // 2
            y = canvas_height // 2

            self.create_image(x, y, image=self._photo_image, anchor="center")
            return True

        except Exception as e:
            self._show_placeholder(f"Error loading image:\n{str(e)[:30]}")
            return False

    def _resize_to_fit(self, img: Image.Image) -> Image.Image:
        """Resize image to fit within max dimensions while preserving aspect ratio."""
        width, height = img.size

        # Calculate scale factor
        scale = min(self.max_width / width, self.max_height / height)

        if scale < 1:
            new_width = int(width * scale)
            new_height = int(height * scale)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        return img

    def _show_placeholder(self, text: str) -> None:
        """Show placeholder text when no image is available."""
        canvas_width = self.winfo_width() or self.max_width
        canvas_height = self.winfo_height() or self.max_height
        x = canvas_width // 2
        y = canvas_height // 2

        self.create_text(
            x, y,
            text=text,
            fill="#888888",
            font=("TkDefaultFont", 10),
            anchor="center",
            justify="center",
        )

    def _on_resize(self, event: tk.Event) -> None:
        """Handle canvas resize by reloading the current image."""
        if self._current_path:
            # Debounce resize events
            self.after(100, lambda: self.load_image(self._current_path))

    def clear(self) -> None:
        """Clear the current image."""
        self.delete("all")
        self._photo_image = None
        self._current_path = None
        self._show_placeholder("No image selected")
