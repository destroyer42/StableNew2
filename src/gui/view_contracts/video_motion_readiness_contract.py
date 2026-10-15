"""Toolkit-neutral state for the Video Workflow "Motion source readiness" panel (PR-VID-196).

The session holds only transient, unsaved display state: the latest prepared-source preview, the
latest driving-video inspection and the guidance projection of the selected workflow.  It owns no
generation authority: the two operations that touch files (the exact source preview and the
bounded driving-video probe) are injected callables run on a worker, it never builds a payload,
touches the queue or names a workflow or model, and nothing it shows can change what is submitted.

Stale-result protection.  Each channel (source image, driving video) has a selection-generation
token that is bumped whenever its selection changes.  At most one worker per channel is in flight;
a selection that changes meanwhile cancels the running probe and the newest selection is started
when the old worker returns, so a completed worker can never overwrite a newer selection.
"""

from __future__ import annotations

import io
import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

from src.gui.view_contracts.video_experiment_contract import WorkOutcome
from src.video.driving_video_inspection import (
    PREVIEW_MAX_EDGE,
    STATUS_FAILED,
    DrivingVideoFacts,
    DrivingVideoInspection,
)
from src.video.motion_source_readiness import (
    BASIS_DERIVED,
    BASIS_MEASURED,
    BASIS_METADATA,
    DrivingFrameConsumption,
    MotionSourceAssessment,
    OutputTiming,
    assess_motion_source,
)
from src.video.workflow_source_preparation import WorkflowSourceGeometry

SOURCE_DISPLAY_MAX_EDGE = 240

STATE_IDLE = "idle"
STATE_LOADING = "loading"
STATE_READY = "ready"
STATE_ERROR = "error"

_BASIS_LABELS = {
    BASIS_MEASURED: "measured from the image",
    BASIS_METADATA: "reported by the file",
    BASIS_DERIVED: "derived",
}
_GUIDANCE_BASIS_LABELS = {
    "runtime": "pinned runtime",
    "declared": "declared",
    "tested": "tested, one sample",
    "unresolved": "tested, not delivered",
    "untested": "untested",
}


@dataclass(frozen=True)
class SourcePreviewWork:
    token: int
    path: str
    policy: dict[str, Any]


@dataclass(frozen=True)
class VideoInspectionWork:
    token: int
    path: str
    cancel: threading.Event = field(default_factory=threading.Event, compare=False)


@dataclass(frozen=True)
class SourcePreviewResult:
    geometry: WorkflowSourceGeometry
    display_png: bytes
    display_width: int
    display_height: int


@dataclass(frozen=True)
class FrameThumb:
    png_bytes: bytes
    caption: str


@dataclass(frozen=True)
class MotionReadinessView:
    """Everything the panel renders, as plain data (no Tk, no PIL)."""

    source_state: str
    source_png: bytes | None
    source_lines: tuple[str, ...]
    source_message: str
    video_state: str
    video_frames: tuple[FrameThumb, ...]
    reported_lines: tuple[str, ...]
    measured_lines: tuple[str, ...]
    video_message: str
    timing_lines: tuple[str, ...]
    advisory_lines: tuple[str, ...]
    guidance_supported: bool
    guidance_title: str
    guidance_lines: tuple[str, ...]
    summary: str
    busy: bool
    accepts_driving_video: bool


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def _dims(width: Any, height: Any) -> str:
    return f"{int(width)}x{int(height)}"


def _seconds(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.2f} s"


