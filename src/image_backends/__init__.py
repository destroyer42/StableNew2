"""StableNew-owned still-image backend contracts and implementations."""

from src.image_backends.a1111_webui_backend import A1111WebUIImageBackend
from src.image_backends.forge_webui_backend import ForgeWebUIImageBackend
from src.image_backends.image_backend_registry import (
    ImageBackendRegistry,
    build_default_image_backend_registry,
)
from src.image_backends.image_backend_types import (
    A1111_IMAGE_BACKEND_ID,
    FORGE_IMAGE_BACKEND_ID,
    LEGACY_MISSING_IMAGE_BACKEND_ID,
    NEW_IMAGE_BACKEND_DEFAULT_ID,
    ImageBackendCapabilities,
    ImageBackendInterface,
    ImageExecutionRequest,
    ImageExecutionResult,
    normalize_image_backend_options,
    resolve_image_backend_id,
)

__all__ = [
    "A1111WebUIImageBackend",
    "A1111_IMAGE_BACKEND_ID",
    "FORGE_IMAGE_BACKEND_ID",
    "ForgeWebUIImageBackend",
    "ImageBackendCapabilities",
    "ImageBackendInterface",
    "ImageBackendRegistry",
    "ImageExecutionRequest",
    "ImageExecutionResult",
    "LEGACY_MISSING_IMAGE_BACKEND_ID",
    "NEW_IMAGE_BACKEND_DEFAULT_ID",
    "normalize_image_backend_options",
    "build_default_image_backend_registry",
    "resolve_image_backend_id",
]
