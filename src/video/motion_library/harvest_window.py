"""Exact action-window arithmetic for Harvest Motion (PR-VID-MOTION-400).  Pure: no I/O, no Tk, no process.

Conventions, stated once because every control uses them:

* Frames are numbered from 0 in decode order.
* A window is ``[start_frame, end_frame)``: it **includes** ``start_frame`` and **excludes** ``end_frame``, so it holds
  ``end_frame - start_frame`` frames.  "Set End after current frame" therefore sets ``end_frame = current + 1``.
* A time ``t`` seconds is the frame *nearest* ``t`` on a constant-rate timeline (``floor(t * rate + 1/2)``, computed
  with exact fractions from the rate FFprobe reported, so 30000/1001 is exact).  A frame ``n`` starts at ``n / rate``.
* Native cadence keeps every window frame at the clip's own rate.  Normalized cadence is the explicit conversion to
  24 fps that PR-VID-MOTION-210 already defines (``workflow_rate``): output frame ``j`` takes the source frame nearest
  ``j / 24`` seconds after the window start (a tie takes the later one).  Faster clips omit frames, slower ones repeat.

Nothing here knows a workflow, a generation length or a model.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from src.video.motion_library.models import CADENCE_NATIVE, CADENCE_NORMALIZED_24
from src.video.motion_source_plan import MAX_SOURCE_SPAN_FRAMES, frame_from_seconds

NORMALIZED_FPS = 24
#: A native-cadence window is one contiguous run, so its FFmpeg expression is short whatever its length.
MAX_NATIVE_OUTPUT_FRAMES = 2400
#: A normalized window can need one ``between()`` term per kept frame, and FFmpeg's expression parser stops at about
#: 100 nested terms (measured with FFmpeg 9.0.1); this stays below that.  Native cadence has no such limit and is the
#: choice for a longer action.
MAX_NORMALIZED_OUTPUT_FRAMES = 90
MAX_WINDOW_SOURCE_FRAMES = MAX_SOURCE_SPAN_FRAMES

UNIT_FRAMES = "frames"
UNIT_SECONDS = "seconds"


class WindowError(ValueError):
    """The requested window cannot be placed or prepared; the message is operator-facing."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def parse_rate(text: str) -> Fraction | None:
    """An exact positive rate from FFprobe text (``"30000/1001"`` or ``"24"``), or None."""

    try:
        rate = Fraction(str(text or "").strip())
    except (ValueError, ZeroDivisionError):
        return None
    return rate if rate > 0 else None


def rate_text(rate: Fraction) -> str:
    return f"{rate.numerator}/{rate.denominator}"


def rate_label(rate: Fraction | None) -> str:
    """``"24 fps"`` or ``"29.97 fps (30000/1001)"`` for a label."""

    if rate is None:
        return "frame rate not reported"
    if rate.denominator == 1:
        return f"{rate.numerator} fps"
    return f"{float(rate):.3f} fps ({rate_text(rate)})"


def frame_start_seconds(frame: int, rate: Fraction) -> float:
    return float(Fraction(frame) / rate)


def timecode(frame: int, rate: Fraction | None) -> str:
    """``m:ss.mmm`` for the start of ``frame``; empty when the rate is unknown."""

    if rate is None:
        return ""
    seconds = Fraction(frame) / rate
    minutes, rest = divmod(float(seconds), 60.0)
    return f"{int(minutes)}:{rest:06.3f}"


@dataclass(frozen=True, slots=True)
class ResolvedWindow:
    start_frame: int
    end_frame: int  # exclusive
    requested_start: float
    requested_end: float | None
    unit: str

    @property
    def frames(self) -> int:
        return self.end_frame - self.start_frame


def _to_frame(value: float, unit: str, rate: Fraction | None, label: str) -> int:
    if value is None or isinstance(value, bool) or value != value or value in (float("inf"),):
        raise WindowError("window_invalid", f"The {label} is not a number.")
    if value < 0:
        raise WindowError("window_invalid", f"The {label} cannot be before the start of the video.")
    if unit == UNIT_FRAMES:
        if float(value) != int(value):
            raise WindowError("window_invalid", f"The {label} frame must be a whole number.")
        return int(value)
    if unit != UNIT_SECONDS:
        raise WindowError("window_invalid", f"Unknown unit {unit!r}.")
    if rate is None:
        raise WindowError(
            "frame_rate_unknown",
            "The video reports no frame rate, so a time cannot be placed. Enter frame numbers instead.",
        )
    return frame_from_seconds(value, rate)


def resolve_window(
    *,
    start: float,
    end: float | None,
    unit: str,
    rate: Fraction | None,
    frame_count: int | None,
    count_is_reliable: bool,
) -> ResolvedWindow:
    """Place a requested window on the frame timeline.

    ``end=None`` means "to the end of the video" and needs a known frame count.  A window that runs past a *reported*
    frame count is refused (a harvested asset never receives artificial held frames); with only an estimated count the
    refusal is deferred to the real decode."""

    first = _to_frame(start, unit, rate, "start")
    if end is None:
        if frame_count is None:
            raise WindowError(
                "frame_count_unknown",
                "The video does not report how many frames it has, so 'to the end' cannot be placed. "
                "Enter an end.",
            )
        last = frame_count
    else:
        last = _to_frame(end, unit, rate, "end")
    if last <= first:
        raise WindowError(
            "window_empty",
            f"The window is empty: it starts at frame {first} and ends before frame {first + 1} "
            f"(end frame {last}, exclusive). Choose an end after the start.",
        )
    if last - first > MAX_WINDOW_SOURCE_FRAMES:
        raise WindowError(
            "window_too_long",
            f"The window spans {last - first} frames; harvesting is limited to "
            f"{MAX_WINDOW_SOURCE_FRAMES} source frames at once.",
        )
    if frame_count is not None and count_is_reliable:
        if first >= frame_count:
            raise WindowError(
                "window_outside",
                f"The video has {frame_count} frames (0-{frame_count - 1}); the window starts at frame {first}.",
            )
        if last > frame_count:
            raise WindowError(
                "window_outside",
                f"The video has {frame_count} frames; the window ends at frame {last} (exclusive). "
                "Shorten the window, or reset it to the full source.",
            )
    return ResolvedWindow(first, last, float(start), None if end is None else float(end), unit)


