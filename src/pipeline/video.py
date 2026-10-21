"""Video creation utilities using FFmpeg."""

import logging
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src.utils import save_image_from_base64
from src.utils.managed_process import run_bounded

logger = logging.getLogger(__name__)

#: x264/x265 speed presets; any other ``quality`` value keeps the default preset.
X264_PRESETS = frozenset(
    {
        "ultrafast",
        "superfast",
        "veryfast",
        "faster",
        "fast",
        "medium",
        "slow",
        "slower",
        "veryslow",
    }
)
_CRF_CODECS = frozenset({"libx264", "libx265"})
_FASTSTART_SUFFIXES = frozenset({".mp4", ".mov", ".m4v"})
ENCODE_TIMEOUT_SECONDS = 900.0
_ENCODE_MAX_STDOUT_BYTES = 64 * 1024
_ENCODE_MAX_STDERR_BYTES = 256 * 1024


@dataclass(frozen=True)
class VideoEncodeSettings:
    """How StableNew encodes every MP4 it writes from frames.

    CRF (constant quality) instead of x264's default 23: 16 is visually transparent for
    generated video. Frames are RGB PNGs, so the RGB->YUV conversion is pinned to BT.709 and
    the stream is tagged, which keeps colours stable across players. ``+faststart`` lets a
    clip start playing before it is fully read.
    """

    crf: int = 16
    preset: str = "slow"
    pix_fmt: str = "yuv420p"

    def __post_init__(self) -> None:
        if not 0 <= int(self.crf) <= 51:
            raise ValueError("crf must be in 0..51")
        if self.preset not in X264_PRESETS:
            raise ValueError(f"Unknown encoder preset: {self.preset}")


#: Operator-facing encode profiles. ``balanced`` is the default. Names must not collide with
#: an x264 preset name, which ``quality`` also accepts.
ENCODE_PROFILES: dict[str, VideoEncodeSettings] = {
    "draft": VideoEncodeSettings(crf=20, preset="medium"),
    "balanced": VideoEncodeSettings(crf=16, preset="slow"),
    "archival": VideoEncodeSettings(crf=12, preset="slow"),
}
DEFAULT_ENCODE_SETTINGS = ENCODE_PROFILES["balanced"]


def resolve_encode_settings(
    quality: str | None, settings: VideoEncodeSettings | None = None
) -> VideoEncodeSettings:
    """Resolve the settings for a legacy ``quality`` argument.

    ``quality`` historically carried an x264 speed preset name; it still selects the preset,
    but no longer leaves the quality at x264's CRF 23 default. A profile name selects a profile.
    """

    if settings is not None:
        return settings
    key = str(quality or "").strip().lower()
    if key in ENCODE_PROFILES:
        return ENCODE_PROFILES[key]
    if key in X264_PRESETS:
        return VideoEncodeSettings(crf=DEFAULT_ENCODE_SETTINGS.crf, preset=key)
    return DEFAULT_ENCODE_SETTINGS


def build_video_encode_filter() -> str:
    """The colour/size filter every encode ends with (BT.709, even dimensions).

    Even dimensions are required by 4:2:0; the matrix is pinned so the tags are true. setparams stamps the frames too:
    FFmpeg lets frame colour properties override the output-level tags, which alone leave primaries and transfer
    "unknown". A ``-filter_complex`` graph appends this to its last video chain instead of passing ``-vf``.
    """

    return (
        "scale=trunc(iw/2)*2:trunc(ih/2)*2:out_color_matrix=bt709:out_range=tv,"
        "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv"
    )


def build_video_encode_args(
    *,
    codec: str,
    settings: VideoEncodeSettings,
    output_path: Path,
    include_filter: bool = True,
) -> list[str]:
    """Encoder arguments shared by every frames-to-video path.

    ``include_filter=False`` leaves out ``-vf`` for a caller whose ``-filter_complex`` graph already ends with
    ``build_video_encode_filter()`` (FFmpeg refuses both on one output stream).
    """

    args = ["-c:v", codec]
    if codec in _CRF_CODECS:
        args += ["-crf", str(int(settings.crf)), "-preset", settings.preset]
    if include_filter:
        args += ["-vf", build_video_encode_filter()]
    args += [
        "-pix_fmt",
        settings.pix_fmt,
        "-colorspace",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-color_range",
        "tv",
    ]
    if output_path.suffix.lower() in _FASTSTART_SUFFIXES:
        args += ["-movflags", "+faststart"]
    return args


class VideoEncodeCancelled(RuntimeError):
    """The encode was stopped by its cancel signal; the partial output was removed."""


