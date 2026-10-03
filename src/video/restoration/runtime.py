"""Readiness for StableNew's optional local restoration/upscale runtime.

Cheap and side-effect free: it only asks the import system whether packages exist. It never
imports a model library, touches the GPU, reads weights, or downloads anything.
"""

from __future__ import annotations

import importlib.util

# Feature -> ((import name, distribution name), ...) required by the StableNew-owned adapters.
_FEATURE_PACKAGES: dict[str, tuple[tuple[str, str], ...]] = {
    "upscale": (("spandrel", "spandrel"), ("cv2", "opencv-python")),
    "codeformer": (
        ("spandrel", "spandrel"),
        ("spandrel_extra_arches", "spandrel-extra-arches"),
        ("facelib", "codeformer"),  # legacy face helper vendored in the codeformer wheel
        ("cv2", "opencv-python"),
    ),
}

POSTPROCESS_INSTALL_HINT = (
    "Install the optional postprocess runtime with scripts/bootstrap_windows.ps1 -WithPostprocess."
)

# The legacy GFPGANer loader (BasicSR-era package paths and a torchvision compatibility shim) was
# retired by PR-POSTPROC-100 without a qualified replacement. GFPGAN stays a named method and
# fails closed instead of pretending a runtime exists.
GFPGAN_UNSUPPORTED_ISSUE = "GFPGAN runtime (not part of the supported postprocess profile)"


def _module_available(import_name: str) -> bool:
    try:
        return importlib.util.find_spec(import_name) is not None
    except (ImportError, ValueError):
        return False


def missing_packages(feature: str) -> list[str]:
    """Distribution names the feature needs that are not importable in this environment."""

    return [
        f"{distribution} package"
        for import_name, distribution in _FEATURE_PACKAGES[feature]
        if not _module_available(import_name)
    ]
