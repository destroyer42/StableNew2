"""Tk-owned dialogs, controller command bindings and workspace handoffs."""

from __future__ import annotations

import logging
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from tkinter import TclError
from typing import Any

from src.controller.ports.ui_dispatcher import UiDispatcher
from src.gui.controllers.video_workspace_handoff import (
    route_bundle_to_movie_clips,
    route_bundle_to_video_workflow,
    route_image_to_movie_clips,
    route_image_to_video_workflow,
)
from src.utils.error_envelope_v2 import UnifiedErrorEnvelope
from src.video.video_artifact_helpers import extract_source_image_for_handoff

logger = logging.getLogger(__name__)


def bind_controller_commands(window: Any, controller: Any) -> None:
    """Replace the legacy attachment bindings, preserving callback identity.

    The V2 pack-loader compatibility surface already owns its button wiring.
    Listbox binding replaces the previous binding, as the controller used to do.
    """
    header, left = window.header_zone, window.left_zone
    for button, command in (
        ("run_button", "run_txt2img_once"),
        ("stop_button", "on_stop_clicked"),
        ("preview_button", "on_preview_clicked"),
        ("settings_button", "on_open_settings"),
        ("help_button", "on_help_clicked"),
    ):
        callback = getattr(controller, command, None)
        if callable(callback):
            getattr(header, button).configure(command=callback)
    if left is not None and not hasattr(left, "load_config_button"):
        if hasattr(left, "load_pack_button"):
            left.load_pack_button.configure(command=controller.on_load_pack)
        if hasattr(left, "edit_pack_button"):
            left.edit_pack_button.configure(command=controller.on_edit_pack)
        if hasattr(left, "packs_list"):
            left.packs_list.bind("<<ListboxSelect>>", controller._on_pack_list_select)


class TkPresentationActions:
    """One attachment owned by the existing Tk window and its UiDispatcher."""

    def __init__(self, window: Any, controller: Any, dispatcher: UiDispatcher) -> None:
        self._window = window
        self._controller = controller
        self._dispatcher = dispatcher
        self._active = True

    def is_attached_to(self, controller: Any) -> bool:
        return self._active and self._controller is controller

    def detach(self) -> None:
        # No Tk calls here: shutdown/detach can originate on a worker thread.
        self._active = False

    def _available(self) -> bool:
        return self._active and not (
            getattr(self._window, "_disposed", False)
            or getattr(self._window, "_close_in_progress", False)
            or getattr(self._controller, "_is_shutting_down", False)
        )

    def _deliver(self, action: Callable[[], object]) -> None:
        if not self._available():
            return

        def guarded() -> None:
            if not self._available():
                return
            try:
                exists = self._window.root.winfo_exists()
            except TclError:
                return
            if exists:
                action()

        self._dispatcher.run_on_ui_thread(guarded)

    def bind_commands(self) -> None:
        self._deliver(lambda: bind_controller_commands(self._window, self._controller))

    def open_debug_hub(self) -> None:
        def show() -> None:
            try:
                from src.gui.panels_v2.debug_hub_panel_v2 import DebugHubPanelV2

                DebugHubPanelV2.open(
                    master=self._window.root,
                    controller=self._controller,
                    app_state=self._controller.app_state,
                    log_handler=self._controller.gui_log_handler,
                )
            except Exception as exc:
                logger.exception("Failed to open Debug Hub")
                self._controller._append_log(f"[controller] Failed to open Debug Hub: {exc!r}")

        self._deliver(show)

    def explain_job(self, job_id: str) -> None:
        if not job_id:
            return

        def show() -> None:
            try:
                from src.gui.panels_v2.job_explanation_panel_v2 import JobExplanationPanelV2

                JobExplanationPanelV2(job_id, master=self._window.root, controller=self._controller)
            except Exception as exc:
                logger.exception("Failed to explain job %s", job_id)
                self._controller._append_log(
                    f"[controller] Failed to explain job {job_id}: {exc!r}"
                )

        self._deliver(show)

    def show_structured_error(self, envelope: UnifiedErrorEnvelope) -> None:
        def show() -> None:
            try:
                from src.gui.views.error_modal_v2 import ErrorModalV2

                modal = getattr(self._window, "_structured_error_modal", None)
                if modal and modal.winfo_exists():
                    modal.lift()
                    return
                self._window._structured_error_modal = ErrorModalV2(
                    self._window.root,
                    envelope=envelope,
                    on_close=self._clear_error_modal,
                )
            except Exception:
                logger.exception("Failed to show structured error modal")

        self._deliver(show)

    def _clear_error_modal(self) -> None:
        self._window._structured_error_modal = None

    def _require_destination(self, tab_name: str, setter: str, label: str, kind: str) -> None:
        if not self._available():
            raise RuntimeError("Presentation actions are detached")
        tab = getattr(self._window, tab_name, None)
        if tab is None:
            raise RuntimeError(f"{label} tab is not available")
        if not callable(getattr(tab, setter, None)):
            raise RuntimeError(f"{label} tab does not support {kind} handoff")

    def image_to_video_workflow(
        self,
        image_path: str | Path,
        *,
        status_message: str,
        lineage: dict[str, str] | None = None,
    ) -> str:
        self._require_destination(
            "video_workflow_tab", "set_source_image_path", "Video Workflow", "source"
        )
        path, lineage = str(image_path), dict(lineage) if lineage else None
        self._deliver(
            lambda: route_image_to_video_workflow(
                main_window=self._window,
                image_path=path,
                status_message=status_message,
                lineage=lineage,
            )
        )
        return path

    def bundle_to_video_workflow(
        self, bundle: dict[str, Any], *, status_message: str
    ) -> str | None:
        self._require_destination(
            "video_workflow_tab", "set_source_bundle", "Video Workflow", "bundle"
        )
        snapshot = deepcopy(bundle)
        self._deliver(
            lambda: route_bundle_to_video_workflow(
                main_window=self._window,
                bundle=snapshot,
                status_message=status_message,
            )
        )
        return extract_source_image_for_handoff(snapshot)

    def image_to_movie_clips(self, image_path: str | Path, *, status_message: str) -> list[str]:
        self._require_destination(
            "movie_clips_tab", "set_source_frame_paths", "Movie Clips", "image"
        )
        path = str(image_path)
        self._deliver(
            lambda: route_image_to_movie_clips(
                main_window=self._window,
                image_path=path,
                status_message=status_message,
            )
        )
        return [path]

    def bundle_to_movie_clips(self, bundle: dict[str, Any], *, status_message: str) -> None:
        self._require_destination("movie_clips_tab", "set_source_bundle", "Movie Clips", "bundle")
        snapshot = deepcopy(bundle)
        self._deliver(
            lambda: route_bundle_to_movie_clips(
                main_window=self._window,
                bundle=snapshot,
                status_message=status_message,
            )
        )
