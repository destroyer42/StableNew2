"""Video creation utilities using FFmpeg"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class VideoCreator:
    """Create videos from image sequences using FFmpeg"""

    def __init__(self):
        """Initialize video creator"""
        self.ffmpeg_available = self._check_ffmpeg()

    def _check_ffmpeg(self) -> bool:
        """
        Check if FFmpeg is available.

        Returns:
            True if FFmpeg is available
        """
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                logger.info("FFmpeg is available")
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.warning("FFmpeg not found or not responding")

        return False

    def create_video_from_images(
        self,
        image_paths: list[Path],
        output_path: Path,
        fps: int = 24,
        codec: str = "libx264",
        quality: str = "medium",
    ) -> bool:
        """
        Create video from a list of images.

        Args:
            image_paths: List of paths to images
            output_path: Path for output video
            fps: Frames per second (default: 24)
            codec: Video codec (default: libx264)
            quality: Quality preset (default: medium)

        Returns:
            True if video created successfully
        """
        if not self.ffmpeg_available:
            logger.error("FFmpeg not available, cannot create video")
            return False

        if not image_paths:
            logger.error("No images provided for video creation")
            return False

        try:
            # Sort images by name for proper sequence
            sorted_paths = sorted(image_paths, key=lambda x: x.name)

            # Create temporary file list for FFmpeg
            temp_dir = output_path.parent / "temp"
            temp_dir.mkdir(exist_ok=True)

            # Copy/symlink images with sequential names
            temp_images = []
            for i, img_path in enumerate(sorted_paths):
                if not img_path.exists():
                    logger.warning(f"Image not found: {img_path}")
                    continue

                temp_name = f"frame_{i:06d}{img_path.suffix}"
                temp_path = temp_dir / temp_name

                # Create symlink or copy
                try:
                    if hasattr(temp_path, "symlink_to"):
                        temp_path.symlink_to(img_path.absolute())
                    else:
                        import shutil

                        shutil.copy2(img_path, temp_path)
                    temp_images.append(temp_path)
                except Exception as e:
                    logger.warning(f"Failed to link/copy {img_path.name}: {e}")

            if not temp_images:
                logger.error("No valid images for video creation")
                return False

            # Build FFmpeg command
            input_pattern = str(temp_dir / "frame_%06d*")

            cmd = [
                "ffmpeg",
                "-y",  # Overwrite output
                "-framerate",
                str(fps),
                "-pattern_type",
                "glob",
                "-i",
                input_pattern,
                "-c:v",
                codec,
                "-preset",
                quality,
                "-pix_fmt",
                "yuv420p",  # Compatibility
                str(output_path),
            ]

            logger.info(f"Creating video with {len(temp_images)} frames")
            logger.info(f"FFmpeg command: {' '.join(cmd)}")

            # Execute FFmpeg
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            # Cleanup temp directory
            try:
                import shutil

                shutil.rmtree(temp_dir)
            except Exception as e:
                logger.warning(f"Failed to cleanup temp directory: {e}")

            if result.returncode == 0:
                logger.info(f"Video created successfully: {output_path.name}")
                return True
            else:
                logger.error(f"FFmpeg failed: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("FFmpeg timed out")
            return False
        except Exception as e:
            logger.error(f"Video creation failed: {e}")
            return False

    def create_slideshow_video(
        self,
        image_paths: list[Path],
        output_path: Path,
        duration_per_image: float = 3.0,
        transition_duration: float = 0.5,
        fps: int = 24,
    ) -> bool:
        """
        Create a slideshow video with transitions.

        Args:
            image_paths: List of paths to images
            output_path: Path for output video
            duration_per_image: Duration each image is shown (seconds)
            transition_duration: Duration of fade transitions (seconds)
            fps: Frames per second

        Returns:
            True if video created successfully
            fps: Frames per second
            codec: Video codec to use
            quality: Video quality preset

        Returns:
            True if video created successfully
        """
        if not self.ffmpeg_available:
            logger.error("FFmpeg is not available")
            return False

        if not image_paths:
            logger.error("No images provided")
            return False

        try:
            # Create a temporary file list for FFmpeg
            list_file = output_path.parent / "ffmpeg_input.txt"
            with open(list_file, "w", encoding="utf-8") as f:
                for img_path in image_paths:
                    # FFmpeg concat demuxer format
                    f.write(f"file '{img_path.absolute()}'\n")
                    f.write(f"duration {1/fps}\n")
                # Add last image again for proper duration
                if image_paths:
                    f.write(f"file '{image_paths[-1].absolute()}'\n")

            # Build FFmpeg command
            cmd = [
                "ffmpeg",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c:v",
                codec,
                "-preset",
                quality,
                "-pix_fmt",
                "yuv420p",
                "-y",  # Overwrite output file
                str(output_path),
            ]

            logger.info(f"Creating video with {len(image_paths)} images at {fps} fps")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            # Clean up temp file
            list_file.unlink(missing_ok=True)

            if result.returncode == 0:
                logger.info(f"Video created successfully: {output_path.name}")
                return True
            else:
                logger.error(f"FFmpeg failed: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("FFmpeg command timed out")
            return False
        except Exception as e:
            logger.error(f"Failed to create video: {e}")
            return False

    def create_video_from_directory(
        self,
        image_dir: Path,
        output_path: Path,
        pattern: str = "*.png",
        fps: int = 24,
        codec: str = "libx264",
        quality: str = "medium",
    ) -> bool:
        """
        Create video from all images in a directory.

        Args:
            image_dir: Directory containing images
            output_path: Path for output video
            pattern: Glob pattern for image files
            fps: Frames per second
            codec: Video codec to use
            quality: Video quality preset

        Returns:
            True if video created successfully
        """
        image_paths = sorted(image_dir.glob(pattern))
        if not image_paths:
            logger.warning(f"No images found in {image_dir} with pattern {pattern}")
            return False

        logger.info(f"Found {len(image_paths)} images in {image_dir}")
        return self.create_video_from_images(image_paths, output_path, fps, codec, quality)
