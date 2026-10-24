"""Toolkit-neutral state of the "Create map from image" task (PR-IMG-CNET-230).

The flow owns what the dialog may show and do: choose a source and a map type, prepare a preview on a tracked worker,
cancel it, and save-and-use the result. It never touches a widget. Worker threads only run the service and hand their
outcome to ``post``, which the GUI marshals onto its own thread; every method and every ``on_change`` call therefore runs
on the GUI thread. A newer source or map type (or a cancel, or closing) supersedes whatever is in flight: its late result
is dropped and the stale preview is cleared, so a map prepared from something no longer selected can never be saved.

The flow submits no job and starts no runtime; it only calls ``ReferenceMapService``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any

from src.conditioning.openpose_library import thumbnail_png
from src.conditioning.reference_map.contracts import (
    CODE_CANCELLED,
    CODE_SOURCE_CHANGED,
    CODE_UNAVAILABLE,
    MapRequest,
    PreparedMap,
    ReferenceMapError,
    warning_text,
)
from src.conditioning.reference_map.library import SavedMap

PREVIEW_EDGE = 320
Spawn = Callable[[Callable[[], None], str], Any]
Post = Callable[[Callable[[], None]], None]
_Outcome = tuple[PreparedMap | None, bytes | None, ReferenceMapError | None]


class FlowState(Enum):
    IDLE = "idle"
    PREPARING = "preparing"
    READY = "ready"
    SAVING = "saving"
    SAVED = "saved"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class FlowView:
    state: FlowState = FlowState.IDLE
    source_name: str = ""
    modality: str = "canny"
    message: str = "Choose a source image."
    #: Stable reason codes behind an unavailable or failed attempt (shown verbatim; never message-parsed).
    reasons: tuple[str, ...] = ()
    failure_code: str = ""
    preview_png: bytes | None = None
    facts: str = ""
    warnings: tuple[str, ...] = ()
    can_choose: bool = True
    can_prepare: bool = False
    can_cancel: bool = False
    can_save: bool = False


def _default_spawn(target: Callable[[], None], name: str) -> Any:
    from src.utils.thread_registry import get_thread_registry

    return get_thread_registry().spawn(
        target=target, name=name, daemon=False, purpose="Create a ControlNet reference map"
    )


class ReferenceMapFlow:
    def __init__(
        self,
        service: Any,
        *,
        post: Post,
        on_change: Callable[[FlowView], None],
        spawn: Spawn = _default_spawn,
        save_gate: Callable[[str], bool] | None = None,
    ) -> None:
        self._service = service
        self._post = post
        self._on_change = on_change
        self._spawn = spawn
        self._save_gate = save_gate or (lambda _modality: True)
        self._source: Path | None = None
        self._generation = 0
        self._cancel: threading.Event | None = None
        self._prepared: PreparedMap | None = None
        self._closed = False
        self._view = FlowView()

    # ------------------------------------------------------------------ queries

    @property
    def view(self) -> FlowView:
        return self._view

    @property
    def prepared(self) -> PreparedMap | None:
        return self._prepared

    def availability(self, modality: str) -> tuple[str, ...]:
        """Cheap reason codes that make ``modality`` unavailable here (empty when it looks usable)."""

        return tuple(self._service.availability(modality))

    # ------------------------------------------------------------------ operator actions (GUI thread)

    def set_source(self, path: Path | str | None) -> None:
        self._supersede()
        self._source = Path(path) if path else None
        self._publish(
            FlowView(
                state=FlowState.IDLE,
                source_name=self._source.name if self._source else "",
                modality=self._view.modality,
                message=("Press Create preview." if self._source else "Choose a source image."),
                can_prepare=self._source is not None,
            )
        )

    def set_modality(self, modality: str) -> None:
        if modality == self._view.modality:
            return
        self._supersede()
        self._publish(
            FlowView(
                state=FlowState.IDLE,
                source_name=self._view.source_name,
                modality=modality,
                message="Press Create preview." if self._source else "Choose a source image.",
                can_prepare=self._source is not None,
            )
        )

    def prepare(self) -> None:
        if (
            self._source is None
            or self._closed
            or self._view.state
            in (
                FlowState.PREPARING,
                FlowState.SAVING,
            )
        ):
            return
        modality = self._view.modality
        reasons = self.availability(modality)
        if reasons:
            self._publish(
                replace(
                    self._idle(),
                    state=FlowState.FAILED,
                    message=(
                        "This map type is unavailable on this machine, and no other map type is substituted. "
                        "Pick a pre-rendered map instead, or fix the reasons below."
                    ),
                    reasons=tuple(reasons),
                    failure_code=CODE_UNAVAILABLE,
                )
            )
            return
        self._supersede()
        generation, cancel = self._generation, threading.Event()
        self._cancel = cancel
        request = MapRequest(self._source, modality)
        self._publish(
            replace(
                self._idle(),
                state=FlowState.PREPARING,
                message="Creating the map… This can take a while for depth and pose.",
                can_choose=False,
                can_cancel=True,
            )
        )

        def work() -> None:
            outcome: _Outcome
            try:
                prepared = self._service.prepare(request, cancel.is_set)
                outcome = (prepared, thumbnail_png(prepared.png, PREVIEW_EDGE), None)
            except ReferenceMapError as exc:
                outcome = (None, None, exc)
            except Exception:  # noqa: BLE001 - a content-free failure reaches the dialog; nothing is logged with paths
                outcome = (
                    None,
                    None,
                    ReferenceMapError("inference_failed", "Creating the map failed unexpectedly."),
                )
            self._post(lambda: self._finish_prepare(generation, outcome))

        self._spawn(work, "ReferenceMap-Prepare")

    def cancel(self) -> None:
        if self._view.state is not FlowState.PREPARING:
            return
        self._supersede()
        self._publish(
            replace(
                self._idle(),
                message="Cancelled. No map was kept.",
                can_prepare=self._source is not None,
            )
        )

    def save(self, on_saved: Callable[[SavedMap, PreparedMap], None]) -> None:
        prepared = self._prepared
        if (
            prepared is None
            or self._closed
            or self._view.state is not FlowState.READY
            or not self._save_gate(prepared.modality)
        ):
            return
        generation = self._generation
        self._publish(
            replace(
                self._view,
                state=FlowState.SAVING,
                message="Saving to the library…",
                can_choose=False,
                can_prepare=False,
                can_cancel=False,
                can_save=False,
            )
        )

        def work() -> None:
            try:
                saved: SavedMap | None = self._service.save(prepared)
                error = None
            except ReferenceMapError as exc:
                saved, error = None, exc
            except Exception:  # noqa: BLE001
                saved, error = (
                    None,
                    ReferenceMapError("library_write_failed", "Saving the map failed."),
                )
            self._post(lambda: self._finish_save(generation, prepared, saved, error, on_saved))

        self._spawn(work, "ReferenceMap-Save")

    def close(self) -> None:
        self._closed = True
        self._supersede()
        self._prepared = None

    # ------------------------------------------------------------------ completion (GUI thread, via post)

    def _finish_prepare(self, generation: int, outcome: _Outcome) -> None:
        if self._closed or generation != self._generation:
            return  # superseded: the stale result is dropped and nothing of it is kept
        prepared, preview, error = outcome
        self._cancel = None
        if error is not None or prepared is None:
            if error is not None and error.code == CODE_CANCELLED:
                self._publish(
                    replace(
                        self._idle(),
                        message="Cancelled. No map was kept.",
                        can_prepare=self._source is not None,
                    )
                )
                return
            self._publish(
                replace(
                    self._idle(),
                    state=FlowState.FAILED,
                    message=error.message if error else "Creating the map failed.",
                    reasons=error.reasons if error else (),
                    failure_code=error.code if error else "",
                    can_prepare=self._source is not None,
                )
            )
            return
        self._prepared = prepared
        facts = (
            f"{prepared.width}×{prepared.height} px, PNG {len(prepared.png) // 1024} KiB, "
            f"SHA-256 {prepared.sha256[:12]}…"
        )
        self._publish(
            replace(
                self._idle(),
                state=FlowState.READY,
                message="Preview ready. Nothing is saved yet.",
                preview_png=preview,
                facts=facts,
                warnings=tuple(warning_text(code) for code in prepared.warnings),
                can_prepare=True,
                can_save=self._save_gate(prepared.modality),
            )
        )

    def _finish_save(
        self,
        generation: int,
        prepared: PreparedMap,
        saved: SavedMap | None,
        error: ReferenceMapError | None,
        on_saved: Callable[[SavedMap, PreparedMap], None],
    ) -> None:
        if self._closed:
            return
        if error is not None or saved is None:
            stale = error is not None and error.code == CODE_SOURCE_CHANGED
            if stale:
                self._prepared = (
                    None  # the preview no longer matches its source: it can never be saved
                )
            self._publish(
                replace(
                    self._view,
                    state=FlowState.FAILED if stale else FlowState.READY,
                    message=(error.message if error else "Saving the map failed.")
                    + ("" if stale else " The preview is still here; nothing was attached."),
                    failure_code=error.code if error else "",
                    preview_png=None if stale else self._view.preview_png,
                    can_choose=True,
                    can_prepare=self._source is not None,
                    can_save=not stale and self._save_gate(prepared.modality),
                )
            )
            return
        note = "" if saved.provenance_saved else " (provenance note could not be written)"
        self._publish(
            replace(
                self._view,
                state=FlowState.SAVED,
                message=f"Saved as {saved.identity} and attached{note}. No job was queued.",
                can_choose=True,
                can_prepare=True,
                can_save=False,
            )
        )
        on_saved(saved, prepared)

    # ------------------------------------------------------------------ helpers

    def _idle(self) -> FlowView:
        return FlowView(
            source_name=self._view.source_name,
            modality=self._view.modality,
        )

    def _supersede(self) -> None:
        self._generation += 1
        if self._cancel is not None:
            self._cancel.set()
            self._cancel = None
        self._prepared = None

    def _publish(self, view: FlowView) -> None:
        self._view = view
        self._on_change(view)


__all__ = ["FlowState", "FlowView", "ReferenceMapFlow", "PREVIEW_EDGE"]
