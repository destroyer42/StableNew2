"""V1-1: motion presets are versioned data applied through the existing suggestions and pins (pure, no Tk)."""

from __future__ import annotations

import pytest

from src.video.motion_presets import (
    CONTROL_FIELD_PREFIX,
    FIELD_MOTION_PHRASE,
    INTENT_FOLLOW_DRIVER,
    INTENT_PROMPT_ONLY,
    MOTION_LADDER,
    PRESETS,
    REASON_NO_PRESET,
    intent_suggestions,
    ladder_step,
    preset_by_id,
    preset_by_label,
    preset_is_modified,
    preset_labels,
    preset_suggestions,
)
from src.video.workflow_tasks import (
    FIELD_LENGTH,
    TASK_ANIMATE,
    TASK_FOLLOW_CLIP,
    reconcile,
    suggest_settings,
)

A14B_RECORD = {
    "workflow_id": "a14b",
    "form_visibility": {"frame_count": True, "seed": True},
    "frame_count": {
        "default": 81,
        "fps": 16,
        "advisory_above": 81,
        "choices": [{"frames": n, "seconds": round(n / 16, 1)} for n in range(17, 122, 4)],
    },
}
TI2V_RECORD = {
    "workflow_id": "ti2v",
    "form_visibility": {"frame_count": True, "seed": True},
    "frame_count": {
        "default": 49,
        "fps": 24,
        "choices": [{"frames": n, "seconds": round(n / 24, 1)} for n in range(17, 82, 4)],
    },
}
FIXED_LENGTH_RECORD = {"workflow_id": "svd-like", "form_visibility": {"frame_count": False}}
ANIMATE_RECORD = {
    "workflow_id": "animate",
    "form_visibility": {"frame_count": True, "pose_video": True},
    "frame_count": TI2V_RECORD["frame_count"],
    "operator_controls": [
        {"name": "pose_prompt"},
        {"name": "pose_strength"},
        {"name": "reference_image_strength"},
    ],
}


def test_the_four_presets_are_versioned_data():
    assert [preset.preset_id for preset in PRESETS] == ["subtle", "gesture", "walk", "dance"]
    assert all(preset.version == 1 for preset in PRESETS)
    assert preset_labels() == ("None", "Subtle", "Gesture", "Walk", "Dance")
    assert preset_by_label("Walk") is preset_by_id("walk")
    assert (
        preset_by_id("none") is None and preset_by_id("") is None and preset_by_id("zoom") is None
    )
    for preset in PRESETS:
        for side in (preset.prompt_only, preset.follow_driver):
            assert side.basis and side.motion_phrase


def test_values_beyond_catalog_defaults_say_they_are_unqualified():
    for preset_id in ("gesture", "dance"):
        side = preset_by_id(preset_id).follow_driver
        assert any(value != 1.0 for value in side.controls.values())
        assert "observed once, not qualified" in side.basis
    assert "untested" in preset_by_id("walk").prompt_only.basis
    assert preset_by_id("walk").prompt_only.warning


@pytest.mark.parametrize(
    ("preset_id", "record", "frames"),
    [
        ("subtle", A14B_RECORD, 49),
        ("gesture", A14B_RECORD, 49),
        ("walk", A14B_RECORD, 81),
        ("dance", A14B_RECORD, 121),
        ("walk", TI2V_RECORD, 81),  # 5 s is longer than TI2V-5B allows: its longest
        ("dance", TI2V_RECORD, 81),
    ],
)
def test_prompt_only_presets_set_a_legal_length_and_their_phrase(preset_id, record, frames):
    preset = preset_by_id(preset_id)
    suggestions, notes = preset_suggestions(preset, INTENT_PROMPT_ONLY, record)
    assert suggestions[FIELD_LENGTH].value == frames
    assert suggestions[FIELD_MOTION_PHRASE].value == preset.prompt_only.motion_phrase
    assert suggestions[FIELD_LENGTH].reason.startswith(f"{preset.label} preset:")
    assert notes == []


def test_an_undeclared_length_is_skipped_with_a_note():
    suggestions, notes = preset_suggestions(
        preset_by_id("walk"), INTENT_PROMPT_ONLY, FIXED_LENGTH_RECORD
    )
    assert FIELD_LENGTH not in suggestions
    assert any("duration is skipped" in note for note in notes)


