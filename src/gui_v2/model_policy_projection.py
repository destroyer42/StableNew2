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

from src.image_backends.forge_klein_lora import LoraResolver
from src.image_backends.model_policy import (
    VALUE_CONTROLS,
    ControlMode,
    FamilyLookup,
    ModelPolicy,
    resolve_model_policy,
)
from src.image_backends.model_policy_lora import assess_lora_selection

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
    #: The selected checkpoint this projection was made for (read-only context for other panels, such as the Prompt tab).
    model_name: str = ""
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


def _project_loras(
    policy: ModelPolicy, selected: Sequence[tuple[str, float]], resolver: LoraResolver | None
) -> tuple[dict[str, str], str]:
    """The Base Generation LoRA annotations and blocking sentence (the decision is ``assess_lora_selection``)."""

    assessment = assess_lora_selection(policy, selected, resolver)
    return dict(assessment.annotations), assessment.blocking


def project_model_controls(
    policy: ModelPolicy,
    backend_id: str | None,
    *,
    selected_loras: Sequence[tuple[str, float]] = (),
    lora_resolver: LoraResolver | None = None,
    model_name: str = "",
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
        model_name=str(model_name or ""),
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
        model_name=str(model_name or ""),
    )


__all__ = [
    "ControlState",
    "ModelControlProjection",
    "project_model_controls",
    "project_model_selection",
]
