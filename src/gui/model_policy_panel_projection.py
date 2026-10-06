"""Tk glue that shows the selected model's policy on the Base Generation panel (PR-IMG-130A; generalizes PR-IMG-116).

The decision comes from the pure ``project_model_selection`` (one ``ModelPolicy`` per selection); this class only writes
fixed values into the panel's variables, locks/restricts the affected controls while a constrained policy is selected,
and restores the operator's working values when an unconstrained model is selected again. It does not build payloads,
switch the backend, scan or hash assets, or submit anything; the compiler and backend enforce the same profile
independently.

Draft state (works for any number of families). Values are snapshotted exactly when the operator's working values are
about to be overwritten, i.e. on a transition from an unconstrained model into a constrained one, keyed by the family
that was left; later constrained -> constrained moves never overwrite it. Selecting an unconstrained model again restores
that family's draft (consumed), else the most recent snapshot (the operator's last working values). Moves between
unconstrained models leave the values untouched, exactly as before.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from src.gui_v2.model_policy_projection import (
    ModelControlProjection,
    project_model_controls,
    project_model_selection,
)
from src.image_backends.image_backend_types import configured_image_backend_id
from src.image_backends.model_policy import (
    CONTROL_CFG,
    CONTROL_GEOMETRY,
    CONTROL_SAMPLER,
    CONTROL_SCHEDULER,
    CONTROL_STEPS,
    CONTROL_VAE,
    ControlMode,
    FamilyLookup,
    ModelPolicy,
    RegistryFamilyLookup,
    resolve_model_policy,
)

logger = logging.getLogger(__name__)

_VALUE_VARS = (
    "sampler_var",
    "scheduler_var",
    "steps_var",
    "cfg_var",
    "vae_var",
    "width_var",
    "height_var",
    "resolution_preset_var",
)
#: Which panel widgets each policy-governed control owns.
_WIDGETS = {
    CONTROL_SAMPLER: ("_sampler_combo",),
    CONTROL_SCHEDULER: ("_scheduler_combo",),
    CONTROL_STEPS: ("_steps_spin",),
    CONTROL_CFG: ("_cfg_spin",),
    CONTROL_VAE: ("_vae_combo",),
    CONTROL_GEOMETRY: ("_width_combo", "_height_combo"),
}
_FIXED_VARS = {
    CONTROL_SAMPLER: "sampler_var",
    CONTROL_SCHEDULER: "scheduler_var",
    CONTROL_STEPS: "steps_var",
    CONTROL_CFG: "cfg_var",
}
_NO_VAE_LABEL = "No VAE (model default)"
_INITIAL = "<initial>"


class ModelPolicyPanelProjection:
    def __init__(
        self,
        panel: Any,
        *,
        backend_id_provider: Callable[[], str] = configured_image_backend_id,
        family_lookup: FamilyLookup | None = None,
        policy_resolver: Callable[[str | None], ModelPolicy] | None = None,
    ) -> None:
        self._panel = panel
        self._backend_id_provider = backend_id_provider
        # Persisted registry snapshot only: constructing/using it never scans, hashes or touches the network.
        self._family_lookup: FamilyLookup | None = family_lookup if family_lookup is not None else RegistryFamilyLookup()
        #: Replaces ``resolve_model_policy`` (tests/future families); the default is the one policy authority.
        self._policy_resolver = policy_resolver
        self._policy_key: str | None = None
        self._constrained = False
        self._drafts: dict[str, dict[str, Any]] = {}
        self._last_working: dict[str, Any] | None = None
        self._saved_states: dict[str, str] = {}
        self._saved_presets: tuple[str, ...] | None = None
        self._saved_helper = ""
        self._added_presets: list[str] = []
        self._lora_provider: Callable[[], list[tuple[str, float]]] | None = None
        self._lora_sink: Callable[[dict[str, str]], None] | None = None
        self._lora_resolver: Any = None
        self.last_projection: ModelControlProjection = project_model_selection(None, None)

    def set_lora_integration(
        self,
        *,
        provider: Callable[[], list[tuple[str, float]]],
        sink: Callable[[dict[str, str]], None],
        resolver: Any,
    ) -> None:
        """Connect the selected LoRAs (read) and their annotations (write); the decision stays in the projection."""

        self._lora_provider, self._lora_sink, self._lora_resolver = provider, sink, resolver

    @property
    def active(self) -> bool:
        """Whether a constrained policy (fixed/restricted controls) is currently projected."""

        return self._constrained

    @property
    def drafts(self) -> dict[str, dict[str, Any]]:
        return self._drafts

    def refresh(self) -> ModelControlProjection:
        panel = self._panel
        try:
            backend_id: str | None = self._backend_id_provider()
        except Exception:
            backend_id = None
        selected: list[tuple[str, float]] = []
        if self._lora_provider is not None:
            try:
                selected = list(self._lora_provider())
            except Exception:
                logger.debug("Could not read the selected LoRAs", exc_info=True)
        model_name = panel.model_var.get()
        policy = (
            self._policy_resolver(model_name)
            if self._policy_resolver is not None
            else resolve_model_policy(model_name, family_lookup=self._family_lookup)
        )
        projection = project_model_controls(
            policy, backend_id, selected_loras=selected, lora_resolver=self._lora_resolver
        )
        self.last_projection = projection
        key = projection.policy.policy_id
        if projection.constrained:
            if not self._constrained:
                self._remember_working_values(self._policy_key or _INITIAL)
            self._apply_constrained(projection)
        elif self._constrained:
            self._release(key)
        self._policy_key = key
        if self._lora_sink is not None:
            try:
                # An unconstrained model clears every annotation: the picker looks exactly as before.
                self._lora_sink(dict(projection.lora_annotations))
            except Exception:
                logger.debug("Could not update the LoRA annotations", exc_info=True)
        return projection

    # -- draft state -------------------------------------------------------------------------------------------

    def _snapshot(self) -> dict[str, Any]:
        panel = self._panel
        return {
            name: getattr(panel, name).get() for name in _VALUE_VARS if getattr(panel, name, None) is not None
        }

    def _remember_working_values(self, key: str) -> None:
        values = self._snapshot()
        self._drafts[key] = values
        self._last_working = values

    def _restore_working_values(self, key: str) -> None:
        values = self._drafts.pop(key, None)
        if values is None:
            values = self._last_working
            self._drafts.clear()  # the operator's working state moved on; older family drafts would be stale
        for name, value in (values or {}).items():
            getattr(self._panel, name).set(value)

    # -- widgets ----------------------------------------------------------------------------------------------

    def _widget_state(self, name: str) -> str:
        widget = getattr(self._panel, name, None)
        try:
            return str(widget.cget("state")) if widget is not None else ""
        except Exception:
            return ""

    def _set_state(self, name: str, state: str) -> None:
        widget = getattr(self._panel, name, None)
        if widget is None:
            return
        try:
            widget.configure(state=state)
        except Exception:
            logger.debug("Could not set %s state", name, exc_info=True)

    def _apply_constrained(self, projection: ModelControlProjection) -> None:
        panel = self._panel
        if not self._constrained:
            self._saved_states = {
                name: self._widget_state(name) for names in _WIDGETS.values() for name in names
            }
            combo = getattr(panel, "_preset_combo", None)
            self._saved_presets = tuple(combo["values"]) if combo is not None else None
            helper = getattr(panel, "_helper_label", None)
            self._saved_helper = str(helper.cget("text")) if helper is not None else ""
            self._constrained = True
        else:
            self._reset_widgets()  # a different constrained policy: start from the operator's baseline controls
        locked: list[str] = []
        for control, var_name in _FIXED_VARS.items():
            state = projection.state(control)
            if state.mode is ControlMode.FIXED:
                getattr(panel, var_name).set(state.value)
            if state.mode is not ControlMode.CONFIGURABLE:
                locked.append(control)
        vae = projection.state(CONTROL_VAE)
        if vae.mode is not ControlMode.CONFIGURABLE:
            if vae.mode is ControlMode.FIXED and hasattr(panel, "vae_var"):
                panel.vae_var.set(vae.value or _NO_VAE_LABEL)
            locked.append(CONTROL_VAE)
        if projection.presets:
            self._apply_presets(projection)
            locked.append(CONTROL_GEOMETRY)
        elif projection.state(CONTROL_GEOMETRY).mode is not ControlMode.CONFIGURABLE:
            locked.append(CONTROL_GEOMETRY)
        for control in locked:
            for name in _WIDGETS[control]:
                self._set_state(name, "disabled")
        helper = getattr(panel, "_helper_label", None)
        if helper is not None:
            text = projection.note
            for extra in (projection.blocking, projection.lora_blocking):
                if extra:
                    text += f"\n{extra}" if text else extra
            helper.configure(text=text)

    def _apply_presets(self, projection: ModelControlProjection) -> None:
        panel = self._panel
        qualified = {(w, h) for _, w, h in projection.presets}
        try:
            current = (int(panel.width_var.get()), int(panel.height_var.get()))
        except (TypeError, ValueError):
            current = (0, 0)
        for label, width, height in projection.presets:
            if label not in panel._preset_map:
                panel._preset_map[label] = (width, height)
                self._added_presets.append(label)
            panel._preset_reverse_map.setdefault((width, height), label)
        if current not in qualified:
            _label, width, height = projection.presets[0]
            panel.width_var.set(str(width))
            panel.height_var.set(str(height))
            current = (width, height)
        combo = getattr(panel, "_preset_combo", None)
        if combo is not None:
            combo["values"] = tuple(label for label, _, _ in projection.presets)
            for label, width, height in projection.presets:
                if (width, height) == current:
                    panel.resolution_preset_var.set(label)

    def _reset_widgets(self) -> None:
        panel = self._panel
        for name, state in self._saved_states.items():
            if state:
                self._set_state(name, state)
        combo = getattr(panel, "_preset_combo", None)
        if combo is not None and self._saved_presets is not None:
            combo["values"] = self._saved_presets
        for label in self._added_presets:
            size = panel._preset_map.pop(label, None)
            if size is not None and panel._preset_reverse_map.get(size) == label:
                panel._preset_reverse_map.pop(size, None)
        self._added_presets = []
        helper = getattr(panel, "_helper_label", None)
        if helper is not None:
            helper.configure(text=self._saved_helper)

    def _release(self, new_key: str) -> None:
        self._reset_widgets()
        self._restore_working_values(new_key)
        self._saved_states = {}
        self._saved_presets = None
        self._saved_helper = ""
        self._constrained = False


__all__ = ["ModelPolicyPanelProjection"]
