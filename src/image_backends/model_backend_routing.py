"""Which image backend a model *requires*, when it is not a WebUI-family checkpoint (PR-IMG-120).

New still-image work runs on the configured WebUI-family identity (Forge by default). A model that exists only behind
another runtime (Ideogram 4 behind Diffusers) names that runtime here, so construction stamps it instead of the
configured WebUI identity. This is not a fallback and not a backend selector: a persisted explicit identity is never
rewritten, and a conflicting one is refused by the model's own profile.

Additive by design: a later backend package (a Comfy still-image backend, further Diffusers families) appends one
resolver to ``_RESOLVERS``. Resolvers are pure, cheap name matches and import nothing heavy.
"""

from __future__ import annotations

from collections.abc import Callable


def _ideogram4(model_name: str) -> str | None:
    from src.image_backends.diffusers_ideogram4_profile import (
        IDEOGRAM4_PROFILE_V1,
        is_ideogram4_model_name,
    )

    return IDEOGRAM4_PROFILE_V1.backend_id if is_ideogram4_model_name(model_name) else None


_RESOLVERS: tuple[Callable[[str], str | None], ...] = (_ideogram4,)


def _ideogram4_offer() -> tuple[str, str] | None:
    from src.image_backends.diffusers_ideogram4_profile import IDEOGRAM4_PROFILE_V1
    from src.image_backends.diffusers_readiness import check_installation

    if not check_installation().ready:
        return None
    return IDEOGRAM4_PROFILE_V1.display_name, IDEOGRAM4_PROFILE_V1.model_name


#: Models offered in the model list because their own runtime is installed (display name, model identity).
_OFFERS: tuple[Callable[[], tuple[str, str] | None], ...] = (_ideogram4_offer,)


def offered_backend_models() -> tuple[tuple[str, str], ...]:
    """Installed non-WebUI models to offer beside the WebUI checkpoints (offline, read-only checks only)."""

    offers: list[tuple[str, str]] = []
    for offer in _OFFERS:
        try:
            item = offer()
        except Exception:  # noqa: BLE001 - an unreadable install is simply not offered; the backend re-checks
            item = None
        if item is not None:
            offers.append(item)
    return tuple(offers)


def required_backend_for_model(model_name: str | None) -> str | None:
    """The non-WebUI backend this model requires, or ``None`` for an ordinary WebUI-family checkpoint."""

    name = str(model_name or "").strip()
    if not name:
        return None
    for resolver in _RESOLVERS:
        backend_id = resolver(name)
        if backend_id:
            return backend_id
    return None


__all__ = ["offered_backend_models", "required_backend_for_model"]
