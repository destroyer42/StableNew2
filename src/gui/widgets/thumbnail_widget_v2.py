"""Thumbnail display widget for GUI V2."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from PIL import Image, ImageTk

from src.gui.theme_v2 import BACKGROUND_ELEVATED, TEXT_MUTED
from src.gui.view_contracts.workspace_density_contract import (
    PREVIEW_MIN_EDGE,
    RESIZE_COALESCE_MS,
    preview_resize_needed,
    preview_side,
)

logger = logging.getLogger(__name__)


class ThumbnailWidget(ttk.Frame):
    """Widget displaying a thumbnail image with placeholder support.

    ``responsive=True`` (PR-GUI-110) turns ``width``/``height`` into a *maximum* square edge: the widget fits
    its parent's real width (never wider than ``max(width, height)``, never narrower than ``min_edge``),
    keeps the image aspect ratio, re-fits only after resizing settles (one coalesced job), rescales the
    already-decoded image instead of decoding again, and ignores load results that were superseded.
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        width: int = 150,
        height: int = 150,
        placeholder_text: str = "No Preview",
        background: str = BACKGROUND_ELEVATED,
        responsive: bool = False,
        min_edge: int = PREVIEW_MIN_EDGE,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)

        self._responsive = bool(responsive)
        self._max_edge = max(int(width), int(height))
        self._min_edge = min(int(min_edge), self._max_edge)
        self._source_image: Image.Image | None = None
        self._placeholder_shown: str | None = None
        self._request_id = 0
        self._inflight_path: str | None = None
        self._loaded_path: str | None = None
        self._fit_job: str | None = None
        self._has_fit = False
        self._destroyed = False

        self._width = width
        self._height = height
        self._placeholder_text = placeholder_text
        self._background = background
        self._photo_image: ImageTk.PhotoImage | None = None
        self._load_thread: threading.Thread | None = None
        self._current_path: str | None = None
        self._open_path: str | None = None

        # Create canvas for image display
        self._canvas = tk.Canvas(
            self,
            width=width,
            height=height,
            bg=background,
            highlightthickness=1,
            highlightbackground="#3a3a3a",
        )
        if self._responsive:
            # The frame requests only the minimum width so it never forces its parent wider; the parent's real
            # allotment drives the fit (see _fit_now).
            self.configure(width=self._min_edge, height=int(height))
            self.pack_propagate(False)
            self.grid_propagate(False)
            self._canvas.pack(anchor="n")
            self.bind("<Configure>", self._schedule_fit, add="+")
        else:
            self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<Button-1>", self._on_activate)
        self._canvas.bind("<Double-Button-1>", self._on_activate)

        # Show initial placeholder
        self._show_placeholder()
        self._update_clickability()

    def _show_placeholder(self, text: str | None = None) -> None:
        """Display placeholder text."""
        self._canvas.delete("all")
        display_text = text or self._placeholder_text
        self._placeholder_shown = display_text
        self._source_image = None
        self._canvas.create_text(
            self._width // 2,
            self._height // 2,
            text=display_text,
            fill=TEXT_MUTED,
            font=("Segoe UI", 9),
            anchor="center",
        )

    def set_image(self, image: Image.Image | None) -> None:
        """Set the displayed thumbnail from a PIL Image."""
        if image is None:
            self.clear()
            return

        try:
            from PIL import ImageTk

            if self._responsive:
                self._source_image = image
                image = self._fitted(image)

            # Keep reference to prevent garbage collection
            self._photo_image = ImageTk.PhotoImage(image)

            self._canvas.delete("all")
            self._placeholder_shown = None
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
        key = str(path)
        self._current_path = key
        self._open_path = key
        self._update_clickability()
        if self._inflight_path == key:
            return  # the same decode is already running; its result is still the current request
        self._request_id += 1
        request_id = self._request_id
        self._inflight_path = key
        self.set_loading()
        # Responsive previews decode once at the maximum edge and are rescaled for narrower parents.
        decode_size = (
            (self._max_edge, self._max_edge) if self._responsive else (self._width, self._height)
        )

        def _load() -> None:
            from src.utils.image_utils import load_image_thumbnail

            thumb = load_image_thumbnail(path, decode_size)

            # Schedule UI update on main thread
            try:
                self.after(0, lambda: self._on_image_loaded(thumb, request_id, key))
            except (RuntimeError, tk.TclError) as e:
                # Widget or Tk root was torn down while the background load completed.
                logger.debug(
                    f"ThumbnailWidget teardown race condition detected (id={id(self)}): {e}",
                    exc_info=False,
                )
                return

        # PR-THREAD-001: Use ThreadRegistry for thumbnail loading
        from src.utils.thread_registry import get_thread_registry

        registry = get_thread_registry()
        self._load_thread = registry.spawn(
            target=_load,
            name=f"Thumbnail-Loader-{id(self)}",
            daemon=False,
            purpose="Load and cache thumbnail image asynchronously",
        )

    def _on_image_loaded(
        self,
        image: Image.Image | None,
        request_id: int | None = None,
        path: str | None = None,
    ) -> None:
        """Handle async image load completion; superseded or post-destroy results are dropped."""
        if request_id is not None:
            if request_id != self._request_id or self._destroyed:
                return
            if path is not None and path == self._inflight_path:
                self._inflight_path = None
        if self._destroyed:
            return
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        if image is None:
            self._show_placeholder("Not found")
        else:
            self.set_image(image)

    # -- responsive fitting (PR-GUI-110) ----------------------------------------------------------------------------

    def _fitted(self, image: Image.Image) -> Image.Image:
        from src.utils.image_utils import generate_thumbnail

        side = self._width
        if image.width <= side and image.height <= side:
            return image
        return generate_thumbnail(image, (side, side))

    def _schedule_fit(self, _event: tk.Event | None = None) -> None:
        if not self._responsive or self._fit_job is not None or self._destroyed:
            return
        if not self._has_fit and self.winfo_width() > 1:
            self._has_fit = True  # the first real width is applied immediately: no wrong-size flash
            self._fit_now()
            return
        try:
            self._fit_job = self.after(RESIZE_COALESCE_MS, self._fit_now)
        except tk.TclError:
            self._fit_job = None

    def _fit_now(self) -> None:
        self._fit_job = None
        if self._destroyed:
            return
        try:
            if not self.winfo_exists():
                return
            side = preview_side(
                self.winfo_width(), max_edge=self._max_edge, min_edge=self._min_edge
            )
            if not preview_resize_needed(self._width, side):
                return
            self._width = self._height = side
            self._canvas.configure(width=side, height=side)
            self.configure(height=side + 2)
            self._render_current()
        except tk.TclError:
            return

    def fitted_edge(self) -> int:
        """Current square edge in pixels (the configured size for non-responsive widgets)."""
        return int(self._width)

    def _render_current(self) -> None:
        if self._source_image is not None:
            self.set_image(self._source_image)
        elif self._placeholder_shown is not None:
            self._show_placeholder(self._placeholder_shown)

    def destroy(self) -> None:
        self._destroyed = True
        self._request_id += 1  # any in-flight decode is now stale
        if self._fit_job is not None:
            try:
                self.after_cancel(self._fit_job)
            except tk.TclError:
                pass
            self._fit_job = None
        super().destroy()

    def set_image_from_base64(self, data: str) -> None:
        """Load and display thumbnail from base64 string."""
        import base64
        import io

        try:
            self._invalidate_pending_load()
            self._current_path = None
            self._open_path = None
            self._update_clickability()
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
        self._invalidate_pending_load()
        self._photo_image = None
        self._current_path = None
        self._open_path = None
        self._show_placeholder()
        self._update_clickability()

    def set_placeholder(self, text: str) -> None:
        """Show an explicit neutral state without implying an image exists."""
        self._invalidate_pending_load()
        self._photo_image = None
        self._current_path = None
        self._open_path = None
        self._show_placeholder(text)
        self._update_clickability()

    def _invalidate_pending_load(self) -> None:
        """A newer explicit state supersedes any decode still in flight."""
        self._request_id += 1
        self._inflight_path = None

    def set_loading(self) -> None:
        """Show loading indicator."""
        self._show_placeholder("Loading...")

    def set_open_target(self, path: Path | str | None) -> None:
        """Set the file path opened when the thumbnail is activated."""
        self._open_path = None if path in (None, "") else str(path)
        self._update_clickability()

    def _on_activate(self, _event: tk.Event | None = None) -> None:
        self._open_current_path()

    def _open_current_path(self) -> None:
        target = self._open_path or self._current_path
        if not target:
            return
        candidate = Path(target)
        if not candidate.exists():
            return
        try:
            if os.name == "nt":
                os.startfile(str(candidate))
            elif os.sys.platform == "darwin":
                subprocess.Popen(["open", str(candidate)])
            else:
                subprocess.Popen(["xdg-open", str(candidate)])
        except Exception:
            logger.exception("Failed to open thumbnail target: %s", candidate)

    def _update_clickability(self) -> None:
        target = self._open_path or self._current_path
        cursor = "hand2" if target else ""
        try:
            self._canvas.configure(cursor=cursor)
        except Exception:
            pass
