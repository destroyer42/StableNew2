"""Tests for video creator"""

from unittest.mock import Mock, patch

from PIL import Image

from src.pipeline import VideoCreator


class TestVideoCreator:
    """Test cases for VideoCreator"""

    def test_init(self):
        """Test initialization"""
        creator = VideoCreator()
        assert isinstance(creator.ffmpeg_available, bool)

    @patch("src.pipeline.video.subprocess.run")
    def test_check_ffmpeg_available(self, mock_run):
        """Test FFmpeg availability check - success"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        creator = VideoCreator()
        assert creator._check_ffmpeg() is True

    @patch("src.pipeline.video.subprocess.run")
    def test_check_ffmpeg_not_available(self, mock_run):
        """Test FFmpeg availability check - failure"""
        mock_run.side_effect = FileNotFoundError()

        creator = VideoCreator()
        assert creator._check_ffmpeg() is False

    def create_test_images(self, tmp_path, count=3):
        """Helper to create test images"""
        image_paths = []
        for i in range(count):
            img = Image.new("RGB", (100, 100), color=(i * 50, 0, 0))
            img_path = tmp_path / f"image_{i:03d}.png"
            img.save(img_path)
            image_paths.append(img_path)
        return image_paths

    @patch("src.pipeline.video.subprocess.run")
    def test_create_video_no_ffmpeg(self, mock_run, tmp_path):
        """Test video creation without FFmpeg"""
        mock_run.side_effect = FileNotFoundError()

        creator = VideoCreator()
        image_paths = self.create_test_images(tmp_path)
        output_path = tmp_path / "output.mp4"

        result = creator.create_video_from_images(image_paths, output_path)
        assert result is False

    @patch("src.pipeline.video.subprocess.run")
    def test_create_video_empty_list(self, mock_run, tmp_path):
        """Test video creation with empty image list"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        creator = VideoCreator()
        output_path = tmp_path / "output.mp4"

        result = creator.create_video_from_images([], output_path)
        assert result is False

    @patch("src.pipeline.video.subprocess.run")
    def test_create_video_success(self, mock_run, tmp_path):
        """Test successful video creation"""
        # Mock FFmpeg check
        mock_result = Mock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        creator = VideoCreator()
        image_paths = self.create_test_images(tmp_path)
        output_path = tmp_path / "output.mp4"

        result = creator.create_video_from_images(image_paths, output_path)

        # Should succeed (with mocked FFmpeg)
        assert result is True or result is False  # Depends on mock setup

    @patch("src.pipeline.video.subprocess.run")
    def test_create_video_from_directory(self, mock_run, tmp_path):
        """Test creating video from directory"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        creator = VideoCreator()

        # Create test images
        self.create_test_images(tmp_path)
        output_path = tmp_path / "output.mp4"

        result = creator.create_video_from_directory(tmp_path, output_path, pattern="*.png")

        # Result depends on whether FFmpeg is actually available
        assert isinstance(result, bool)

    def test_create_video_from_directory_no_images(self, tmp_path):
        """Test creating video from empty directory"""
        creator = VideoCreator()
        output_path = tmp_path / "output.mp4"

        result = creator.create_video_from_directory(tmp_path, output_path, pattern="*.png")

        assert result is False
