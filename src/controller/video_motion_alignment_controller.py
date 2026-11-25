"""Spatial-alignment support on the Video Workflow controller (PR-VID-MOTION-420).

A mixin so ``VideoWorkflowController`` keeps one surface for the Video Workflow tab (and stays under its
size guard).  Every call here is a local media operation: nothing queues work, builds a job, starts a
runtime or reaches the network.  The heavy ones (FFmpeg decode, the aligned encode) are meant to be called
from a worker the view owns; the pure ones (support, observations) are cheap.

The aligned clip enters a job only through the existing prepared-motion contract: the form carries the record
``prepare_aligned_motion_source`` returned, and ``VideoWorkflowNjrBuilder`` re-verifies every byte at admission.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from typing import Any

from src.video.driving_frame_consumption import driving_frame_consumption
from src.video.motion_alignment_compatibility import SubjectObservations
from src.video.motion_alignment_preparation import (
    AlignmentPreview,
    PreviewSource,
    aligned_request_for_form,
    load_preview_source,
    prepare_aligned_for_form,
    render_preview,
)
from src.video.motion_alignment_support import AlignmentSupport, alignment_support
from src.video.motion_library.models import UNKNOWN as LIBRARY_UNKNOWN
from src.video.motion_library.store import LibraryError
from src.video.motion_source_readiness import assess_motion_source, requested_output_timing
from src.video.workflow_motion_guidance import motion_guidance


class VideoMotionAlignmentControllerMixin:
    """Requires ``_njr_builder`` and (for annotations) the Motion Library mixin on the host controller."""

    _njr_builder: Any

    def motion_alignment_support(self, form: Mapping[str, Any]) -> AlignmentSupport:
        """Whether the form's selected workflow can take an aligned clip, and why not."""

        try:
            spec = self._njr_builder.spec_for(form)
        except Exception as exc:  # noqa: BLE001 - an unknown workflow only means "not offered"
            return AlignmentSupport(False, f"Alignment is not offered: {exc}")
        return alignment_support(spec)

    def load_alignment_frames(
        self,
        form: Mapping[str, Any],
        request: Mapping[str, Any],
        indices: Sequence[int],
        cancel: threading.Event | None = None,
    ) -> PreviewSource:
        """Decode the planned driving frames for chosen output frames (worker-thread safe; writes nothing
        that survives the call and publishes nothing)."""

        try:
            aligned = aligned_request_for_form(self._njr_builder.spec_for(form), form, request)
        except ValueError as exc:
            return PreviewSource("failed", str(exc), "unavailable")
        loaded = load_preview_source(
            aligned, indices, output_root=self._njr_builder.output_dir(), cancel=cancel
        )
        if loaded.ok:
            loaded.readiness_notes = self._readiness_notes(form, loaded)
            loaded.historical_notes = self._historical_notes(form)
        return loaded

    def _historical_notes(self, form: Mapping[str, Any]) -> tuple[str, ...]:
        """The workflow's recorded evidence statements (basis and all), reused from the existing guidance projection."""

        try:
            guidance = motion_guidance(self._njr_builder.spec_for(form))
        except Exception:  # noqa: BLE001 - evidence is optional context, never the reason a preview fails
            return ()
        return tuple(
            f"{topic.title}: {point.text} [{point.basis}]"
            for topic in guidance.topics
            for point in topic.points
        )[:8]

    def _readiness_notes(self, form: Mapping[str, Any], loaded: PreviewSource) -> tuple[str, ...]:
        """The existing readiness advisories (crop, upscaling, rotation, timing) for this pairing, reused as is.

        The geometry and the clip facts are the ones the preview already measured; nothing is inspected twice and
        nothing here changes a job."""

        try:
            spec = self._njr_builder.spec_for(form)
            assessment = assess_motion_source(
                geometry=loaded.source_geometry,
                driving=loaded.facts,
                output=requested_output_timing(spec, form.get("frame_count")),
                consumption=driving_frame_consumption(spec),
            )
        except Exception:  # noqa: BLE001 - advisories are optional context, never the reason a preview fails
            return ()
        return tuple(advisory.message for advisory in assessment.advisories)

    @staticmethod
    def render_alignment_frames(loaded: PreviewSource, intent: Any) -> AlignmentPreview:
        """Re-render decoded frames under an alignment (pure CPU; no process)."""

        return render_preview(loaded, intent)

    def prepare_aligned_motion_source(
        self,
        form: Mapping[str, Any],
        request: Mapping[str, Any],
        cancel: threading.Event | None = None,
    ) -> Any:
        """Prepare the aligned clip for the form's workflow, length, clip and source image (worker-thread safe)."""

        builder = self._njr_builder
        return prepare_aligned_for_form(
            builder.spec_for(form), form, request, builder.output_dir(), cancel
        )

    def motion_asset_observations(self, asset_id: str) -> SubjectObservations | None:
        """What the Motion Library reports about a clip, as *reported* (never verified) observations."""

        library = getattr(self, "motion_library", None)
        if not asset_id or not callable(library):
            return None
        try:
            asset = library().get(asset_id)
        except (LibraryError, OSError, KeyError, AttributeError):
            return None
        if asset is None:
            return None

        def known(value: str) -> str:
            return value if value else LIBRARY_UNKNOWN

        return SubjectObservations(
            kind=known(asset.subject_kind),
            count=asset.subject_count,
            framing=known(asset.framing),
            viewpoint=known(asset.viewpoint),
            start_pose=asset.start_pose or "",
            camera_movement=known(asset.camera_movement),
            motion_direction=asset.motion_direction or "",
        )


__all__ = ["VideoMotionAlignmentControllerMixin"]
