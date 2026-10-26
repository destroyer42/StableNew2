"""Toolkit-neutral presentation effects requested by application commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from src.utils.error_envelope_v2 import UnifiedErrorEnvelope


class PresentationActions(Protocol):
    """A host-owned attachment; detach fences all pending presentation requests.

    Navigation returns the accepted source payload, not completion of rendering.
    Hosts deliver effects through their existing UiDispatcher, inline on the UI
    thread. Missing destinations raise RuntimeError at request time.
    """

    def open_debug_hub(self) -> None: ...

    def explain_job(self, job_id: str) -> None: ...

    def show_structured_error(self, envelope: UnifiedErrorEnvelope) -> None: ...

    def image_to_video_workflow(
        self,
        image_path: str | Path,
        *,
        status_message: str,
        lineage: dict[str, str] | None = None,
    ) -> str: ...

    def bundle_to_video_workflow(
        self,
        bundle: dict[str, Any],
        *,
        status_message: str,
    ) -> str | None: ...

    def image_to_movie_clips(
        self,
        image_path: str | Path,
        *,
        status_message: str,
    ) -> list[str]: ...

    def bundle_to_movie_clips(
        self,
        bundle: dict[str, Any],
        *,
        status_message: str,
    ) -> None: ...

    def detach(self) -> None: ...
