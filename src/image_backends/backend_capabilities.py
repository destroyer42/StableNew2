"""Backend-owned capability facts that presentation layers consult (PR-IMG-FORGE-120).

The UI must not advertise what the configured runtime cannot do. These helpers expose the capabilities declared by the
backend adapters, never a second copy of them, and are deliberately tolerant: an unresolvable configuration yields the
legacy (A1111) presentation. Enforcement is separate and fails closed: the backend refuses unsupported work before any
dispatch, and an invalid backend configuration stops selection altogether.
"""

from __future__ import annotations

from src.image_backends.image_backend_types import (
    A1111_IMAGE_BACKEND_ID,
    FORGE_IMAGE_BACKEND_ID,
    ImageBackendCapabilities,
    configured_image_backend_id,
)


def capabilities_for(backend_id: str) -> ImageBackendCapabilities:
    """The declared capabilities of a registered image backend (class-level; nothing is instantiated)."""

    from src.image_backends.a1111_webui_backend import A1111WebUIImageBackend
    from src.image_backends.forge_webui_backend import ForgeWebUIImageBackend

    backends = {A1111_IMAGE_BACKEND_ID: A1111WebUIImageBackend, FORGE_IMAGE_BACKEND_ID: ForgeWebUIImageBackend}
    return backends[backend_id].capabilities


def _configured_backend_or_none() -> str | None:
    try:
        return configured_image_backend_id()
    except Exception:  # noqa: BLE001 - presentation only; selection itself fails closed elsewhere
        return None


def configured_backend_supports_hypernetworks() -> bool:
    """Whether the configured runtime supports Hypernetworks (False under Forge)."""

    backend_id = _configured_backend_or_none()
    return True if backend_id is None else capabilities_for(backend_id).supports_hypernetworks


def adetailer_detector_fallbacks(backend_id: str | None) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    """(face, hand) detector names to show when the endpoint's own list is unavailable, or None for the generic list.

    Under Forge only the managed runtime's accepted local detector set is guaranteed, so that is all that is offered.
    """

    if backend_id != FORGE_IMAGE_BACKEND_ID:
        return None
    from src.utils.managed_forge_runtime import accepted_detector_names

    names = accepted_detector_names()
    hands = tuple(name for name in names if name.startswith("hand_"))
    return tuple(name for name in names if name not in hands), hands


def configured_adetailer_detector_fallbacks() -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    return adetailer_detector_fallbacks(_configured_backend_or_none())


__all__ = [
    "adetailer_detector_fallbacks",
    "capabilities_for",
    "configured_adetailer_detector_fallbacks",
    "configured_backend_supports_hypernetworks",
]
