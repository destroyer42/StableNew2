"""Explicit runtime dependencies for fake-client image execution, without bypassing policy."""

from types import SimpleNamespace

from src.api.webui_identity_attestation import ManagedWebUIIdentityAttestor
from src.image_backends import A1111WebUIImageBackend, ForgeWebUIImageBackend, ImageBackendRegistry
from src.services.runtime_transition_service import RuntimeTransitionCoordinator


def isolated_image_backends(
    *, webui_present: bool = False, webui_identity: str = "unknown", comfy_present: bool = False
) -> ImageBackendRegistry:
    """No launched process/cache or host probes; explicit conflicting residency still refuses.

    Backend identity verification continues to use the supplied execution client's
    evidence. A Forge client without positive evidence is never made READY here.
    """
    transition = RuntimeTransitionCoordinator(
        webui_manager_getter=lambda: None,
        comfy_manager_getter=lambda: None,
        svd_service_factory=lambda: SimpleNamespace(clear_model_cache=lambda: None),
        webui_endpoint_present=lambda: webui_present,
        webui_endpoint_identity=lambda: webui_identity,
        comfy_endpoint_present=lambda: comfy_present,
    )
    attestor = ManagedWebUIIdentityAttestor(manager_getter=lambda: None)
    registry = ImageBackendRegistry()
    for backend in (A1111WebUIImageBackend, ForgeWebUIImageBackend):
        registry.register(backend(transition=transition, identity_attestor=attestor))
    return registry
