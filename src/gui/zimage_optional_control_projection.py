"""Presentation-only availability for Z-Image's unsupported optional controls.

Stored intent is preserved, never silently removed: conflicting saved/PromptPack
features still produce compiler rejection. Switching models restores widget states.
"""

from __future__ import annotations

from typing import Any

from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1


class ZImageOptionalControlProjection:
    def __init__(self, pipeline_tab: Any, prompt_tab: Any, sidebar: Any) -> None:
        self.pipeline_tab, self.prompt_tab, self.sidebar = pipeline_tab, prompt_tab, sidebar
        self._states: list[tuple[Any, str]] = []
        self._active = False
        self._clip_draft: Any = None

    def _roots(self) -> list[Any]:
        cards = getattr(self.pipeline_tab, "stage_cards_panel", None)
        txt = getattr(cards, "txt2img_card", None)
        return [getattr(cards, name + "_card", None) for name in ("img2img", "adetailer", "upscale")] + [
            getattr(txt, "_refiner_frame", None), getattr(txt, "_hires_frame", None),
            getattr(self.prompt_tab, "lora_picker", None),
            getattr(self.prompt_tab, "negative_editor", None),
        ]

    def apply(self, projection: Any) -> None:
        active = projection.policy.policy_id == ZIMAGE_PROFILE_V1.profile_id
        if active == self._active:
            return
        cards = getattr(self.pipeline_tab, "stage_cards_panel", None)
        txt = getattr(cards, "txt2img_card", None)
        clip = getattr(txt, "clip_skip_var", None)
        if not active:
            if clip is not None and self._clip_draft is not None:
                clip.set(self._clip_draft)
            for widget, state in self._states:
                widget.configure(state=state)
            self._states.clear()
            self._clip_draft = None
            self._active = False
            return
        if clip is not None:
            self._clip_draft = clip.get()
            clip.set(1)
        roots = self._roots()
        control = getattr(txt, "_setting_controls", {}).get("clip_skip")
        roots.append(control)
        variables = {str(v) for name, v in getattr(self.sidebar, "stage_states", {}).items() if name != "txt2img"}
        variables.update(str(getattr(self.sidebar, name, "")) for name in
                         ("global_positive_enabled_var", "global_negative_enabled_var"))

        def visit(widget: Any, *, restrict: bool) -> None:
            if widget is None:
                return
            try:
                state = str(widget.cget("state"))
                variable = str(widget.cget("variable")) if not restrict else ""
                if restrict or variable in variables:
                    self._states.append((widget, state))
                    widget.configure(state="disabled")
            except Exception:
                pass  # containers/labels have no state or variable option
            for child in widget.winfo_children():
                visit(child, restrict=restrict)

        for root in roots:
            visit(root, restrict=True)
        visit(self.sidebar, restrict=False)
        self._active = True
