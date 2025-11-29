"""Helpers for locating the Aesthetic Gradient extension."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

# Normalised names observed in the wild for the Aesthetic Gradient extension
KNOWN_AESTHETIC_EXTENSION_NAMES = {
    "stable-diffusion-webui-aesthetic-gradients",
    "stable-diffusion-webui-aesthetic-gradients-master",
    "sd-webui-aesthetic-gradients",
    "sd-webui-aesthetic-gradients-master",
}


def _normalise(path: Path | str) -> str:
    return str(path).strip().lower()


def find_aesthetic_extension_dir(extensions_root: Path) -> Path | None:
    """Return the first extension directory that looks like Aesthetic Gradient."""

    if not extensions_root or not extensions_root.is_dir():
        return None

    for child in sorted(extensions_root.iterdir()):
        if not child.is_dir():
            continue
        name = child.name.lower()
        if name in KNOWN_AESTHETIC_EXTENSION_NAMES:
            return child
        if "aesthetic" in name and "gradient" in name:
            return child
    return None


def detect_aesthetic_extension(candidates: Iterable[Path]) -> tuple[bool, Path | None]:
    """Scan candidate roots for the extension directory."""

    seen: set[str] = set()
    for root in candidates:
        if not root:
            continue
        root_path = Path(root)
        key = _normalise(root_path)
        if key in seen:
            continue
        seen.add(key)
        extensions_dir = root_path / "extensions"
        match = find_aesthetic_extension_dir(extensions_dir)
        if match:
            return True, match
    return False, None
