"""Owns the one non-modal Harvest Motion window for the Video Workflow tab (PR-VID-MOTION-400).

The tab, the Motion Library panel, Recent outputs and the cross-tab handoffs all open the same workspace through
``open``; this host builds its ports from the Video Workflow controller and the form, enforces content visibility and
keeps a single window.  It imports no job, queue or runtime code and never edits the form.
"""

from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable, Mapping, Sequence
from fractions import Fraction
from typing import Any

from src.controller.content_visibility_resolver import ContentVisibilityResolver
from src.gui.view_contracts.motion_harvest_contract import HarvestPorts
from src.gui.views.motion_harvest_dialog import MotionHarvestDialog
from src.video.motion_library.harvest import HarvestRequest
from src.video.motion_library.harvest_service import HarvestSourceRef


class HarvestHost:
    def __init__(
        self,
        owner: tk.Misc,
        *,
        controller: Callable[[], Any],
        read_form: Callable[[], Mapping[str, Any]],
        mode_provider: Callable[[], str],
        source_image: Callable[[], str] | None = None,
        on_saved: Callable[[Any], None] | None = None,
    ) -> None:
        self._owner = owner
        self._controller = controller
        self._read_form = read_form
        self._mode = mode_provider
        self._source_image = source_image
        self._on_saved = on_saved
        self._dialog: MotionHarvestDialog | None = None

    def ports(self) -> HarvestPorts:
        def ctl() -> Any:
            return self._controller()

        def preview(
            path: str,
            frames: Sequence[int],
            rate: Fraction | None,
            cancel: threading.Event,
            label: str,
        ) -> Any:
            return ctl().preview_harvest_frames(path, frames, rate, cancel, label)

        def timing(window_frames: int, rate: Fraction | None, convert: bool) -> tuple[str, ...]:
            lines: tuple[str, ...] = ctl().harvest_workflow_timing(
                dict(self._read_form()), window_frames, rate, convert
            )
            return lines

        return HarvestPorts(
            open_source=lambda ref, cancel: ctl().open_harvest_source(ref, cancel),
            preview=preview,
            harvest=lambda request, cancel: self._harvest(ctl(), request, cancel),
            workflow_timing=timing,
            library_ready=lambda: bool(ctl().motion_library_ready()),
            is_visible=self.is_visible,
        )

    @staticmethod
    def _harvest(controller: Any, request: HarvestRequest, cancel: threading.Event) -> Any:
        return controller.harvest_motion_window(request, cancel)

    def is_visible(self, ref: HarvestSourceRef) -> bool:
        """A video the current content filter hides is neither opened nor previewed (no subject: nothing to hide)."""

        subject = ref.subject
        if subject is None:
            return True
        return bool(ContentVisibilityResolver(self._mode()).is_visible(subject))

    def open(self, ref: HarvestSourceRef) -> None:
        dialog = self._dialog
        try:
            if dialog is None or not dialog.winfo_exists():
                dialog = MotionHarvestDialog(
                    self._owner,
                    ports=self.ports(),
                    on_saved=self._on_saved,
                    source_image=self._source_image,
                )
                self._dialog = dialog
        except tk.TclError:
            self._dialog = None
            return
        dialog.open_source(ref)

    @property
    def dialog(self) -> MotionHarvestDialog | None:
        return self._dialog


__all__ = ["HarvestHost"]
