"""Forge WebUI image backend (PR-IMG-FORGE-100): explicit, non-default ``forge_webui`` identity.

Forge shares StableNew's WebUI-family executor with A1111; the stage translation is inherited from
``WebUIFamilyImageBackend`` unchanged. What makes this a distinct backend is its durable identity,
the ``forge_webui`` runtime-transition target (A1111 and Forge occupy one WebUI-family slot, so the
other identity is released only when StableNew owns it), and the read-only runtime identity guard
that requires a *positively identified* Forge endpoint before any generation dispatch. It never
falls back to A1111 and is never selected for historical records without an image backend.

Capabilities are exactly the four still-image stages StableNew's executor already drives. ControlNet
is deliberately not a StableNew image stage.
"""

from __future__ import annotations

from src.image_backends.image_backend_types import FORGE_IMAGE_BACKEND_ID, ImageBackendCapabilities
from src.image_backends.webui_family_backend import WebUIFamilyImageBackend
from src.services.runtime_transition_service import RUNTIME_FORGE_WEBUI


class ForgeWebUIImageBackend(WebUIFamilyImageBackend):
    backend_id = FORGE_IMAGE_BACKEND_ID
    capabilities = ImageBackendCapabilities(
        backend_id=backend_id,
        stage_types=("txt2img", "img2img", "adetailer", "upscale"),
    )
    transition_target = RUNTIME_FORGE_WEBUI
