"""The task-first motion intent layer (V1, ``docs/work_packages/V1_motion_controls.md`` sections 5.3, 5.4, 5.9 and 7).

Pure functions shared by the desktop Video Workflow form and, later, the phone actions (RG-140), so a duration or a
tweak resolves identically on both:

- :func:`frames_for_duration` turns seconds into the nearest legal frame count of a workflow's declared length policy
  (ties go shorter, clamped to the engine's range).  It is a presentation function: the count it returns is shown to
  the operator and is exactly what the form submits, and admission (``parse_frame_count``) still validates it.
- :func:`compose_prompt` builds the submitted prompt from the scene prompt and the visible motion phrase (D3).
- :func:`motion_intent_record` / :func:`normalize_motion_intent_record` are the provenance-only record of the applied
  preset and the basis of each automatic choice (D5), stored under ``extra_metadata["video_workflow"]["motion_intent"]``.
  Admission and replay never read it.

Nothing here reads Tk, a file, a clock or a workflow id.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from src.video.workflow_frame_count import frame_count_advisory

if TYPE_CHECKING:
    from src.video.motion_presets import MotionPreset

#: The form key a submission carries the record under, and the ``extra_metadata["video_workflow"]`` key it is frozen as.
MOTION_INTENT_FIELD: Final = "motion_intent"
MOTION_INTENT_SCHEMA: Final = "stablenew.motion-intent.v1"
MOTION_PHRASE_MAX: Final = 300
_BASIS_TEXT_MAX: Final = 300
_BASIS_ENTRIES_MAX: Final = 16
_BASIS_KEY = re.compile(r"^[a-z][a-z0-9_:]{0,39}$")
_KNOWN_INTENTS: Final = frozenset({"animate", "follow_clip", "continue_clip", "sequence", "batch"})

#: The short list of durations a form offers (about 2, 3 and 5 s), plus the engine's longest (5.3).
DURATION_TARGETS: Final[tuple[float, ...]] = (2.0, 3.0, 5.0)
LONGEST_SUFFIX: Final = " (longest)"
_SECONDS = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(?:s|sec|secs|seconds)?\b")

CLAMP_MINIMUM: Final = "minimum"
CLAMP_MAXIMUM: Final = "maximum"
CLAMP_WINDOW: Final = "window"
NOTE_HELD_LAST_FRAME: Final = (
    "The driver is shorter than the engine's shortest length; its last frame is held."
)


@dataclass(frozen=True)
class LengthPolicy:
    """A workflow's legal lengths: ``minimum <= n <= maximum`` with ``(n - offset) % step == 0``."""

    minimum: int
    maximum: int
    step: int
    offset: int
    fps: int
    default: int
    advisory_above: int | None = None

    def legal(self) -> tuple[int, ...]:
        return tuple(
            count
            for count in range(self.minimum, self.maximum + 1)
            if (count - self.offset) % self.step == 0
        )

    def seconds(self, frames: int) -> float:
        return round(frames / self.fps, 1)


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def length_policy(value: Any) -> LengthPolicy | None:
    """The policy behind a form's ``frame_count`` projection (or a declared ``frame_count_policy``); ``None`` when the
    workflow has no selectable length."""

    if not isinstance(value, Mapping):
        return None
    fps = _int(value.get("fps"))
    if not fps or fps < 1:
        return None
    if "minimum" in value:
        numbers = [
            _int(value.get(key)) for key in ("minimum", "maximum", "step", "offset", "default")
        ]
        if any(number is None for number in numbers):
            return None
        minimum, maximum, step, offset, default = (int(number or 0) for number in numbers)
    else:
        frames = sorted(
            {
                count
                for count in (
                    _int(choice.get("frames")) if isinstance(choice, Mapping) else None
                    for choice in value.get("choices") or ()
                )
                if count is not None
            }
        )
        if not frames:
            return None
        minimum, maximum = frames[0], frames[-1]
        step = frames[1] - frames[0] if len(frames) > 1 else 1
        offset = minimum % step if step else 0
        default = _int(value.get("default")) or minimum
    if step < 1 or minimum > maximum:
        return None
    advisory = _int(value.get("advisory_above"))
    policy = LengthPolicy(minimum, maximum, step, offset, fps, default, advisory)
    if default not in policy.legal():
        policy = LengthPolicy(minimum, maximum, step, offset, fps, minimum, advisory)
    return policy


