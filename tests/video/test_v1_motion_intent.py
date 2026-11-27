"""V1-1: seconds-first duration, the composed prompt and the motion-intent provenance record (pure, no Tk)."""

from __future__ import annotations

import math

import pytest

from src.video.motion_intent import (
    MOTION_INTENT_SCHEMA,
    MOTION_PHRASE_MAX,
    compose_prompt,
    duration_label,
    duration_options,
    frames_for_duration,
    length_policy,
    motion_intent_record,
    normalize_motion_intent_record,
    parse_seconds,
    split_composed_prompt,
)
from src.video.motion_presets import preset_by_id

# The A14B 4-step and TI2V-5B projections exactly as ``frame_count_projection`` shapes them.
A14B = {
    "default": 81,
    "fps": 16,
    "advisory_above": 81,
    "choices": [{"frames": n, "seconds": round(n / 16, 1)} for n in range(17, 122, 4)],
}
TI2V = {
    "default": 49,
    "fps": 24,
    "choices": [{"frames": n, "seconds": round(n / 24, 1)} for n in range(17, 82, 4)],
}


@pytest.fixture
def a14b():
    policy = length_policy(A14B)
    assert policy is not None
    return policy


def test_policy_is_derived_from_the_projection(a14b):
    assert (a14b.minimum, a14b.maximum, a14b.step, a14b.offset, a14b.fps) == (17, 121, 4, 1, 16)
    assert a14b.default == 81 and a14b.advisory_above == 81
    assert a14b.legal()[:3] == (17, 21, 25)
    assert length_policy(None) is None and length_policy({"choices": []}) is None


def test_policy_also_accepts_a_declared_frame_count_policy():
    policy = length_policy(
        {"default": 49, "minimum": 17, "maximum": 81, "step": 4, "offset": 1, "fps": 24}
    )
    assert policy is not None and policy.legal()[-1] == 81 and policy.default == 49


@pytest.mark.parametrize(
    ("seconds", "frames"),
    [(2.0, 33), (3.0, 49), (5.0, 81), (3.1, 49), (7.6, 121)],
)
def test_seconds_round_to_the_nearest_legal_length(a14b, seconds, frames):
    choice = frames_for_duration(seconds, a14b)
    assert choice.frames == frames
    assert (choice.frames - 1) % 4 == 0
    assert choice.requested_seconds == seconds


def test_a_tie_goes_to_the_shorter_length(a14b):
    # 47/16 s sits exactly between 45 and 49 frames.
    assert frames_for_duration(47 / 16, a14b).frames == 45


def test_lengths_are_clamped_to_the_engine_range_and_say_so(a14b):
    short = frames_for_duration(0.2, a14b)
    long = frames_for_duration(30.0, a14b)
    assert (short.frames, short.clamped) == (17, "minimum")
    assert (long.frames, long.clamped) == (121, "maximum")
    assert frames_for_duration(3.0, a14b).clamped == ""


def test_no_request_means_the_engine_default(a14b):
    choice = frames_for_duration(None, a14b)
    assert choice.frames == 81 and choice.requested_seconds is None


def test_the_advisory_appears_only_above_the_threshold(a14b):
    assert frames_for_duration(5.0, a14b).advisory == ""
    assert "Longer than 81 frames" in frames_for_duration(6.0, a14b).advisory


def test_the_line_shows_seconds_and_frames(a14b):
    assert frames_for_duration(3.0, a14b).line() == "3.1 s · 49 frames at 16 fps"


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf])
def test_impossible_durations_are_refused(a14b, bad):
    with pytest.raises(ValueError):
        frames_for_duration(bad, a14b)


def test_a_driver_window_caps_the_length(a14b):
    whole = frames_for_duration(None, a14b, window=4.2)  # 67.2 frames of motion
    assert whole.frames == 65 and whole.clamped == "window"
    assert frames_for_duration(3.0, a14b, window=2.0).frames == 29
    assert frames_for_duration(None, a14b, window=20.0).frames == 121
    held = frames_for_duration(None, a14b, window=0.5)
    assert held.frames == 17 and "last frame" in held.note


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("3", 3.0), ("3 s", 3.0), ("3.5s", 3.5), (" 2,5 ", 2.5), ("7.6 s (longest)", 7.6)],
)
def test_parse_seconds(text, seconds):
    assert parse_seconds(text) == seconds


