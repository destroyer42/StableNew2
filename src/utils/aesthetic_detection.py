from pathlib import Path


def detect_aesthetic_extension(candidates: list[Path]) -> tuple[bool, Path | None]:
    """
    Scan candidate directories for an 'extensions/Aesthetic-Gradient' subdir.
    Returns (found, extension_dir) where extension_dir is the Path if found.
    """
    for root in candidates:
        ext_dir = root / "extensions" / "Aesthetic-Gradient"
        if ext_dir.exists() and ext_dir.is_dir():
            return True, ext_dir
    return False, None
