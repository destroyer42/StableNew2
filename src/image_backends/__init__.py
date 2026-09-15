"""StableNew-owned still-image backend contracts and implementations."""

from src.image_backends.a1111_webui_backend import A1111WebUIImageBackend
from src.image_backends.image_backend_registry import (
    ImageBackendRegistry,
    build_default_image_backend_registry,
)
from src.image_backends.image_backend_types import (
    DEFAULT_IMAGE_BACKEND_ID,
    ImageBackendCapabilities,
    ImageBackendInterface,
    ImageExecutionRequest,
    ImageExecutionResult,
    normalize_image_backend_options,
    resolve_image_backend_id,
)

__all__ = [
    "A1111WebUIImageBackend",
    "DEFAULT_IMAGE_BACKEND_ID",
    "ImageBackendCapabilities",
    "ImageBackendInterface",
    "ImageBackendRegistry",
    "ImageExecutionRequest",
    "ImageExecutionResult",
    "normalize_image_backend_options",
    "build_default_image_backend_registry",
    "resolve_image_backend_id",
]
