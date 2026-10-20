"""Which driving-video frames a workflow consumes, as a pure plan (PR-VID-MOTION-210).

A registered driving-video workflow reads its clip in decode order from the start, keeps the first
``length`` frames, resizes each one and holds the last frame when the clip is shorter (verified
against the pinned ComfyUI node in ``driving_frame_consumption``).  The plan
here decides, with exact integer arithmetic and no I/O, which *source* frame becomes each of those
``length`` consumed frames:

* ``none`` (the default): consumed frame ``j`` is source frame ``start + j``.  Nothing is resampled,
  so a clip at another rate plays at ``output_fps / source_fps`` of its original speed.
* ``workflow_rate``: an explicit conversion to the workflow's declared output rate.  Output frame
  ``j`` sits at ``j / output_fps`` seconds after the window start and takes the *nearest* source
  frame in time (a tie takes the later frame).  Faster clips omit frames, slower ones repeat them.

An optional exclusive ``end_frame`` bounds the window; when the window (or the clip) runs out, the
last available frame is held for the remaining output frames.  The plan also explains, in operator
words, which frames are omitted, repeated, held or never used.  It imports nothing from the GUI,
queue, controller or NJR layers and never reads a file.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from src.video.driving_frame_consumption import driving_frame_consumption
from src.video.driving_video_inspection import DrivingVideoFacts
from src.video.workflow_frame_count import frame_count_policy, parse_frame_count

SCHEMA = "stablenew.motion-source-preparation.v1"

FPS_CONVERSION_NONE = "none"
FPS_CONVERSION_WORKFLOW_RATE = "workflow_rate"
FPS_CONVERSIONS = (FPS_CONVERSION_NONE, FPS_CONVERSION_WORKFLOW_RATE)

#: Upper bounds that keep a plan, and the FFmpeg expressions built from it, small.
MAX_OUTPUT_FRAMES = 512
MAX_SOURCE_SPAN_FRAMES = 20_000


class MotionSourceUnavailable(ValueError):
    """The selected workflow cannot honestly offer motion-source preparation (reason in the message)."""


@dataclass(frozen=True, slots=True)
class MotionSourceContract:
    """What the selected, registered workflow consumes: identity, length, rate and verified rule."""

    workflow_id: str
    workflow_version: str
    output_frames: int
    output_fps: int
    runtime_revision: str
    consumption_rule: str

    def to_record(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "output_frames": self.output_frames,
            "output_fps": self.output_fps,
            "runtime_revision": self.runtime_revision,
            "consumption_rule": self.consumption_rule,
        }


def motion_source_contract(spec: Any, frame_count_value: Any) -> MotionSourceContract:
    """The consumption contract of ``spec`` for the operator's chosen length.

    Fails closed: a workflow without a driving video, whose frame timing was not verified against
    its pinned runtime, or without a declared length policy is not offered preparation.  An illegal
    length raises the workflow's own ``ValueError`` (never rounded)."""

    name = getattr(spec, "display_name", None) or getattr(spec, "workflow_id", "workflow")
    if "pose_video" not in tuple(getattr(spec, "declared_input_names", ()) or ()):
        raise MotionSourceUnavailable(
            f"'{name}' takes no driving video, so there is nothing to prepare."
        )
    consumption = driving_frame_consumption(spec)
    if not consumption.verified:
        raise MotionSourceUnavailable(
            f"{consumption.reason} Preparation is only offered where the frames a workflow consumes "
            "were verified against its pinned runtime."
        )
    policy = frame_count_policy(spec)
    if policy is None:
        raise MotionSourceUnavailable(f"'{name}' declares no frame-count policy.")
    count = parse_frame_count(spec, frame_count_value)
    if count > MAX_OUTPUT_FRAMES:
        raise MotionSourceUnavailable(f"A length of {count} frames exceeds the preparation limit.")
    return MotionSourceContract(
        workflow_id=str(spec.workflow_id),
        workflow_version=str(spec.workflow_version),
        output_frames=count,
        output_fps=policy["fps"],
        runtime_revision=consumption.runtime_revision,
        consumption_rule=consumption.rule,
    )


