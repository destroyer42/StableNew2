from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Dict, Iterable, Sequence

import tkinter as tk
from tkinter import ttk

from src.utils.config import ConfigManager


class DropdownLoader:
    """Helper that unifies dropdown data for the Pipeline tab."""

    _RESOURCE_KEYS: Sequence[str] = (
        "models",
        "vaes",
        "samplers",
        "schedulers",
        "upscalers",
        "adetailer_models",
        "adetailer_detectors",
    )
    _MODEL_HASH_PATTERN = re.compile(r"(?:\s*\[[^\]]+\])+\s*$")

    def __init__(self, config_manager: ConfigManager | None = None) -> None:
        self._config_manager = config_manager or ConfigManager()
        self._last_dropdowns: Dict[str, list[Any]] | None = None
        self._pipeline_tab: Any | None = None

    @staticmethod
    def normalize_model_label(raw: str) -> str:
        label = str(raw or "").strip()
        if not label:
            return ""
        cleaned = DropdownLoader._MODEL_HASH_PATTERN.sub("", label).strip()
        return cleaned

    @staticmethod
    def normalize_vae_label(raw: str) -> str:
        label = str(raw or "").strip()
        if not label:
            return ""
        cleaned = DropdownLoader._MODEL_HASH_PATTERN.sub("", label).strip()
        try:
            stem = Path(cleaned).stem
        except Exception:
            stem = cleaned
        return stem or cleaned

    def load_dropdowns(
        self,
        controller: Any,
        app_state: Any | None,
        resources: dict[str, list[Any]] | None = None,
    ) -> dict[str, list[Any]]:
        resources = resources if resources is not None else (getattr(app_state, "resources", None) or {})
        defaults = self._config_manager.get_default_config()
        dropdowns: dict[str, list[Any]] = {}
        for key in self._RESOURCE_KEYS:
            dropdowns[key] = list(resources.get(key) or [])

        ad_defaults = defaults.get("adetailer", {}) or {}
        if not dropdowns["adetailer_models"] and ad_defaults.get("adetailer_model"):
            dropdowns["adetailer_models"] = [ad_defaults["adetailer_model"]]

        txt_defaults = defaults.get("txt2img", {}) or {}
        sampler_name = txt_defaults.get("sampler_name")
        if sampler_name and not dropdowns["samplers"]:
            dropdowns["samplers"] = [sampler_name]

        self._last_dropdowns = dropdowns
        return dropdowns

    def apply(self, resources: dict[str, list[Any]] | None = None, *, pipeline_tab: Any | None = None) -> None:
        target_tab = pipeline_tab or self._pipeline_tab
        if target_tab is None and pipeline_tab is not None:
            self._pipeline_tab = pipeline_tab
            target_tab = pipeline_tab
        dropdowns = self._normalize_resources(resources)
        self.apply_to_gui(target_tab, dropdowns)

    def apply_to_gui(
        self,
        pipeline_tab: Any | None,
        dropdowns: dict[str, list[Any]] | None = None,
    ) -> None:
        payload = dropdowns or self._last_dropdowns
        if not payload or pipeline_tab is None:
            return

        self._apply_stage_cards(pipeline_tab, payload)
        self._apply_sidebar(pipeline_tab, payload)

    def _normalize_resources(self, resources: dict[str, list[Any]] | None) -> dict[str, list[Any]]:
        if resources is None:
            return self._last_dropdowns or {key: [] for key in self._RESOURCE_KEYS}
        normalized: dict[str, list[Any]] = {key: list(resources.get(key) or []) for key in self._RESOURCE_KEYS}
        self._last_dropdowns = normalized
        return normalized

    def _apply_stage_cards(self, pipeline_tab: Any, resources: dict[str, list[Any]]) -> None:
        stage_panel = getattr(pipeline_tab, "stage_cards_panel", None)
        if stage_panel and hasattr(stage_panel, "apply_resource_update"):
            try:
                stage_panel.apply_resource_update(resources)
                return
            except Exception:
                pass
        self._apply_direct_stage_cards(pipeline_tab, resources)

    def _apply_direct_stage_cards(self, container: Any, resources: dict[str, list[Any]]) -> None:
        for card_name in ("txt2img_card", "img2img_card", "adetailer_card", "upscale_card"):
            card = getattr(container, card_name, None)
            if card is None:
                continue
            updater = getattr(card, "apply_resource_update", None)
            if callable(updater):
                try:
                    updater(resources)
                    continue
                except Exception:
                    pass
            self._apply_var_if_present(
                card,
                "model_var",
                resources.get("models", []),
                resource_key="models",
            )
            self._apply_var_if_present(
                card,
                "vae_var",
                resources.get("vaes", []),
                resource_key="vaes",
            )
            self._apply_var_if_present(
                card,
                "sampler_var",
                resources.get("samplers", []),
                resource_key="samplers",
            )
            self._apply_var_if_present(
                card,
                "scheduler_var",
                resources.get("schedulers", []),
                resource_key="schedulers",
            )
            self._apply_var_if_present(
                card,
                "upscaler_var",
                resources.get("upscalers", []),
                resource_key="upscalers",
            )

    def _apply_sidebar(self, pipeline_tab: Any, resources: dict[str, list[Any]]) -> None:
        sidebar = getattr(pipeline_tab, "sidebar", None) or getattr(pipeline_tab, "sidebar_panel_v2", None)
        if sidebar is None:
            sidebar = getattr(pipeline_tab, "sidebar_panel", None)
        target_panel = getattr(sidebar, "pipeline_config_panel", None) or getattr(pipeline_tab, "pipeline_config_panel", None)
        if target_panel and hasattr(target_panel, "apply_resources"):
            try:
                target_panel.apply_resources(resources)
            except Exception:
                pass
        core_panel = getattr(sidebar, "core_config_panel", None)
        if core_panel is not None:
            self._apply_core_config_panel(core_panel, resources)

    def _apply_core_config_panel(self, panel: Any, resources: dict[str, list[Any]]) -> None:
        self._apply_combo(
            panel,
            "_model_combo",
            getattr(panel, "model_var", None),
            resources.get("models", []),
            resource_key="models",
        )
        self._apply_combo(
            panel,
            "_vae_combo",
            getattr(panel, "vae_var", None),
            resources.get("vaes", []),
            resource_key="vaes",
        )
        self._apply_combo(
            panel,
            "_sampler_combo",
            getattr(panel, "sampler_var", None),
            resources.get("samplers", []),
            resource_key="samplers",
        )

    def _apply_combo(
        self,
        panel: Any,
        combo_attr: str,
        var: tk.Variable | None,
        values: Iterable[Any],
        *,
        resource_key: str | None = None,
    ) -> None:
        combo: ttk.Combobox | None = getattr(panel, combo_attr, None)
        if combo is None or var is None:
            return
        new_values = self._combo_options(values or [], resource_key)
        try:
            combo["values"] = new_values
        except Exception:
            return
        current = var.get() if hasattr(var, "get") else ""
        if current in new_values:
            return
        if new_values:
            try:
                var.set(new_values[0])
            except Exception:
                pass
        else:
            try:
                var.set("")
            except Exception:
                pass

    def _apply_var_if_present(
        self,
        obj: Any,
        var_name: str,
        values: list[Any],
        *,
        resource_key: str | None = None,
    ) -> None:
        var = getattr(obj, var_name, None)
        if var is None:
            return
        try:
            current = var.get()
        except Exception:
            current = None
        options = list(self._combo_options(values or [], resource_key))
        if current in options:
            return
        if options:
            try:
                var.set(options[0])
            except Exception:
                pass
        else:
            try:
                var.set("")
            except Exception:
                pass

    def _combo_options(self, values: Iterable[Any], resource_key: str | None = None) -> tuple[str, ...]:
        options: list[str] = []
        seen: set[str] = set()
        for entry in values or []:
            display = self._resource_display_value(entry, resource_key)
            if not display or display in seen:
                continue
            seen.add(display)
            options.append(display)
        return tuple(options)

    def _resource_display_value(self, entry: Any, resource_key: str | None) -> str:
        if entry is None:
            return ""
        display = getattr(entry, "display_name", None)
        if not display:
            display = getattr(entry, "name", None)
        if not display:
            display = entry
        text = str(display).strip()
        if not text:
            return ""
        if resource_key == "models" or resource_key in {"adetailer_models", "adetailer_detectors"}:
            return self.normalize_model_label(text)
        if resource_key == "vaes":
            return self.normalize_vae_label(text)
        return text


DropdownLoaderV2 = DropdownLoader
