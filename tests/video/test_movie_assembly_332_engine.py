"""PR-VID-ASM-332: the assembly engine against real FFmpeg on KB-sized generated clips.

Skipped where FFmpeg/FFprobe are not installed. Clips are solid colours so the order, the normalization and the exact
crossfade window can be read back from the encoded pixels.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from src.controller.runtime_state import CancellationError
from src.pipeline.video import resolve_ffmpeg_executable
from src.video.container_metadata import resolve_ffprobe_executable
from src.video.movie_assembly_compiler import (
    AssemblyIntentClip,
    MovieAssemblyIntent,
    freeze_movie_assembly,
)
from src.video.movie_assembly_engine import (
    MANIFEST_SCHEMA,
    MovieAssemblyInputError,
    run_movie_assembly,
)
from src.video.movie_assembly_models import MODE_SEQUENCE

FFMPEG = resolve_ffmpeg_executable()
FFPROBE = resolve_ffprobe_executable()
needs_ffmpeg = pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None, reason="FFmpeg/FFprobe are not installed"
)
pytestmark = needs_ffmpeg

RED, GREEN, BLUE = (255, 0, 0), (0, 255, 0), (0, 0, 255)


def _color_clip(
    path: Path, color: str, size: tuple[int, int], fps: int, seconds: float = 1.0
) -> Path:
    subprocess.run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s={size[0]}x{size[1]}:r={fps}:d={seconds}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def _tone(path: Path, seconds: float) -> Path:
    subprocess.run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def _still(path: Path, rgb: tuple[int, int, int], size: tuple[int, int]) -> Path:
    Image.new("RGB", size, rgb).save(path)
    return path


def _probe(path: Path) -> dict:
    result = subprocess.run(
        [
            str(FFPROBE),
            "-v",
            "error",
            "-count_frames",
            "-show_entries",
            "stream=codec_type,width,height,r_frame_rate,nb_read_frames,duration,color_space:"
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _frames(path: Path, width: int, height: int) -> list[bytes]:
    raw = subprocess.run(
        [str(FFMPEG), "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True,
        capture_output=True,
    ).stdout
    size = width * height * 3
    return [raw[offset : offset + size] for offset in range(0, len(raw), size)]


def _pixel(frame: bytes, width: int, x: int, y: int) -> tuple[int, int, int]:
    index = (y * width + x) * 3
    return frame[index], frame[index + 1], frame[index + 2]


def _dominant(rgb: tuple[int, int, int]) -> tuple[int, int, int] | None:
    """The pure colour a pixel clearly is (after 4:2:0 encoding), or None for a blend."""

    for colour in (RED, GREEN, BLUE):
        if all(abs(channel - target) <= 40 for channel, target in zip(rgb, colour, strict=True)):
            return colour
    return None


@pytest.fixture
def mixed_clips(tmp_path: Path) -> list[Path]:
    """A red 96x64 @ 12 fps clip, a green 50x50 still and a blue 48x80 @ 30 fps clip; names sort the other way."""

    src = tmp_path / "src"
    src.mkdir()
    return [
        _color_clip(src / "z_red.mp4", "red", (96, 64), 12),
        _still(src / "m_green.png", GREEN, (50, 50)),
        _color_clip(src / "a_blue.mp4", "blue", (48, 80), 30),
    ]


def _intent(paths: list[Path], **overrides) -> MovieAssemblyIntent:
    values = {
        "clips": tuple(AssemblyIntentClip(str(path), 1.0) for path in paths),
        "fps": 24,
        "resolution": "64x64",
        "transition_seconds": 0.25,
        "clip_name": "movie",
    }
    values.update(overrides)
    return MovieAssemblyIntent(**values)


def test_mixed_sizes_and_rates_become_one_valid_file(
    tmp_path: Path, mixed_clips: list[Path]
) -> None:
    spec = freeze_movie_assembly(_intent(mixed_clips))
    outcome = run_movie_assembly(spec, run_dir=tmp_path / "run", job_id="job-1")

    probe = _probe(outcome.output_path)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (64, 64)
    assert video["r_frame_rate"] == "24/1"
    assert video["color_space"] == "bt709"
    # 3 x 24 frames, two 6-frame crossfades overlap: 72 - 12.
    assert outcome.timeline.total_frames == 60
    assert int(video["nb_read_frames"]) == 60
    assert float(probe["format"]["duration"]) == pytest.approx(2.5, abs=0.05)
    assert not [p for p in outcome.output_path.parent.iterdir() if p.name.startswith(".asm_")]
    assert not list(outcome.output_path.parent.glob("*.assembling.mp4"))


def test_user_order_is_kept_and_the_crossfade_spans_its_frames(
    tmp_path: Path, mixed_clips: list[Path]
) -> None:
    spec = freeze_movie_assembly(_intent(mixed_clips))
    outcome = run_movie_assembly(spec, run_dir=tmp_path / "run")
    frames = _frames(outcome.output_path, 64, 64)
    centre = [_dominant(_pixel(frame, 64, 32, 32)) for frame in frames]

    # The list order (red, green, blue), not the file-name order (blue, green, red).
    assert centre[5] == RED
    assert centre[30] == GREEN
    assert centre[55] == BLUE
    # Each crossfade starts at its planned offset (18 and 36) and blends for its 6-frame duration.
    assert spec.transition_seconds == 0.25
    assert outcome.timeline.transition_offsets == (18, 36)
    blended = [index for index, colour in enumerate(centre) if colour is None]
    assert blended == [19, 20, 21, 22, 23, 37, 38, 39, 40, 41]
    assert centre[18] == RED and centre[24] == GREEN
    assert centre[36] == GREEN and centre[42] == BLUE


def test_portrait_clip_is_letterboxed_not_stretched(
    tmp_path: Path, mixed_clips: list[Path]
) -> None:
    spec = freeze_movie_assembly(_intent(mixed_clips))
    outcome = run_movie_assembly(spec, run_dir=tmp_path / "run")
    blue_frame = _frames(outcome.output_path, 64, 64)[55]
    # 48x80 fitted into 64x64 is about 38 wide: black bars at the sides, blue in the middle.
    assert max(_pixel(blue_frame, 64, 2, 32)) < 40
    assert _dominant(_pixel(blue_frame, 64, 32, 32)) == BLUE


def test_hard_cuts_without_a_transition(tmp_path: Path, mixed_clips: list[Path]) -> None:
    spec = freeze_movie_assembly(_intent(mixed_clips, transition_seconds=0.0))
    outcome = run_movie_assembly(spec, run_dir=tmp_path / "run")
    centre = [_dominant(_pixel(f, 64, 32, 32)) for f in _frames(outcome.output_path, 64, 64)]
    assert len(centre) == 72
    assert centre[:24] == [RED] * 24
    assert centre[24:48] == [GREEN] * 24
    assert centre[48:] == [BLUE] * 24


def test_still_durations_are_per_clip(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    first = _still(src / "one.png", RED, (32, 32))
    second = _still(src / "two.png", BLUE, (32, 32))
    intent = MovieAssemblyIntent(
        clips=(AssemblyIntentClip(str(first), 0.5), AssemblyIntentClip(str(second), 1.5)),
        fps=10,
        transition_seconds=0.0,
    )
    outcome = run_movie_assembly(freeze_movie_assembly(intent), run_dir=tmp_path / "run")
    centre = [_dominant(_pixel(f, 32, 16, 16)) for f in _frames(outcome.output_path, 32, 32)]
    assert centre == [RED] * 5 + [BLUE] * 15


def test_audio_track_is_padded_to_the_movie_and_faded(
    tmp_path: Path, mixed_clips: list[Path]
) -> None:
    tone = _tone(tmp_path / "src" / "tone.wav", 1.0)
    spec = freeze_movie_assembly(
        _intent(mixed_clips, audio_path=str(tone), audio_fade_out_seconds=0.5)
    )
    outcome = run_movie_assembly(spec, run_dir=tmp_path / "run")
    streams = {s["codec_type"]: s for s in _probe(outcome.output_path)["streams"]}
    assert set(streams) == {"video", "audio"}
    assert float(streams["audio"]["duration"]) == pytest.approx(2.5, abs=0.1)
    assert int(streams["video"]["nb_read_frames"]) == 60


def test_frame_sequence_keeps_list_order_and_normalizes_sizes(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    frames = [
        _still(src / "c.png", RED, (40, 30)),
        _still(src / "a.png", GREEN, (30, 40)),
        _still(src / "b.png", BLUE, (40, 40)),
    ]
    intent = MovieAssemblyIntent(
        clips=tuple(AssemblyIntentClip(str(path)) for path in frames),
        mode=MODE_SEQUENCE,
        fps=2,
        resolution="40x40",
    )
    outcome = run_movie_assembly(freeze_movie_assembly(intent), run_dir=tmp_path / "run")
    decoded = _frames(outcome.output_path, 40, 40)
    assert [_dominant(_pixel(f, 40, 20, 20)) for f in decoded] == [RED, GREEN, BLUE]


def test_manifest_records_inputs_digest_and_plan(tmp_path: Path, mixed_clips: list[Path]) -> None:
    spec = freeze_movie_assembly(_intent(mixed_clips))
    outcome = run_movie_assembly(spec, run_dir=tmp_path / "run", job_id="job-7")
    manifest = json.loads(outcome.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == MANIFEST_SCHEMA
    assert manifest["job_id"] == "job-7"
    assert manifest["output_sha256"] == outcome.output_sha256
    assert manifest["spec"] == spec.to_dict()
    assert manifest["timeline"]["transition_offsets"] == [18, 36]
    assert [clip["path"] for clip in manifest["spec"]["clips"]] == [
        str(p.resolve()) for p in mixed_clips
    ]


def test_a_changed_input_is_refused_before_encoding(
    tmp_path: Path, mixed_clips: list[Path]
) -> None:
    spec = freeze_movie_assembly(_intent(mixed_clips))
    _still(mixed_clips[1], (0, 250, 0), (50, 50))  # same name, different pixels

    run_dir = tmp_path / "run"
    with pytest.raises(MovieAssemblyInputError, match="changed since the job was created"):
        run_movie_assembly(spec, run_dir=run_dir)
    assert not run_dir.exists() or not list(run_dir.rglob("*.mp4"))


def test_a_missing_input_is_refused(tmp_path: Path, mixed_clips: list[Path]) -> None:
    spec = freeze_movie_assembly(_intent(mixed_clips))
    mixed_clips[2].unlink()
    with pytest.raises(MovieAssemblyInputError, match="is missing or was moved"):
        run_movie_assembly(spec, run_dir=tmp_path / "run")


class _CancelAfter:
    """Not cancelled for the first ``calls`` checks, cancelled afterwards (so FFmpeg is already running)."""

    def __init__(self, calls: int) -> None:
        self.remaining = calls

    def is_cancelled(self) -> bool:
        self.remaining -= 1
        return self.remaining < 0


def test_cancel_stops_ffmpeg_and_leaves_no_partial_output(
    tmp_path: Path, mixed_clips: list[Path]
) -> None:
    spec = freeze_movie_assembly(_intent(mixed_clips))
    run_dir = tmp_path / "run"
    # Two checks before verification/encoding and one per staged still pass; the next one is inside run_ffmpeg.
    token = _CancelAfter(calls=2 + len(spec.clips))
    with pytest.raises(CancellationError):
        run_movie_assembly(spec, run_dir=run_dir, cancel_token=token)  # type: ignore[arg-type]
    assert token.remaining < 0
    leftovers = [p.name for p in run_dir.rglob("*") if p.is_file()]
    assert leftovers == []
