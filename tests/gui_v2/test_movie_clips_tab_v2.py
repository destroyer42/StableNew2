"""GUI regression tests for MovieClipsTabFrameV2.

PR-GUI-VIDEO-001: Tab shell, source selection, image list, settings, persistence.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.gui.view_contracts.movie_clips_contract import (
    DEFAULT_CODEC,
    DEFAULT_FPS,
    DEFAULT_MODE,
    DEFAULT_QUALITY,
    SOURCE_MODE_FOLDER,
    SOURCE_MODE_MANUAL,
    build_clip_settings_summary,
    extract_source_paths_from_bundle,
    format_canonical_source_summary,
    format_image_list_summary,
    format_source_mode_label,
    sort_image_names,
)
from src.gui.views.movie_clips_tab_frame_v2 import MovieClipsTabFrameV2


# ---------------------------------------------------------------------------
# Contract helpers – unit tests (no Tk required)
# ---------------------------------------------------------------------------


def test_format_source_mode_label_folder():
    assert "Folder" in format_source_mode_label(SOURCE_MODE_FOLDER)


def test_format_source_mode_label_manual():
    assert "Manual" in format_source_mode_label(SOURCE_MODE_MANUAL)


def test_format_image_list_summary_zero():
    assert format_image_list_summary(0) == "No images selected"


def test_format_image_list_summary_one():
    assert format_image_list_summary(1) == "1 image selected"


def test_format_image_list_summary_many():
    assert "5" in format_image_list_summary(5)


def test_sort_image_names_deterministic():
    names = ["c.png", "a.png", "b.png"]
    assert sort_image_names(names) == ["a.png", "b.png", "c.png"]


def test_build_clip_settings_summary_display():
    summary = build_clip_settings_summary(24, "libx264", "medium", "sequence")
    text = summary.to_display_string()
    assert "24" in text
    assert "libx264" in text
    assert "medium" in text
    assert "sequence" in text


def test_build_clip_settings_summary_clamps_fps():
    summary = build_clip_settings_summary(0, "libx264", "medium", "sequence")
    assert summary.fps >= 1


def test_build_clip_settings_summary_defaults_codec():
    summary = build_clip_settings_summary(24, "", "medium", "sequence")
    assert summary.codec == "libx264"


def test_extract_source_paths_from_sequence_bundle() -> None:
    bundle = {
        "segment_provenance": [
            {"primary_output_path": "C:/tmp/seg0.mp4"},
            {"output_paths": ["C:/tmp/seg1.mp4"]},
        ]
    }
    assert extract_source_paths_from_bundle(bundle) == [
        "C:/tmp/seg0.mp4",
        "C:/tmp/seg1.mp4",
    ]


def test_extract_source_paths_from_assembled_bundle() -> None:
    bundle = {
        "export_output": {
            "artifact_bundle": {
                "primary_path": "C:/tmp/assembled.mp4",
                "output_paths": ["C:/tmp/assembled.mp4"],
            }
        }
    }
    assert extract_source_paths_from_bundle(bundle) == ["C:/tmp/assembled.mp4"]


def test_format_canonical_source_summary_sequence() -> None:
    bundle = {"segment_provenance": [{"primary_output_path": "C:/tmp/seg0.mp4"}]}
    assert "sequence segment" in format_canonical_source_summary(bundle)


# ---------------------------------------------------------------------------
# Tab widget tests
# ---------------------------------------------------------------------------


@pytest.fixture
def tab(tk_root: tk.Tk) -> MovieClipsTabFrameV2:
    t = MovieClipsTabFrameV2(tk_root)
    yield t
    try:
        t.destroy()
    except Exception:
        pass


def test_tab_renders(tab: MovieClipsTabFrameV2):
    """Tab frame must exist and expose key widgets."""
    assert isinstance(tab, MovieClipsTabFrameV2)
    assert hasattr(tab, "image_list")
    assert hasattr(tab, "build_btn")
    assert hasattr(tab, "fps_var")
    assert hasattr(tab, "codec_var")
    assert hasattr(tab, "quality_var")
    assert hasattr(tab, "mode_var")


def test_tab_default_source_mode(tab: MovieClipsTabFrameV2):
    assert tab.source_mode_var.get() == SOURCE_MODE_FOLDER


def test_tab_default_settings(tab: MovieClipsTabFrameV2):
    assert tab.fps_var.get() == DEFAULT_FPS
    assert tab.codec_var.get() == DEFAULT_CODEC
    assert tab.quality_var.get() == DEFAULT_QUALITY
    assert tab.mode_var.get() == DEFAULT_MODE


def test_tab_image_list_initially_empty(tab: MovieClipsTabFrameV2):
    assert tab.image_list.size() == 0
    assert len(tab._image_paths) == 0


def test_tab_clear_all(tk_root: tk.Tk, tmp_path: Path):
    tab = MovieClipsTabFrameV2(tk_root)
    try:
        # Inject some fake paths
        fake_paths = [tmp_path / "a.png", tmp_path / "b.png"]
        tab._set_image_list(fake_paths)
        assert tab.image_list.size() == 2
        tab._on_clear_all()
        assert tab.image_list.size() == 0
        assert len(tab._image_paths) == 0
    finally:
        tab.destroy()


def test_tab_load_images_from_folder(tk_root: tk.Tk, tmp_path: Path):
    """Load images from a folder with known image files."""
    (tmp_path / "img_a.png").write_bytes(b"")
    (tmp_path / "img_b.jpg").write_bytes(b"")
    (tmp_path / "README.txt").write_bytes(b"")

    tab = MovieClipsTabFrameV2(tk_root)
    try:
        tab.folder_var.set(str(tmp_path))
        tab._on_load_images()
        assert tab.image_list.size() == 2
        names = [tab.image_list.get(i) for i in range(tab.image_list.size())]
        assert "img_a.png" in names
        assert "img_b.jpg" in names
        # txt file must not appear
        assert "README.txt" not in names
    finally:
        tab.destroy()


def test_tab_load_images_missing_folder(tk_root: tk.Tk):
    tab = MovieClipsTabFrameV2(tk_root)
    try:
        tab.folder_var.set("/nonexistent/path/xyz")
        tab._on_load_images()
        assert tab.image_list.size() == 0
    finally:
        tab.destroy()


def test_tab_remove_selected(tk_root: tk.Tk, tmp_path: Path):
    paths = [tmp_path / f"img_{i}.png" for i in range(3)]
    for p in paths:
        p.write_bytes(b"")
    tab = MovieClipsTabFrameV2(tk_root)
    try:
        tab._set_image_list(paths)
        assert tab.image_list.size() == 3
        tab.image_list.selection_set(1)  # select second item
        tab._on_remove_selected()
        assert tab.image_list.size() == 2
    finally:
        tab.destroy()


def test_tab_ordering_is_stable(tk_root: tk.Tk, tmp_path: Path):
    """Images loaded from folder must be alphabetically ordered."""
    names = ["zebra.png", "alpha.png", "middle.jpg"]
    for n in names:
        (tmp_path / n).write_bytes(b"")
    tab = MovieClipsTabFrameV2(tk_root)
    try:
        tab.folder_var.set(str(tmp_path))
        tab._on_load_images()
        displayed = [tab.image_list.get(i) for i in range(tab.image_list.size())]
        assert displayed == sorted(displayed)
    finally:
        tab.destroy()


# ---------------------------------------------------------------------------
# State persistence tests
# ---------------------------------------------------------------------------


def test_tab_get_state_has_required_keys(tab: MovieClipsTabFrameV2):
    state = tab.get_movie_clips_state()
    assert "source_mode" in state
    assert "last_folder" in state
    assert "fps" in state
    assert "codec" in state
    assert "quality" in state
    assert "mode" in state


def test_tab_restore_state_round_trip(tk_root: tk.Tk):
    tab = MovieClipsTabFrameV2(tk_root)
    try:
        original = {
            "source_mode": SOURCE_MODE_MANUAL,
            "last_folder": "/some/folder",
            "fps": 30,
            "codec": "libx265",
            "quality": "slow",
            "mode": "slideshow",
        }
        result = tab.restore_movie_clips_state(original)
        assert result is True
        restored = tab.get_movie_clips_state()
        assert restored["source_mode"] == SOURCE_MODE_MANUAL
        assert restored["fps"] == 30
        assert restored["codec"] == "libx265"
        assert restored["quality"] == "slow"
        assert restored["mode"] == "slideshow"
    finally:
        tab.destroy()


def test_tab_restore_state_ignores_invalid_payload(tab: MovieClipsTabFrameV2):
    assert tab.restore_movie_clips_state(None) is False
    assert tab.restore_movie_clips_state("bad") is False
    assert tab.restore_movie_clips_state(42) is False


def test_tab_restore_state_ignores_unknown_codec(tk_root: tk.Tk):
    tab = MovieClipsTabFrameV2(tk_root)
    try:
        original_codec = tab.codec_var.get()
        tab.restore_movie_clips_state({"codec": "totally_unknown_codec"})
        # Unknown codec must not be applied - original is kept
        assert tab.codec_var.get() == original_codec
    finally:
        tab.destroy()


# ---------------------------------------------------------------------------
# Build clip action tests
# ---------------------------------------------------------------------------


def test_tab_build_clip_no_controller(tab: MovieClipsTabFrameV2, tmp_path: Path):
    """Build with no controller sets status without crashing."""
    tab._set_image_list([tmp_path / "a.png"])
    tab._on_build_clip()
    assert "Controller" in tab._build_status or tab._build_status != ""


# ---------------------------------------------------------------------------
# PR-VIDEO-215: set_source_frame_paths handoff
# ---------------------------------------------------------------------------


@pytest.mark.gui
def test_set_source_frame_paths_loads_valid_images(tk_root: tk.Tk, tmp_path: Path) -> None:
    """set_source_frame_paths populates the image list and switches to manual mode."""
    tab = MovieClipsTabFrameV2(tk_root)
    try:
        frame1 = tmp_path / "frame_001.png"
        frame2 = tmp_path / "frame_002.png"
        frame1.write_bytes(b"png")
        frame2.write_bytes(b"png")

        tab.set_source_frame_paths([str(frame1), str(frame2)])

        assert tab.source_mode_var.get() == SOURCE_MODE_MANUAL
        assert len(tab._image_paths) == 2
        assert frame1 in tab._image_paths
        assert frame2 in tab._image_paths
    finally:
        tab.destroy()


@pytest.mark.gui
def test_set_source_frame_paths_filters_non_image_extensions(tk_root: tk.Tk, tmp_path: Path) -> None:
    """set_source_frame_paths ignores non-image file extensions."""
    tab = MovieClipsTabFrameV2(tk_root)
    try:
        frame_png = tmp_path / "frame_001.png"
        frame_mp4 = tmp_path / "clip.mp4"
        frame_png.write_bytes(b"png")
        frame_mp4.write_bytes(b"mp4")

        tab.set_source_frame_paths([str(frame_png), str(frame_mp4)])

        assert len(tab._image_paths) == 1
        assert frame_png in tab._image_paths
    finally:
        tab.destroy()


@pytest.mark.gui
def test_set_source_frame_paths_empty_list_sets_status(tk_root: tk.Tk) -> None:
    """set_source_frame_paths with no valid frames sets a status message."""
    tab = MovieClipsTabFrameV2(tk_root)
    try:
        tab.set_source_frame_paths([])
        # Status label should have been updated (non-empty text about no frames)
        status = tab.status_label.cget("text")
        assert status  # Some status text is set
    finally:
        tab.destroy()


@pytest.mark.gui
def test_set_source_frame_paths_accepts_custom_status_message(tk_root: tk.Tk, tmp_path: Path) -> None:
    """set_source_frame_paths applies a caller-provided status message."""
    tab = MovieClipsTabFrameV2(tk_root)
    try:
        frame1 = tmp_path / "frame_001.png"
        frame1.write_bytes(b"png")

        tab.set_source_frame_paths([str(frame1)], status_message="Loaded from workflow")

        assert tab.status_label.cget("text") == "Loaded from workflow"
    finally:
        tab.destroy()


@pytest.mark.gui
def test_set_source_bundle_loads_sequence_segments(tk_root: tk.Tk, tmp_path: Path) -> None:
    tab = MovieClipsTabFrameV2(tk_root)
    try:
        seg0 = tmp_path / "seg0.mp4"
        seg1 = tmp_path / "seg1.mp4"
        seg0.write_bytes(b"mp4-0")
        seg1.write_bytes(b"mp4-1")

        tab.set_source_bundle(
            {
                "segment_provenance": [
                    {"primary_output_path": str(seg0)},
                    {"primary_output_path": str(seg1)},
                ]
            }
        )

        assert tab.source_mode_var.get() == SOURCE_MODE_MANUAL
        assert len(tab._image_paths) == 2
        assert seg0 in tab._image_paths
        assert seg1 in tab._image_paths
    finally:
        tab.destroy()


@pytest.mark.gui
def test_set_source_bundle_prefers_frame_paths_for_video_bundle(tk_root: tk.Tk, tmp_path: Path) -> None:
    tab = MovieClipsTabFrameV2(tk_root)
    try:
        frame0 = tmp_path / "frame_000.png"
        frame1 = tmp_path / "frame_001.png"
        clip = tmp_path / "clip.mp4"
        frame0.write_bytes(b"png")
        frame1.write_bytes(b"png")
        clip.write_bytes(b"mp4")

        tab.set_source_bundle(
            {
                "stage": "video_workflow",
                "frame_paths": [str(frame0), str(frame1)],
                "output_paths": [str(clip)],
            }
        )

        assert tab._image_paths == [frame0, frame1]
        assert "source item" in tab.status_label.cget("text") or tab.status_label.cget("text")
    finally:
        tab.destroy()


def test_tab_build_clip_delegates_to_controller(tk_root: tk.Tk, tmp_path: Path):
    controller = MagicMock()
    tab = MovieClipsTabFrameV2(tk_root, app_controller=controller)
    try:
        (tmp_path / "img.png").write_bytes(b"")
        tab._set_image_list([tmp_path / "img.png"])
        tab._on_build_clip()
        controller.on_build_movie_clip.assert_called_once()
        call_kwargs = controller.on_build_movie_clip.call_args.kwargs
        assert "image_paths" in call_kwargs
        assert "settings" in call_kwargs
        assert len(call_kwargs["image_paths"]) == 1
    finally:
        tab.destroy()


def test_tab_build_clip_empty_list_no_delegate(tk_root: tk.Tk):
    controller = MagicMock()
    tab = MovieClipsTabFrameV2(tk_root, app_controller=controller)
    try:
        tab._on_build_clip()
        controller.on_build_movie_clip.assert_not_called()
    finally:
        tab.destroy()


def test_tab_on_build_complete_sets_status(tab: MovieClipsTabFrameV2):
    tab._on_build_complete("/some/output/video.mp4")
    assert "video.mp4" in tab._build_status


def test_tab_on_build_error_sets_status(tab: MovieClipsTabFrameV2):
    tab._on_build_error("FFmpeg not found")
    assert "FFmpeg not found" in tab._build_status


# ---------------------------------------------------------------------------
# PR-VIDEO-002: Controller-action regression tests
# ---------------------------------------------------------------------------


def test_tab_wires_on_build_complete_callback(tk_root: tk.Tk, tmp_path: Path):
    """on_complete callback must update the build status label."""
    controller = MagicMock()
    tab = MovieClipsTabFrameV2(tk_root, app_controller=controller)
    try:
        (tmp_path / "f.png").write_bytes(b"")
        tab._set_image_list([tmp_path / "f.png"])
        tab._on_build_clip()
        # Extract the on_complete kwarg that was passed to the controller
        cb = controller.on_build_movie_clip.call_args.kwargs.get("on_complete")
        assert callable(cb)
        cb("/output/myclip.mp4")
        assert "myclip.mp4" in tab._build_status
    finally:
        tab.destroy()


def test_tab_wires_on_error_callback(tk_root: tk.Tk, tmp_path: Path):
    """on_error callback must update the build status label."""
    controller = MagicMock()
    tab = MovieClipsTabFrameV2(tk_root, app_controller=controller)
    try:
        (tmp_path / "f.png").write_bytes(b"")
        tab._set_image_list([tmp_path / "f.png"])
        tab._on_build_clip()
        cb = controller.on_build_movie_clip.call_args.kwargs.get("on_error")
        assert callable(cb)
        cb("FFmpeg not on PATH")
        assert "FFmpeg not on PATH" in tab._build_status
    finally:
        tab.destroy()


def test_tab_build_passes_settings_to_controller(tk_root: tk.Tk, tmp_path: Path):
    """Clip settings gathered by the tab must be forwarded to the controller."""
    controller = MagicMock()
    tab = MovieClipsTabFrameV2(tk_root, app_controller=controller)
    try:
        (tmp_path / "img.png").write_bytes(b"")
        tab._set_image_list([tmp_path / "img.png"])
        tab.fps_var.set(30)
        tab.codec_var.set("libx265")
        tab.quality_var.set("slow")
        tab.mode_var.set("slideshow")
        tab._on_build_clip()
        settings = controller.on_build_movie_clip.call_args.kwargs["settings"]
        assert settings["fps"] == 30
        assert settings["codec"] == "libx265"
        assert settings["quality"] == "slow"
        assert settings["mode"] == "slideshow"
    finally:
        tab.destroy()