@dataclass(frozen=True, slots=True)
class MotionSourceSettings:
    """What the operator chose.  ``end_frame`` is exclusive; None means "to the end of the clip"."""

    start_frame: int = 0
    end_frame: int | None = None
    fps_conversion: str = FPS_CONVERSION_NONE

    def validate(self) -> None:
        if isinstance(self.start_frame, bool) or not isinstance(self.start_frame, int):
            raise ValueError("The start frame must be a whole number.")
        if self.start_frame < 0:
            raise ValueError("The start frame cannot be negative.")
        if self.end_frame is not None:
            if isinstance(self.end_frame, bool) or not isinstance(self.end_frame, int):
                raise ValueError("The end frame must be a whole number.")
            if self.end_frame <= self.start_frame:
                raise ValueError("The window must end after it starts.")
        if self.fps_conversion not in FPS_CONVERSIONS:
            raise ValueError(f"Unknown frame-rate conversion: {self.fps_conversion!r}.")

    def to_record(self) -> dict[str, Any]:
        return {
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "fps_conversion": self.fps_conversion,
        }


def source_rate(facts: DrivingVideoFacts) -> Fraction | None:
    """The clip's exact reported frame rate, or None when it reports none."""

    if facts.reported_fps is None:
        return None
    try:
        exact = Fraction(facts.fps_rational) if facts.fps_rational else None
    except (ValueError, ZeroDivisionError):
        exact = None
    if exact is not None and exact > 0:
        return exact
    return Fraction(facts.reported_fps).limit_denominator(1_001_000)


def frame_from_seconds(seconds: float, rate: Fraction) -> int:
    """The source frame nearest ``seconds`` on a constant-rate timeline (exact; a tie rounds up)."""

    exact = Fraction(str(seconds)) * rate
    return max(0, math.floor(exact + Fraction(1, 2)))


def _offsets(
    settings: MotionSourceSettings, contract: MotionSourceContract, rate: Fraction | None
) -> list[int]:
    """Source-frame offset (from the window start) that becomes each consumed frame, unclamped."""

    count = contract.output_frames
    if settings.fps_conversion == FPS_CONVERSION_NONE:
        return list(range(count))
    if rate is None:
        raise ValueError("Frame-rate conversion needs a clip that reports its frame rate.")
    numerator, denominator, fps = rate.numerator, rate.denominator, contract.output_fps
    # floor(j * source_fps / output_fps + 1/2): nearest source frame in time, tie to the later one.
    return [
        (2 * j * numerator + fps * denominator) // (2 * fps * denominator) for j in range(count)
    ]


def last_source_frame_needed(
    settings: MotionSourceSettings, contract: MotionSourceContract, rate: Fraction | None
) -> int:
    """The highest source frame index the window could need (before the clip's real length is known)."""

    settings.validate()
    last = settings.start_frame + _offsets(settings, contract, rate)[-1]
    if settings.end_frame is not None:
        last = min(last, settings.end_frame - 1)
    if last - settings.start_frame + 1 > MAX_SOURCE_SPAN_FRAMES:
        raise ValueError(
            f"This window spans more than {MAX_SOURCE_SPAN_FRAMES} source frames; choose a shorter one."
        )
    return last


