"""Tk glue that shows the FLUX.2 Klein profile on the Base Generation panel (PR-IMG-116).

The decision comes from the pure ``project_klein_controls``; this class only writes the fixed values
into the panel's variables, restricts/locks the affected controls while Klein is selected, and restores
them exactly when a normal model is selected again. It does not build payloads, switch the backend or
submit anything.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from src.gui_v2.klein_projection import KleinControlProjection, project_klein_controls
from src.image_backends.image_backend_types import configured_image_backend_id

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
_LOCKABLE = (
    "_sampler_combo",
    "_scheduler_combo",
    "_steps_spin",
    "_cfg_spin",
    "_width_combo",
    "_height_combo",
    "_vae_combo",
)


class KleinPanelProjection:
    def __init__(
        self,
        panel: Any,
        *,
        backend_id_provider: Callable[[], str] = configured_image_backend_id,
    ) -> None:
        self._panel = panel
        self._backend_id_provider = backend_id_provider
        self._active = False
        self._saved_states: dict[str, str] = {}
        self._saved_presets: tuple[str, ...] | None = None
        self._saved_helper = ""
        self._saved_values: dict[str, Any] = {}
        self._added_presets: list[str] = []
        self.last_projection: KleinControlProjection = project_klein_controls(None, None)

    @property
    def active(self) -> bool:
        return self._active

    def refresh(self) -> KleinControlProjection:
        panel = self._panel
        try:
            backend_id: str | None = self._backend_id_provider()
        except Exception:
            backend_id = None
        projection = project_klein_controls(panel.model_var.get(), backend_id)
        self.last_projection = projection
        if projection.active:
            self._enter(projection)
        elif self._active:
            self._leave()
        return projection

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

    def _enter(self, projection: KleinControlProjection) -> None:
        panel = self._panel
        if not self._active:
            self._saved_states = {name: self._widget_state(name) for name in _LOCKABLE}
            combo = getattr(panel, "_preset_combo", None)
            self._saved_presets = tuple(combo["values"]) if combo is not None else None
            helper = getattr(panel, "_helper_label", None)
            self._saved_helper = str(helper.cget("text")) if helper is not None else ""
            # The actual previous values (taken once, on the first transition into Klein; never overwritten
            # while Klein stays active) so leaving Klein restores exactly what the operator had.
            self._saved_values = {
                name: getattr(panel, name).get()
                for name in _VALUE_VARS
                if getattr(panel, name, None) is not None
            }
            self._active = True
        panel.sampler_var.set(projection.sampler)
        panel.scheduler_var.set(projection.scheduler)
        panel.steps_var.set(projection.steps)
        panel.cfg_var.set(projection.cfg_scale)
        if hasattr(panel, "vae_var"):
            panel.vae_var.set("No VAE (model default)")
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
        for name in _LOCKABLE:
            self._set_state(name, "disabled")
        helper = getattr(panel, "_helper_label", None)
        if helper is not None:
            text = projection.note + (f"\n{projection.blocking}" if projection.blocking else "")
            helper.configure(text=text)

    def _leave(self) -> None:
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
        for name, value in self._saved_values.items():
            getattr(panel, name).set(value)
        self._saved_values = {}  # transient: cleared once restored
        self._saved_states = {}
        self._saved_presets = None
        self._saved_helper = ""
        self._active = False


__all__ = ["KleinPanelProjection"]
