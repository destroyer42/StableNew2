"""Tests for Stage Chooser modal dialog."""

import queue
from pathlib import Path
from unittest.mock import Mock

import pytest

# Skip tests if tkinter is not available
pytest.importorskip("tkinter")

import tkinter as tk

from src.gui.stage_chooser import StageChoice, StageChooser


class TestStageChooser:
    """Test StageChooser modal dialog."""

    @pytest.fixture
    def root(self):
        """Create root window for testing."""
        root = tk.Tk()
        root.withdraw()  # Hide window during tests
        yield root
        try:
            root.destroy()
        except tk.TclError:
            # Ignore errors if the window is already destroyed or not fully initialized
            pass

    def test_stage_choice_enum(self):
        """Test StageChoice enum values."""
        assert StageChoice.IMG2IMG.value == "img2img"
        assert StageChoice.ADETAILER.value == "adetailer"
        assert StageChoice.UPSCALE.value == "upscale"
        assert StageChoice.NONE.value == "none"

    def test_stage_chooser_creation(self, root):
        """Test StageChooser window creation."""
        result_queue = queue.Queue()
        image_path = Path("test.png")

        chooser = StageChooser(
            parent=root,
            image_path=image_path,
            image_index=1,
            total_images=5,
            result_queue=result_queue,
        )

        assert chooser.window is not None
        assert chooser.image_path == image_path
        assert chooser.image_index == 1
        assert chooser.total_images == 5
        assert chooser.result_queue == result_queue
        assert chooser.selected_choice is None
        assert chooser.apply_to_batch is False

    def test_choice_selection_img2img(self, root):
        """Test selecting img2img choice."""
        result_queue = queue.Queue()
        chooser = StageChooser(
            parent=root,
            image_path=Path("test.png"),
            image_index=1,
            total_images=5,
            result_queue=result_queue,
        )

        # Simulate choosing img2img
        chooser._select_choice(StageChoice.IMG2IMG)

        # Check result was queued
        assert not result_queue.empty()
        result = result_queue.get_nowait()
        assert result["choice"] == StageChoice.IMG2IMG
        assert result["apply_to_batch"] is False
        assert result["cancelled"] is False

    def test_choice_with_batch_toggle(self, root):
        """Test selecting choice with batch toggle enabled."""
        result_queue = queue.Queue()
        chooser = StageChooser(
            parent=root,
            image_path=Path("test.png"),
            image_index=1,
            total_images=5,
            result_queue=result_queue,
        )

        # Enable batch toggle
        chooser.batch_var.set(True)
        chooser._select_choice(StageChoice.UPSCALE)

        # Check result includes batch setting
        result = result_queue.get_nowait()
        assert result["choice"] == StageChoice.UPSCALE
        assert result["apply_to_batch"] is True

    def test_cancel_choice(self, root):
        """Test canceling the chooser."""
        result_queue = queue.Queue()
        chooser = StageChooser(
            parent=root,
            image_path=Path("test.png"),
            image_index=1,
            total_images=5,
            result_queue=result_queue,
        )

        chooser._on_cancel()

        # Check cancel result
        result = result_queue.get_nowait()
        assert result["cancelled"] is True
        assert result["choice"] is None

    def test_multi_image_workflow(self, root):
        """Test workflow with multiple images."""
        result_queue = queue.Queue()

        # First image - choose img2img
        chooser1 = StageChooser(
            parent=root,
            image_path=Path("image1.png"),
            image_index=1,
            total_images=3,
            result_queue=result_queue,
        )
        chooser1._select_choice(StageChoice.IMG2IMG)

        result1 = result_queue.get_nowait()
        assert result1["choice"] == StageChoice.IMG2IMG

        # Second image - choose upscale
        chooser2 = StageChooser(
            parent=root,
            image_path=Path("image2.png"),
            image_index=2,
            total_images=3,
            result_queue=result_queue,
        )
        chooser2._select_choice(StageChoice.UPSCALE)

        result2 = result_queue.get_nowait()
        assert result2["choice"] == StageChoice.UPSCALE

    def test_batch_persistence(self, root):
        """Test that batch choice persists for remaining images."""
        result_queue = queue.Queue()

        # First image with batch toggle
        chooser = StageChooser(
            parent=root,
            image_path=Path("image1.png"),
            image_index=1,
            total_images=5,
            result_queue=result_queue,
        )
        chooser.batch_var.set(True)
        chooser._select_choice(StageChoice.ADETAILER)

        result = result_queue.get_nowait()
        assert result["apply_to_batch"] is True
        assert result["choice"] == StageChoice.ADETAILER

        # This result should be used for remaining images without showing modal again

    def test_window_title_shows_progress(self, root):
        """Test that window title shows image progress."""
        chooser = StageChooser(
            parent=root,
            image_path=Path("test.png"),
            image_index=3,
            total_images=10,
            result_queue=queue.Queue(),
        )

        title = chooser.window.title()
        assert "3" in title
        assert "10" in title

    def test_retune_settings_callback(self, root):
        """Test re-tune settings callback."""
        result_queue = queue.Queue()
        retune_callback = Mock()

        chooser = StageChooser(
            parent=root,
            image_path=Path("test.png"),
            image_index=1,
            total_images=5,
            result_queue=result_queue,
            on_retune=retune_callback,
        )

        chooser._on_retune()

        # Check callback was invoked
        retune_callback.assert_called_once()


class TestStageChooserIntegration:
    """Integration tests for StageChooser with pipeline."""

    @pytest.fixture
    def root(self):
        """Create root window for testing."""
        root = tk.Tk()
        root.withdraw()
        yield root
        try:
            root.destroy()
        except tk.TclError:
            # Ignore errors if the window is already destroyed or not fully initialized
            pass

    def test_queue_communication_non_blocking(self, root):
        """Test that queue communication is non-blocking."""
        result_queue = queue.Queue()

        chooser = StageChooser(
            parent=root,
            image_path=Path("test.png"),
            image_index=1,
            total_images=5,
            result_queue=result_queue,
        )

        # Queue should be empty before choice
        assert result_queue.empty()

        # Make a choice
        chooser._select_choice(StageChoice.UPSCALE)

        # Result should be immediately available (non-blocking)
        assert not result_queue.empty()
        result = result_queue.get_nowait()
        assert result is not None

    def test_image_preview_loading(self, root):
        """Test image preview loading."""
        result_queue = queue.Queue()

        # Create a temporary test image
        import tempfile

        from PIL import Image

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            img = Image.new("RGB", (100, 100), color="red")
            img.save(tmp.name)
            tmp_path = Path(tmp.name)

        try:
            chooser = StageChooser(
                parent=root,
                image_path=tmp_path,
                image_index=1,
                total_images=1,
                result_queue=result_queue,
            )

            # Preview label should exist
            assert hasattr(chooser, "preview_label")

        finally:
            # Clean up
            tmp_path.unlink()