@dataclass(frozen=True, slots=True)
class FramePlan:
    """One source frame per consumed frame, plus what that selection does to the clip."""

    settings: MotionSourceSettings
    output_fps: int
    source_rate: Fraction | None
    window_frames: (
        int  # source frames available from ``start_frame`` (the operator window and the clip)
    )
    source_indices: tuple[int, ...]
    held_frames: int  # trailing consumed frames that repeat the last available frame

    @property
    def start_frame(self) -> int:
        return self.settings.start_frame

    @property
    def output_frames(self) -> int:
        return len(self.source_indices)

    @property
    def window_end(self) -> int:
        """Exclusive end of the frames actually available to the plan."""

        return self.start_frame + self.window_frames

    @property
    def fresh_indices(self) -> tuple[int, ...]:
        """The source frames of the consumed frames that are not a hold."""

        return self.source_indices[: self.output_frames - self.held_frames]

    @property
    def used_sources(self) -> tuple[int, ...]:
        return tuple(sorted(set(self.source_indices)))

    @property
    def repeated(self) -> dict[int, int]:
        """Source frame -> extra copies, for frames used more than once outside the hold."""

        counts: dict[int, int] = {}
        for index in self.fresh_indices:
            counts[index] = counts.get(index, 0) + 1
        return {index: count - 1 for index, count in counts.items() if count > 1}

    @property
    def omitted(self) -> tuple[int, ...]:
        """Source frames inside the consumed span that no consumed frame takes."""

        fresh = set(self.fresh_indices)
        if not fresh:
            return ()
        return tuple(i for i in range(min(fresh), max(fresh) + 1) if i not in fresh)

    @property
    def unused_after(self) -> int:
        """Window frames after the last frame the plan takes."""

        return max(0, self.window_end - 1 - max(self.source_indices))

    @property
    def output_rate(self) -> Fraction:
        """The rate the prepared file carries: the clip's own for ``none``, else the workflow's."""

        if self.settings.fps_conversion == FPS_CONVERSION_NONE and self.source_rate is not None:
            return self.source_rate
        return Fraction(self.output_fps)

    @property
    def speed_vs_original(self) -> float | None:
        """Playback speed of the clip's motion in the output (1.0 when converted or same rate)."""

        if self.settings.fps_conversion != FPS_CONVERSION_NONE or self.source_rate is None:
            return 1.0
        return float(Fraction(self.output_fps) / self.source_rate)

    def to_record(self) -> dict[str, Any]:
        return {
            "source_indices": list(self.source_indices),
            "window_frames": self.window_frames,
            "held_frames": self.held_frames,
            "output_fps": self.output_fps,
            "output_rate": f"{self.output_rate.numerator}/{self.output_rate.denominator}",
        }


def build_frame_plan(
    settings: MotionSourceSettings,
    contract: MotionSourceContract,
    *,
    rate: Fraction | None,
    available_frames: int,
) -> FramePlan:
    """The plan for a clip that really has ``available_frames`` frames from ``start_frame`` on."""

    settings.validate()
    available = int(available_frames)
    if settings.end_frame is not None:
        available = min(available, settings.end_frame - settings.start_frame)
    if available < 1:
        raise ValueError("The clip has no frames inside the selected window.")
    offsets = _offsets(settings, contract, rate)
    held = sum(1 for offset in offsets if offset >= available)
    indices = tuple(settings.start_frame + min(offset, available - 1) for offset in offsets)
    return FramePlan(
        settings=settings,
        output_fps=contract.output_fps,
        source_rate=rate,
        window_frames=available,
        source_indices=indices,
        held_frames=held,
    )


# --- FFmpeg realisation ---------------------------------------------------------------------------


def _runs(indices: Sequence[int]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    for index in indices:
        if runs and index == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], index)
        else:
            runs.append((index, index))
    return runs


def ffmpeg_filter_chain(plan: FramePlan) -> str:
    """The ``-vf`` chain that makes exactly ``plan.source_indices`` the output, in order.

    The unique source frames are kept by ``select``; each is stamped with the output slot where it
    first appears (exact integer ticks) and ``fps`` repeats a frame until the next one's slot.  One
    extra clone of the last frame is stamped at slot ``output_frames`` so the frame before it is
    never FFmpeg's end-of-stream frame (whose handling differs between filters and builds); the
    caller keeps exactly ``output_frames`` frames with ``-frames:v``.  No resampling decision is
    left to FFmpeg."""

    unique = plan.used_sources
    slots = [plan.source_indices.index(index) for index in unique] + [plan.output_frames]
    rate = plan.output_rate
    selection = "+".join(f"between(n,{low},{high})" for low, high in _runs(unique))
    stamp = "+".join(
        f"gte(N,{i})*{(slots[i] - slots[i - 1]) * rate.denominator}" for i in range(1, len(slots))
    )
    return ",".join(
        [
            f"select='{selection}'",
            "tpad=stop=1:stop_mode=clone",
            f"settb=1/{rate.numerator}",
            f"setpts='{stamp}'",
            f"fps=fps={rate.numerator}/{rate.denominator}",
        ]
    )


# --- explanation ----------------------------------------------------------------------------------


