"""PR-VID-MOTION-210: the pure frame plan (which source frame becomes each consumed frame).

No file, process or GUI is touched.  The numbers are small enough to be checked by hand.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from src.controller.ports.default_runtime_ports import DefaultWorkflowRegistryPort
from src.video.driving_video_inspection import DrivingVideoFacts, parse_probe_output
from src.video.motion_source_plan import (
    FPS_CONVERSION_NONE,
    FPS_CONVERSION_WORKFLOW_RATE,
    MAX_SOURCE_SPAN_FRAMES,
    FramePlan,
    MotionSourceContract,
    MotionSourceSettings,
    MotionSourceUnavailable,
    build_frame_plan,
    explain_plan,
    ffmpeg_filter_chain,
    format_ranges,
    frame_from_seconds,
    last_source_frame_needed,
    motion_source_contract,
    source_rate,
)
from src.video.workflow_catalog_wan_animate2 import (
    WAN_ANIMATE2_DRIVE_ID,
    WAN_ANIMATE2_PROMPT_ID,
    WAN_ANIMATE2_RUNTIME_VERSION,
)

REGISTRY = DefaultWorkflowRegistryPort()
CONVERT = FPS_CONVERSION_WORKFLOW_RATE
NONE = FPS_CONVERSION_NONE


def _contract(frames: int = 17, fps: int = 24) -> MotionSourceContract:
    return MotionSourceContract("wf", "1.0.0", frames, fps, "rev", "rule")


def _plan(
    mode: str = NONE,
    *,
    start: int = 0,
    end: int | None = None,
    rate: Fraction | None = Fraction(30),
    available: int = 1000,
    frames: int = 17,
) -> FramePlan:
    return build_frame_plan(
        MotionSourceSettings(start, end, mode),
        _contract(frames),
        rate=rate,
        available_frames=available,
    )


# ------------------------------------------------------------------------------------ contract


def _drive_spec(version: str = WAN_ANIMATE2_RUNTIME_VERSION) -> Any:
    return REGISTRY.get(WAN_ANIMATE2_DRIVE_ID, version)


def test_contract_comes_from_the_registered_spec_and_the_chosen_legal_length():
    contract = motion_source_contract(_drive_spec(), "49")
    assert (contract.workflow_id, contract.workflow_version) == (
        WAN_ANIMATE2_DRIVE_ID,
        WAN_ANIMATE2_RUNTIME_VERSION,
    )
    assert (contract.output_frames, contract.output_fps) == (49, 24)
    assert contract.runtime_revision == "6b747c0428c343e1417219641db93a4fb7cb69ae"
    assert "no frame-rate conversion" in contract.consumption_rule
    assert motion_source_contract(_drive_spec(), "").output_frames == 41  # the declared default


@pytest.mark.parametrize("bad", ["40", "16", "85", "abc"])
def test_an_illegal_length_is_refused_never_rounded(bad):
    with pytest.raises(ValueError):
        motion_source_contract(_drive_spec(), bad)


def test_workflows_without_a_verified_driving_video_contract_are_not_offered_preparation():
    prompt = REGISTRY.get(WAN_ANIMATE2_PROMPT_ID, WAN_ANIMATE2_RUNTIME_VERSION)
    with pytest.raises(MotionSourceUnavailable, match="no driving video"):
        motion_source_contract(prompt, "41")
    ti2v = REGISTRY.get("wan22_ti2v_5b_i2v_v1", "1.1.0")
    with pytest.raises(MotionSourceUnavailable, match="no driving video"):
        motion_source_contract(ti2v, "49")

    spec = _drive_spec()
    defaults = copy.deepcopy(dict(spec.backend_defaults))
    defaults["provenance"]["comfyui_revision"] = "0" * 40
    unverified = dataclasses.replace(spec, backend_defaults=defaults)
    with pytest.raises(MotionSourceUnavailable, match="not verified"):
        motion_source_contract(unverified, "41")
    defaults = copy.deepcopy(dict(spec.backend_defaults))
    defaults["prompt_template"]["10"]["inputs"]["video_frame_offset"] = 4
    with pytest.raises(MotionSourceUnavailable, match="seeks"):
        motion_source_contract(dataclasses.replace(spec, backend_defaults=defaults), "41")


# ------------------------------------------------------------------------------------ settings


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        (MotionSourceSettings(-1), "negative"),
        (MotionSourceSettings(5, 5), "end after"),
        (MotionSourceSettings(5, 3), "end after"),
        (MotionSourceSettings(0, None, "bicubic"), "Unknown"),
        (MotionSourceSettings(1.5), "whole"),  # type: ignore[arg-type]
        (MotionSourceSettings(True), "whole"),  # type: ignore[arg-type]
    ],
)
def test_invalid_settings_are_refused(settings, message):
    with pytest.raises(ValueError, match=message):
        settings.validate()


def test_seconds_become_the_nearest_frame_exactly():
    assert frame_from_seconds(1.2, Fraction(30)) == 36
    assert frame_from_seconds(0, Fraction(30)) == 0
    assert frame_from_seconds(0.0166, Fraction(30)) == 0  # half a frame is 0.01666...
    assert frame_from_seconds(0.0167, Fraction(30)) == 1
    assert frame_from_seconds(1.0, Fraction(30000, 1001)) == 30
    assert frame_from_seconds(0.5, Fraction(1)) == 1  # a tie takes the later frame


def test_the_exact_rational_rate_is_preferred_to_the_float():
    stream = b'{"streams":[{"width":64,"height":48,"avg_frame_rate":"30000/1001","r_frame_rate":"30000/1001","nb_frames":"90","pix_fmt":"yuv420p","duration":"3.0"}]}'
    facts = parse_probe_output(stream)
    assert facts.fps_rational == "30000/1001"
    assert source_rate(facts) == Fraction(30000, 1001)
    no_rate = dataclasses.replace(facts, reported_fps=None, fps_rational="")
    assert source_rate(no_rate) is None
    float_only = dataclasses.replace(facts, fps_rational="")
    assert source_rate(float_only) == Fraction(30000, 1001)  # recovered from the float


# ------------------------------------------------------------------------------------ the plan


def test_without_conversion_each_consumed_frame_is_the_next_source_frame():
    plan = _plan(NONE, start=5)
    assert plan.source_indices == tuple(range(5, 22))
    assert plan.held_frames == 0 and plan.omitted == () and plan.repeated == {}
    assert plan.output_frames == 17 and plan.window_end == 1005
    assert plan.output_rate == Fraction(30)  # the clip's own rate, nothing converted
    assert plan.speed_vs_original == pytest.approx(24 / 30)


def test_without_a_known_rate_the_prepared_file_carries_the_workflow_rate():
    plan = _plan(NONE, rate=None)
    assert plan.output_rate == Fraction(24)
    assert plan.speed_vs_original == 1.0


def test_down_conversion_takes_the_nearest_source_frame_and_omits_the_rest():
    plan = _plan(CONVERT, start=5, rate=Fraction(30))
    offsets = [index - 5 for index in plan.source_indices]
    # j * 30/24 = j * 1.25 -> 0, 1.25, 2.5, 3.75, 5 ... rounded to the nearest, a tie to the later.
    assert offsets == [0, 1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14, 15, 16, 18, 19, 20]
    assert plan.repeated == {} and plan.held_frames == 0
    assert plan.omitted == (7, 12, 17, 22)
    assert plan.output_rate == Fraction(24) and plan.speed_vs_original == 1.0


def test_up_conversion_repeats_source_frames():
    plan = _plan(CONVERT, rate=Fraction(12), frames=9)
    assert plan.source_indices == (0, 1, 1, 2, 2, 3, 3, 4, 4)
    assert plan.omitted == ()
    assert plan.repeated == {1: 1, 2: 1, 3: 1, 4: 1}


@pytest.mark.parametrize(
    ("rate", "expected_first_twelve"),
    [
        (Fraction(60), [0, 3, 5, 8, 10, 13, 15, 18, 20, 23, 25, 28]),
        (Fraction(25), [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]),
        (Fraction(24), [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]),
        (Fraction(30000, 1001), [0, 1, 2, 4, 5, 6, 7, 9, 10, 11, 12, 14]),
        (Fraction(48), [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22]),
        (Fraction(36), [0, 2, 3, 5, 6, 8, 9, 11, 12, 14, 15, 17]),  # 1.5x: every tie goes later
    ],
)
def test_the_conversion_rule_for_common_clip_rates(rate, expected_first_twelve):
    plan = _plan(CONVERT, rate=rate, frames=41)
    assert list(plan.source_indices[:12]) == expected_first_twelve


def test_indices_never_decrease_and_never_leave_the_window():
    for rate in (Fraction(12), Fraction(25), Fraction(30), Fraction(60), Fraction(120)):
        plan = _plan(CONVERT, start=7, rate=rate, available=40, frames=41)
        assert list(plan.source_indices) == sorted(plan.source_indices)
        assert min(plan.source_indices) >= 7 and max(plan.source_indices) <= 7 + 39


def test_a_short_clip_holds_its_last_frame_for_the_remaining_consumed_frames():
    plan = _plan(NONE, start=10, available=4, frames=9)
    assert plan.source_indices == (10, 11, 12, 13, 13, 13, 13, 13, 13)
    assert plan.held_frames == 5 and plan.window_end == 14
    assert plan.fresh_indices == (10, 11, 12, 13) and plan.repeated == {}


def test_an_operator_window_end_bounds_the_clip_and_holds():
    plan = _plan(NONE, start=3, end=6, frames=7)
    assert plan.source_indices == (3, 4, 5, 5, 5, 5, 5)
    assert plan.held_frames == 4 and plan.window_frames == 3

    converted = _plan(CONVERT, start=0, end=3, rate=Fraction(30), frames=9)
    assert converted.window_frames == 3
    assert converted.source_indices == (0, 1, 2, 2, 2, 2, 2, 2, 2)
    # Output frame 2 wants source frame 3, which the window does not have: from there on it is a hold.
    assert converted.held_frames == 7 and converted.fresh_indices == (0, 1)


def test_the_window_end_cannot_extend_the_clip():
    plan = _plan(NONE, start=0, end=500, available=6, frames=9)
    assert plan.window_frames == 6 and plan.held_frames == 3


def test_an_empty_window_is_refused():
    with pytest.raises(ValueError, match="no frames"):
        _plan(NONE, start=0, available=0)


def test_a_longer_clip_leaves_unused_frames_after_the_window():
    plan = _plan(NONE, start=0, available=100, frames=17)
    assert plan.unused_after == 100 - 17


def test_conversion_needs_a_reported_rate():
    with pytest.raises(ValueError, match="reports its frame rate"):
        _plan(CONVERT, rate=None)


def test_the_last_needed_frame_is_known_before_the_clip_length_is_known():
    contract = _contract(17)
    assert last_source_frame_needed(MotionSourceSettings(5), contract, Fraction(30)) == 21
    assert (
        last_source_frame_needed(MotionSourceSettings(5, None, CONVERT), contract, Fraction(60))
        == 5 + 40
    )
    assert last_source_frame_needed(MotionSourceSettings(5, 9), contract, Fraction(30)) == 8
    with pytest.raises(ValueError, match="spans more than"):
        last_source_frame_needed(
            MotionSourceSettings(0, None, CONVERT), _contract(81), Fraction(MAX_SOURCE_SPAN_FRAMES)
        )


# ------------------------------------------------------------------------------------ FFmpeg chain


def test_the_filter_chain_for_a_contiguous_plan_is_pinned():
    plan = _plan(NONE, start=5, frames=4)
    assert ffmpeg_filter_chain(plan) == (
        "select='between(n,5,8)',tpad=stop=1:stop_mode=clone,settb=1/30,"
        "setpts='gte(N,1)*1+gte(N,2)*1+gte(N,3)*1+gte(N,4)*1',fps=fps=30/1"
    )


def test_the_filter_chain_stamps_repeats_and_holds_with_exact_integer_ticks():
    plan = _plan(CONVERT, rate=Fraction(12), frames=5)  # 0 1 1 2 2
    assert plan.source_indices == (0, 1, 1, 2, 2)
    assert ffmpeg_filter_chain(plan) == (
        "select='between(n,0,2)',tpad=stop=1:stop_mode=clone,settb=1/24,"
        "setpts='gte(N,1)*1+gte(N,2)*2+gte(N,3)*2',fps=fps=24/1"
    )
    held = _plan(NONE, start=10, available=2, frames=5)  # 10 11 11 11 11
    assert ffmpeg_filter_chain(held) == (
        "select='between(n,10,11)',tpad=stop=1:stop_mode=clone,settb=1/30,"
        "setpts='gte(N,1)*1+gte(N,2)*4',fps=fps=30/1"
    )


def test_the_filter_chain_uses_runs_for_omitted_frames_and_the_exact_ntsc_timebase():
    plan = _plan(CONVERT, rate=Fraction(30), frames=6)  # 0 1 3 4 5 6
    assert "select='between(n,0,1)+between(n,3,6)'" in ffmpeg_filter_chain(plan)
    ntsc = _plan(NONE, rate=Fraction(30000, 1001), frames=3)
    chain = ffmpeg_filter_chain(ntsc)
    assert "settb=1/30000" in chain and "fps=fps=30000/1001" in chain
    assert "gte(N,1)*1001" in chain  # one slot is 1001 ticks of 1/30000 s


def test_a_single_frame_plan_is_valid():
    plan = _plan(NONE, start=0, available=1, frames=1)
    assert plan.source_indices == (0,)
    assert ffmpeg_filter_chain(plan).endswith("setpts='gte(N,1)*1',fps=fps=30/1")


# ------------------------------------------------------------------------------------ explanation


def test_the_explanation_says_what_is_omitted_repeated_held_and_unused():
    contract = _contract(17)
    converted = _plan(CONVERT, start=5, rate=Fraction(30))
    text = "\n".join(explain_plan(converted, contract))
    assert "source frames 5-" in text and "Frame numbers start at 0" in text
    assert "exactly 17 frames" in text and "24 fps" in text
    assert "converted from 30 fps to 24 fps" in text
    assert "Omitted: 4 source frame(s)" in text and "7, 12, 17, 22" in text
    assert "Repeated: none." in text

    upsampled = _plan(CONVERT, rate=Fraction(12), frames=9)
    text = "\n".join(explain_plan(upsampled, _contract(9)))
    assert "Repeated: 4 extra copy(ies) of 4 source frame(s)" in text and "Omitted: none." in text

    held = _plan(NONE, start=10, available=4, frames=9)
    text = "\n".join(explain_plan(held, _contract(9)))
    assert "Held: the clip ends at source frame 13" in text and "last 5 output frame(s)" in text

    windowed = _plan(NONE, start=3, end=6, frames=7)
    assert "the window ends at source frame 5" in "\n".join(explain_plan(windowed, _contract(7)))

    long = _plan(NONE, available=100)
    assert "Unused: 83 frame(s) after source frame 16" in "\n".join(explain_plan(long, contract))


def test_without_conversion_the_explanation_states_the_playback_speed():
    text = "\n".join(explain_plan(_plan(NONE, rate=Fraction(30)), _contract(17)))
    assert "not converted" in text and "0.80x its original speed" in text
    same = "\n".join(explain_plan(_plan(NONE, rate=Fraction(24)), _contract(17)))
    assert "original speed" not in same


def test_range_formatting_is_compact_and_bounded():
    assert format_ranges([7, 3, 4, 5, 9]) == "3-5, 7, 9"
    many = format_ranges(range(0, 100, 2), limit=3)
    assert many == "0, 2, 4 (and 47 more ranges)"


# ------------------------------------------------------------------------------------ structure


def test_the_plan_module_is_pure():
    root = Path(__file__).resolve().parents[2] / "src" / "video"
    imports: set[str] = set()
    for name in ("motion_source_plan.py", "driving_frame_consumption.py"):
        for node in ast.walk(ast.parse((root / name).read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            elif isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
    forbidden = re.compile(
        r"^(src\.(gui|queue|controller|history|learning|pipeline)|subprocess|socket|tkinter|PIL)"
    )
    assert [module for module in imports if forbidden.match(module)] == []
    assert "src.video.motion_source_readiness" not in imports  # advisories stay display-only


def test_facts_are_a_frozen_value():
    facts = DrivingVideoFacts(
        "mp4",
        "h264",
        "yuv420p",
        8,
        8,
        0,
        8,
        8,
        "",
        24.0,
        "average",
        False,
        10,
        None,
        "reported",
        0.4,
        "stream",
    )
    assert facts.fps_rational == ""  # the new field is optional: older constructions are unchanged
    with pytest.raises(dataclasses.FrozenInstanceError):
        facts.codec_name = "x"  # type: ignore[misc]
