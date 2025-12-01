from __future__ import annotations

from typing import Any, Dict, Iterable, Sequence

from src.utils.config import ConfigManager


class DropdownLoader:
    """Helper that unifies dropdown data for the Pipeline tab."""

    _RESOURCE_KEYS: Sequence[str] = (
        "models",
        "vaes",
        "samplers",
        "schedulers",
        "adetailer_models",
        "adetailer_detectors",
    )

    def __init__(self, config_manager: ConfigManager | None = None) -> None:
        self._config_manager = config_manager or ConfigManager()
        self._last_dropdowns: Dict[str, list[Any]] | None = None

    def load_dropdowns(self, controller: Any, app_state: Any | None) -> dict[str, list[Any]]:
        resources = getattr(app_state, "resources", None) or {}
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

    def apply_to_gui(
        self,
        pipeline_tab: Any | None,
        dropdowns: dict[str, list[Any]] | None = None,
    ) -> None:
        payload = dropdowns or self._last_dropdowns
        if not payload or pipeline_tab is None:
            return

        stage_panel = getattr(pipeline_tab, "stage_cards_panel", None)
        if stage_panel and hasattr(stage_panel, "apply_resource_update"):
            try:
                stage_panel.apply_resource_update(payload)
            except Exception:
                pass

        sidebar = getattr(pipeline_tab, "sidebar", None)
        panel = getattr(sidebar, "pipeline_config_panel", None)
        if panel and hasattr(panel, "apply_resources"):
            try:
                panel.apply_resources(payload)
            except Exception:
                pass
