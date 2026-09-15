"""Input image validation and resize policy for native SVD."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from src.video.svd_config import SVDPreprocessConfig
from src.video.svd_errors import SVDInputError
from src.video.svd_models import SVDPreprocessResult

SVD_SUPPORTED_IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}
)


@dataclass(frozen=True)
class SVDSourceProbe:
    """A readable, supported SVD source with its immutable discovery facts."""

    path: Path
    width: int
    height: int


@dataclass(frozen=True)
class SVDFolderDiscovery:
    """Non-recursive SVD source discovery, separated from runtime admission."""

    folder: Path
    sources: tuple[SVDSourceProbe, ...]
    ignored_paths: tuple[Path, ...]
    invalid_candidates: tuple[tuple[Path, str], ...]


def probe_svd_source_image(path: str | Path) -> SVDSourceProbe:
    """Validate and read image dimensions without loading an SVD model."""

    source = Path(path).expanduser().resolve()
    validate_svd_source_image(source)
    try:
        with Image.open(source) as image:
            image.verify()
        with Image.open(source) as image:
            width, height = image.size
    except Exception as exc:
        raise SVDInputError(f"Failed to open source image: {exc}") from exc
    if width <= 0 or height <= 0:
        raise SVDInputError("Source image dimensions must be positive")
    return SVDSourceProbe(path=source, width=int(width), height=int(height))


def discover_svd_folder_sources(folder: str | Path) -> SVDFolderDiscovery:
    """Discover direct supported image files in deterministic Windows-safe order."""

    root = Path(folder).expanduser()
    if not root.exists() or not root.is_dir():
        raise SVDInputError(f"SVD source folder does not exist or is not a directory: {root}")
    root = root.resolve()
    candidates = sorted(root.iterdir(), key=lambda item: (item.name.casefold(), str(item).casefold()))
    sources: list[SVDSourceProbe] = []
    ignored: list[Path] = []
    invalid: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate.is_file():
            continue
        if candidate.suffix.lower() not in SVD_SUPPORTED_IMAGE_SUFFIXES:
            ignored.append(candidate)
            continue
        try:
            probe = probe_svd_source_image(candidate)
        except Exception as exc:
            invalid.append((candidate, str(exc)))
            continue
        resolved_key = str(probe.path).casefold()
        if resolved_key not in seen:
            seen.add(resolved_key)
            sources.append(probe)
    return SVDFolderDiscovery(
        folder=root,
        sources=tuple(sources),
        ignored_paths=tuple(ignored),
        invalid_candidates=tuple(invalid),
    )


def load_svd_source_image(path: str | Path) -> Image.Image:
    validate_svd_source_image(path)
    try:
        return Image.open(Path(path)).convert("RGB")
    except Exception as exc:
        raise SVDInputError(f"Failed to open source image: {exc}") from exc


def validate_svd_source_image(path: str | Path) -> None:
    source_path = Path(path)
    if not source_path.exists():
        raise SVDInputError(f"Source image does not exist: {source_path}")
    if not source_path.is_file():
        raise SVDInputError(f"Source image is not a file: {source_path}")
    if source_path.suffix.lower() not in SVD_SUPPORTED_IMAGE_SUFFIXES:
        raise SVDInputError(f"Unsupported source image type: {source_path.suffix}")


def prepare_svd_input(
    *,
    source_path: str | Path,
    config: SVDPreprocessConfig,
    temp_dir: str | Path,
) -> SVDPreprocessResult:
    source = Path(source_path)
    temp_root = Path(temp_dir)
    temp_root.mkdir(parents=True, exist_ok=True)

    image = load_svd_source_image(source)
    original_width, original_height = image.size

    prepared, was_resized, was_padded, was_cropped = _prepare_image(image, config)
    prepared_path = temp_root / f"{source.stem}_svd_input.png"
    prepared.save(prepared_path, format="PNG")

    return SVDPreprocessResult(
        source_path=source,
        prepared_path=prepared_path,
        original_width=original_width,
        original_height=original_height,
        target_width=config.target_width,
        target_height=config.target_height,
        resize_mode=config.resize_mode,
        was_resized=was_resized,
        was_padded=was_padded,
        was_cropped=was_cropped,
    )


def _prepare_image(
    image: Image.Image,
    config: SVDPreprocessConfig,
) -> tuple[Image.Image, bool, bool, bool]:
    target_size = (config.target_width, config.target_height)
    original_size = image.size

    if config.resize_mode == "letterbox":
        prepared = ImageOps.pad(
            image,
            target_size,
            method=Image.Resampling.LANCZOS,
            color=config.pad_color,
            centering=(0.5, 0.5),
        )
        return prepared, prepared.size != original_size, True, False

    if config.resize_mode == "center_crop":
        prepared = ImageOps.fit(
            image,
            target_size,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
        return prepared, prepared.size != original_size, False, True

    contained = ImageOps.contain(image, target_size, method=Image.Resampling.LANCZOS)
    if contained.size == target_size:
        return contained, contained.size != original_size, False, False
    prepared = ImageOps.pad(
        contained,
        target_size,
        method=Image.Resampling.LANCZOS,
        color=config.pad_color,
        centering=(0.5, 0.5),
    )
    return prepared, prepared.size != original_size, True, False
