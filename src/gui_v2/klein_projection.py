"""Toolkit-neutral projection of the FLUX.2 Klein 4B FP8 profile onto the Base Generation controls.

Pure (no Tk, no I/O): given the selected checkpoint and the configured image backend it says whether
the Klein profile is active, which fixed values the controls must show, which resolution presets are
qualified, and the operator-facing note or blocking message. The values come from the immutable
profile in ``src/image_backends/forge_klein_profile.py``; nothing here is a second authority.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.image_backends.forge_klein_profile import (
    is_klein_transformer_name,
    latest_klein_profile,
)
from src.image_backends.image_backend_types import FORGE_IMAGE_BACKEND_ID


@dataclass(frozen=True, slots=True)
class KleinControlProjection:
    active: bool
    sampler: str = ""
    scheduler: str = ""
    steps: int = 0
    cfg_scale: float = 0.0
    #: Qualified presets as (label, width, height).
    presets: tuple[tuple[str, int, int], ...] = ()
    note: str = ""
    #: Non-empty when the selection cannot run with the configured backend (shown, never auto-fixed).
    blocking: str = ""


_INACTIVE = KleinControlProjection(active=False)

_PRESET_LABELS = {(768, 1024): "768x1024 (3:4)", (1024, 1024): "1024x1024 (1:1)"}


def project_klein_controls(
    model_name: str | None, backend_id: str | None
) -> KleinControlProjection:
    if not is_klein_transformer_name(model_name):
        return _INACTIVE
    profile = latest_klein_profile()
    presets = tuple(
        (_PRESET_LABELS.get((w, h), f"{w}x{h}"), w, h) for w, h in profile.geometries
    )
    blocking = ""
    if str(backend_id or "") != FORGE_IMAGE_BACKEND_ID:
        blocking = (
            f"{profile.display_name} runs only on the Forge WebUI backend, but the configured backend "
            f"is '{backend_id}'. StableNew will not switch backends for you: select the Forge WebUI "
            "runtime in settings before submitting."
        )
    note = (
        f"{profile.display_name} uses fixed distilled settings ({profile.sampler}, {profile.scheduler}, "
        f"{profile.steps} steps, CFG {profile.cfg_scale:g}), no negative prompt, and the qualified "
        "768x1024 / 1024x1024 sizes only."
    )
    return KleinControlProjection(
        active=True,
        sampler=profile.sampler,
        scheduler=profile.scheduler,
        steps=profile.steps,
        cfg_scale=profile.cfg_scale,
        presets=presets,
        note=note,
        blocking=blocking,
    )


__all__ = ["KleinControlProjection", "project_klein_controls"]
