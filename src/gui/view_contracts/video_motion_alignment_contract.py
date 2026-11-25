"""Toolkit-neutral state for the Video Workflow "Align Motion" workspace (PR-VID-MOTION-420).

The session holds two things and keeps them apart:

* the **draft** the operator is editing in the workspace (scale, shift, mirror, marked anchors, a pending
  suggestion, entered subject bounds and observations).  Editing and inspecting never queue a job, start a
  runtime or change what the form submits;
* the **applied alignment** the operator explicitly accepted for the *current* source image, driving clip,
  window, workflow and length.  Only an applied alignment whose aligned clip was prepared and is still current
  contributes to the form (as the existing ``prepared_motion_source`` record); a running, failed, cancelled,
  unprepared or out-of-date one contributes a blocker instead, so a job never silently falls back to the
  unaligned clip while looking aligned.

The workspace status words (not applied, editing, preparation required, preparing, verified, stale, failed or
unsupported) are preparation/UI states, not job lifecycle states.  Decoding, rendering and the aligned encode
are injected ports run on workers; a result for a superseded request is dropped by a token, and a running
worker is cancelled by its own ``threading.Event``.  Nothing here imports Tk, PIL, the queue or a runner.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.gui.view_contracts.video_motion_readiness_contract import FrameThumb
from src.video.motion_alignment import (
    IDENTITY,
    ORIGIN_ANCHOR_FIT,
    AlignmentError,
    AlignmentIntent,
    AnchorPair,
    FitResult,
    Rect,
    ResolvedAlignment,
    fit_anchors,
    inspect_envelope,
    resolve_alignment,
)
from src.video.motion_alignment_compatibility import (
    CompatibilityAssessment,
    MediaFacts,
    SubjectObservations,
    assess_compatibility,
)

PREPARED_FIELD = "prepared_motion_source"
BLOCKED_FIELD = "motion_source_preparation_blocked"

STATUS_NOT_APPLIED = "not_applied"
STATUS_EDITING = "editing"
STATUS_PREPARATION_REQUIRED = "preparation_required"
STATUS_PREPARING = "preparing"
STATUS_VERIFIED = "verified"
STATUS_STALE = "stale"
STATUS_FAILED = "failed"
STATUS_LABELS = {
    STATUS_NOT_APPLIED: "Not applied",
    STATUS_EDITING: "Editing",
    STATUS_PREPARATION_REQUIRED: "Preparation required",
    STATUS_PREPARING: "Preparing",
    STATUS_VERIFIED: "Verified",
    STATUS_STALE: "Stale",
    STATUS_FAILED: "Failed or unsupported",
}

VIEW_SIDE_BY_SIDE = "side_by_side"
VIEW_OVERLAY = "overlay"
SHOW_ALIGNED = "aligned"
SHOW_ORIGINAL = "original"
MAX_SAMPLE_FRAMES = 9
_KEY_LABELS = (
    "workflow",
    "workflow version",
    "length",
    "driving video",
    "source image",
    "start",
    "end",
    "frame-rate conversion",
    "driving video file",
    "source image file",
)
_ROOT_CHOICES = ("unknown", "none", "small", "large")


@dataclass(frozen=True)
class AlignInputs:
    """A plain snapshot of what the workspace reads from the form (Tk reads happen before this)."""

    available: bool
    unavailable_reason: str = ""
    workflow_id: str = ""
    workflow_version: str = ""
    frame_count: int | None = None
    output_fps: int | None = None
    clip_path: str = ""
    source_path: str = ""
    start_text: str = ""
    end_text: str = ""
    convert: bool = False
    #: ``(size, mtime_ns)`` of the two files: a cheap proxy for "the bytes changed"; admission re-hashes.
    clip_stat: tuple[int, int] | None = None
    source_stat: tuple[int, int] | None = None
    library_asset_id: str = ""

    def key(self) -> tuple[Any, ...]:
        return (
            self.workflow_id,
            self.workflow_version,
            self.frame_count,
            self.clip_path.strip(),
            self.source_path.strip(),
            self.start_text.strip(),
            self.end_text.strip(),
            bool(self.convert),
            self.clip_stat,
            self.source_stat,
        )


@dataclass(frozen=True)
class AlignPorts:
    load: Callable[[Mapping[str, Any], Mapping[str, Any], Sequence[int], threading.Event], Any]
    render: Callable[[Any, AlignmentIntent], Any]
    prepare: Callable[[Mapping[str, Any], Mapping[str, Any], threading.Event], Any]
    driver_observations: Callable[[str], SubjectObservations | None] = lambda _asset_id: None
    #: False when the content-visibility policy (or "Show media") hides the source image or the driving
    #: clip: nothing is then opened, decoded or previewed.
    media_allowed: Callable[[], bool] = lambda: True


@dataclass(frozen=True)
class Marker:
    kind: str
    x: float
    y: float
    label: str = ""


@dataclass(frozen=True)
class AlignView:
    """Everything the workspace renders, as plain data (no Tk, no PIL)."""

    status: str
    status_label: str
    status_text: str
    available: bool
    unavailable_reason: str
    loading: bool
    load_message: str
    can_apply: bool
    can_prepare: bool
    can_cancel: bool
    can_discard: bool
    can_suggest: bool
    scale_text: str
    translate_x_text: str
    translate_y_text: str
    mirror: bool
    param_error: str
    geometry_lines: tuple[str, ...]
    explanation_lines: tuple[str, ...]
    view_mode: str
    show: str
    opacity: float
    frame_indices: tuple[int, ...]
    selected_frame: int | None
    source_png: bytes | None
    baseline_png: bytes | None
    aligned_png: bytes | None
    target_size: tuple[int, int] | None
    driver_size: tuple[int, int] | None
    source_markers: tuple[Marker, ...]
    driver_markers: tuple[Marker, ...]  # in target-frame pixels of the shown driver view
    anchor_lines: tuple[str, ...]
    pending_prompt: str
    proposal_lines: tuple[str, ...]
    has_proposal: bool
    envelope_lines: tuple[str, ...]
    compatibility: CompatibilityAssessment | None
    identity_lines: tuple[str, ...]
    mirror_disclosure: str
    frames: tuple[FrameThumb, ...] = ()
    #: Where the driving frame sits in the target frame (left, top, right, bottom), aligned and baseline.
    placement: tuple[float, float, float, float] | None = None
    baseline_placement: tuple[float, float, float, float] | None = None


@dataclass
class _Applied:
    intent: AlignmentIntent
    key: tuple[Any, ...]
    state: str = "required"  # required | preparing | ready | failed
    record: Mapping[str, Any] | None = None
    message: str = ""
    explanation: tuple[str, ...] = ()
    preview: Any = None


@dataclass
class _Draft:
    scale_text: str = "1"
    tx_text: str = "0"
    ty_text: str = "0"
    mirror: bool = False

    def reset(self) -> None:
        self.scale_text, self.tx_text, self.ty_text, self.mirror = "1", "0", "0", False


def _number(text: str, label: str) -> float:
    cleaned = str(text).strip()
    try:
        value = float(cleaned)
    except ValueError as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number.")
    return value


def _short(sha: Any) -> str:
    return str(sha or "")[:12]


def sample_indices(frames: int, limit: int = MAX_SAMPLE_FRAMES) -> tuple[int, ...]:
    """First, middle and last output frame plus evenly spaced others, at most ``limit``."""

    if frames <= 0:
        return ()
    if frames <= limit:
        return tuple(range(frames))
    return tuple(sorted({round(i * (frames - 1) / (limit - 1)) for i in range(limit)}))


class MotionAlignmentSession:
    """State machine behind the Align Motion workspace; see the module docstring for the contract."""

    def __init__(
        self,
        *,
        ports: AlignPorts,
        runner: BackgroundWorkRunner,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._ports = ports
        self._runner = runner
        self._listeners: list[Callable[[], None]] = [on_change] if on_change is not None else []
        self._closed = False
        self._inputs = AlignInputs(available=False)
        self._draft = _Draft()
        self._applied: _Applied | None = None
        self._tokens: dict[str, int] = {}
        self._cancels: dict[str, threading.Event] = {}
        self._loaded: Any = None
        self._loaded_key: tuple[Any, ...] | None = None
        self._loading = False
        self._load_message = ""
        self._preview: Any = None
        self._resolved: ResolvedAlignment | None = None
        self._param_error = ""
        self.workspace_open = False
        self.view_mode = VIEW_SIDE_BY_SIDE
        self.show = SHOW_ALIGNED
        self.opacity = 0.5
        self.selected_frame: int | None = None
        self._extra_frames: set[int] = set()
        self.anchors: list[AnchorPair] = []
        self._pending_kind = ""
        self._pending_source: tuple[float, float] | None = None
        self._pending_driver: tuple[float, float] | None = None
        self._proposal: FitResult | None = None
        self._fit: tuple[tuple[AnchorPair, ...], Mapping[str, Any]] | None = None
        self._rendering = False
        self.source_obs = SubjectObservations()
        self.driver_obs = SubjectObservations()
        self._driver_loaded_for = ""
        self._envelope: dict[int, Rect] = {}
        self._notice = ""

    # ------------------------------------------------------------------ plumbing

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Hear about every change (UI thread).  Returns the function that stops listening."""

        self._listeners.append(callback)

        def unsubscribe() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)

        return unsubscribe

    def _notify(self) -> None:
        if self._closed:
            return
        for callback in tuple(self._listeners):
            callback()

    def _next(self, kind: str) -> int:
        self._tokens[kind] = self._tokens.get(kind, 0) + 1
        previous = self._cancels.pop(kind, None)
        if previous is not None:
            previous.set()  # the superseded worker stops at its next bounded step
        self._cancels[kind] = threading.Event()
        return self._tokens[kind]

    def _live(self, kind: str, token: int) -> bool:
        return not self._closed and self._tokens.get(kind) == token

    def _run(
        self, kind: str, work: Callable[[threading.Event], Any], finish: Callable[[Any], None]
    ) -> None:
        token = self._next(kind)
        cancel = self._cancels[kind]

        def done(outcome: WorkOutcome) -> None:
            if not self._live(kind, token):
                return  # superseded, closed or cleared meanwhile: the result no longer applies
            finish(outcome)
            self._notify()

        def task() -> WorkOutcome:
            try:
                return WorkOutcome(value=work(cancel))
            except (OSError, ValueError, RuntimeError, LookupError, TypeError) as exc:
                return WorkOutcome(error=str(exc) or type(exc).__name__)

        self._runner.start(f"align-{kind}", task, done)

    def _cancel_kind(self, kind: str) -> None:
        event = self._cancels.get(kind)
        if event is not None:
            event.set()

    @property
    def inputs(self) -> AlignInputs:
        return self._inputs

    # ------------------------------------------------------------------ inputs

    def _stale_names(self) -> list[str]:
        applied = self._applied
        if applied is None:
            return []
        current = self._inputs.key()
        return [
            label
            for label, then, now in zip(_KEY_LABELS, applied.key, current, strict=True)
            if then != now
        ]

    def refresh(self, inputs: AlignInputs) -> None:
        """Adopt the current form.  A changed material input makes the applied alignment stale and the
        loaded preview obsolete; nothing is silently reused."""

        previous = self._inputs
        if inputs == previous:
            return  # nothing moved: no notification, so a listener that re-reads the form cannot loop
        self._inputs = inputs
        applied = self._applied
        if applied is not None and applied.state == "preparing" and self._stale_names():
            self._cancel_kind("prepare")  # what it prepares is no longer what the form asks for
        if self._loaded_key is not None and inputs.key() != self._loaded_key:
            self._next("load")  # supersede and cancel a decode of the old inputs
            self._loaded, self._loaded_key, self._preview, self._resolved = None, None, None, None
            self._loading = False
            self._load_message = (
                "The inputs changed; reopen the workspace or press Reload to decode the new frames."
            )
            self.anchors.clear()
            self._proposal = None
            self._envelope.clear()
        if (
            inputs.library_asset_id != previous.library_asset_id
            or inputs.library_asset_id != self._driver_loaded_for
        ):
            self._load_driver_observations(inputs.library_asset_id)
        self._notify()

    def _load_driver_observations(self, asset_id: str) -> None:
        self._driver_loaded_for = asset_id
        found = self._ports.driver_observations(asset_id) if asset_id else None
        # Reported by the Motion Library, never verified: the operator may overwrite every field.
        self.driver_obs = found if found is not None else SubjectObservations()

    # ------------------------------------------------------------------ draft controls

    @property
    def draft(self) -> _Draft:
        return self._draft

    def set_params(
        self,
        *,
        scale: str | None = None,
        translate_x: str | None = None,
        translate_y: str | None = None,
        mirror: bool | None = None,
    ) -> None:
        self._fit = None  # adjusting by hand: the numbers are the operator's now, not the fit's
        if scale is not None:
            self._draft.scale_text = scale
        if translate_x is not None:
            self._draft.tx_text = translate_x
        if translate_y is not None:
            self._draft.ty_text = translate_y
        if mirror is not None:
            self._draft.mirror = bool(mirror)
        self._render()

    def reset_draft(self) -> None:
        """Back to the identity transform; anchors, bounds and the applied alignment are untouched."""

        self._draft.reset()
        self._proposal = None
        self._fit = None
        self._render()

    def draft_intent(self) -> AlignmentIntent:
        """The draft as an intent (raises ``ValueError`` with the reason for an unusable entry)."""

        intent = AlignmentIntent(
            scale=_number(self._draft.scale_text, "Scale"),
            translate_x=_number(self._draft.tx_text, "Horizontal shift"),
            translate_y=_number(self._draft.ty_text, "Vertical shift"),
            mirror=self._draft.mirror,
        )
        if (
            self._fit is not None
        ):  # accepted from a suggestion and not edited since: keep its provenance
            return replace(intent, origin=ORIGIN_ANCHOR_FIT, anchors=self._fit[0], fit=self._fit[1])
        return intent

    # ------------------------------------------------------------------ workspace lifecycle

    def open_workspace(self) -> None:
        self.workspace_open = True
        if self._applied is not None and self._applied.intent is not None:
            self._adopt(self._applied.intent)
        if self._loaded is None and not self._loading:
            self.reload()
        self._notify()

    def close_workspace(self) -> None:
        self.workspace_open = False
        self._notify()

    def _adopt(self, intent: AlignmentIntent) -> None:
        self._draft.scale_text = f"{intent.scale:g}"
        self._draft.tx_text = f"{intent.translate_x:g}"
        self._draft.ty_text = f"{intent.translate_y:g}"
        self._draft.mirror = intent.mirror
        self.anchors = list(intent.anchors)
        self._fit = (
            (intent.anchors, intent.fit or {}) if intent.origin == ORIGIN_ANCHOR_FIT else None
        )

    def _form(self) -> dict[str, Any]:
        inputs = self._inputs
        return {
            "workflow_id": inputs.workflow_id,
            "workflow_version": inputs.workflow_version,
            "frame_count": inputs.frame_count,
            "pose_video_path": inputs.clip_path.strip(),
            "source_image_path": inputs.source_path.strip(),
        }

    def _request(self, intent: AlignmentIntent) -> dict[str, Any]:
        inputs = self._inputs
        start, end = inputs.start_text.strip(), inputs.end_text.strip()
        return {
            "intent": intent,
            "start": float(start) if start else 0.0,
            "end": float(end) if end else None,
            "unit": "seconds",
            "fps_conversion": "workflow_rate" if inputs.convert else "none",
        }

    def reload(self) -> None:
        """Decode the sampled frames for the current inputs (no generation, no runtime, nothing published)."""

        inputs = self._inputs
        if not inputs.available:
            self._load_message = inputs.unavailable_reason or "Alignment is not available."
            self._notify()
            return
        if not self._ports.media_allowed():
            self._load_message = (
                "The source image or driving video is hidden by the current content filter (or Show media "
                "is off), so nothing is opened or previewed."
            )
            self._notify()
            return
        if not inputs.clip_path.strip() or not inputs.source_path.strip() or not inputs.frame_count:
            self._load_message = "Choose a source image, a driving video and a length first."
            self._notify()
            return
        try:
            form, request = self._form(), self._request(IDENTITY)
        except ValueError:
            self._load_message = "Start and End must be numbers of seconds."
            self._notify()
            return
        frames = sample_indices(int(inputs.frame_count))
        wanted = tuple(sorted({*frames, *self._extra_frames}))[: MAX_SAMPLE_FRAMES + 3]
        key = inputs.key()
        self._loading, self._load_message = True, "Decoding the driving frames..."

        def work(cancel: threading.Event) -> Any:
            return self._ports.load(form, request, wanted, cancel)

        def finish(outcome: WorkOutcome) -> None:
            self._loading = False
            value = outcome.value
            if outcome.error or value is None or getattr(value, "status", "") != "prepared":
                self._load_message = outcome.error or str(
                    getattr(value, "message", "") or "The frames could not be read."
                )
                self._loaded, self._loaded_key = None, None
                return
            if key != self._inputs.key():  # the form moved on while this decoded
                self._load_message = "The inputs changed while decoding; press Reload."
                return
            self._loaded, self._loaded_key, self._load_message = value, key, ""
            frames_loaded = sorted(value.frames)
            if self.selected_frame not in frames_loaded:
                self.selected_frame = frames_loaded[0] if frames_loaded else None
            self._render()

        self._run("load", work, finish)

    def add_inspection_frame(self, output_index: int) -> None:
        """Also decode one operator-chosen output frame (the extra frames are bounded)."""

        total = self._inputs.frame_count or 0
        if not 0 <= int(output_index) < total:
            self._load_message = f"Frame {output_index} is outside 0-{max(0, total - 1)}."
            self._notify()
            return
        self._extra_frames.add(int(output_index))
        self.selected_frame = int(output_index)
        self.reload()

    def select_frame(self, output_index: int) -> None:
        if self._loaded is not None and output_index in self._loaded.frames:
            self.selected_frame = output_index
            self._notify()

    def step_frame(self, delta: int) -> None:
        if self._loaded is None or not self._loaded.frames:
            return
        ordered = sorted(self._loaded.frames)
        current = ordered.index(self.selected_frame) if self.selected_frame in ordered else 0
        self.select_frame(ordered[(current + delta) % len(ordered)])

    # ------------------------------------------------------------------ rendering (worker)

    def _render(self) -> None:
        """Resolve the draft and re-render the decoded frames under it; nothing is decoded again."""

        self._param_error = ""
        try:
            intent = self.draft_intent()
            if self._loaded is None:
                self._resolved = None
                self._notify()
                return
            resolved = resolve_alignment(
                intent, driver=self._loaded.driver, target=self._loaded.target
            )
        except (ValueError, AlignmentError) as exc:
            self._param_error = str(exc)
            self._resolved = None
            self._notify()
            return
        loaded = self._loaded
        self._rendering = True

        def work(cancel: threading.Event) -> Any:
            if cancel.is_set():
                return None
            return self._ports.render(loaded, intent)

        def finish(outcome: WorkOutcome) -> None:
            self._rendering = False
            value = outcome.value
            if outcome.error or value is None or getattr(value, "status", "") != "prepared":
                self._param_error = outcome.error or str(
                    getattr(value, "message", "") or "The preview failed."
                )
                return
            self._preview, self._resolved = value, value.resolved

        self._resolved = resolved
        self._run("render", work, finish)
        self._notify()  # the numbers and any disclosure show at once; the frames follow when rendered

    # ------------------------------------------------------------------ anchors and suggestion

    def begin_anchor(self, kind: str) -> None:
        self._pending_kind, self._pending_source, self._pending_driver = kind, None, None
        self._notify()

    def place_source_point(self, x: float, y: float) -> None:
        """A click on the source image, in target-frame pixels."""

        if self._pending_kind:
            self._pending_source = (float(x), float(y))
            self._complete_pending()

    def place_driver_point(self, x: float, y: float) -> None:
        """A click on the *original* driving frame as shown in the target frame (baseline placement)."""

        if self._pending_kind and self._loaded is not None and self._loaded.baseline is not None:
            self._pending_driver = self._loaded.baseline.to_driver((float(x), float(y)))
            self._complete_pending()

    def _complete_pending(self) -> None:
        if self._pending_source is not None and self._pending_driver is not None:
            self.anchors.append(
                AnchorPair(self._pending_kind, self._pending_source, self._pending_driver)
            )
            self._pending_kind, self._pending_source, self._pending_driver = "", None, None
            self._proposal = None
        self._notify()

    def remove_anchor(self, index: int) -> None:
        if 0 <= index < len(self.anchors):
            del self.anchors[index]
            self._proposal = None
            self._notify()

    def clear_anchors(self) -> None:
        self.anchors.clear()
        self._pending_kind, self._pending_source, self._pending_driver = "", None, None
        self._proposal = None
        self._notify()

    def suggest(self) -> FitResult | None:
        """Fit scale and shift to the marked anchors.  The result is a *proposal*; the draft and the applied
        alignment are unchanged until ``accept_suggestion``."""

        if self._loaded is None:
            self._notify()
            return None
        self._proposal = fit_anchors(
            self.anchors,
            driver=self._loaded.driver,
            target=self._loaded.target,
            mirror=self._draft.mirror,
        )
        self._notify()
        return self._proposal

    def accept_suggestion(self) -> None:
        proposal = self._proposal
        if proposal is None or proposal.intent is None:
            return
        intent = proposal.intent
        self._draft.scale_text = f"{intent.scale:g}"
        self._draft.tx_text = f"{intent.translate_x:g}"
        self._draft.ty_text = f"{intent.translate_y:g}"
        self._draft.mirror = intent.mirror
        self._fit = (tuple(self.anchors), intent.fit or {})
        self._proposal = None
        self._render()

    def discard_suggestion(self) -> None:
        self._proposal = None
        self._notify()

    # ------------------------------------------------------------------ bounds and observations

    def set_envelope_bounds(self, output_frame: int, rect: Rect | None) -> None:
        """Operator-entered subject bounds (driver display pixels) at one output frame, or removal."""

        if rect is None:
            self._envelope.pop(int(output_frame), None)
        else:
            self._envelope[int(output_frame)] = rect.validate("subject bounds")
        self._notify()

    def set_observations(self, which: str, observations: SubjectObservations) -> None:
        if which == "source":
            self.source_obs = observations
        else:
            self.driver_obs = observations
        self._notify()

    # ------------------------------------------------------------------ apply / prepare / discard

    def apply(self) -> bool:
        """Accept the draft as the alignment for the *current* inputs.  Prepares nothing yet."""

        if not self._inputs.available or self._resolved is None or self._param_error:
            self._notice = self._param_error or "Open the workspace and wait for the preview first."
            self._notify()
            return False
        try:
            normal = self.draft_intent().normalized(self._resolved.target)
        except (ValueError, AlignmentError) as exc:
            self._notice = str(exc)
            self._notify()
            return False
        self._next("prepare")  # a preparation of the previous alignment is superseded
        self._applied = _Applied(intent=normal, key=self._inputs.key())
        self._notice = ""
        self._notify()
        return True

    def prepare(self) -> bool:
        """Prepare the exact aligned driving frames for the applied alignment (worker)."""

        applied = self._applied
        if applied is None or applied.state == "preparing" or not self._inputs.available:
            return False
        if self._stale_names():
            applied.state, applied.message = "failed", "Out of date: apply the alignment again."
            self._notify()
            return False
        try:
            form, request = self._form(), self._request(applied.intent)
        except ValueError:
            applied.state, applied.message = "failed", "Start and End must be numbers of seconds."
            self._notify()
            return False
        applied.state, applied.message, applied.record = "preparing", "", None
        key = applied.key

        def work(cancel: threading.Event) -> Any:
            return self._ports.prepare(form, request, cancel)

        def finish(outcome: WorkOutcome) -> None:
            if self._applied is not applied:
                return  # discarded or replaced while it ran
            value = outcome.value
            if key != self._inputs.key():
                applied.state, applied.message = (
                    "failed",
                    "Out of date: the inputs changed while preparing.",
                )
                return
            if outcome.error or value is None:
                applied.state, applied.message = "failed", outcome.error or "Preparation failed."
            elif getattr(value, "status", "") == "prepared" and getattr(value, "record", None):
                applied.state, applied.record = "ready", value.record
                applied.message = str(getattr(value, "message", "") or "Prepared.")
                applied.explanation = tuple(getattr(value, "explanation", ()) or ())
                applied.preview = getattr(value, "preview", None)
            elif getattr(value, "status", "") == "cancelled":
                applied.state, applied.message = "failed", "Preparation was cancelled."
            else:
                applied.state = "failed"
                applied.message = str(getattr(value, "message", "") or "Preparation failed.")

        self._run("prepare", work, finish)
        self._notify()
        return True

    def cancel(self) -> None:
        self._cancel_kind("prepare")
        applied = self._applied
        if applied is not None and applied.state == "preparing":
            applied.message = "Cancelling..."
        self._notify()

    def discard(self) -> None:
        """Return to ordinary preparation: the applied alignment (and any running preparation) is dropped."""

        self._next("prepare")  # supersedes and cancels a running worker; its result is dropped
        self._applied = None
        self._notice = ""
        self._notify()

    def close(self) -> None:
        self._closed = True
        for event in self._cancels.values():
            event.set()
        self.workspace_open = False

    # ------------------------------------------------------------------ the form

    @property
    def status(self) -> str:
        applied = self._applied
        dirty = self.workspace_open and self._draft_differs()
        if applied is None:
            return STATUS_EDITING if dirty else STATUS_NOT_APPLIED
        if applied.state == "preparing":
            return STATUS_PREPARING
        if self._stale_names():
            return STATUS_STALE
        if applied.state == "failed" or not self._inputs.available:
            return STATUS_FAILED
        if dirty:
            return STATUS_EDITING
        return STATUS_VERIFIED if applied.state == "ready" else STATUS_PREPARATION_REQUIRED

    def _draft_differs(self) -> bool:
        applied = self._applied
        try:
            current = self.draft_intent()
        except ValueError:
            return True
        if applied is None:
            return not current.is_identity
        base = applied.intent
        return (current.scale, current.translate_x, current.translate_y, current.mirror) != (
            base.scale,
            base.translate_x,
            base.translate_y,
            base.mirror,
        )

    def submission_fields(self) -> dict[str, Any]:
        """The aligned record, a blocker, or nothing (the unaligned preparation applies)."""

        applied = self._applied
        if applied is None:
            return {}
        names = self._stale_names()
        if applied.state == "preparing":
            return {
                BLOCKED_FIELD: "Motion alignment is still preparing. Wait for it to finish, cancel it, "
                "or discard the alignment."
            }
        if names:
            return {
                BLOCKED_FIELD: "The motion alignment is out of date (changed: "
                + ", ".join(names)
                + "). Align and prepare it again, or discard the alignment."
            }
        if not self._inputs.available:
            return {
                BLOCKED_FIELD: "Motion alignment is not available for this workflow ("
                + (self._inputs.unavailable_reason or "unsupported")
                + "). Discard the alignment or choose another workflow."
            }
        if applied.state == "failed":
            return {
                BLOCKED_FIELD: f"Motion alignment failed: {applied.message} Prepare it again, or "
                "discard the alignment."
            }
        if applied.state == "required" or applied.record is None:
            return {
                BLOCKED_FIELD: "A motion alignment was applied but its driving frames are not prepared "
                "yet. Prepare them, or discard the alignment."
            }
        return {PREPARED_FIELD: applied.record}

    # ------------------------------------------------------------------ projection

    def _media(self) -> MediaFacts | None:
        loaded = self._loaded
        if loaded is None or loaded.plan is None:
            return None
        facts = loaded.facts
        return MediaFacts(
            target=loaded.target,
            driver=loaded.driver,
            driver_rate=getattr(facts, "reported_fps", None),
            driver_frame_count=getattr(facts, "frame_count", None),
            window_start=loaded.plan.settings.start_frame,
            window_end=loaded.plan.settings.end_frame,
            output_frames=loaded.plan.output_frames,
            output_fps=loaded.plan.output_fps,
            held_frames=loaded.plan.held_frames,
        )

    def compatibility(self) -> CompatibilityAssessment | None:
        media = self._media()
        if media is None:
            return None
        return assess_compatibility(
            source=self.source_obs,
            driver=self.driver_obs,
            media=media,
            alignment=self._resolved,
            readiness_notes=tuple(getattr(self._loaded, "readiness_notes", ()) or ()),
        )

    def _markers(
        self, resolved: ResolvedAlignment | None
    ) -> tuple[tuple[Marker, ...], tuple[Marker, ...]]:
        source = tuple(
            Marker(a.kind, a.source_xy[0], a.source_xy[1], str(i + 1))
            for i, a in enumerate(self.anchors)
        )
        base = self._loaded.baseline if self._loaded is not None else None
        mapper = resolved if self.show == SHOW_ALIGNED and resolved is not None else base
        driver: tuple[Marker, ...] = ()
        if mapper is not None:
            points = [mapper.to_target(a.driver_xy) for a in self.anchors]
            driver = tuple(
                Marker(a.kind, x, y, str(i + 1))
                for i, (a, (x, y)) in enumerate(zip(self.anchors, points, strict=True))
            )
        return source, driver

    def view(self) -> AlignView:
        inputs, status = self._inputs, self.status
        applied, loaded, resolved = self._applied, self._loaded, self._resolved
        preview = self._preview
        frames = sorted(loaded.frames) if loaded is not None else []
        selected = (
            self.selected_frame
            if self.selected_frame in frames
            else (frames[0] if frames else None)
        )
        baseline_png = aligned_png = None
        if preview is not None:
            for item in preview.frames:
                if item.output_index == selected:
                    baseline_png, aligned_png = item.baseline_png, item.aligned_png
        geometry: list[str] = []
        if loaded is not None:
            geometry.append(
                f"Target frame {loaded.target.width}x{loaded.target.height} (the prepared source image); "
                f"driving frame {loaded.driver.width}x{loaded.driver.height}."
            )
        if resolved is not None:
            intent = resolved.intent
            geometry.append(
                f"Scale {intent.scale:g}, shift ({intent.translate_x:+g}, {intent.translate_y:+g}) px"
                + (", mirrored" if intent.mirror else "")
                + f". Driving frame {resolved.driver_visible_fraction:.0%} in view; "
                f"{resolved.fill_fraction:.0%} of the target is neutral gray fill."
            )
            clipped = [name for name, hit in resolved.clipped.items() if hit]
            if clipped:
                geometry.append(
                    "Driving frame is cropped at the "
                    + ", ".join(clipped)
                    + " of the target frame."
                )
        envelope: list[str] = []
        if resolved is not None and loaded is not None and loaded.plan is not None:
            report = inspect_envelope(
                resolved, self._envelope, total_frames=loaded.plan.output_frames
            )
            envelope = [report.statement]
            envelope += [
                f"Frame {item.output_frame}: "
                + (
                    "inside the frame."
                    if item.fully_visible
                    else "clipped at the " + ", ".join(item.clipped_sides) + "."
                )
                for item in report.frames
            ]
        proposal = self._proposal
        proposal_lines: list[str] = []
        if proposal is not None:
            if proposal.intent is None:
                proposal_lines = [issue.message for issue in proposal.issues]
            else:
                proposal_lines = [
                    f"Suggested: scale {proposal.intent.scale:g}, shift ({proposal.intent.translate_x:+g}, "
                    f"{proposal.intent.translate_y:+g}) px. Residual error {proposal.rms_error:.1f} px RMS, "
                    f"{proposal.max_error:.1f} px worst, from {proposal.anchors_used} marked pair(s). "
                    "Nothing changes until you accept it.",
                    *(issue.message for issue in proposal.issues),
                ]
        identity: list[str] = []
        if (
            applied is not None
            and applied.record is not None
            and status in (STATUS_VERIFIED, STATUS_STALE)
        ):
            record = applied.record
            original, derived = record["original"], record["derived"]
            identity = [
                f"Original driving video: sha256 {_short(original['sha256'])} (unchanged, reusable).",
                f"Aligned clip: {derived['width']}x{derived['height']}, {derived['frames']} frames at "
                f"{derived['frame_rate']} fps, sha256 {_short(derived['sha256'])} (lossless RGB, "
                "content-addressed; not pixel-identical to the original).",
                f"Transform {_short(record['alignment']['transform_sha256'])} for source image "
                f"{_short(record['alignment']['source_image']['original_sha256'])}.",
            ]
        if status == STATUS_PREPARING:
            text = (
                applied.message
                if applied is not None and applied.message
                else "Preparing the aligned driving frames..."
            )
        elif status == STATUS_VERIFIED:
            text = "The aligned clip is verified and will be used for this job."
        elif status == STATUS_STALE:
            text = (
                "Out of date (changed: "
                + ", ".join(self._stale_names())
                + "). Apply and prepare again, or discard."
            )
        elif status == STATUS_FAILED:
            text = (applied.message if applied is not None else "") or "Alignment is unavailable."
            if not inputs.available:
                text = inputs.unavailable_reason or text
        elif status == STATUS_PREPARATION_REQUIRED:
            text = "Applied; the exact aligned driving frames still have to be prepared."
        elif status == STATUS_EDITING:
            text = "Editing; the unapplied changes do not affect the job."
        else:
            text = self._notice or "Not applied: the driving video is used as it is."
        source_markers, driver_markers = self._markers(resolved)
        can_edit = inputs.available and loaded is not None
        return AlignView(
            status=status,
            status_label=STATUS_LABELS[status],
            status_text=text,
            available=inputs.available,
            unavailable_reason=inputs.unavailable_reason,
            loading=self._loading or self._rendering,
            load_message=self._load_message,
            can_apply=can_edit
            and resolved is not None
            and not self._param_error
            and status != STATUS_PREPARING,
            can_prepare=applied is not None and applied.state != "preparing" and inputs.available,
            can_cancel=status == STATUS_PREPARING,
            can_discard=applied is not None,
            can_suggest=can_edit and bool(self.anchors),
            scale_text=self._draft.scale_text,
            translate_x_text=self._draft.tx_text,
            translate_y_text=self._draft.ty_text,
            mirror=self._draft.mirror,
            param_error=self._param_error,
            geometry_lines=tuple(geometry),
            explanation_lines=tuple(preview.explanation) if preview is not None else (),
            view_mode=self.view_mode,
            show=self.show,
            opacity=self.opacity,
            frame_indices=tuple(frames),
            selected_frame=selected,
            source_png=(getattr(loaded, "source_png", None) or None)
            if loaded is not None
            else None,
            baseline_png=baseline_png,
            aligned_png=aligned_png,
            target_size=(loaded.target.width, loaded.target.height) if loaded is not None else None,
            driver_size=(loaded.driver.width, loaded.driver.height) if loaded is not None else None,
            source_markers=source_markers,
            driver_markers=driver_markers,
            anchor_lines=tuple(
                f"{i + 1}. {a.kind.replace('_', ' ')}: source ({a.source_xy[0]:.0f}, {a.source_xy[1]:.0f}) "
                f"<-> driving ({a.driver_xy[0]:.0f}, {a.driver_xy[1]:.0f})"
                for i, a in enumerate(self.anchors)
            ),
            pending_prompt=(
                (
                    f"Marking {self._pending_kind.replace('_', ' ')}: click the "
                    + ("driving frame" if self._pending_source is not None else "source image")
                    + " next."
                )
                if self._pending_kind
                and (self._pending_source is None or self._pending_driver is None)
                else ""
            ),
            proposal_lines=tuple(proposal_lines),
            has_proposal=proposal is not None and proposal.intent is not None,
            envelope_lines=tuple(envelope),
            compatibility=self.compatibility(),
            identity_lines=tuple(identity),
            placement=(
                (
                    resolved.placement.left,
                    resolved.placement.top,
                    resolved.placement.right,
                    resolved.placement.bottom,
                )
                if resolved is not None
                else None
            ),
            baseline_placement=(
                (lambda r: (r.left, r.top, r.right, r.bottom))(loaded.baseline.placement)
                if loaded is not None and loaded.baseline is not None
                else None
            ),
            mirror_disclosure=(
                "Mirroring reverses the motion's direction and swaps left and right. It is never applied "
                "automatically and the motion prompt is not changed."
                if self._draft.mirror
                else ""
            ),
        )


__all__ = [
    "BLOCKED_FIELD",
    "MAX_SAMPLE_FRAMES",
    "PREPARED_FIELD",
    "SHOW_ALIGNED",
    "SHOW_ORIGINAL",
    "STATUS_EDITING",
    "STATUS_FAILED",
    "STATUS_LABELS",
    "STATUS_NOT_APPLIED",
    "STATUS_PREPARATION_REQUIRED",
    "STATUS_PREPARING",
    "STATUS_STALE",
    "STATUS_VERIFIED",
    "VIEW_OVERLAY",
    "VIEW_SIDE_BY_SIDE",
    "AlignInputs",
    "AlignPorts",
    "AlignView",
    "Marker",
    "MotionAlignmentSession",
    "sample_indices",
]
