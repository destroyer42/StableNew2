"""Toolkit-neutral projection of the FLUX.2 Klein 4B FP8 profile onto the Base Generation controls.

Pure (no Tk, no I/O): given the selected checkpoint and the configured image backend it says whether
the Klein profile is active, which fixed values the controls must show, which resolution presets are
qualified, and the operator-facing note or blocking message. The values come from the immutable
profile in ``src/image_backends/forge_klein_profile.py``; nothing here is a second authority.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from src.image_backends.forge_klein_lora import LoraResolver, evaluate_klein_loras
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
    #: Per selected LoRA: the same compatibility decision admission makes ("" key set = nothing selected).
    lora_annotations: dict[str, str] = field(default_factory=dict)
    #: Non-empty when the current LoRA selection would be rejected before generation (shown, never auto-removed).
    lora_blocking: str = ""


_INACTIVE = KleinControlProjection(active=False)

_PRESET_LABELS = {(768, 1024): "768x1024 (3:4)", (1024, 1024): "1024x1024 (1:1)"}


def _project_loras(
    profile_max: int,
    selected: Sequence[tuple[str, float]],
    resolver: LoraResolver | None,
) -> tuple[dict[str, str], str]:
    """Annotate each selected LoRA with the admission decision; never remove or rewrite a selection."""

    if not selected:
        return {}, ""
    prompt = " ".join(f"<lora:{name}:{weight:g}>" for name, weight in selected)
    problems, decisions, _tags = evaluate_klein_loras(
        max_loras=profile_max, prompt=prompt, resolver=resolver
    )
    annotations: dict[str, str] = {}
    by_name = {decision.name: decision for decision in decisions}
    for name, _weight in selected:
        decision = by_name.get(name)
        if decision is None:
            continue
        annotations[name] = (
            "verified for FLUX.2 Klein 4B"
            if decision.runnable
            else f"not verified for FLUX.2 Klein 4B ({decision.status.value}): {decision.reason}"
        )
    blocking = (
        "This LoRA selection would be rejected before generation: " + "; ".join(problems)
        if problems
        else ""
    )
    return annotations, blocking


def project_klein_controls(
    model_name: str | None,
    backend_id: str | None,
    *,
    selected_loras: Sequence[tuple[str, float]] = (),
    lora_resolver: LoraResolver | None = None,
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
        f"{profile.steps} steps, CFG {profile.cfg_scale:g}) and the qualified 768x1024 / 1024x1024 sizes "
        "only. The qualified distilled path uses no standard negative prompt (CFG 1.0 ignores negative text), "
        "so describe what you want positively instead."
    )
    if profile.max_loras > 0:
        note += (
            f" Up to {profile.max_loras} LoRA is supported, and only one whose metadata explicitly names "
            "FLUX.2 Klein 4B; other adapters are shown as not verified and are rejected before generation."
        )
    annotations, lora_blocking = (
        _project_loras(profile.max_loras, selected_loras, lora_resolver)
        if profile.max_loras > 0
        else ({}, "")
    )
    if selected_loras and profile.max_loras <= 0:
        lora_blocking = f"{profile.display_name} (profile v{profile.version}) does not support LoRAs."
    return KleinControlProjection(
        active=True,
        sampler=profile.sampler,
        scheduler=profile.scheduler,
        steps=profile.steps,
        cfg_scale=profile.cfg_scale,
        presets=presets,
        note=note,
        blocking=blocking,
        lora_annotations=annotations,
        lora_blocking=lora_blocking,
    )


__all__ = ["KleinControlProjection", "project_klein_controls"]
