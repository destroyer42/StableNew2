# Renamed from stage_cards_panel.py to stage_cards_panel_v2.py
# ...existing code...

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Any

from src.gui.stage_cards_v2.advanced_img2img_stage_card_v2 import AdvancedImg2ImgStageCardV2
from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2
from src.gui.stage_cards_v2.advanced_upscale_stage_card_v2 import AdvancedUpscaleStageCardV2


class _StageCard(ttk.Frame):
	"""Wrapper that provides a header toggle around a real stage card."""

	def __init__(
		self,
		master: tk.Misc,
		title: str,
		*,
		build_child: Callable[[ttk.Frame], ttk.Frame],
		on_change: Callable[[], None] | None = None,
		**kwargs,
	) -> None:
		super().__init__(master, **kwargs)
		self.columnconfigure(0, weight=1)
		self._on_change = on_change

		header = ttk.Frame(self)
		header.grid(row=0, column=0, sticky="ew")
		header.columnconfigure(0, weight=1)
		ttk.Label(header, text=title).grid(row=0, column=0, sticky="w")
		self.toggle_btn = ttk.Button(header, text="Hide", width=8, command=self._toggle_body)
		self.toggle_btn.grid(row=0, column=1, sticky="e")

		self.body = ttk.Frame(self, padding=6, style="Panel.TFrame")
		self.body.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
		child = build_child(self.body)
		child.pack(fill="both", expand=True)
		self._child = child
		self._bind_watchers()
		self._visible = True

	def _toggle_body(self) -> None:
		if self._visible:
			self.body.grid_remove()
			self.toggle_btn.config(text="Show")
		else:
			self.body.grid()
			self.toggle_btn.config(text="Hide")
		self._visible = not self._visible

	def _bind_watchers(self) -> None:
		"""Attach variable traces if the child exposes watchable_vars()."""
		if not self._on_change:
			return
		try:
			watchable = getattr(self._child, "watchable_vars", None)
			if callable(watchable):
				for var in watchable() or []:
					try:
						var.trace_add("write", lambda *_: self._on_change())
					except Exception:
						pass
		except Exception:
			pass


class StageCardsPanel(ttk.Frame):
	"""Container for pipeline stage cards."""

	def __init__(
		self,
		master: tk.Misc,
		controller=None,
		theme=None,
		on_change: Callable[[], None] | None = None,
		*args,
		**kwargs,
	) -> None:
		super().__init__(master, *args, **kwargs)
		self.columnconfigure(0, weight=1)
		self._on_change = on_change

		self.txt2img_card = _StageCard(
			self,
			title="txt2img Stage",
			build_child=lambda parent: AdvancedTxt2ImgStageCardV2(parent, controller=controller, theme=theme),
			on_change=self._on_change,
		)
		self.img2img_card = _StageCard(
			self,
			title="img2img / ADetailer Stage",
			build_child=lambda parent: AdvancedImg2ImgStageCardV2(parent, controller=controller, theme=theme),
			on_change=self._on_change,
		)
		self.upscale_card = _StageCard(
			self,
			title="Upscale Stage",
			build_child=lambda parent: AdvancedUpscaleStageCardV2(parent, controller=controller, theme=theme),
			on_change=self._on_change,
		)

		self.txt2img_card.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
		self.img2img_card.grid(row=1, column=0, sticky="nsew", pady=(0, 6))
		self.upscale_card.grid(row=2, column=0, sticky="nsew")

		self.rowconfigure(0, weight=1)
		self.rowconfigure(1, weight=1)
		self.rowconfigure(2, weight=1)

		# Propagate change callbacks to cards that expose a setter
		try:
			setter = getattr(self.txt2img_card._child, "set_on_change", None)
			if callable(setter):
				setter(lambda: self._on_change() if self._on_change else None)
		except Exception:
			pass

	def set_stage_enabled(self, stage: str, enabled: bool) -> None:
		mapping = {
			"txt2img": self.txt2img_card,
			"img2img": self.img2img_card,
			"upscale": self.upscale_card,
		}
		card = mapping.get(stage)
		if not card:
			return
		if enabled and not card._visible:
			card._toggle_body()
		elif not enabled and card._visible:
			card._toggle_body()

	def to_overrides(self, prompt_text: str | None = None) -> dict[str, Any]:
		"""Flatten stage card configs into a GuiOverrides-friendly dict."""
		overrides: dict[str, Any] = {}
		txt_cfg = getattr(self.txt2img_card, "_child", None)
		if txt_cfg:
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
		img_cfg = getattr(self.img2img_card, "_child", None)
		if img_cfg:
			try:
				metadata["img2img"] = img_cfg.to_config_dict().get("img2img", {})
			except Exception:
				metadata["img2img"] = {}
		up_cfg = getattr(self.upscale_card, "_child", None)
		if up_cfg:
			try:
				metadata["upscale"] = up_cfg.to_config_dict().get("upscale", {})
			except Exception:
				metadata["upscale"] = {}
		if metadata:
			overrides["metadata"] = metadata
		return overrides

StageCardsPanel = StageCardsPanel
