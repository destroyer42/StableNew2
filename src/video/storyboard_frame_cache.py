"""Bounded cache of downscaled storyboard frames and thumbnails (PR-VID-STORY-380, spec 7.2).

Worker-side only: loading a PNG and resizing it must never run on the Tk thread. Both caches are small LRUs keyed by
file path, file size and modification time, so a frame that changed on disk is reloaded. Thread-safe: several worker
tasks may ask at once. Tk-free; the widgets turn the returned Pillow images into ``PhotoImage`` on the UI thread.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path
from typing import Final

from PIL import Image

DEFAULT_MAX_FRAMES: Final = 400
DEFAULT_MAX_THUMBNAILS: Final = 300
DEFAULT_VIEWER_SIZE: Final = (960, 540)
DEFAULT_THUMB_SIZE: Final = (92, 52)

_Key = tuple[str, int, int]


class _Lru:
    def __init__(self, limit: int) -> None:
        self._limit = max(1, limit)
        self._items: OrderedDict[_Key, Image.Image] = OrderedDict()

    def get(self, key: _Key) -> Image.Image | None:
        image = self._items.get(key)
        if image is not None:
            self._items.move_to_end(key)
        return image

    def put(self, key: _Key, image: Image.Image) -> None:
        self._items[key] = image
        self._items.move_to_end(key)
        while len(self._items) > self._limit:
            self._items.popitem(last=False)

    def __len__(self) -> int:
        return len(self._items)


def _key(path: str) -> _Key:
    stat = Path(path).stat()
    return (str(Path(path)), stat.st_size, stat.st_mtime_ns)


def _fit(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Downscale to fit inside ``size`` keeping the aspect ratio; never enlarge."""

    width, height = image.size
    scale = min(size[0] / width, size[1] / height, 1.0)
    target = (max(1, round(width * scale)), max(1, round(height * scale)))
    if target == image.size:
        return image.copy()
    return image.resize(target, Image.Resampling.LANCZOS)


class FrameCache:
    def __init__(
        self,
        *,
        max_frames: int = DEFAULT_MAX_FRAMES,
        max_thumbnails: int = DEFAULT_MAX_THUMBNAILS,
        viewer_size: tuple[int, int] = DEFAULT_VIEWER_SIZE,
        thumb_size: tuple[int, int] = DEFAULT_THUMB_SIZE,
    ) -> None:
        self._frames = _Lru(max_frames)
        self._thumbs = _Lru(max_thumbnails)
        self._viewer_size = viewer_size
        self._thumb_size = thumb_size
        self._lock = threading.Lock()

    def frame(self, path: str) -> Image.Image:
        """The frame fitted into the viewer size. Raises ``OSError`` when the file cannot be read."""

        return self._load(path, self._frames, self._viewer_size)

    def thumbnail(self, path: str) -> Image.Image:
        """The frame fitted into the thumbnail size. Raises ``OSError`` when the file cannot be read."""

        return self._load(path, self._thumbs, self._thumb_size)

    def _load(self, path: str, cache: _Lru, size: tuple[int, int]) -> Image.Image:
        key = _key(path)
        with self._lock:
            hit = cache.get(key)
        if hit is not None:
            return hit
        with Image.open(path) as source:
            image = _fit(source.convert("RGB"), size)
        with self._lock:
            cache.put(key, image)
        return image

    def sizes(self) -> tuple[int, int]:
        """``(frames, thumbnails)`` currently held."""

        with self._lock:
            return len(self._frames), len(self._thumbs)


__all__ = ["FrameCache"]
