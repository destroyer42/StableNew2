"""Journey test — Movie Clips MVP smoke.

PR-TEST-VIDEO-003: End-to-end smoke for the tab + service flow.

Tests are deterministic; FFmpeg is mocked so no real video encoding occurs.
All tests are headless-safe (Tk is driven via withdraw/destroy pattern from
the shared journeys conftest).
"""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.gui.view_contracts.movie_clips_contract import (
    DEFAULT_CODEC,
    DEFAULT_FPS,
    DEFAULT_MODE,
    DEFAULT_QUALITY,
    SOURCE_MODE_FOLDER,
    SOURCE_MODE_MANUAL,
)
from src.gui.views.movie_clips_tab_frame_v2 import MovieClipsTabFrameV2
from src.video.movie_clip_models import ClipManifest, ClipRequest, ClipResult, ClipSettings
from src.video.movie_clip_service import MovieClipService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tk_root() -> tk.Tk:
    """Create a withdrawn Tk root for in-process tests; skip if unavailable."""
    try:
        root = tk.Tk()
        root.withdraw()
        return root
    except tk.TclError as exc:
        pytest.skip(f"Tkinter unavailable: {exc}")


def _make_images(directory: Path, count: int) -> list[Path]:
    """Create stub PNG files and return their paths."""
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(count):
        p = directory / f"frame_{i:04d}.png"
        p.write_bytes(b"PNG_STUB")
        paths.append(p)
    return paths


def _mocked_service(success: bool = True) -> MovieClipService:
    mock_creator = MagicMock()
    mock_creator.ffmpeg_available = True
    mock_creator.create_video_from_images.return_value = success
    mock_creator.create_slideshow_video.return_value = success
    return MovieClipService(video_creator=mock_creator)


# ---------------------------------------------------------------------------
# Journey: load source images
# ---------------------------------------------------------------------------


@pytest.mark.journey
def test_jt_movie_clips_load_from_folder(tmp_path: Path):
    """Journey: user opens tab, selects a folder, images load into list."""
    root = _tk_root()
    try:
        _make_images(tmp_path / "run_output", 5)
        tab = MovieClipsTabFrameV2(root)
        try:
            tab.folder_var.set(str(tmp_path / "run_output"))
            tab._on_load_images()

            assert tab.image_list.size() == 5
            names = [tab.image_list.get(i) for i in range(tab.image_list.size())]
            assert names == sorted(names), "Images must be displayed in alphabetical order"
        finally:
            tab.destroy()
    finally:
        root.destroy()


@pytest.mark.journey
def test_jt_movie_clips_manual_add_images(tmp_path: Path):
    """Journey: user adds images manually and the list accumulates uniquely."""
    root = _tk_root()
    try:
        imgs = _make_images(tmp_path, 3)
        tab = MovieClipsTabFrameV2(root)
        tab.source_mode_var.set(SOURCE_MODE_MANUAL)
        try:
            # Directly inject (filedialog is not mocked in unit path — use internal API)
            tab._set_image_list(imgs[:2])
            assert tab.image_list.size() == 2

            # Add a third image (simulate add_images result)
            tab._set_image_list(sorted(imgs, key=lambda p: p.name))
            assert tab.image_list.size() == 3
        finally:
            tab.destroy()
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# Journey: build clip
# ---------------------------------------------------------------------------


@pytest.mark.journey
def test_jt_movie_clips_build_clip_sequence_success(tmp_path: Path):
    """Journey: user selects images, builds a sequence clip — success path."""
    svc = _mocked_service(success=True)
    imgs = _make_images(tmp_path / "source", 4)

    request = ClipRequest(
        image_paths=imgs,
        output_dir=tmp_path / "out",
        settings=ClipSettings(fps=24, codec="libx264", quality="medium", mode="sequence"),
        clip_name="journey_clip",
    )
    result = svc.build_clip(request)

    assert result.success is True
    assert result.output_path is not None
    assert result.frame_count == 4
    assert result.manifest_path is not None


@pytest.mark.journey
def test_jt_movie_clips_build_clip_slideshow_success(tmp_path: Path):
    """Journey: user builds a slideshow clip — service delegates to slideshow method."""
    svc = _mocked_service(success=True)
    imgs = _make_images(tmp_path / "source", 3)

    request = ClipRequest(
        image_paths=imgs,
        output_dir=tmp_path / "out",
        settings=ClipSettings(mode="slideshow", duration_per_image=2.0),
    )
    result = svc.build_clip(request)
    assert result.success is True
    svc._creator.create_slideshow_video.assert_called_once()


