"""Worker-side file work for the Review workspace (PR-GUI-UX-580).

Everything here is blocking filesystem or decode work that must never run on the Tk thread: the recursive folder scan,
the per-image metadata and ADetailer-pair lookup, and the bounded comparison composite. The functions are Tk-free,
read-only (no file is written, renamed or stamped) and return immutable results the view publishes only while the
request that started them is still the latest.
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from src.review.adetailer_outcome import AdetailerPair, resolve_adetailer_pair
from src.utils.image_metadata import (
    extract_embedded_metadata,
    resolve_model_vae_fields,
    resolve_prompt_fields,
)

IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})

#: Beyond this the folder is refused rather than loaded partially: a truncated set must never look complete.
MAX_FOLDER_IMAGES = 20_000
#: Per-side display bound for the comparison viewer; the stored files are never changed.
COMPARE_MAX_EDGE = 2048
#: A single decoded source above this size is refused (RGBA decode memory), with a visible reason.
COMPARE_MAX_PIXELS = 120_000_000


@dataclass(frozen=True)
class FolderScan:
    root: Path
    paths: tuple[Path, ...] = ()
    too_many: bool = False
    unreadable: tuple[str, ...] = ()
    cancelled: bool = False


def scan_image_folder(
    root: Path,
    *,
    limit: int = MAX_FOLDER_IMAGES,
    is_cancelled: Callable[[], bool] = lambda: False,
) -> FolderScan:
    """Recursively list supported images under ``root`` in sorted path order (the previous picker's ordering)."""

    found: list[Path] = []
    unreadable: list[str] = []

    def remember(error: OSError) -> None:
        unreadable.append(str(getattr(error, "filename", "") or error))

    for directory, _subdirs, names in os.walk(root, onerror=remember):
        if is_cancelled():
            return FolderScan(root=root, cancelled=True)
        for name in names:
            if Path(name).suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            candidate = Path(directory) / name
            if not candidate.is_file():
                continue
            found.append(candidate)
            if len(found) > limit:
                return FolderScan(root=root, too_many=True, unreadable=tuple(unreadable))
    return FolderScan(root=root, paths=tuple(sorted(found)), unreadable=tuple(unreadable))


@dataclass(frozen=True)
class ImageContext:
    """What Review shows about one image, gathered off the Tk thread."""

    path: Path
    metadata_status: str
    metadata_ok: bool = False
    prompt: str = ""
    negative_prompt: str = ""
    model: str = ""
    vae: str = ""
    adetailer_pair: AdetailerPair | None = None
    prior_summary: Any = None
    prior_summary_available: bool = False


def load_image_context(
    path: Path,
    *,
    prior_summary_getter: Callable[[str], Any] | None = None,
    extract_metadata: Callable[[Path], Any] = extract_embedded_metadata,
    resolve_pair: Callable[[Path], AdetailerPair | None] = resolve_adetailer_pair,
) -> ImageContext:
    """Read embedded metadata, the verified ADetailer source and the prior review summary for ``path``."""

    pair = resolve_pair(path)
    summary: Any = None
    available = False
    if callable(prior_summary_getter):
        try:
            summary = prior_summary_getter(str(path))
            available = True
        except Exception:  # noqa: BLE001 - the summary is advisory; unavailable is shown, not raised
            summary, available = None, False
    result = extract_metadata(path)
    if result.status != "ok" or not isinstance(result.payload, dict):
        return ImageContext(
            path=path,
            metadata_status=str(result.status),
            adetailer_pair=pair,
            prior_summary=summary,
            prior_summary_available=available,
        )
    prompt, negative_prompt = resolve_prompt_fields(result.payload)
    model, vae = resolve_model_vae_fields(result.payload)
    return ImageContext(
        path=path,
        metadata_status="ok",
        metadata_ok=True,
        prompt=str(prompt or ""),
        negative_prompt=str(negative_prompt or ""),
        model=str(model or ""),
        vae=str(vae or ""),
        adetailer_pair=pair,
        prior_summary=summary,
        prior_summary_available=available,
    )


@dataclass(frozen=True)
class PreparedCompare:
    """A display projection of one or two images (never a stored artifact)."""

    image: Image.Image
    labels_note: str = ""
    scaled: bool = False


class CompareImageError(ValueError):
    """A comparison source could not be shown; the message is safe to display (no prompt text)."""


def _load_bounded(path: Path, max_edge: int, max_pixels: int) -> tuple[Image.Image, bool]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as source:
                width, height = source.size
                if width * height > max_pixels:
                    raise CompareImageError(
                        f"{path.name} is too large to compare ({width} x {height} pixels)."
                    )
                if source.format == "JPEG":
                    source.draft("RGB", (max_edge, max_edge))
                source.load()
                scaled = max(source.size) > max_edge
                if scaled:
                    source.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
                return source.convert("RGBA"), scaled or (source.size != (width, height))
    except CompareImageError:
        raise
    except FileNotFoundError as exc:
        raise CompareImageError(f"{path.name} is no longer available.") from exc
    except (
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise CompareImageError(f"{path.name} could not be opened ({type(exc).__name__}).") from exc


def prepare_compare(
    primary: Path,
    secondary: Path | None = None,
    *,
    max_edge: int = COMPARE_MAX_EDGE,
    max_pixels: int = COMPARE_MAX_PIXELS,
    gutter: int = 24,
) -> PreparedCompare:
    """Decode (bounded) and composite the comparison image; raises ``CompareImageError`` with a visible reason."""

    left, left_scaled = _load_bounded(primary, max_edge, max_pixels)
    if secondary is None:
        return PreparedCompare(image=left, scaled=left_scaled)
    right, right_scaled = _load_bounded(secondary, max_edge, max_pixels)
    composite = Image.new(
        "RGBA",
        (left.size[0] + right.size[0] + gutter, max(left.size[1], right.size[1])),
        (20, 20, 20, 255),
    )
    composite.paste(left, (0, 0))
    composite.paste(right, (left.size[0] + gutter, 0))
    return PreparedCompare(image=composite, scaled=left_scaled or right_scaled)


__all__ = [
    "COMPARE_MAX_EDGE",
    "COMPARE_MAX_PIXELS",
    "CompareImageError",
    "FolderScan",
    "IMAGE_EXTENSIONS",
    "ImageContext",
    "MAX_FOLDER_IMAGES",
    "PreparedCompare",
    "load_image_context",
    "prepare_compare",
    "scan_image_folder",
]