@dataclass(frozen=True)
class DurationChoice:
    """The legal length a duration resolves to, and why."""

    frames: int
    fps: int
    requested_seconds: float | None
    clamped: str = ""
    advisory: str = ""
    note: str = ""

    @property
    def seconds(self) -> float:
        return round(self.frames / self.fps, 1)

    def line(self) -> str:
        return f"{self.seconds:.1f} s · {self.frames} frames at {self.fps} fps"


def _nearest(target: float, legal: Sequence[int]) -> int:
    return min(legal, key=lambda count: (abs(count - target), count))


def frames_for_duration(
    seconds: float | None, policy: LengthPolicy, window: float | None = None
) -> DurationChoice:
    """The nearest legal frame count to ``seconds`` (ties shorter), clamped to the engine's range.

    ``seconds=None`` means the engine's default, or with a driving ``window`` (seconds of usable motion) the whole
    movement: the largest legal length that fits, capped at the engine's maximum.  A window shorter than the engine's
    minimum keeps the minimum and says the last frame is held (the existing behaviour)."""

    if seconds is not None and (not math.isfinite(seconds) or seconds <= 0):
        raise ValueError("A duration must be a positive number of seconds.")
    if window is not None and (not math.isfinite(window) or window < 0):
        raise ValueError("A driving window must be zero or more seconds.")
    legal = policy.legal()
    clamped = ""
    note = ""
    if seconds is None:
        frames = policy.default if window is None else policy.maximum
    else:
        target = seconds * policy.fps
        frames = _nearest(target, legal)
        if target < policy.minimum:
            clamped = CLAMP_MINIMUM
        elif target > policy.maximum:
            clamped = CLAMP_MAXIMUM
    if window is not None:
        available = math.floor(window * policy.fps + 1e-9)
        fitting = [count for count in legal if count <= available]
        if not fitting:
            frames, clamped, note = policy.minimum, CLAMP_WINDOW, NOTE_HELD_LAST_FRAME
        elif fitting[-1] < frames:
            frames, clamped = fitting[-1], CLAMP_WINDOW
        elif seconds is None and available > policy.maximum:
            clamped = CLAMP_MAXIMUM
    advisory = frame_count_advisory({"advisory_above": policy.advisory_above}, frames)
    return DurationChoice(frames, policy.fps, seconds, clamped, advisory, note)


def choice_for_frames(
    frames: int, policy: LengthPolicy, requested_seconds: float | None = None
) -> DurationChoice:
    """A legal length the form already holds, described the way :func:`frames_for_duration` describes one."""

    advisory = frame_count_advisory({"advisory_above": policy.advisory_above}, frames)
    return DurationChoice(int(frames), policy.fps, requested_seconds, advisory=advisory)


def parse_seconds(text: Any) -> float:
    """``"3"``, ``"3 s"``, ``"3.5s"``, ``"2,5"`` or a duration label (``"7.6 s (longest)"``) as seconds."""

    match = _SECONDS.match(str(text if text is not None else ""))
    if match is None:
        raise ValueError("Enter a duration in seconds, for example 3 or 4.5.")
    return float(match.group(1).replace(",", "."))


@dataclass(frozen=True)
class DurationOption:
    label: str
    frames: int


def duration_label(frames: int, policy: LengthPolicy) -> str:
    """How a form shows one legal length: its seconds, marked when it is the engine's longest."""

    text = f"{policy.seconds(frames):.1f} s"
    return text + LONGEST_SUFFIX if frames == policy.maximum else text


def duration_options(policy: LengthPolicy) -> tuple[DurationOption, ...]:
    """About 2, 3 and 5 s and the engine's longest, as distinct legal lengths in order."""

    frames: list[int] = []
    for target in DURATION_TARGETS:
        count = frames_for_duration(target, policy).frames
        if count not in frames and count != policy.maximum:
            frames.append(count)
    frames.append(policy.maximum)
    return tuple(DurationOption(duration_label(count, policy), count) for count in frames)


# ---------------------------------------------------------------- the composed prompt (D3)


def compose_prompt(prompt: Any, motion: Any) -> str:
    """``"<prompt>, <motion>"``: the text a prompt-only job submits.  Either part may be empty."""

    scene = str(prompt or "").strip()
    phrase = str(motion or "").strip()
    if not phrase:
        return scene
    if not scene:
        return phrase
    return f"{scene.rstrip(' ,')}, {phrase}"


