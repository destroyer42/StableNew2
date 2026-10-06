"""Toolkit-neutral projection of a model policy onto the Base Generation controls (PR-IMG-130A).

Pure (no Tk, no I/O). Given the selected checkpoint and the configured image backend it says, per value control,
whether the control is configurable, supported-but-fixed (shown disabled at its authoritative value) or unsupported,
which resolution presets are qualified, and the operator-facing note or blocking message. Every fact comes from
``ModelPolicy`` (which projects the immutable qualified profile where one exists); nothing here is a second authority,
and the compiler/backend independently enforce the same profile. It never switches the backend and never rewrites a
selection.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from math import gcd
from typing import Any

from src.image_backends.forge_klein_lora import LoraResolver, evaluate_klein_loras
from src.image_backends.model_policy import (
    LORA_POLICY_KLEIN_4B_EXPLICIT,
    VALUE_CONTROLS,
    ControlMode,
    FamilyLookup,
    ModelPolicy,
    resolve_model_policy,
)

_BACKEND_LABELS = {"forge_webui": "Forge WebUI", "a1111_webui": "A1111 WebUI"}


@dataclass(frozen=True, slots=True)
class ControlState:
    mode: ControlMode = ControlMode.CONFIGURABLE
    #: The authoritative value when ``FIXED``.
    value: Any = None


@dataclass(frozen=True, slots=True)
class ModelControlProjection:
    policy: ModelPolicy
    controls: Mapping[str, ControlState]
    #: Qualified resolution presets as (label, width, height); empty when geometry is unrestricted.
    presets: tuple[tuple[str, int, int], ...] = ()
    note: str = ""
    #: Non-empty when the selection cannot run with the configured backend (shown, never auto-fixed).
    blocking: str = ""
    #: Per selected LoRA: the same compatibility decision admission makes (empty = nothing selected / not applicable).
    lora_annotations: dict[str, str] = field(default_factory=dict)
    #: Non-empty when the current LoRA selection would be rejected before generation (shown, never auto-removed).
    lora_blocking: str = ""

    def state(self, name: str) -> ControlState:
        return self.controls.get(name, ControlState())

    @property
    def constrained(self) -> bool:
        """Whether the panel must fix or restrict anything (an ordinary model projects as unconstrained)."""

        return self.policy.constrained


def _preset_label(width: int, height: int) -> str:
    divisor = gcd(width, height) or 1
    return f"{width}x{height} ({width // divisor}:{height // divisor})"


def _project_klein_loras(
    profile_max: int, selected: Sequence[tuple[str, float]], resolver: LoraResolver | None
) -> tuple[dict[str, str], str]:
    """Annotate each selected LoRA with the admission decision; never remove or rewrite a selection."""

    if not selected:
        return {}, ""
    prompt = " ".join(f"<lora:{name}:{weight:g}>" for name, weight in selected)
    problems, decisions, _tags = evaluate_klein_loras(max_loras=profile_max, prompt=prompt, resolver=resolver)
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
        "This LoRA selection would be rejected before generation: " + "; ".join(problems) if problems else ""
    )
    return annotations, blocking


def _project_loras(
    policy: ModelPolicy, selected: Sequence[tuple[str, float]], resolver: LoraResolver | None
) -> tuple[dict[str, str], str]:
    lora = policy.feature("lora")
    if lora.compatibility_policy == LORA_POLICY_KLEIN_4B_EXPLICIT and lora.supported:
        return _project_klein_loras(int(lora.limit or 0), selected, resolver)
    if selected and not lora.supported and policy.qualified:
        version = (policy.profile_ref or {}).get("version")
        return {}, f"{policy.display_name} (profile v{version}) does not support LoRAs."
    return {}, ""


def project_model_controls(
    policy: ModelPolicy,
    backend_id: str | None,
    *,
    selected_loras: Sequence[tuple[str, float]] = (),
    lora_resolver: LoraResolver | None = None,
) -> ModelControlProjection:
    controls = {
        name: ControlState(policy.control(name).mode, policy.control(name).value) for name in VALUE_CONTROLS
    }
    geometry = policy.control("geometry")
    presets = tuple((_preset_label(w, h), w, h) for w, h in geometry.allowed)
    blocking = ""
    required = policy.required_backend
    if required and str(backend_id or "") != required:
        label = _BACKEND_LABELS.get(required, required)
        blocking = (
            f"{policy.display_name} runs only on the {label} backend, but the configured backend "
            f"is '{backend_id}'. StableNew will not switch backends for you: select the {label} "
            "runtime in settings before submitting."
        )
    annotations, lora_blocking = _project_loras(policy, selected_loras, lora_resolver)
    return ModelControlProjection(
        policy=policy,
        controls=controls,
        presets=presets,
        note=policy.note,
        blocking=blocking,
        lora_annotations=annotations,
        lora_blocking=lora_blocking,
    )


def project_model_selection(
    model_name: str | None,
    backend_id: str | None,
    *,
    selected_loras: Sequence[tuple[str, float]] = (),
    lora_resolver: LoraResolver | None = None,
    family_lookup: FamilyLookup | None = None,
) -> ModelControlProjection:
    """Resolve the selected model's policy and project it (the one call the panel makes)."""

    return project_model_controls(
        resolve_model_policy(model_name, family_lookup=family_lookup),
        backend_id,
        selected_loras=selected_loras,
        lora_resolver=lora_resolver,
    )


__all__ = [
    "ControlState",
    "ModelControlProjection",
    "project_model_controls",
    "project_model_selection",
]