@pytest.mark.parametrize("text", ["", "fast", "-2", "s3"])
def test_parse_seconds_refuses_non_durations(text):
    with pytest.raises(ValueError):
        parse_seconds(text)


def test_duration_options_are_short_and_end_at_the_maximum(a14b):
    assert [option.label for option in duration_options(a14b)] == [
        "2.1 s",
        "3.1 s",
        "5.1 s",
        "7.6 s (longest)",
    ]
    ti2v = length_policy(TI2V)
    assert ti2v is not None
    assert [option.frames for option in duration_options(ti2v)] == [49, 73, 81]
    assert duration_label(81, ti2v) == "3.4 s (longest)"
    assert duration_label(49, a14b) == "3.1 s"


def test_every_label_round_trips_to_its_length(a14b):
    for frames in a14b.legal():
        assert (
            frames_for_duration(parse_seconds(duration_label(frames, a14b)), a14b).frames == frames
        )


@pytest.mark.parametrize(
    ("prompt", "motion", "composed"),
    [
        ("a cat on a sofa", "slow pan", "a cat on a sofa, slow pan"),
        ("a cat on a sofa,", "slow pan", "a cat on a sofa, slow pan"),
        ("", "slow pan", "slow pan"),
        ("a cat", "   ", "a cat"),
        ("  a cat  ", "", "a cat"),
    ],
)
def test_compose_prompt(prompt, motion, composed):
    assert compose_prompt(prompt, motion) == composed


def test_split_reverses_compose():
    composed = compose_prompt("a cat on a sofa", "slow pan")
    assert split_composed_prompt(composed, "slow pan") == ("a cat on a sofa", "slow pan")
    assert split_composed_prompt("slow pan", "slow pan") == ("", "slow pan")
    # A phrase that is not at the end was not composed by the form: keep the prompt whole, add nothing again.
    assert split_composed_prompt("slow pan, a cat", "slow pan") == ("slow pan, a cat", "")


def test_the_record_names_the_preset_and_every_basis(a14b):
    walk = preset_by_id("walk")
    record = motion_intent_record(
        intent="animate",
        preset=walk,
        preset_modified=True,
        motion_phrase="walks forward",
        duration=frames_for_duration(5.0, a14b),
        basis={
            "workflow_id": "Recommended: approved for production.",
            "frame_count": "Your choice.",
        },
    )
    assert record["schema"] == MOTION_INTENT_SCHEMA
    assert record["preset"] == {"id": "walk", "version": 1, "modified": True}
    assert record["duration"] == {"requested_seconds": 5.0, "frames": 81, "fps": 16}
    assert record["basis"]["frame_count"] == "Your choice."
    none = motion_intent_record(
        intent="animate",
        preset=None,
        preset_modified=False,
        motion_phrase="",
        duration=None,
        basis={},
    )
    assert none["preset"] is None and "duration" not in none


def test_normalize_keeps_known_fields_and_takes_the_frozen_length():
    record = normalize_motion_intent_record(
        {
            "schema": MOTION_INTENT_SCHEMA,
            "intent": "animate",
            "preset": {"id": "gesture", "version": 1, "modified": False, "extra": "x"},
            "motion_phrase": "y" * (MOTION_PHRASE_MAX + 50),
            "duration": {"requested_seconds": 3.0, "frames": 999, "fps": 1},
            "basis": {"frame_count": "Gesture preset", "bogus": 3},
            "unknown": {"anything": 1},
        },
        frame_count=49,
        fps=16,
    )
    assert record is not None
    assert set(record) == {"schema", "intent", "preset", "motion_phrase", "duration", "basis"}
    assert record["preset"] == {"id": "gesture", "version": 1, "modified": False}
    assert len(record["motion_phrase"]) == MOTION_PHRASE_MAX
    assert record["duration"] == {"requested_seconds": 3.0, "frames": 49, "fps": 16}
    assert record["basis"] == {"frame_count": "Gesture preset"}


@pytest.mark.parametrize("value", [None, "text", {"schema": "other"}, {"intent": "animate"}])
def test_normalize_drops_anything_that_is_not_a_record(value):
    assert normalize_motion_intent_record(value, frame_count=49, fps=16) is None


def test_normalize_drops_an_unknown_preset():
    record = normalize_motion_intent_record(
        {
            "schema": MOTION_INTENT_SCHEMA,
            "intent": "animate",
            "preset": {"id": "zoom", "version": 9},
        },
        frame_count=None,
        fps=None,
    )
    assert record is not None and record["preset"] is None and "duration" not in record
