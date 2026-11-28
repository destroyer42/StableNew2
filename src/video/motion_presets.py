"""Versioned motion presets for the task-first Video Workflow (V1, ``docs/work_packages/V1_motion_controls.md`` 5.4).

A preset is **data**, never a code path: an id and version, a label and, per intent, a duration, a visible motion
phrase, the declared controls it sets and the basis it rests on.  Applying one produces ordinary
:class:`~src.video.workflow_tasks.Suggestion` values that go through the existing pins and ``reconcile`` exactly as the
engine's own suggestions do, so an edited field is never overwritten and a setting the engine does not declare is
skipped with a note that says so.  Nothing here reads Tk, a file or a workflow id; a replay never re-resolves a preset
(the NJR holds frozen values only, and the preset id/version is provenance, D5).

Values beyond the catalog defaults (pose 2.0, reference 0.5) were observed once in MOTION-410 Stage C1 and are not
qualified (owner decision D2); each such side says so in its basis.  Prompt-only presets are prompt wording plus a
duration; the wording is untested and is always shown, editable, in the form and in Preview (D3).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from src.video.motion_intent import frames_for_duration, length_policy
from src.video.workflow_tasks import (
    FIELD_LENGTH,
    TASK_ANIMATE,
    TASK_CONTINUE,
    TASK_FOLLOW_CLIP,
    Suggestion,
)

INTENT_PROMPT_ONLY: Final = "prompt_only"
INTENT_FOLLOW_DRIVER: Final = "follow_driver"

#: A side's duration: seconds, the engine's longest legal length, or (follow a driver) the driver's whole movement.
DURATION_ENGINE_MAX: Final = "engine_max"
DURATION_WHOLE_MOVEMENT: Final = "whole_movement"

#: The form field holding the visible motion phrase (composed into the prompt for prompt-only engines).
FIELD_MOTION_PHRASE: Final = "motion_phrase"
#: Prefix of a declared workflow control's suggestion field (``control:pose_strength``).
CONTROL_FIELD_PREFIX: Final = "control:"
#: The declared Animate control the phrase fills for a driving-video engine (5.4: "instead of the main prompt").
MOTION_PROMPT_CONTROL: Final = "pose_prompt"

NO_PRESET_ID: Final = "none"
NO_PRESET_LABEL: Final = "None"
REASON_NO_PRESET: Final = "No preset: nothing is added to the prompt."
REASON_NO_DRIVER_PRESET: Final = "No preset: the engine's own default."

_UNQUALIFIED: Final = "observed once, not qualified"
_WORDING: Final = "prompt wording only; its effect on the clip is untested"


@dataclass(frozen=True)
class PresetSide:
    """What one preset sets for one intent."""

    duration: float | str
    motion_phrase: str
    basis: str
    controls: Mapping[str, float] = field(default_factory=dict)
    library_tags: tuple[str, ...] = ()
    alignment: str = ""
    warning: str = ""


@dataclass(frozen=True)
class MotionPreset:
    preset_id: str
    version: int
    label: str
    description: str
    prompt_only: PresetSide
    follow_driver: PresetSide

    def side(self, intent: str) -> PresetSide:
        if intent == INTENT_FOLLOW_DRIVER:
            return self.follow_driver
        if intent == INTENT_PROMPT_ONLY:
            return self.prompt_only
        raise ValueError(f"unknown motion intent {intent!r}")

    def identity(self) -> dict[str, Any]:
        return {"id": self.preset_id, "version": self.version}


_SUBTLE_PHRASE = "subtle natural movement, slight head and shoulder motion, steady camera"
_GESTURE_PHRASE = "expressive hand and arm gestures, upper body movement"
_WALK_PHRASE = "walks forward naturally, full body in frame, camera follows"
_DANCE_PHRASE = "dances rhythmically, full body movement"

PRESETS: Final[tuple[MotionPreset, ...]] = (
    MotionPreset(
        preset_id="subtle",
        version=1,
        label="Subtle",
        description="A little natural movement; the camera stays still.",
        prompt_only=PresetSide(3.0, _SUBTLE_PHRASE, f"3 s; {_WORDING}."),
        follow_driver=PresetSide(
            3.0,
            _SUBTLE_PHRASE,
            "Catalog defaults (pose 1.0, reference 1.0); 3 s, or the whole movement if shorter.",
            controls={"pose_strength": 1.0, "reference_image_strength": 1.0},
        ),
    ),
    MotionPreset(
        preset_id="gesture",
        version=1,
        label="Gesture",
        description="Hand, arm and upper-body gestures.",
        prompt_only=PresetSide(3.0, _GESTURE_PHRASE, f"3 s; {_WORDING}."),
        follow_driver=PresetSide(
            DURATION_WHOLE_MOVEMENT,
            _GESTURE_PHRASE,
            f"MOTION-410 C1: reference 0.5 gave head and body movement (one subject, one seed; {_UNQUALIFIED}).",
            controls={"pose_strength": 1.0, "reference_image_strength": 0.5},
            library_tags=("wave", "gesture", "arms"),
        ),
    ),
    MotionPreset(
        preset_id="walk",
        version=1,
        label="Walk",
        description="Walking forward, full body in frame.",
        prompt_only=PresetSide(
            5.0,
            _WALK_PHRASE,
            f"5 s, or the engine's longest if shorter; {_WORDING}.",
            warning="Walking is unresolved in tests.",
        ),
        follow_driver=PresetSide(
            DURATION_WHOLE_MOVEMENT,
            _WALK_PHRASE,
            "Motion guidance (walking unresolved); MOTION-420 walk case: alignment kept the subject in frame "
            f"({_UNQUALIFIED}).",
            library_tags=("walk",),
            alignment="auto",
            warning="Walking is unresolved in tests.",
        ),
    ),
    MotionPreset(
        preset_id="dance",
        version=1,
        label="Dance",
        description="Rhythmic, full-body movement.",
        prompt_only=PresetSide(
            DURATION_ENGINE_MAX, _DANCE_PHRASE, f"The engine's longest length; {_WORDING}."
        ),
        follow_driver=PresetSide(
            DURATION_WHOLE_MOVEMENT,
            _DANCE_PHRASE,
            "MOTION-410 C1: pose 2.0 gave more full-body movement, possible expression bleed (one subject; "
            f"{_UNQUALIFIED}).",
            controls={"pose_strength": 2.0, "reference_image_strength": 0.5},
            library_tags=("dance",),
        ),
    ),
)

_BY_ID: Final = {preset.preset_id: preset for preset in PRESETS}

#: ``more_motion`` / ``less_motion`` move one step along this ladder (5.9).
MOTION_LADDER: Final[tuple[str, ...]] = ("subtle", "gesture", "dance")


def preset_by_id(preset_id: Any) -> MotionPreset | None:
    """The preset with this id, or ``None`` (``"none"``, empty or unknown)."""

    return _BY_ID.get(str(preset_id or "").strip().lower())


def preset_by_label(label: Any) -> MotionPreset | None:
    text = str(label or "").strip()
    return next((preset for preset in PRESETS if preset.label == text), None)


def preset_labels() -> tuple[str, ...]:
    """The choices a preset picker offers, "None" first."""

    return (NO_PRESET_LABEL, *(preset.label for preset in PRESETS))


def ladder_step(preset_id: Any, direction: int) -> tuple[str, str]:
    """One step along :data:`MOTION_LADDER` (``direction`` +1 more motion, -1 less) and a note when it cannot move.

    A snapshot with no preset, or one off the ladder (Walk), starts from the middle step."""

    if direction not in (1, -1):
        raise ValueError("direction must be +1 or -1")
    current = str(preset_id or "").strip().lower()
    if current not in MOTION_LADDER:
        return ("gesture" if direction > 0 else "subtle"), ""
    index = MOTION_LADDER.index(current) + direction
    if index < 0:
        return current, "Already the least motion."
    if index >= len(MOTION_LADDER):
        return current, "Already the most motion."
    return MOTION_LADDER[index], ""


# ---------------------------------------------------------------- application (a suggestion source)


def _visibility(record: Mapping[str, Any]) -> Mapping[str, Any]:
    visible = record.get("form_visibility")
    return visible if isinstance(visible, Mapping) else {}


def _declared_controls(record: Mapping[str, Any]) -> set[str]:
    return {
        str(control.get("name"))
        for control in record.get("operator_controls") or ()
        if isinstance(control, Mapping) and control.get("name")
    }


def _preset_frames(
    duration: float | str, record: Mapping[str, Any], window_seconds: float | None
) -> int | None:
    policy = length_policy(record.get("frame_count"))
    if policy is None:
        return None
    if duration == DURATION_ENGINE_MAX:
        return policy.maximum
    if duration == DURATION_WHOLE_MOVEMENT:
        return frames_for_duration(None, policy, window=window_seconds).frames
    return frames_for_duration(float(duration), policy, window=window_seconds).frames


def preset_suggestions(
    preset: MotionPreset,
    intent: str,
    record: Mapping[str, Any],
    *,
    window_seconds: float | None = None,
) -> tuple[dict[str, Suggestion], list[str]]:
    """The values ``preset`` suggests on the engine ``record`` describes, and a note per skipped setting."""

    side = preset.side(intent)
    reason = f"{preset.label} preset: {side.basis}"
    suggestions: dict[str, Suggestion] = {}
    notes: list[str] = []
    declared = _declared_controls(record)
    if _visibility(record).get("frame_count"):
        frames = _preset_frames(side.duration, record, window_seconds)
        if frames is not None:
            suggestions[FIELD_LENGTH] = Suggestion(FIELD_LENGTH, frames, reason)
    else:
        notes.append(
            f"{preset.label}: this engine has a fixed length; the preset's duration is skipped."
        )
    if intent == INTENT_PROMPT_ONLY:
        suggestions[FIELD_MOTION_PHRASE] = Suggestion(
            FIELD_MOTION_PHRASE, side.motion_phrase, reason
        )
    elif MOTION_PROMPT_CONTROL in declared:
        name = CONTROL_FIELD_PREFIX + MOTION_PROMPT_CONTROL
        suggestions[name] = Suggestion(name, side.motion_phrase, reason)
    for control, value in side.controls.items():
        if control in declared:
            name = CONTROL_FIELD_PREFIX + control
            suggestions[name] = Suggestion(name, value, reason)
        else:
            notes.append(
                f"{preset.label}: this engine does not declare {control.replace('_', ' ')}; skipped."
            )
    return suggestions, notes


def intent_suggestions(
    task_id: str, preset_id: Any, record: Mapping[str, Any]
) -> tuple[dict[str, Suggestion], list[str]]:
    """What the motion intent adds to the engine's own suggestions for ``task_id``.

    The prompt-only and continue tasks: the motion phrase is empty without a preset (so an untouched form submits what it always
    did), and a chosen preset overlays its duration and phrase.  The follow-a-driver task (V1-3): the declared motion
    controls return to their defaults without a preset, and a chosen preset overlays them; the length is not a
    suggestion here, because it follows the driver (``driver_intent.plan_driver_clip``)."""

    if task_id == TASK_FOLLOW_CLIP:
        return _driver_suggestions(preset_by_id(preset_id), record)
    if task_id not in (TASK_ANIMATE, TASK_CONTINUE):
        return {}, []
    suggestions = {FIELD_MOTION_PHRASE: Suggestion(FIELD_MOTION_PHRASE, "", REASON_NO_PRESET)}
    preset = preset_by_id(preset_id)
    if preset is None:
        return suggestions, []
    overlay, notes = preset_suggestions(preset, INTENT_PROMPT_ONLY, record)
    suggestions.update(overlay)
    return suggestions, notes


def preset_duration_seconds(preset: MotionPreset | None) -> float | None:
    """The seconds a follow-a-driver preset asks for; ``None`` means the whole movement."""

    if preset is None:
        return None
    duration = preset.follow_driver.duration
    return None if isinstance(duration, str) else float(duration)


def _driver_suggestions(
    preset: MotionPreset | None, record: Mapping[str, Any]
) -> tuple[dict[str, Suggestion], list[str]]:
    touched = (MOTION_PROMPT_CONTROL, "pose_strength", "reference_image_strength")
    suggestions: dict[str, Suggestion] = {}
    for control in record.get("operator_controls") or ():
        if not isinstance(control, Mapping) or control.get("name") not in touched:
            continue
        name = CONTROL_FIELD_PREFIX + str(control["name"])
        default = "" if control.get("kind") == "text" else control.get("default")
        suggestions[name] = Suggestion(name, default, REASON_NO_DRIVER_PRESET)
    if preset is None:
        return suggestions, []
    overlay, notes = preset_suggestions(preset, INTENT_FOLLOW_DRIVER, record)
    overlay.pop(FIELD_LENGTH, None)
    suggestions.update(overlay)
    return suggestions, notes


def _same_value(current: Any, suggested: Any) -> bool:
    text = str(current if current is not None else "").strip()
    if isinstance(suggested, (int, float)):
        try:
            return float(text) == float(suggested)
        except ValueError:
            return False
    return text == str(suggested).strip()


def preset_is_modified(
    preset: MotionPreset | None,
    intent: str,
    record: Mapping[str, Any],
    current: Mapping[str, Any],
) -> bool:
    """Whether any field the preset sets now holds another value (the chip then reads ``Walk (modified)``)."""

    if preset is None:
        return False
    suggestions, _notes = preset_suggestions(preset, intent, record)
    for name, suggestion in suggestions.items():
        if name not in current:
            continue
        value = current[name]
        if name == FIELD_LENGTH:
            try:
                if int(value) != int(suggestion.value):
                    return True
            except (TypeError, ValueError):
                return True
        elif not _same_value(value, suggestion.value):
            return True
    return False


__all__ = [
    "CONTROL_FIELD_PREFIX",
    "DURATION_ENGINE_MAX",
    "DURATION_WHOLE_MOVEMENT",
    "FIELD_MOTION_PHRASE",
    "INTENT_FOLLOW_DRIVER",
    "INTENT_PROMPT_ONLY",
    "MOTION_LADDER",
    "MOTION_PROMPT_CONTROL",
    "NO_PRESET_ID",
    "NO_PRESET_LABEL",
    "PRESETS",
    "REASON_NO_PRESET",
    "MotionPreset",
    "PresetSide",
    "intent_suggestions",
    "ladder_step",
    "preset_by_id",
    "preset_by_label",
    "preset_duration_seconds",
    "preset_is_modified",
    "preset_labels",
    "preset_suggestions",
]
