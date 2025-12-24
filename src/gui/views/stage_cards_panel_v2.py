from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from src.gui.stage_cards_v2.adetailer_stage_card_v2 import ADetailerStageCardV2
from src.gui.stage_cards_v2.advanced_img2img_stage_card_v2 import AdvancedImg2ImgStageCardV2
from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2
from src.gui.stage_cards_v2.advanced_upscale_stage_card_v2 import AdvancedUpscaleStageCardV2
from src.gui.zone_map_v2 import get_pipeline_stage_order


class StageCardsPanel(ttk.Frame):
    """Container for the pipeline stage cards."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        controller=None,
        theme=None,
        app_state: Any | None = None,
        on_change: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self.columnconfigure(0, weight=1)
        self._on_change = on_change
        self.app_state = app_state
        self._stage_order = get_pipeline_stage_order() or [
            "txt2img",
            "adetailer",
            "img2img",
            "upscale",
        ]
        self.stage_order: list[str] = []
        self._stage_builders: dict[str, Callable[[tk.Misc], ttk.Frame]] = {
            "txt2img": lambda parent: AdvancedTxt2ImgStageCardV2(
                parent,
                controller=controller,
                theme=theme,
                app_state=self.app_state,
                collapsible=True,
                collapse_key="card_txt2img",
            ),
            "img2img": lambda parent: AdvancedImg2ImgStageCardV2(
                parent,
                controller=controller,
                theme=theme,
                app_state=self.app_state,
                collapsible=True,
                collapse_key="card_img2img",
            ),
            "adetailer": lambda parent: ADetailerStageCardV2(
                parent,
                theme=theme,
                app_state=self.app_state,
                collapsible=True,
                collapse_key="card_adetailer",
            ),
            "upscale": lambda parent: AdvancedUpscaleStageCardV2(
                parent,
                controller=controller,
                theme=theme,
                app_state=self.app_state,
                collapsible=True,
                collapse_key="card_upscale",
            ),
        }
        self._stage_cards: dict[str, ttk.Frame] = {}
        for stage_name in self._stage_order:
            builder = self._stage_builders.get(stage_name)
            if not builder:
                continue
            try:
                card = builder(self)
                self._stage_cards[stage_name] = card
                setattr(self, f"{stage_name}_card", card)
                self.stage_order.append(stage_name)
            except Exception as exc:
                print(f"[ERROR] Failed to create {stage_name} card: {exc}")
                import traceback
                traceback.print_exc()
        self._layout_stage_cards()
        self._attach_watchers()
        self._adetailer_listeners: list[Callable[[dict[str, Any]], None]] = []
        self._attach_adetailer_watchers()
        self._attach_dimension_watchers()
        if self.app_state is not None:
            try:
                self.app_state.add_resource_listener(self._on_app_state_resources_changed)
            except Exception:
                pass
            try:
                self.app_state.subscribe("resources", self._on_app_state_resources_changed)
            except Exception:
                pass
            self._on_app_state_resources_changed(self.app_state.resources)

    def _layout_stage_cards(self) -> None:
        last_idx = len(self.stage_order) - 1
        for idx, stage_name in enumerate(self.stage_order):
            card = self._stage_cards.get(stage_name)
            if not card:
                continue
            pady = (0, 0) if idx == last_idx else (0, 6)
            card.grid(row=idx, column=0, sticky="nsew", pady=pady)
        for idx in range(len(self.stage_order)):
            self.rowconfigure(idx, weight=1)

    def _attach_watchers(self) -> None:
        if not callable(self._on_change):
            return
        for card in self._stage_cards.values():
            watcher = getattr(card, "watchable_vars", None)
            if not callable(watcher):
                continue
            for var in watcher() or []:
                try:
                    var.trace_add("write", lambda *_: self._on_change())
                except Exception:
                    pass

    def _attach_adetailer_watchers(self) -> None:
        card = getattr(self, "adetailer_card", None)
        if card is None:
            return
        watchable = getattr(card, "watchable_vars", None)
        if not callable(watchable):
            return
        for var in watchable() or []:
            try:
                var.trace_add("write", lambda *_: self._notify_adetailer_listeners())
            except Exception:
                pass
        self._notify_adetailer_listeners()

    def _attach_dimension_watchers(self) -> None:
        """Attach watchers to update upscale card when txt2img/img2img dimensions change."""
        upscale_card = getattr(self, "upscale_card", None)
        if upscale_card is None or not hasattr(upscale_card, "update_input_dimensions"):
            return

        # PR-GUI-E: Simplified watcher attachment - directly watch width/height vars
        txt2img_card = getattr(self, "txt2img_card", None)
        if txt2img_card is not None:
            width_var = getattr(txt2img_card, "width_var", None)
            height_var = getattr(txt2img_card, "height_var", None)
            if width_var is not None:
                try:
                    width_var.trace_add("write", lambda *_: self._update_upscale_dimensions())
                except Exception:
                    pass
            if height_var is not None:
                try:
                    height_var.trace_add("write", lambda *_: self._update_upscale_dimensions())
                except Exception:
                    pass

        # Watch img2img dimensions
        img2img_card = getattr(self, "img2img_card", None)
        if img2img_card is not None:
            width_var = getattr(img2img_card, "width_var", None)
            height_var = getattr(img2img_card, "height_var", None)
            if width_var is not None:
                try:
                    width_var.trace_add("write", lambda *_: self._update_upscale_dimensions())
                except Exception:
                    pass
            if height_var is not None:
                try:
                    height_var.trace_add("write", lambda *_: self._update_upscale_dimensions())
                except Exception:
                    pass

        # Initial update
        self._update_upscale_dimensions()

    def _update_upscale_dimensions(self) -> None:
        """Update the upscale card with current pipeline dimensions."""
        upscale_card = getattr(self, "upscale_card", None)
        if upscale_card is None or not hasattr(upscale_card, "update_input_dimensions"):
            return

        # Get dimensions from txt2img (primary) or img2img
        width, height = 512, 512  # defaults

        txt2img_card = getattr(self, "txt2img_card", None)
        if (
            txt2img_card is not None
            and hasattr(txt2img_card, "width_var")
            and hasattr(txt2img_card, "height_var")
        ):
            try:
                width = int(txt2img_card.width_var.get())
                height = int(txt2img_card.height_var.get())
            except Exception:
                pass

        img2img_card = getattr(self, "img2img_card", None)
        if (
            img2img_card is not None
            and hasattr(img2img_card, "width_var")
            and hasattr(img2img_card, "height_var")
        ):
            try:
                width = int(img2img_card.width_var.get())
                height = int(img2img_card.height_var.get())
            except Exception:
                pass

        upscale_card.update_input_dimensions(width, height)

    def _notify_adetailer_listeners(self) -> None:
        if not self._adetailer_listeners:
            return
        config = self.collect_adetailer_config()
        for listener in list(self._adetailer_listeners):
            try:
                listener(config)
            except Exception:
                pass

    def set_stage_enabled(self, stage: str, enabled: bool) -> None:
        card = self._stage_cards.get(stage)
        if not card:
            return
        currently = bool(card.winfo_ismapped())
        if enabled and not currently:
            card.grid()
        elif not enabled and currently:
            card.grid_remove()

    def to_overrides(self, prompt_text: str | None = None) -> dict[str, Any]:
        overrides: dict[str, Any] = {}
        txt_cfg = getattr(self, "txt2img_card", None)
        if txt_cfg and hasattr(txt_cfg, "to_config_dict"):
            try:
                section = txt_cfg.to_config_dict().get("txt2img", {}) or {}
                overrides.update(
                    {
                        "prompt": prompt_text or "",
                        "model": section.get("model", ""),
                        "model_name": section.get("model", ""),
                        "vae_name": section.get("vae", ""),
                        "sampler": section.get("sampler_name", ""),
                        "steps": int(section.get("steps", 20) or 20),
                        "cfg_scale": float(section.get("cfg_scale", 7.0) or 7.0),
                        "width": int(section.get("width", 512) or 512),
                        "height": int(section.get("height", 512) or 512),
                    }
                )
            except Exception:
                pass
        metadata: dict[str, Any] = {}
        img_cfg = getattr(self, "img2img_card", None)
        if img_cfg and hasattr(img_cfg, "to_config_dict"):
            try:
                metadata["img2img"] = img_cfg.to_config_dict().get("img2img", {})
            except Exception:
                metadata["img2img"] = {}
        up_cfg = getattr(self, "upscale_card", None)
        if up_cfg and hasattr(up_cfg, "to_config_dict"):
            try:
                metadata["upscale"] = up_cfg.to_config_dict().get("upscale", {})
            except Exception:
                metadata["upscale"] = {}
        if metadata:
            overrides["metadata"] = metadata
        return overrides

    def collect_adetailer_config(self) -> dict[str, Any]:
        card = getattr(self, "adetailer_card", None)
        if not card or not hasattr(card, "to_config_dict"):
            return {}
        try:
            return dict(card.to_config_dict())
        except Exception:
            return {}

    def load_adetailer_config(self, config: dict[str, Any]) -> None:
        card = getattr(self, "adetailer_card", None)
        if not card or not hasattr(card, "load_from_dict"):
            return
        try:
            card.load_from_dict(config)
        except Exception:
            pass

    def add_adetailer_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
        if listener not in self._adetailer_listeners:
            self._adetailer_listeners.append(listener)
        try:
            listener(self.collect_adetailer_config())
        except Exception:
            pass

    def apply_resource_update(self, resources: dict[str, list[Any]] | None) -> None:
        if not resources:
            return
        for card in self._stage_cards.values():
            updater = getattr(card, "apply_resource_update", None)
            if callable(updater):
                try:
                    updater(resources)
                except Exception:
                    pass

    def _on_app_state_resources_changed(
        self, resources: dict[str, list[Any]] | None = None
    ) -> None:
        if resources is None and self.app_state is not None:
            try:
                resources = self.app_state.resources
            except Exception:
                resources = None
        self.apply_resource_update(resources)


StageCardsPanel = StageCardsPanel
