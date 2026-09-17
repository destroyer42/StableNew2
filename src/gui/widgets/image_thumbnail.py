"""Reusable image thumbnail widget for Tkinter."""

from __future__ import annotations

import os
import subprocess
import tkinter as tk
from pathlib import Path
from typing import Any

# PIL is optional - graceful degradation
try:
    from PIL import Image, ImageTk

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


def fit_image_size(
    source_width: int,
    source_height: int,
    viewport_width: int,
    viewport_height: int,
    *,
    max_width: int | None = None,
    max_height: int | None = None,
    allow_enlarge: bool = False,
) -> tuple[int, int]:
    """Return aspect-preserving dimensions fully contained in a viewport."""
    source_width = max(1, int(source_width))
    source_height = max(1, int(source_height))
    viewport_width = max(1, int(viewport_width))
    viewport_height = max(1, int(viewport_height))
    limits = [viewport_width / source_width, viewport_height / source_height]
    if max_width:
        limits.append(max(1, int(max_width)) / source_width)
    if max_height:
        limits.append(max(1, int(max_height)) / source_height)
    scale = min(limits)
    if not allow_enlarge:
        scale = min(1.0, scale)
    return max(1, int(source_width * scale)), max(1, int(source_height * scale))


class ImageThumbnail(tk.Canvas):
    """Canvas widget that displays a resizable image thumbnail."""

    def __init__(
        self,
        master: tk.Misc,
        max_width: int = 300,
        max_height: int = 300,
        fit_to_widget: bool = False,
        bg: str = "#1E1E1E",
        **kwargs: Any,
    ) -> None:
        super().__init__(master, bg=bg, highlightthickness=0, **kwargs)
        self.max_width = max_width
        self.max_height = max_height
        self.fit_to_widget = bool(fit_to_widget)
        self._photo_image: Any = None  # Keep reference to prevent GC
        self._current_path: str | None = None
        self._resize_after_id: str | None = None

        # Bind resize event
        self.bind("<Configure>", self._on_resize)
        self.bind("<Button-1>", self._on_activate)
        self.bind("<Double-Button-1>", self._on_activate)
        self._update_clickability()

    def load_image(self, path: str | None) -> bool:
        """Load and display an image from the given path.

        Returns True if successful, False otherwise.
        """
        self.delete("all")
        self._photo_image = None
        self._current_path = path
        self._update_clickability()

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
        """Resize without crop using either widget viewport or constructor caps."""
        if self.fit_to_widget:
            viewport_width = self.winfo_width() or self.max_width
            viewport_height = self.winfo_height() or self.max_height
            new_size = fit_image_size(
                img.width,
                img.height,
                viewport_width,
                viewport_height,
                max_width=self.max_width,
                max_height=self.max_height,
            )
        else:
            new_size = fit_image_size(
                img.width,
                img.height,
                self.max_width,
                self.max_height,
                max_width=self.max_width,
                max_height=self.max_height,
            )
        if new_size != img.size:
            return img.resize(new_size, Image.Resampling.LANCZOS)
        return img

    def _show_placeholder(self, text: str) -> None:
        """Show placeholder text when no image is available."""
        canvas_width = self.winfo_width() or self.max_width
        canvas_height = self.winfo_height() or self.max_height
        x = canvas_width // 2
        y = canvas_height // 2

        self.create_text(
            x,
            y,
            text=text,
            fill="#888888",
            font=("TkDefaultFont", 10),
            anchor="center",
            justify="center",
        )

    def _on_resize(self, event: tk.Event) -> None:
        """Handle canvas resize by reloading the current image."""
        if self._current_path and self.fit_to_widget:
            if self._resize_after_id is not None:
                try:
                    self.after_cancel(self._resize_after_id)
                except Exception:
                    pass
            path = self._current_path
            self._resize_after_id = self.after(100, lambda: self._reload_after_resize(path))

    def _reload_after_resize(self, path: str) -> None:
        self._resize_after_id = None
        if self._current_path == path:
            self.load_image(path)

    def clear(self) -> None:
        """Clear the current image."""
        if getattr(self, "_resize_after_id", None) is not None:
            try:
                self.after_cancel(self._resize_after_id)
            except Exception:
                pass
            self._resize_after_id = None
        self.delete("all")
        self._photo_image = None
        self._current_path = None
        self._show_placeholder("No image selected")
        self._update_clickability()

    def _on_activate(self, _event: tk.Event | None = None) -> None:
        self._open_current_path()

    def _open_current_path(self) -> None:
        if not self._current_path:
            return
        candidate = Path(self._current_path)
        if not candidate.exists():
            return
        if os.name == "nt":
            os.startfile(str(candidate))
            return
        if os.sys.platform == "darwin":
            subprocess.Popen(["open", str(candidate)])
            return
        subprocess.Popen(["xdg-open", str(candidate)])

    def _update_clickability(self) -> None:
        cursor = "hand2" if self._current_path else ""
        try:
            self.configure(cursor=cursor)
        except Exception:
            pass
