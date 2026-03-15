"""Typed error surface for native SVD runtime."""

from __future__ import annotations


class SVDError(Exception):
    """Base exception for native SVD failures."""


class SVDConfigError(SVDError):
    """Raised when SVD configuration is invalid."""


class SVDInputError(SVDError):
    """Raised when the source image is invalid or missing."""


class SVDModelLoadError(SVDError):
    """Raised when the SVD model or runtime cannot be loaded."""


class SVDInferenceError(SVDError):
    """Raised when the SVD backend fails during frame generation."""


class SVDExportError(SVDError):
    """Raised when generated frames cannot be exported."""


class SVDPostprocessError(SVDError):
    """Raised when optional SVD frame postprocessing fails."""
