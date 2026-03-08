"""Tests for ImageThumbnail widget."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def test_thumbnail_handles_missing_pil():
    """Verify graceful degradation without PIL."""
    from src.gui.widgets import image_thumbnail

    # Module should load regardless of PIL availability
    assert hasattr(image_thumbnail, "ImageThumbnail")
    assert hasattr(image_thumbnail, "PIL_AVAILABLE")


def test_thumbnail_handles_missing_file():
    """Verify error handling for missing files."""
    from src.gui.widgets.image_thumbnail import ImageThumbnail

    # Create mock widget
    thumb = ImageThumbnail.__new__(ImageThumbnail)
    thumb.max_width = 300
    thumb.max_height = 300
    thumb._photo_image = None
    thumb._current_path = None
    thumb.delete = MagicMock()
    thumb.create_text = MagicMock()
    thumb.winfo_width = MagicMock(return_value=300)
    thumb.winfo_height = MagicMock(return_value=300)

    # Load non-existent file
    result = thumb.load_image("/nonexistent/path/image.png")

    assert result is False
    thumb.create_text.assert_called()  # Should show placeholder


@pytest.mark.skipif(True, reason="Requires full Tkinter environment - tested manually")
def test_thumbnail_loads_valid_image():
    """Verify loading a valid image file."""
    from PIL import Image

    from src.gui.widgets.image_thumbnail import ImageThumbnail

    # Create a test image
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        img = Image.new("RGB", (100, 100), color="red")
        img.save(f.name)

        # Create mock widget
        thumb = ImageThumbnail.__new__(ImageThumbnail)
        thumb.max_width = 300
        thumb.max_height = 300
        thumb._photo_image = None
        thumb._current_path = None
        thumb.delete = MagicMock()
        thumb.create_image = MagicMock()
        thumb.winfo_width = MagicMock(return_value=300)
        thumb.winfo_height = MagicMock(return_value=300)

        result = thumb.load_image(f.name)

        assert result is True
        thumb.create_image.assert_called()

        # Cleanup
        Path(f.name).unlink(missing_ok=True)


def test_thumbnail_clear():
    """Verify clearing thumbnail resets state."""
    from src.gui.widgets.image_thumbnail import ImageThumbnail

    thumb = ImageThumbnail.__new__(ImageThumbnail)
    thumb.max_width = 300
    thumb.max_height = 300
    thumb._photo_image = "fake_image"
    thumb._current_path = "/some/path.png"
    thumb.delete = MagicMock()
    thumb.create_text = MagicMock()
    thumb.winfo_width = MagicMock(return_value=300)
    thumb.winfo_height = MagicMock(return_value=300)

    thumb.clear()

    assert thumb._photo_image is None
    assert thumb._current_path is None
    thumb.delete.assert_called_with("all")
    thumb.create_text.assert_called()