class MotionReadinessSession:
    """State machine behind the panel; see the module docstring for the staleness contract."""

    def __init__(
        self,
        *,
        preview_source: Callable[[str, Mapping[str, Any]], Any],
        inspect_video: Callable[[str, threading.Event], DrivingVideoInspection],
    ) -> None:
        self._preview_source = preview_source
        self._inspect_video = inspect_video
        self._meta: dict[str, Any] = {}
        self._frame_meta: dict[str, Any] | None = None
        self._selected_frames: int | None = None

        self._source_token = 0
        self._source_key: str | None = None
        self._source_path = ""
        self._source_policy: dict[str, Any] | None = None
        self._source_state = STATE_IDLE
        self._source_result: SourcePreviewResult | None = None
        self._source_error = ""
        self._source_inflight: SourcePreviewWork | None = None

        self._video_token = 0
        self._video_key: str | None = None
        self._video_path = ""
        self._video_state = STATE_IDLE
        self._video_result: DrivingVideoInspection | None = None
        self._video_error = ""
        self._video_inflight: VideoInspectionWork | None = None

    # ------------------------------------------------------------------ inputs (UI thread)

    @property
    def accepts_driving_video(self) -> bool:
        return bool(self._meta.get("accepts_driving_video"))

    @property
    def busy(self) -> bool:
        return self._source_inflight is not None or self._video_inflight is not None

    def refresh(
        self,
        *,
        source_path: str,
        video_path: str,
        readiness: Mapping[str, Any] | None,
        frame_count: Mapping[str, Any] | None,
        selected_frames: int | None,
        force: bool = False,
    ) -> list[SourcePreviewWork | VideoInspectionWork]:
        """Adopt the current selections; return the (at most two) workers the caller must start."""

        self._meta = dict(readiness) if isinstance(readiness, Mapping) else {}
        self._frame_meta = dict(frame_count) if isinstance(frame_count, Mapping) else None
        self._selected_frames = selected_frames
        started: list[SourcePreviewWork | VideoInspectionWork] = []

        policy = self._meta.get("source_preparation")
        policy = dict(policy) if isinstance(policy, Mapping) else None
        path = str(source_path or "").strip()
        source_key = _canonical([path, policy]) if path and policy is not None else None
        if force or source_key != self._source_key:
            self._source_token += 1
            self._source_key = source_key
            self._source_path, self._source_policy = path, policy
            self._source_result = None
            self._source_error = ""
            self._source_state = STATE_LOADING if source_key is not None else STATE_IDLE
            if source_key is not None and self._source_inflight is None:
                source_work = self._start_source()
                if source_work is not None:
                    started.append(source_work)

        video = str(video_path or "").strip() if self.accepts_driving_video else ""
        video_key = _canonical(video) if video else None
        if force or video_key != self._video_key:
            self._video_token += 1
            self._video_key = video_key
            self._video_path = video
            self._video_result = None
            self._video_error = ""
            self._video_state = STATE_LOADING if video_key is not None else STATE_IDLE
            if self._video_inflight is not None:
                self._video_inflight.cancel.set()  # the running probe is for a superseded selection
            elif video_key is not None:
                video_work = self._start_video()
                if video_work is not None:
                    started.append(video_work)
        return started

    def _start_source(self) -> SourcePreviewWork | None:
        if self._source_key is None or self._source_policy is None:
            return None
        work = SourcePreviewWork(
            token=self._source_token, path=self._source_path, policy=dict(self._source_policy)
        )
        self._source_inflight = work
        return work

    def _start_video(self) -> VideoInspectionWork | None:
        if self._video_key is None:
            return None
        work = VideoInspectionWork(token=self._video_token, path=self._video_path)
        self._video_inflight = work
        return work

    def close(self) -> None:
        """The panel is going away: stop the running probe and discard every late result."""

        self._source_token += 1
        self._video_token += 1
        self._source_key = self._video_key = None
        self._source_state = self._video_state = STATE_IDLE
        if self._video_inflight is not None:
            self._video_inflight.cancel.set()

    # ------------------------------------------------------------------ worker thread

    def run_source(self, work: SourcePreviewWork) -> WorkOutcome:
        try:
            transformed = self._preview_source(work.path, work.policy)
            display = transformed.image.copy()
            display.thumbnail(
                (SOURCE_DISPLAY_MAX_EDGE, SOURCE_DISPLAY_MAX_EDGE), Image.Resampling.LANCZOS
            )
            buffer = io.BytesIO()
            display.save(buffer, format="PNG")
            return WorkOutcome(
                value=SourcePreviewResult(
                    geometry=transformed.geometry,
                    display_png=buffer.getvalue(),
                    display_width=display.width,
                    display_height=display.height,
                )
            )
        except Exception as exc:  # a worker must always report back
            return WorkOutcome(error=str(exc) or type(exc).__name__)

    def run_video(self, work: VideoInspectionWork) -> WorkOutcome:
        try:
            return WorkOutcome(value=self._inspect_video(work.path, work.cancel))
        except Exception as exc:
            return WorkOutcome(error=str(exc) or type(exc).__name__)

    # ------------------------------------------------------------------ completion (UI thread)

    def finish_source(
        self, work: SourcePreviewWork, outcome: WorkOutcome
    ) -> SourcePreviewWork | None:
        """Apply a result only when it is for the current selection; else start the newest."""

        self._source_inflight = None
        if work.token == self._source_token:
            if outcome.error:
                self._source_state, self._source_error = STATE_ERROR, outcome.error
            else:
                self._source_state, self._source_result = STATE_READY, outcome.value
            return None
        if self._source_state == STATE_LOADING:
            return self._start_source()
        return None

    def finish_video(
        self, work: VideoInspectionWork, outcome: WorkOutcome
    ) -> VideoInspectionWork | None:
        self._video_inflight = None
        if work.token == self._video_token:
            inspection = outcome.value
            if outcome.error or not isinstance(inspection, DrivingVideoInspection):
                self._video_state = STATE_ERROR
                self._video_error = outcome.error or "The driving video could not be inspected."
            elif inspection.status == STATUS_FAILED:
                self._video_state = STATE_ERROR
                self._video_result = inspection
                self._video_error = (
                    inspection.issues[0].message
                    if inspection.issues
                    else "The driving video could not be inspected."
                )
            else:
                self._video_state, self._video_result = STATE_READY, inspection
            return None
        if self._video_state == STATE_LOADING:
            return self._start_video()
        return None

    # ------------------------------------------------------------------ projection

    def _output_timing(self) -> OutputTiming | None:
        meta = self._frame_meta
        if not meta:
            return None
        try:
            fps = int(meta["fps"])
            frames = int(self._selected_frames if self._selected_frames else meta["default"])
        except (KeyError, TypeError, ValueError):
            return None
        seconds = next(
            (
                float(choice["seconds"])
                for choice in meta.get("choices") or ()
                if int(choice.get("frames", -1)) == frames
            ),
            round(frames / fps, 1) if fps else 0.0,
        )
        return OutputTiming(
            frame_count=frames, fps=fps, seconds=seconds, from_default=not self._selected_frames
        )

    def _consumption(self) -> DrivingFrameConsumption | None:
        raw = self._meta.get("driving_frame_consumption")
        if not self.accepts_driving_video or not isinstance(raw, Mapping):
            return None
        return DrivingFrameConsumption(
            verified=bool(raw.get("verified")),
            reason=str(raw.get("reason") or ""),
            rule=str(raw.get("rule") or ""),
            runtime_revision=str(raw.get("runtime_revision") or ""),
        )

    def assessment(self) -> MotionSourceAssessment:
        geometry = self._source_result.geometry if self._source_result is not None else None
        facts: DrivingVideoFacts | None = None
        if self._video_result is not None and self._video_state == STATE_READY:
            facts = self._video_result.facts
        return assess_motion_source(
            geometry=geometry,
            driving=facts,
            output=self._output_timing(),
            consumption=self._consumption(),
        )

    def view(self) -> MotionReadinessView:
        assessment = self.assessment()
        source_lines: list[str] = []
        source_png: bytes | None = None
        if self._source_state == STATE_READY and assessment.source is not None:
            framing = assessment.source
            stored = (
                f" (stored {_dims(framing.stored_width, framing.stored_height)}, rotated by EXIF)"
                if framing.exif_transposed
                else ""
            )
            source_lines = [
                f"Source: {_dims(framing.width, framing.height)} {framing.orientation}{stored}",
                f"Prepared: {_dims(framing.prepared_width, framing.prepared_height)} "
                f"{framing.policy_orientation} (the exact prepared image, scaled for display)",
                f"Crop: x {framing.crop_left:.0f} to {framing.crop_right:.0f}, "
                f"y {framing.crop_top:.0f} to {framing.crop_bottom:.0f}; about "
                f"{framing.discarded_fraction * 100:.0f}% of the image is discarded.",
            ]
            source_png = self._source_result.display_png if self._source_result else None
        source_message = {
            STATE_IDLE: "Select a source image to preview how it will be prepared.",
            STATE_LOADING: "Preparing the preview...",
            STATE_ERROR: self._source_error,
        }.get(self._source_state, "")
        if (
            self._source_state == STATE_IDLE
            and self._meta
            and self._meta.get("source_preparation") is None
        ):
            source_message = "This workflow declares no source preparation, so there is no preview."

        reported: list[str] = []
        measured: list[str] = []
        frames: list[FrameThumb] = []
        video_message = {
            STATE_LOADING: "Inspecting the driving video...",
            STATE_ERROR: self._video_error,
        }.get(self._video_state, "")
        if self._video_state == STATE_READY and self._video_result is not None:
            inspection = self._video_result
            facts = inspection.facts
            if facts is not None:
                reported.extend(self._reported_lines(facts))
            decoded = len(inspection.frames)
            measured.append(
                f"Decoded {decoded} of {inspection.requested_frames} preview frame(s), each "
                f"scaled to at most {PREVIEW_MAX_EDGE} px; the file was not scanned in full."
            )
            for issue in inspection.issues:
                measured.append(f"Note: {issue.message}")
            frames = [
                FrameThumb(frame.png_bytes, f"{frame.position_seconds:.1f} s")
                for frame in inspection.frames
            ]
        elif self._video_state == STATE_ERROR and self._video_result is not None:
            for issue in self._video_result.issues[1:]:
                measured.append(f"Note: {issue.message}")

        timing_lines = self._timing_lines(assessment)
        advisory_lines = tuple(
            f"{item.message} [{_BASIS_LABELS.get(item.basis, item.basis)}]"
            for item in assessment.advisories
        )
        guidance = self._meta.get("guidance")
        guidance_lines: tuple[str, ...] = ()
        guidance_title = ""
        supported = False
        if isinstance(guidance, Mapping):
            guidance_title = str(guidance.get("title") or "")
            supported = bool(guidance.get("supported"))
            guidance_lines = tuple(self._guidance_lines(guidance))
        summary = ""
        if STATE_READY in (self._source_state, self._video_state):
            count = len(advisory_lines)
            summary = f"{count} advisory note(s)" if count else "No geometry or timing advisories"
        return MotionReadinessView(
            source_state=self._source_state,
            source_png=source_png,
            source_lines=tuple(source_lines),
            source_message=source_message,
            video_state=self._video_state,
            video_frames=tuple(frames),
            reported_lines=tuple(reported),
            measured_lines=tuple(measured),
            video_message=video_message,
            timing_lines=tuple(timing_lines),
            advisory_lines=advisory_lines,
            guidance_supported=supported,
            guidance_title=guidance_title,
            guidance_lines=guidance_lines,
            summary=summary,
            busy=self.busy,
            accepts_driving_video=self.accepts_driving_video,
        )

    @staticmethod
    def _reported_lines(facts: DrivingVideoFacts) -> list[str]:
        lines = [
            f"Size: {_dims(facts.display_width, facts.display_height)} {facts.orientation}, "
            f"aspect {facts.aspect_ratio:.2f}"
            + (
                f" (stored {_dims(facts.coded_width, facts.coded_height)}, rotated by metadata)"
                if facts.rotation_quadrants % 2
                else ""
            )
        ]
        if facts.reported_fps is None:
            lines.append("Frame rate: unknown")
        else:
            lines.append(
                f"Frame rate: {facts.reported_fps:g} fps ({facts.fps_basis}"
                + (", possibly variable" if facts.fps_is_variable_suspected else "")
                + ")"
            )
        if facts.frame_count is None:
            lines.append("Frames: unknown")
        elif facts.frame_count_basis == "reported":
            lines.append(f"Frames: {facts.frame_count} (reported)")
        else:
            lines.append(f"Frames: about {facts.frame_count} (estimated from duration and fps)")
        lines.append(f"Duration: {_seconds(facts.duration_seconds)}")
        detail = " / ".join(
            part for part in (facts.codec_name, facts.pixel_format, facts.container_format) if part
        )
        if detail:
            lines.append(f"Encoding: {detail}")
        if facts.sample_aspect_ratio:
            lines.append(
                f"Pixel aspect ratio: {facts.sample_aspect_ratio} (reported; framing figures use "
                "stored pixel dimensions)"
            )
        return lines

    def _timing_lines(self, assessment: MotionSourceAssessment) -> list[str]:
        timing = assessment.timing
        if timing is None:
            return []
        lines: list[str] = []
        if timing.output_frames is not None and timing.output_fps is not None:
            origin = self._selected_frames is None
            lines.append(
                f"Output: {timing.output_frames} frames at {timing.output_fps} fps "
                f"(about {timing.output_seconds:.1f} s"
                + (", workflow default" if origin else "")
                + ")"
            )
        if not self.accepts_driving_video:
            return lines
        if self._video_state != STATE_READY:
            lines.append("Driving-frame use: select a readable driving video to see it.")
            return lines
        if not timing.consumption_known:
            lines.append(f"Driving-frame use: unknown. {timing.consumption_note}")
            return lines
        lines.append(f"Driving-frame use: {timing.consumption_note}")
        if timing.driving_frames_used is not None and timing.driving_frames is not None:
            about = "" if timing.driving_frames_basis == "reported" else "about "
            lines.append(
                f"Uses {timing.driving_frames_used} of {about}{timing.driving_frames} driving "
                "frames."
            )
        if timing.playback_speed_vs_original is not None and timing.driving_fps is not None:
            lines.append(
                f"Timeline: a {timing.driving_fps:g} fps clip into a {timing.output_fps} fps output "
                f"= {timing.playback_speed_vs_original:.2f}x its original speed (derived "
                "arithmetic; the generated motion is not measured)."
            )
        return lines

    @staticmethod
    def _guidance_lines(guidance: Mapping[str, Any]) -> list[str]:
        lines: list[str] = []
        summary = str(guidance.get("summary") or "")
        if summary:
            lines.append(summary)
        for topic in guidance.get("topics") or ():
            lines.append("")
            lines.append(str(topic.get("title") or ""))
            for point in topic.get("points") or ():
                basis = _GUIDANCE_BASIS_LABELS.get(str(point.get("basis")), str(point.get("basis")))
                lines.append(f"  - [{basis}] {point.get('text')}")
                for evidence in point.get("evidence") or ():
                    lines.append(f"      evidence: {evidence}")
        wording = guidance.get("tested_wording") or ()
        if wording:
            lines.append("")
            lines.append("Wording that was actually run (reference only; nothing is inserted):")
            for item in wording:
                lines.append(f'  - {item.get("label")}: "{item.get("text")}"')
                lines.append(f"      result: {item.get('outcome')} ({item.get('evidence')})")
        limitations = guidance.get("limitations") or ()
        if limitations:
            lines.append("")
            lines.append("Limits of this evidence:")
            lines.extend(f"  - {item}" for item in limitations)
        policy = str(guidance.get("prompt_policy") or "")
        if policy:
            lines.append("")
            lines.append(policy)
        return lines


__all__ = [
    "SOURCE_DISPLAY_MAX_EDGE",
    "STATE_ERROR",
    "STATE_IDLE",
    "STATE_LOADING",
    "STATE_READY",
    "FrameThumb",
    "MotionReadinessSession",
    "MotionReadinessView",
    "SourcePreviewResult",
    "SourcePreviewWork",
    "VideoInspectionWork",
]
