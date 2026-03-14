"""Video creation utilities using FFmpeg."""

import logging
import os
import shutil
import subprocess
from pathlib import Path

from src.utils import save_image_from_base64

logger = logging.getLogger(__name__)


def _candidate_ffmpeg_paths() -> list[Path]:
    """Return likely FFmpeg executable candidates in preferred order."""
    candidates: list[Path] = []
    env_override = os.environ.get("STABLENEW_FFMPEG_PATH", "").strip()
    if env_override:
        candidates.append(Path(env_override).expanduser())

    which_path = shutil.which("ffmpeg")
    if which_path:
        candidates.append(Path(which_path))

    if os.name == "nt":
        local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
        if local_appdata:
            candidates.append(Path(local_appdata) / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe")
            candidates.extend(
                sorted(
                    (
                        Path(local_appdata)
                        / "Microsoft"
                        / "WinGet"
                        / "Packages"
                    ).glob("*FFmpeg*\\**\\bin\\ffmpeg.exe")
                )
            )

        candidates.extend(
            [
                Path.home() / "scoop" / "shims" / "ffmpeg.exe",
                Path("C:/ffmpeg/bin/ffmpeg.exe"),
                Path("C:/tools/ffmpeg/bin/ffmpeg.exe"),
                Path("C:/Program Files/ffmpeg/bin/ffmpeg.exe"),
                Path("C:/Program Files (x86)/ffmpeg/bin/ffmpeg.exe"),
            ]
        )

    return candidates


def resolve_ffmpeg_executable() -> Path | None:
    """Resolve the FFmpeg executable path."""
    seen: set[str] = set()
    for candidate in _candidate_ffmpeg_paths():
        normalized = str(candidate).lower() if os.name == "nt" else str(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _write_concat_input_file(image_paths: list[Path], list_file: Path, frame_duration: float) -> None:
    """Write an FFmpeg concat-demuxer input file for still images."""
    with list_file.open("w", encoding="utf-8") as f:
        for img_path in image_paths:
            escaped = str(img_path.absolute()).replace("'", r"'\''")
            f.write(f"file '{escaped}'\n")
            f.write(f"duration {frame_duration}\n")
        if image_paths:
            escaped = str(image_paths[-1].absolute()).replace("'", r"'\''")
            f.write(f"file '{escaped}'\n")


def write_video_frames(
    frame_images: list[str],
    frames_dir: Path,
    *,
    frame_prefix: str = "frame",
) -> list[Path]:
    """Persist base64 video frames to disk with deterministic sequential names."""

    frames_dir.mkdir(parents=True, exist_ok=True)
    saved_paths: list[Path] = []
    for index, frame_image in enumerate(frame_images):
        frame_path = frames_dir / f"{frame_prefix}_{index:06d}.png"
        actual_path = save_image_from_base64(frame_image, frame_path)
        if actual_path:
            saved_paths.append(actual_path)
    return saved_paths


class VideoCreator:
    """Create videos from image sequences using FFmpeg."""

    def __init__(self):
        """Initialize video creator."""
        self.ffmpeg_executable = resolve_ffmpeg_executable()
        self.ffmpeg_available = self._check_ffmpeg()

    def _check_ffmpeg(self) -> bool:
        """
        Check if FFmpeg is available.

        Returns:
            True if FFmpeg is available
        """
        if not self.ffmpeg_executable:
            logger.warning(
                "FFmpeg executable could not be resolved; checked PATH, "
                "STABLENEW_FFMPEG_PATH, and common Windows install locations"
            )
            return False

        try:
            result = subprocess.run(
                [str(self.ffmpeg_executable), "-version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                logger.info("FFmpeg is available: %s", self.ffmpeg_executable)
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.warning("FFmpeg not found or not responding: %s", self.ffmpeg_executable)

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

                # Prefer symlinks for speed, but fall back to a real copy on
                # Windows installs that do not have symlink privileges.
                try:
                    temp_path.symlink_to(img_path.absolute())
                except Exception:
                    try:
                        shutil.copy2(img_path, temp_path)
                    except Exception as e:
                        logger.warning(f"Failed to link/copy {img_path.name}: {e}")
                        continue
                    temp_images.append(temp_path)
                    continue
                temp_images.append(temp_path)

            if not temp_images:
                logger.error("No valid images for video creation")
                return False

            list_file = output_path.parent / "ffmpeg_input.txt"
            _write_concat_input_file(temp_images, list_file, 1 / max(1, fps))

            cmd = [
                str(self.ffmpeg_executable),
                "-f",
                "concat",
                "-safe",
                "0",
                "-y",  # Overwrite output
                "-i",
                str(list_file),
                "-c:v",
                codec,
                "-preset",
                quality,
                "-pix_fmt",
                "yuv420p",  # Compatibility
                "-r",
                str(fps),
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
                list_file.unlink(missing_ok=True)
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
        codec: str = "libx264",
        quality: str = "medium",
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
            per_image_duration = max(duration_per_image, 1 / max(1, fps))
            _write_concat_input_file(image_paths, list_file, per_image_duration)

            # Build FFmpeg command
            cmd = [
                str(self.ffmpeg_executable),
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
                "-r",
                str(fps),
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