def test_driver_presets_set_only_declared_controls_and_the_motion_prompt():
    suggestions, notes = preset_suggestions(
        preset_by_id("dance"), INTENT_FOLLOW_DRIVER, ANIMATE_RECORD, window_seconds=2.0
    )
    assert suggestions[CONTROL_FIELD_PREFIX + "pose_strength"].value == 2.0
    assert suggestions[CONTROL_FIELD_PREFIX + "reference_image_strength"].value == 0.5
    assert suggestions[CONTROL_FIELD_PREFIX + "pose_prompt"].value.startswith("dances")
    assert (
        FIELD_MOTION_PHRASE not in suggestions
    )  # the phrase fills Motion Prompt, not the main prompt
    assert suggestions[FIELD_LENGTH].value == 45  # the whole 2 s movement at 24 fps
    assert notes == []
    narrow = {**ANIMATE_RECORD, "operator_controls": [{"name": "pose_strength"}]}
    suggestions, notes = preset_suggestions(preset_by_id("dance"), INTENT_FOLLOW_DRIVER, narrow)
    assert CONTROL_FIELD_PREFIX + "reference_image_strength" not in suggestions
    assert any("reference image strength" in note for note in notes)


def test_the_prompt_only_task_without_a_preset_adds_no_phrase():
    suggestions, notes = intent_suggestions(TASK_ANIMATE, "none", A14B_RECORD)
    assert suggestions[FIELD_MOTION_PHRASE].value == ""
    assert suggestions[FIELD_MOTION_PHRASE].reason == REASON_NO_PRESET
    assert FIELD_LENGTH not in suggestions and notes == []
    assert intent_suggestions(TASK_FOLLOW_CLIP, "walk", A14B_RECORD) == ({}, [])


def test_applying_a_preset_respects_pins():
    engine = suggest_settings(TASK_ANIMATE, A14B_RECORD, rife_available=True)
    overlay, _notes = intent_suggestions(TASK_ANIMATE, "walk", A14B_RECORD)
    merged = {**engine, **overlay}
    values, _ = reconcile({FIELD_LENGTH: 33}, set(), merged, A14B_RECORD)
    assert values[FIELD_LENGTH] == 81 and values[FIELD_MOTION_PHRASE].startswith("walks")
    pinned_values, _ = reconcile(
        {FIELD_LENGTH: 33}, {FIELD_LENGTH, FIELD_MOTION_PHRASE}, merged, A14B_RECORD
    )
    assert FIELD_LENGTH not in pinned_values and FIELD_MOTION_PHRASE not in pinned_values


def test_modified_compares_the_current_values_with_the_preset():
    walk = preset_by_id("walk")
    phrase = walk.prompt_only.motion_phrase
    current = {FIELD_LENGTH: 81, FIELD_MOTION_PHRASE: phrase}
    assert not preset_is_modified(walk, INTENT_PROMPT_ONLY, A14B_RECORD, current)
    assert preset_is_modified(walk, INTENT_PROMPT_ONLY, A14B_RECORD, {**current, FIELD_LENGTH: 49})
    assert preset_is_modified(
        walk, INTENT_PROMPT_ONLY, A14B_RECORD, {**current, FIELD_MOTION_PHRASE: "runs"}
    )
    assert not preset_is_modified(None, INTENT_PROMPT_ONLY, A14B_RECORD, current)


@pytest.mark.parametrize(
    ("start", "direction", "expected", "noted"),
    [
        ("subtle", 1, "gesture", False),
        ("gesture", 1, "dance", False),
        ("dance", 1, "dance", True),
        ("gesture", -1, "subtle", False),
        ("subtle", -1, "subtle", True),
        ("none", 1, "gesture", False),
        ("walk", -1, "subtle", False),
    ],
)
def test_the_motion_ladder(start, direction, expected, noted):
    assert MOTION_LADDER == ("subtle", "gesture", "dance")
    step, note = ladder_step(start, direction)
    assert step == expected and bool(note) is noted


def test_the_ladder_refuses_a_non_step():
    with pytest.raises(ValueError):
        ladder_step("subtle", 2)