@pytest.mark.journey
def test_jt_movie_clips_build_clip_failure_surfaces_error(tmp_path: Path):
    """Journey: build failure returns success=False with a non-empty error."""
    svc = _mocked_service(success=False)
    imgs = _make_images(tmp_path / "source", 2)

    request = ClipRequest(image_paths=imgs, output_dir=tmp_path / "out")
    result = svc.build_clip(request)
    assert result.success is False
    assert result.error != ""


# ---------------------------------------------------------------------------
# Journey: verify output artifact
# ---------------------------------------------------------------------------


@pytest.mark.journey
def test_jt_movie_clips_verify_output_path(tmp_path: Path):
    """Journey: output path matches the expected location after a successful build."""
    svc = _mocked_service(success=True)
    imgs = _make_images(tmp_path / "images", 2)

    request = ClipRequest(
        image_paths=imgs,
        output_dir=tmp_path / "clips",
        clip_name="test_output",
    )
    result = svc.build_clip(request)

    assert result.success is True
    assert result.output_path == tmp_path / "clips" / "test_output.mp4"


# ---------------------------------------------------------------------------
# Journey: verify manifest
# ---------------------------------------------------------------------------


@pytest.mark.journey
def test_jt_movie_clips_manifest_is_written(tmp_path: Path):
    """Journey: manifest JSON exists after a successful build."""
    svc = _mocked_service(success=True)
    imgs = _make_images(tmp_path / "img", 3)
    request = ClipRequest(
        image_paths=imgs,
        output_dir=tmp_path / "out",
        clip_name="manifest_journey",
    )
    result = svc.build_clip(request)

    assert result.manifest_path is not None
    assert result.manifest_path.exists()
    data = json.loads(result.manifest_path.read_text())
    assert data["clip_name"] == "manifest_journey"
    assert data["frame_count"] == 3
    assert data["schema_version"] == "1.0"
    assert data["settings"]["fps"] == 24


@pytest.mark.journey
def test_jt_movie_clips_manifest_is_deterministic(tmp_path: Path):
    """Journey: two identical builds produce manifests with identical non-path fields."""
    def _build(out_dir: Path) -> dict:
        svc = _mocked_service(success=True)
        imgs = _make_images(tmp_path / "src", 2)
        request = ClipRequest(
            image_paths=imgs,
            output_dir=out_dir,
            settings=ClipSettings(fps=24),
            clip_name="determ",
        )
        result = svc.build_clip(request)
        data = json.loads(result.manifest_path.read_text())
        # Remove volatile fields before comparison
        data.pop("created_at", None)
        data.pop("output_path", None)  # absolute path differs by run directory
        data.pop("source_images", None)  # absolute paths differ by run directory
        return data

    m1 = _build(tmp_path / "run1")
    m2 = _build(tmp_path / "run2")
    assert m1 == m2


# ---------------------------------------------------------------------------
# Journey: settings restore
# ---------------------------------------------------------------------------


@pytest.mark.journey
def test_jt_movie_clips_settings_restore_after_restart(tmp_path: Path):
    """Journey: tab settings survive a simulated save/restore cycle."""
    root = _tk_root()
    try:
        tab = MovieClipsTabFrameV2(root)
        try:
            # User configures settings
            tab.fps_var.set(30)
            tab.codec_var.set("libx265")
            tab.quality_var.set("fast")
            tab.mode_var.set("slideshow")
            tab.folder_var.set(str(tmp_path))
            tab._last_folder = str(tmp_path)

            # Persist
            saved = tab.get_movie_clips_state()

            # Simulate app closed and reopened
            tab2 = MovieClipsTabFrameV2(root)
            try:
                tab2.restore_movie_clips_state(saved)
                restored = tab2.get_movie_clips_state()

                assert restored["fps"] == 30
                assert restored["codec"] == "libx265"
                assert restored["quality"] == "fast"
                assert restored["mode"] == "slideshow"
                assert restored["last_folder"] == str(tmp_path)
            finally:
                tab2.destroy()
        finally:
            tab.destroy()
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# Journey: no pipeline / no queue regression guard
# ---------------------------------------------------------------------------


@pytest.mark.journey
def test_jt_movie_clips_does_not_touch_pipeline(tmp_path: Path):
    """Journey: building a clip must not invoke any pipeline or queue methods."""
    from unittest.mock import patch as _patch

    svc = _mocked_service(success=True)
    imgs = _make_images(tmp_path / "src", 2)
    request = ClipRequest(image_paths=imgs, output_dir=tmp_path / "out")

    with _patch("src.pipeline.pipeline_runner.PipelineRunner") as mock_runner:
        result = svc.build_clip(request)
        mock_runner.assert_not_called()

    assert result.success is True
