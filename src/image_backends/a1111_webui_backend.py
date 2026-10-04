"""A1111 adapter that preserves the existing StableNew image executor behavior."""

from __future__ import annotations

from src.image_backends.image_backend_types import (
    DEFAULT_IMAGE_BACKEND_ID,
    ImageBackendCapabilities,
)
from src.image_backends.webui_family_backend import WebUIFamilyImageBackend
from src.services.runtime_transition_service import RUNTIME_A1111_WEBUI


class A1111WebUIImageBackend(WebUIFamilyImageBackend):
    backend_id = DEFAULT_IMAGE_BACKEND_ID
    capabilities = ImageBackendCapabilities(
        backend_id=backend_id,
        stage_types=("txt2img", "img2img", "adetailer", "upscale"),
    )
    transition_target = RUNTIME_A1111_WEBUI