def split_composed_prompt(composed: Any, motion: Any) -> tuple[str, str]:
    """The scene prompt and motion phrase a submitted prompt was composed from (``compose_prompt`` reversed).

    When the phrase is not at the end, the prompt was not composed by the form: it is kept whole and the phrase is
    dropped, so nothing is ever added twice."""

    text = str(composed or "").strip()
    phrase = str(motion or "").strip()
    if not phrase:
        return text, ""
    if text == phrase:
        return "", phrase
    suffix = f", {phrase}"
    if text.endswith(suffix):
        return text[: -len(suffix)].strip(), phrase
    return text, ""


# ---------------------------------------------------------------- provenance record (D5)


def _bounded(text: Any, limit: int) -> str:
    return str(text if text is not None else "").strip()[:limit]


def _basis(value: Any) -> dict[str, str]:
    basis: dict[str, str] = {}
    if not isinstance(value, Mapping):
        return basis
    for key, text in value.items():
        if len(basis) >= _BASIS_ENTRIES_MAX:
            break
        if isinstance(key, str) and _BASIS_KEY.match(key) and isinstance(text, str):
            basis[key] = _bounded(text, _BASIS_TEXT_MAX)
    return basis


def motion_intent_record(
    *,
    intent: str,
    preset: MotionPreset | None,
    preset_modified: bool,
    motion_phrase: str,
    duration: DurationChoice | None,
    basis: Mapping[str, str],
) -> dict[str, Any]:
    """The provenance record a submission carries: which preset (id and version) and why each value was chosen."""

    record: dict[str, Any] = {
        "schema": MOTION_INTENT_SCHEMA,
        "intent": str(intent),
        "preset": None
        if preset is None
        else {**preset.identity(), "modified": bool(preset_modified)},
        "motion_phrase": _bounded(motion_phrase, MOTION_PHRASE_MAX),
        "basis": _basis(basis),
    }
    if duration is not None:
        record["duration"] = {
            "requested_seconds": duration.requested_seconds,
            "frames": duration.frames,
            "fps": duration.fps,
        }
    return record


def _requested_seconds(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None


def normalize_motion_intent_record(
    value: Any, *, frame_count: int | None, fps: int | None
) -> dict[str, Any] | None:
    """The record as the NJR freezes it: known fields only, bounded text, the job's frozen length.

    Returns ``None`` for anything that is not a motion-intent record; a provenance record never refuses a job."""

    from src.video.motion_presets import preset_by_id

    if not isinstance(value, Mapping) or value.get("schema") != MOTION_INTENT_SCHEMA:
        return None
    intent = str(value.get("intent") or "")
    if intent not in _KNOWN_INTENTS:
        return None
    preset_value = value.get("preset")
    preset: dict[str, Any] | None = None
    if isinstance(preset_value, Mapping):
        known = preset_by_id(preset_value.get("id"))
        if known is not None and _int(preset_value.get("version")) == known.version:
            preset = {**known.identity(), "modified": bool(preset_value.get("modified"))}
    record: dict[str, Any] = {
        "schema": MOTION_INTENT_SCHEMA,
        "intent": intent,
        "preset": preset,
        "motion_phrase": _bounded(value.get("motion_phrase"), MOTION_PHRASE_MAX),
        "basis": _basis(value.get("basis")),
    }
    if frame_count is not None and fps:
        duration = value.get("duration")
        requested = (
            _requested_seconds(duration.get("requested_seconds"))
            if isinstance(duration, Mapping)
            else None
        )
        record["duration"] = {
            "requested_seconds": requested,
            "frames": int(frame_count),
            "fps": int(fps),
        }
    return record


__all__ = [
    "CLAMP_MAXIMUM",
    "CLAMP_MINIMUM",
    "CLAMP_WINDOW",
    "DURATION_TARGETS",
    "LONGEST_SUFFIX",
    "MOTION_INTENT_FIELD",
    "MOTION_INTENT_SCHEMA",
    "MOTION_PHRASE_MAX",
    "DurationChoice",
    "DurationOption",
    "LengthPolicy",
    "choice_for_frames",
    "compose_prompt",
    "duration_label",
    "duration_options",
    "frames_for_duration",
    "length_policy",
    "motion_intent_record",
    "normalize_motion_intent_record",
    "parse_seconds",
    "split_composed_prompt",
]