def format_ranges(indices: Iterable[int], *, limit: int = 8) -> str:
    """ "3-7, 9, 12-14 (and 4 more ranges)" for sorted frame numbers."""

    parts = [str(low) if low == high else f"{low}-{high}" for low, high in _runs(sorted(indices))]
    if len(parts) > limit:
        return ", ".join(parts[:limit]) + f" (and {len(parts) - limit} more ranges)"
    return ", ".join(parts)


def _clock(frame: int, rate: Fraction | None) -> str:
    return "" if rate is None else f"{float(frame / rate):.2f} s"


def explain_plan(plan: FramePlan, contract: MotionSourceContract) -> tuple[str, ...]:
    """Operator-facing sentences for what the plan does.  Frame numbers start at 0."""

    rate = plan.source_rate
    first, last = plan.start_frame, max(plan.source_indices)
    span = f"source frames {first}-{last}" if last > first else f"source frame {first}"
    timing = (
        f" ({_clock(first, rate)} to {_clock(last + 1, rate)} at {float(rate):g} fps)"
        if rate is not None
        else ""
    )
    lines = [
        f"Window: {span}{timing}. Frame numbers start at 0"
        + (f"; {plan.start_frame} earlier frame(s) are skipped." if plan.start_frame else "."),
        f"Result: exactly {contract.output_frames} frames, a legal length for "
        f"{contract.workflow_id} {contract.workflow_version}, at {contract.output_fps} fps "
        f"({contract.output_frames / contract.output_fps:.2f} s).",
    ]
    if plan.settings.fps_conversion == FPS_CONVERSION_NONE:
        speed = plan.speed_vs_original
        lines.append(
            "Frame rate: not converted. Every consumed frame is the next source frame, so nothing is "
            "omitted or repeated"
            + (
                f"; the clip's {float(rate):g} fps motion plays at {speed:.2f}x its original speed "
                f"in the {contract.output_fps} fps output."
                if rate is not None and speed is not None and abs(speed - 1.0) > 1e-9
                else "."
            )
        )
    else:
        lines.append(
            f"Frame rate: converted from {float(rate or 0):g} fps to {contract.output_fps} fps by "
            "taking the nearest source frame to each output time (a tie takes the later frame)."
        )
    if plan.omitted:
        lines.append(
            f"Omitted: {len(plan.omitted)} source frame(s) inside the window are not used "
            f"({format_ranges(plan.omitted)})."
        )
    elif plan.settings.fps_conversion != FPS_CONVERSION_NONE:
        lines.append("Omitted: none.")
    repeated = plan.repeated
    if repeated:
        lines.append(
            f"Repeated: {sum(repeated.values())} extra copy(ies) of {len(repeated)} source frame(s) "
            f"({format_ranges(repeated)})."
        )
    elif plan.settings.fps_conversion != FPS_CONVERSION_NONE:
        lines.append("Repeated: none.")
    if plan.held_frames:
        held_from = plan.output_frames - plan.held_frames
        reason = (
            "the window ends"
            if plan.settings.end_frame is not None
            and plan.start_frame + plan.window_frames >= plan.settings.end_frame
            else "the clip ends"
        )
        lines.append(
            f"Held: {reason} at source frame {plan.window_end - 1}, so that frame is held for the "
            f"last {plan.held_frames} output frame(s) (output frames {held_from}-"
            f"{plan.output_frames - 1}, counting from 0). The workflow itself would also hold it."
        )
    if plan.unused_after:
        lines.append(
            f"Unused: {plan.unused_after} frame(s) after source frame {max(plan.source_indices)} "
            "are not needed."
        )
    return tuple(lines)


__all__ = [
    "FPS_CONVERSIONS",
    "FPS_CONVERSION_NONE",
    "FPS_CONVERSION_WORKFLOW_RATE",
    "MAX_OUTPUT_FRAMES",
    "MAX_SOURCE_SPAN_FRAMES",
    "SCHEMA",
    "FramePlan",
    "MotionSourceContract",
    "MotionSourceSettings",
    "MotionSourceUnavailable",
    "build_frame_plan",
    "explain_plan",
    "ffmpeg_filter_chain",
    "format_ranges",
    "frame_from_seconds",
    "last_source_frame_needed",
    "motion_source_contract",
    "source_rate",
]