def end_after_frame(current_frame: int) -> int:
    """The exclusive end that makes ``current_frame`` the **last frame included** in the window."""

    return int(current_frame) + 1


def normalized_offsets(
    window_frames: int, rate: Fraction, *, target: int = NORMALIZED_FPS
) -> list[int]:
    """Source-frame offsets (from the window start) of every normalized output frame that fits the window.

    Output frame ``j`` takes ``floor(j * rate / target + 1/2)``; frames are produced while that stays inside the
    window, so no output frame is a hold of a frame the window does not contain."""

    numerator, denominator = rate.numerator, rate.denominator
    offsets: list[int] = []
    j = 0
    while True:
        offset = (2 * j * numerator + target * denominator) // (2 * target * denominator)
        if offset >= window_frames:
            break
        offsets.append(offset)
        j += 1
        if j > MAX_NORMALIZED_OUTPUT_FRAMES + 1:
            break
    return offsets


@dataclass(frozen=True, slots=True)
class CadencePlan:
    """What a cadence choice does to a window, in numbers an operator can read before anything is encoded."""

    cadence: str
    window_frames: int
    output_frames: int
    output_rate: Fraction
    source_rate: Fraction | None
    omitted: int
    repeated: int
    duration_seconds: float
    lines: tuple[str, ...]

    @property
    def speed_vs_original(self) -> float:
        """Always 1.0: neither cadence changes how fast the motion plays (native keeps the rate; normalized
        resamples to the new rate by time)."""

        return 1.0


def plan_cadence(window_frames: int, rate: Fraction | None, cadence: str) -> CadencePlan:
    """The frame accounting of harvesting ``window_frames`` frames at ``cadence`` (raises ``WindowError``)."""

    if window_frames < 1:
        raise WindowError("window_empty", "The window has no frames.")
    if rate is None:
        raise WindowError(
            "frame_rate_unknown",
            "The video reports no frame rate, so its timing cannot be preserved or converted exactly.",
        )
    if cadence == CADENCE_NATIVE:
        if window_frames > MAX_NATIVE_OUTPUT_FRAMES:
            raise WindowError(
                "window_too_long",
                f"A native-cadence harvest is limited to {MAX_NATIVE_OUTPUT_FRAMES} frames; the window has "
                f"{window_frames}.",
            )
        duration = float(Fraction(window_frames) / rate)
        return CadencePlan(
            cadence=cadence,
            window_frames=window_frames,
            output_frames=window_frames,
            output_rate=rate,
            source_rate=rate,
            omitted=0,
            repeated=0,
            duration_seconds=duration,
            lines=(
                f"Native cadence: all {window_frames} frames are kept at {rate_label(rate)} "
                f"({duration:.3f} s). Nothing is omitted, repeated or held.",
            ),
        )
    if cadence != CADENCE_NORMALIZED_24:
        raise WindowError("cadence_unknown", f"Unknown cadence {cadence!r}.")
    offsets = normalized_offsets(window_frames, rate)
    if len(offsets) > MAX_NORMALIZED_OUTPUT_FRAMES:
        raise WindowError(
            "window_too_long",
            f"A 24 fps conversion is limited to {MAX_NORMALIZED_OUTPUT_FRAMES} output frames "
            f"({MAX_NORMALIZED_OUTPUT_FRAMES / NORMALIZED_FPS:.0f} s). Shorten the window or keep the native cadence.",
        )
    if not offsets:
        raise WindowError("window_empty", "The window is too short to hold one 24 fps frame.")
    used = set(offsets)
    omitted = window_frames - len(used)  # every window frame the derivative does not contain
    repeated = len(offsets) - len(used)
    duration = len(offsets) / NORMALIZED_FPS
    return CadencePlan(
        cadence=cadence,
        window_frames=window_frames,
        output_frames=len(offsets),
        output_rate=Fraction(NORMALIZED_FPS),
        source_rate=rate,
        omitted=omitted,
        repeated=repeated,
        duration_seconds=duration,
        lines=(
            f"Normalized to {NORMALIZED_FPS} fps: {rate_label(rate)} becomes {len(offsets)} frames "
            f"({duration:.3f} s) by taking the nearest source frame to each output time.",
            f"Omitted source frames: {omitted}. Repeated source frames: {repeated}. "
            "Motion speed is unchanged.",
        ),
    )


__all__ = [
    "MAX_NATIVE_OUTPUT_FRAMES",
    "MAX_NORMALIZED_OUTPUT_FRAMES",
    "MAX_WINDOW_SOURCE_FRAMES",
    "NORMALIZED_FPS",
    "UNIT_FRAMES",
    "UNIT_SECONDS",
    "CadencePlan",
    "ResolvedWindow",
    "WindowError",
    "end_after_frame",
    "frame_start_seconds",
    "normalized_offsets",
    "parse_rate",
    "plan_cadence",
    "rate_label",
    "rate_text",
    "resolve_window",
    "timecode",
]
