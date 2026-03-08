"""Tests for image utility functions."""

import io
from pathlib import Path

import pytest
from PIL import Image as PILImage

from src.utils.image_utils import generate_thumbnail, load_image_thumbnail


class TestGenerateThumbnail:
    """Test generate_thumbnail function."""

    def test_generate_thumbnail_preserves_aspect(self) -> None:
        """Test that aspect ratio is preserved."""
        # Create a 1000x500 image (2:1 aspect ratio)
        img = PILImage.new("RGB", (1000, 500), color="red")

        thumb = generate_thumbnail(img, max_size=(150, 150), preserve_aspect=True)

        # Should be scaled to 150x75 (maintaining 2:1 ratio)
        assert thumb.width == 150
        assert thumb.height == 75

    def test_generate_thumbnail_fits_max_size(self) -> None:
        """Test that thumbnail doesn't exceed max dimensions."""
        img = PILImage.new("RGB", (2000, 2000), color="blue")

        thumb = generate_thumbnail(img, max_size=(150, 150), preserve_aspect=True)

        # Should be exactly 150x150
        assert thumb.width == 150
        assert thumb.height == 150

    def test_generate_thumbnail_with_background(self) -> None:
        """Test letterboxing with background color."""
        # Create a 1000x500 image (wide)
        img = PILImage.new("RGB", (1000, 500), color="green")

        thumb = generate_thumbnail(
            img, max_size=(150, 150), preserve_aspect=True, background="#000000"
        )

        # Should have letterbox bars (150x150 canvas with image centered)
        assert thumb.width == 150
        assert thumb.height == 150
        # Mode should be RGBA for background support
        assert thumb.mode == "RGBA"

    def test_generate_thumbnail_without_preserve_aspect(self) -> None:
        """Test that image is stretched when preserve_aspect=False."""
        img = PILImage.new("RGB", (1000, 500), color="yellow")

        thumb = generate_thumbnail(img, max_size=(150, 150), preserve_aspect=False)

        # Should be stretched to exact size
        assert thumb.width == 150
        assert thumb.height == 150

    def test_generate_thumbnail_portrait(self) -> None:
        """Test thumbnail generation for portrait-oriented image."""
        # Create a 500x1000 image (tall)
        img = PILImage.new("RGB", (500, 1000), color="purple")

        thumb = generate_thumbnail(img, max_size=(150, 150), preserve_aspect=True)

        # Should be scaled to 75x150
        assert thumb.width == 75
        assert thumb.height == 150


class TestLoadImageThumbnail:
    """Test load_image_thumbnail function."""

    def test_load_image_thumbnail_valid_file(self, tmp_path: Path) -> None:
        """Test loading a valid image file."""
        # Create a temporary test image
        img = PILImage.new("RGB", (800, 600), color="cyan")
        img_path = tmp_path / "test.png"
        img.save(img_path)

        thumb = load_image_thumbnail(img_path, max_size=(150, 150))

        assert thumb is not None
        assert thumb.width <= 150
        assert thumb.height <= 150

    def test_load_image_thumbnail_missing_file(self, tmp_path: Path) -> None:
        """Test handling of missing file."""
        missing_path = tmp_path / "nonexistent.png"

        thumb = load_image_thumbnail(missing_path)

        assert thumb is None

    def test_load_image_thumbnail_corrupt_file(self, tmp_path: Path) -> None:
        """Test handling of corrupt/invalid image file."""
        corrupt_path = tmp_path / "corrupt.png"
        corrupt_path.write_text("This is not an image")

        thumb = load_image_thumbnail(corrupt_path)

        assert thumb is None

    def test_load_image_thumbnail_converts_mode(self, tmp_path: Path) -> None:
        """Test that non-RGB modes are converted."""
        # Create a grayscale image
        img = PILImage.new("L", (800, 600), color=128)
        img_path = tmp_path / "grayscale.png"
        img.save(img_path)

        thumb = load_image_thumbnail(img_path)

        assert thumb is not None
        # Should be converted to RGB
        assert thumb.mode in ("RGB", "RGBA")

    def test_load_image_thumbnail_with_string_path(self, tmp_path: Path) -> None:
        """Test that string paths work as well as Path objects."""
        img = PILImage.new("RGB", (800, 600), color="magenta")
        img_path = tmp_path / "test_string.png"
        img.save(img_path)

        # Pass as string
        thumb = load_image_thumbnail(str(img_path))

        assert thumb is not None
        assert thumb.width <= 150
        assert thumb.height <= 150
