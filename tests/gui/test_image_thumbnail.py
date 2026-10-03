"""Tests for ImageThumbnail widget."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.mark.parametrize(
    ("source", "viewport", "expected"),
    [
        ((1600, 800), (400, 300), (400, 200)),
        ((800, 1600), (400, 300), (150, 300)),
        ((320, 180), (800, 600), (320, 180)),
        ((800, 600), (320, 180), (240, 180)),
    ],
)
def test_fit_image_size_preserves_geometry_without_crop_or_unneeded_enlarge(
    source: tuple[int, int],
    viewport: tuple[int, int],
    expected: tuple[int, int],
) -> None:
    from src.gui.widgets.image_thumbnail import fit_image_size

    width, height = fit_image_size(*source, *viewport)

    assert (width, height) == expected
    assert width <= viewport[0]
    assert height <= viewport[1]
    assert abs((width / height) - (source[0] / source[1])) < 0.01


def test_fit_image_size_honors_widget_dimensions_and_caps() -> None:
    from PIL import Image

    from src.gui.widgets.image_thumbnail import ImageThumbnail

    thumb = ImageThumbnail.__new__(ImageThumbnail)
    thumb.max_width = 960
    thumb.max_height = 960
    thumb.fit_to_widget = True
    thumb.winfo_width = MagicMock(return_value=300)
    thumb.winfo_height = MagicMock(return_value=200)

    rendered = thumb._resize_to_fit(Image.new("RGB", (1200, 600)))

    assert rendered.size == (300, 150)


def test_fit_thumbnail_resize_debounces_and_discards_stale_path() -> None:
    from src.gui.widgets.image_thumbnail import ImageThumbnail

    thumb = ImageThumbnail.__new__(ImageThumbnail)
    thumb.fit_to_widget = True
    thumb._current_path = "first.png"
    thumb._resize_after_id = "pending"
    thumb.after_cancel = MagicMock()
    thumb.after = MagicMock(return_value="replacement")
    thumb.load_image = MagicMock()

    thumb._on_resize(MagicMock())

    thumb.after_cancel.assert_called_once_with("pending")
    thumb.after.assert_called_once()
    assert thumb._resize_after_id == "replacement"

    thumb._current_path = "second.png"
    thumb._reload_after_resize("first.png")
    thumb.load_image.assert_not_called()


def test_thumbnail_handles_missing_pil():
    """Verify graceful degradation without PIL."""
    from src.gui.widgets import image_thumbnail

    # Module should load regardless of PIL availability
    assert hasattr(image_thumbnail, "ImageThumbnail")
    assert hasattr(image_thumbnail, "PIL_AVAILABLE")


def test_thumbnail_handles_missing_file():
    """Verify error handling for missing files."""
    from src.gui.widgets.image_thumbnail import ImageThumbnail

    # Create mock widget
    thumb = ImageThumbnail.__new__(ImageThumbnail)
    thumb.max_width = 300
    thumb.max_height = 300
    thumb._photo_image = None
    thumb._current_path = None
    thumb.delete = MagicMock()
    thumb.create_text = MagicMock()
    thumb.winfo_width = MagicMock(return_value=300)
    thumb.winfo_height = MagicMock(return_value=300)

    # Load non-existent file
    result = thumb.load_image("/nonexistent/path/image.png")

    assert result is False
    thumb.create_text.assert_called()  # Should show placeholder


def test_thumbnail_loads_valid_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify loading a valid image file renders it centered without needing a Tk root."""
    from PIL import Image

    from src.gui.widgets import image_thumbnail
    from src.gui.widgets.image_thumbnail import ImageThumbnail

    image_path = tmp_path / "red.png"
    Image.new("RGB", (100, 100), color="red").save(image_path)

    # ImageTk.PhotoImage requires a live Tk interpreter; the widget logic under test does not.
    photo_image_cls = MagicMock(name="PhotoImage")
    monkeypatch.setattr(image_thumbnail, "ImageTk", MagicMock(PhotoImage=photo_image_cls))

    thumb = ImageThumbnail.__new__(ImageThumbnail)
    thumb.max_width = 300
    thumb.max_height = 300
    thumb.fit_to_widget = False
    thumb._photo_image = None
    thumb._current_path = None
    thumb._update_clickability = MagicMock()
    thumb.delete = MagicMock()
    thumb.create_image = MagicMock()
    thumb.winfo_width = MagicMock(return_value=300)
    thumb.winfo_height = MagicMock(return_value=300)

    result = thumb.load_image(str(image_path))

    assert result is True
    assert thumb._current_path == str(image_path)
    rendered = photo_image_cls.call_args.args[0]
    assert rendered.size == (100, 100)
    thumb.create_image.assert_called_once_with(
        150, 150, image=photo_image_cls.return_value, anchor="center"
    )


def test_thumbnail_clear():
    """Verify clearing thumbnail resets state."""
    from src.gui.widgets.image_thumbnail import ImageThumbnail

    thumb = ImageThumbnail.__new__(ImageThumbnail)
    thumb.max_width = 300
    thumb.max_height = 300
    thumb._photo_image = "fake_image"
    thumb._current_path = "/some/path.png"
    thumb.delete = MagicMock()
    thumb.create_text = MagicMock()
    thumb.winfo_width = MagicMock(return_value=300)
    thumb.winfo_height = MagicMock(return_value=300)

    thumb.clear()

    assert thumb._photo_image is None
    assert thumb._current_path is None
    thumb.delete.assert_called_with("all")
    thumb.create_text.assert_called()


@pytest.mark.parametrize(
    ("os_name", "platform", "expected"),
    [
        ("nt", "win32", ("startfile", None)),
        ("posix", "darwin", ("popen", "open")),
        ("posix", "linux", ("popen", "xdg-open")),
    ],
)
def test_thumbnail_open_current_path_uses_default_viewer(
    monkeypatch, tmp_path: Path, os_name: str, platform: str, expected: tuple[str, str | None]
):
    """Verify clicking a loaded image opens the file in the platform default viewer."""
    from types import SimpleNamespace

    from src.gui.widgets import image_thumbnail
    from src.gui.widgets.image_thumbnail import ImageThumbnail

    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"png")

    thumb = ImageThumbnail.__new__(ImageThumbnail)
    thumb._current_path = str(image_path)

    calls: list[tuple[str, object]] = []
    # Patch only this module's view of os/subprocess so every platform branch is
    # deterministic on any host (os.startfile exists only on Windows).
    monkeypatch.setattr(
        image_thumbnail,
        "os",
        SimpleNamespace(
            name=os_name,
            sys=SimpleNamespace(platform=platform),
            startfile=lambda path: calls.append(("startfile", path)),
        ),
    )
    monkeypatch.setattr(
        image_thumbnail,
        "subprocess",
        SimpleNamespace(Popen=lambda argv: calls.append(("popen", argv))),
    )

    thumb._open_current_path()

    kind, launcher = expected
    if kind == "startfile":
        assert calls == [("startfile", str(image_path))]
    else:
        assert calls == [("popen", [launcher, str(image_path)])]