def run_ffmpeg(
    cmd: list[str],
    *,
    timeout_seconds: float = ENCODE_TIMEOUT_SECONDS,
    cancel: Callable[[], bool] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one FFmpeg command contained, bounded and cancellable.

    Raises ``VideoEncodeCancelled`` on cancel. A timeout or launch failure is returned as a
    failed ``CompletedProcess`` so callers keep their existing failure reporting.
    """

    outcome = run_bounded(
        cmd,
        timeout_seconds=timeout_seconds,
        max_stdout_bytes=_ENCODE_MAX_STDOUT_BYTES,
        max_stderr_bytes=_ENCODE_MAX_STDERR_BYTES,
        cancel=cancel,
    )
    if outcome.cancelled:
        raise VideoEncodeCancelled("FFmpeg encode cancelled")
    stderr = outcome.stderr.decode("utf-8", errors="replace")
    if outcome.launch_error:
        return subprocess.CompletedProcess(cmd, -1, "", f"could not start: {outcome.launch_error}")
    if outcome.timed_out:
        return subprocess.CompletedProcess(
            cmd, -1, "", f"timed out after {timeout_seconds:.0f}s and was stopped. {stderr}"
        )
    return subprocess.CompletedProcess(
        cmd,
        outcome.returncode if outcome.returncode is not None else -1,
        outcome.stdout.decode("utf-8", errors="replace"),
        stderr,
    )


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
                    (Path(local_appdata) / "Microsoft" / "WinGet" / "Packages").glob(
                        "*FFmpeg*\\**\\bin\\ffmpeg.exe"
                    )
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


def _write_concat_input_file(
    image_paths: list[Path], list_file: Path, frame_duration: float
) -> None:
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


def _stage_numbered_frames(image_paths: list[Path], temp_dir: Path) -> int:
    """Stage images as ``frame_%06d.png`` for the image2 demuxer; return the staged count.

    PNG sources are linked (or copied without symlink privilege); other formats are converted
    losslessly to PNG so one numbered pattern covers mixed inputs.
    """

    from PIL import Image

    count = 0
    for img_path in image_paths:
        if not img_path.exists():
            logger.warning(f"Image not found: {img_path}")
            continue
        target = temp_dir / f"frame_{count:06d}.png"
        try:
            if img_path.suffix.lower() == ".png":
                try:
                    target.symlink_to(img_path.absolute())
                except OSError:
                    shutil.copy2(img_path, target)
            else:
                with Image.open(img_path) as image:
                    image.convert("RGB").save(target, format="PNG")
        except Exception as e:
            logger.warning(f"Failed to stage {img_path.name}: {e}")
            continue
        count += 1
    return count


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
        *,
        settings: VideoEncodeSettings | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> bool:
        """
        Create a video from an image sequence, one image per frame.

        Args:
            image_paths: Images, in the order they become frames (never re-sorted here)
            output_path: Path for output video
            fps: Frames per second (default: 24)
            codec: Video codec (default: libx264)
            quality: An encode profile (fast/balanced/archival) or an x264 speed preset
            settings: Explicit encode settings (overrides ``quality``)
            cancel: Cooperative cancel probe; a cancel raises ``VideoEncodeCancelled``

        Returns:
            True if video created successfully
        """
        if not self.ffmpeg_available:
            logger.error("FFmpeg not available, cannot create video")
            return False

        if not image_paths:
            logger.error("No images provided for video creation")
            return False

        encode = resolve_encode_settings(quality, settings)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # A private staging folder: never a shared "temp" folder that could hold other files.
        temp_dir = Path(tempfile.mkdtemp(prefix=".ffmpeg_frames_", dir=str(output_path.parent)))
        try:
            frame_count = _stage_numbered_frames(list(image_paths), temp_dir)
            if not frame_count:
                logger.error("No valid images for video creation")
                return False

            # image2 at an integer frame rate: exact frame timing, no per-frame float durations.
            cmd = [
                str(self.ffmpeg_executable),
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-framerate",
                str(int(fps)),
                "-start_number",
                "0",
                "-i",
                str(temp_dir / "frame_%06d.png"),
                *build_video_encode_args(codec=codec, settings=encode, output_path=output_path),
                "-frames:v",
                str(frame_count),
                str(output_path),
            ]

            logger.info(f"Creating video with {frame_count} frames")
            logger.info(f"FFmpeg command: {' '.join(cmd)}")
            try:
                result = run_ffmpeg(cmd, cancel=cancel)
            except VideoEncodeCancelled:
                output_path.unlink(missing_ok=True)
                raise
            if result.returncode == 0:
                logger.info(f"Video created successfully: {output_path.name}")
                return True
            logger.error(f"FFmpeg failed: {result.stderr}")
            output_path.unlink(missing_ok=True)
            return False
        except VideoEncodeCancelled:
            raise
        except Exception as e:
            logger.error(f"Video creation failed: {e}")
            return False
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

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

            # Build FFmpeg command (stills with per-image durations need the concat demuxer)
            cmd = [
                str(self.ffmpeg_executable),
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                *build_video_encode_args(
                    codec=codec,
                    settings=resolve_encode_settings(quality),
                    output_path=output_path,
                ),
                "-r",
                str(fps),
                "-y",  # Overwrite output file
                str(output_path),
            ]

            logger.info(f"Creating video with {len(image_paths)} images at {fps} fps")

            result = run_ffmpeg(cmd)

            # Clean up temp file
            list_file.unlink(missing_ok=True)

            if result.returncode == 0:
                logger.info(f"Video created successfully: {output_path.name}")
                return True
            else:
                logger.error(f"FFmpeg failed: {result.stderr}")
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
