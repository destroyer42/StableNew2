"""Minimal upscale folder helper that reuses the memory-hygiene batch client."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from scripts.a1111_batch_run import BatchRunClient

DEFAULT_PATTERNS: tuple[str, ...] = ("*.png", "*.jpg", "*.jpeg")


def discover_images(folder: Path, *, patterns: Sequence[str] | None = None) -> list[Path]:
    """Return sorted image file candidates under the requested folder."""

    candidates: list[Path] = []
    for pattern in patterns or DEFAULT_PATTERNS:
        candidates.extend(sorted(folder.glob(pattern)))
    return sorted(dict.fromkeys(candidates))


def upscale_folder(
    folder: Path,
    api_url: str,
    *,
    max_images: int | None = None,
    client: BatchRunClient | None = None,
) -> list[str]:
    """Send each matching image through a BatchRunClient with bounded memory usage."""

    images = discover_images(folder)
    if max_images is not None and max_images < len(images):
        images = images[:max_images]
    if not images:
        return []
    runner = client or BatchRunClient()
    return runner.run(images, api_url=api_url)
