"""Tests for MovieClipService.

PR-CORE-VIDEO-002: Service-level unit tests with mocked VideoCreator.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.video.movie_clip_models import (
    ClipManifest,
    ClipRequest,
    ClipResult,
    ClipSettings,
)
from src.video.movie_clip_service import MovieClipService, _normalize_image_order


# ---------------------------------------------------------------------------
# Model unit tests
# ---------------------------------------------------------------------------


def test_clip_settings_valid_defaults():
    settings = ClipSettings()
    assert settings.validate() == []


def test_clip_settings_invalid_fps():
    settings = ClipSettings(fps=0)
    errors = settings.validate()
    assert any("fps" in e for e in errors)


def test_clip_settings_invalid_mode():
    settings = ClipSettings(mode="unknown")
    errors = settings.validate()
    assert any("mode" in e for e in errors)


def test_clip_settings_slideshow_invalid_duration():
    settings = ClipSettings(mode="slideshow", duration_per_image=0.0)
    errors = settings.validate()
    assert any("duration_per_image" in e for e in errors)


def test_clip_request_empty_images():
    req = ClipRequest(image_paths=[], output_dir=Path("/tmp"))
    errors = req.validate()
    assert any("empty" in e for e in errors)


def test_clip_request_missing_image(tmp_path: Path):
    req = ClipRequest(
        image_paths=[tmp_path / "missing.png"],
        output_dir=tmp_path,
    )
    errors = req.validate()
    assert any("do not exist" in e for e in errors)


def test_clip_request_valid(tmp_path: Path):
    img = tmp_path / "a.png"
    img.write_bytes(b"")
    req = ClipRequest(image_paths=[img], output_dir=tmp_path)
    assert req.validate() == []


# ---------------------------------------------------------------------------
# Manifest round-trip
# ---------------------------------------------------------------------------


def test_clip_manifest_round_trip(tmp_path: Path):
    m = ClipManifest(
        clip_name="test",
        output_path="/output/test.mp4",
        source_images=["/a.png", "/b.png"],
        settings={"fps": 24, "codec": "libx264", "quality": "medium", "mode": "sequence"},
        frame_count=2,
        duration_seconds=1.5,
    )
    manifest_path = tmp_path / "manifest.json"
    m.write(manifest_path)

    loaded = ClipManifest.read(manifest_path)
    assert loaded.clip_name == m.clip_name
    assert loaded.output_path == m.output_path
    assert loaded.source_images == m.source_images
    assert loaded.frame_count == m.frame_count
    assert abs(loaded.duration_seconds - m.duration_seconds) < 0.001
    assert loaded.schema_version == "1.0"


def test_clip_manifest_to_dict():
    m = ClipManifest(
        clip_name="my_clip",
        output_path="/out/my_clip.mp4",
        source_images=["/a.png"],
        settings={"fps": 24},
        frame_count=1,
        duration_seconds=0.042,
    )
    d = m.to_dict()
    assert d["clip_name"] == "my_clip"
    assert "created_at" in d
    assert d["schema_version"] == "1.0"


# ---------------------------------------------------------------------------
# Ordering helper
# ---------------------------------------------------------------------------


def test_normalize_image_order_alphabetical(tmp_path: Path):
    paths = [tmp_path / n for n in ["c.png", "a.png", "b.jpg"]]
    ordered = _normalize_image_order(paths)
    names = [p.name for p in ordered]
    assert names == ["a.png", "b.jpg", "c.png"]


def test_normalize_image_order_stable_for_same_name(tmp_path: Path):
    paths = [tmp_path / "frame_001.png", tmp_path / "frame_002.png"]
    ordered = _normalize_image_order(paths)
    assert [p.name for p in ordered] == ["frame_001.png", "frame_002.png"]


# ---------------------------------------------------------------------------
# MovieClipService – mocked VideoCreator (sequence mode)
# ---------------------------------------------------------------------------


def _make_service(ffmpeg_available: bool = True, build_ok: bool = True) -> MovieClipService:
    mock_creator = MagicMock()
    mock_creator.ffmpeg_available = ffmpeg_available
    mock_creator.create_video_from_images.return_value = build_ok
    mock_creator.create_slideshow_video.return_value = build_ok
    return MovieClipService(video_creator=mock_creator)


def test_service_check_ffmpeg_available():
    svc = _make_service(ffmpeg_available=True)
    assert svc.check_ffmpeg_available() is True


def test_service_check_ffmpeg_not_available():
    svc = _make_service(ffmpeg_available=False)
    assert svc.check_ffmpeg_available() is False


def test_service_build_clip_success(tmp_path: Path):
    svc = _make_service(ffmpeg_available=True, build_ok=True)
    img = tmp_path / "a.png"
    img.write_bytes(b"")
    request = ClipRequest(
        image_paths=[img],
        output_dir=tmp_path / "out",
        settings=ClipSettings(fps=24, codec="libx264", quality="medium", mode="sequence"),
        clip_name="myclip",
    )
    result = svc.build_clip(request)
    assert result.success is True
    assert result.output_path is not None
    assert result.frame_count == 1
    assert result.manifest_path is not None
    assert result.manifest_path.exists()


def test_service_build_clip_writes_manifest(tmp_path: Path):
    svc = _make_service(ffmpeg_available=True, build_ok=True)
    img = tmp_path / "img_001.png"
    img.write_bytes(b"")
    request = ClipRequest(
        image_paths=[img],
        output_dir=tmp_path / "out",
        clip_name="manifest_test",
    )
    result = svc.build_clip(request)
    assert result.manifest_path is not None
    data = json.loads(result.manifest_path.read_text())
    assert data["clip_name"] == "manifest_test"
    assert data["frame_count"] == 1
    assert "settings" in data


def test_service_build_clip_ffmpeg_not_available(tmp_path: Path):
    svc = _make_service(ffmpeg_available=False)
    img = tmp_path / "a.png"
    img.write_bytes(b"")
    request = ClipRequest(image_paths=[img], output_dir=tmp_path)
    result = svc.build_clip(request)
    assert result.success is False
    assert "FFmpeg" in result.error


def test_service_build_clip_ffmpeg_failure(tmp_path: Path):
    svc = _make_service(ffmpeg_available=True, build_ok=False)
    img = tmp_path / "a.png"
    img.write_bytes(b"")
    request = ClipRequest(image_paths=[img], output_dir=tmp_path)
    result = svc.build_clip(request)
    assert result.success is False


def test_service_build_clip_empty_images(tmp_path: Path):
    svc = _make_service()
    request = ClipRequest(image_paths=[], output_dir=tmp_path)
    result = svc.build_clip(request)
    assert result.success is False


def test_service_build_clip_missing_image(tmp_path: Path):
    svc = _make_service()
    request = ClipRequest(
        image_paths=[tmp_path / "no_such_file.png"],
        output_dir=tmp_path,
    )
    result = svc.build_clip(request)
    assert result.success is False


def test_service_build_clip_slideshow_mode(tmp_path: Path):
    svc = _make_service(ffmpeg_available=True, build_ok=True)
    imgs = []
    for i in range(3):
        p = tmp_path / f"slide_{i:02d}.png"
        p.write_bytes(b"")
        imgs.append(p)
    request = ClipRequest(
        image_paths=imgs,
        output_dir=tmp_path / "out",
        settings=ClipSettings(
            fps=24,
            mode="slideshow",
            duration_per_image=3.0,
            transition_duration=0.5,
        ),
    )
    result = svc.build_clip(request)
    assert result.success is True
    # Confirm slideshow mode was used
    svc._creator.create_slideshow_video.assert_called_once()
    svc._creator.create_video_from_images.assert_not_called()


def test_service_build_clip_ordering(tmp_path: Path):
    """Images must reach VideoCreator in alphabetical name order."""
    svc = _make_service(ffmpeg_available=True, build_ok=True)
    names = ["z_frame.png", "a_frame.png", "m_frame.png"]
    for n in names:
        (tmp_path / n).write_bytes(b"")
    request = ClipRequest(
        image_paths=[tmp_path / n for n in names],
        output_dir=tmp_path / "out",
    )
    svc.build_clip(request)
    call_args = svc._creator.create_video_from_images.call_args
    passed_paths = call_args.kwargs.get("image_paths") or call_args.args[0]
    passed_names = [p.name for p in passed_paths]
    assert passed_names == sorted(passed_names)


def test_service_build_clip_from_source(tmp_path: Path):
    """build_clip_from_source loads images from directory."""
    svc = _make_service(ffmpeg_available=True, build_ok=True)
    source = tmp_path / "source"
    source.mkdir()
    for n in ["bb.jpg", "aa.png"]:
        (source / n).write_bytes(b"")
    result = svc.build_clip_from_source(source, tmp_path / "out")
    assert result.success is True


def test_service_build_clip_creator_raises_exception(tmp_path: Path):
    """If VideoCreator raises, result.success must be False."""
    mock_creator = MagicMock()
    mock_creator.ffmpeg_available = True
    mock_creator.create_video_from_images.side_effect = RuntimeError("crash")
    svc = MovieClipService(video_creator=mock_creator)
    img = tmp_path / "a.png"
    img.write_bytes(b"")
    request = ClipRequest(image_paths=[img], output_dir=tmp_path)
    result = svc.build_clip(request)
    assert result.success is False
    assert "crash" in result.error
