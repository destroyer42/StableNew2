"""openpose.v1 declaration contract (PR-IMG-CNET-210): pure validation, defaults and identity rules."""

from __future__ import annotations

import pytest

from src.conditioning import openpose as op


def _declaration(**overrides):
    base = {
        "contract": "openpose.v1",
        "enabled": True,
        "asset": "Standing/relaxed.png",
        "model": "xinsir_openpose_sdxl",
        "weight": 1.0,
        "guidance_start": 0.0,
        "guidance_end": 1.0,
        "control_mode": "Balanced",
        "resize_mode": "Resize and Fill",
        "preprocessor": "None",
    }
    base.update(overrides)
    return base


def test_the_specified_declaration_parses_to_the_specified_defaults() -> None:
    selection = op.parse_declaration(_declaration())

    assert selection.asset == "Standing/relaxed.png"
    assert (selection.weight, selection.guidance_start, selection.guidance_end) == (1.0, 0.0, 1.0)
    assert (selection.control_mode, selection.resize_mode, selection.preprocessor) == (
        "Balanced",
        "Resize and Fill",
        "None",
    )
    assert selection.to_dict() == _declaration()  # canonical round trip


def test_a_new_declaration_uses_the_documented_defaults() -> None:
    created = op.new_declaration("Walking\\walking_forward.png", model="m")

    assert created == _declaration(asset="Walking/walking_forward.png", model="m")


@pytest.mark.parametrize(
    "identity",
    [
        "../outside.png",
        "Standing/../../outside.png",
        "/abs/path.png",
        "C:/poses/a.png",
        "C:\\poses\\a.png",
        "Standing//a.png",
        "./a.png",
        "a.png:stream",
        "Standing/a.png ",  # normalizes (strip) but the trailing-dot rule below covers segments
        "",
        "   ",
        "Standing/a.txt",
        "Standing/noextension",
        "Standing/a.png\x00",
        "x" * 600 + ".png",
    ],
)
def test_unsafe_or_unsupported_identities_are_refused(identity: str) -> None:
    if identity == "Standing/a.png ":
        assert op.normalize_asset_identity(identity) == "Standing/a.png"  # surrounding whitespace is not identity
        return
    with pytest.raises(ValueError):
        op.normalize_asset_identity(identity)


def test_identity_is_posix_normalized_and_extension_case_insensitive() -> None:
    assert op.normalize_asset_identity("Standing\\Relaxed.PNG") == "Standing/Relaxed.PNG"
    assert op.normalize_asset_identity("a.JpEg") == "a.JpEg"
    assert op.normalize_asset_identity("a.webp") == "a.webp"


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"contract": "openpose.v2"}, "contract"),
        ({"contract": None}, "contract"),
        ({"enabled": "false"}, "enabled"),
        ({"asset": "../x.png"}, "path segments"),
        ({"asset": "/x.png"}, "relative"),
        ({"model": 7}, "model"),
        ({"weight": -0.1}, "weight"),
        ({"weight": 2.5}, "weight"),
        ({"weight": True}, "finite number"),
        ({"weight": float("nan")}, "finite number"),
        ({"guidance_start": -0.5}, "between 0 and 1"),
        ({"guidance_end": 1.5}, "between 0 and 1"),
        ({"guidance_start": 0.6, "guidance_end": 0.4}, "lower than"),
        ({"guidance_start": 0.5, "guidance_end": 0.5}, "lower than"),
        ({"control_mode": "Wild"}, "control_mode"),
        ({"resize_mode": "Stretch"}, "resize_mode"),
        ({"preprocessor": "openpose_full"}, "preprocessor"),
        ({"surprise": 1}, "unsupported field"),
    ],
)
def test_each_invalid_declaration_is_rejected_with_a_specific_reason(overrides, fragment: str) -> None:
    problems = op.declaration_problems(_declaration(**overrides))

    assert any(fragment in problem for problem in problems), problems
    with pytest.raises(op.OpenPoseDeclarationError):
        op.parse_declaration(_declaration(**overrides))


def test_all_defects_are_reported_together() -> None:
    problems = op.declaration_problems(_declaration(weight=9, control_mode="x", preprocessor="canny"))

    assert len(problems) == 3


def test_a_non_object_is_a_problem_not_a_crash() -> None:
    assert op.declaration_problems("nope") == ("controlnet_openpose must be an object",)
    assert op.declaration_problems(None) == ("controlnet_openpose must be an object",)


def test_declaration_enabled_is_tolerant_and_never_raises() -> None:
    assert op.declaration_enabled(_declaration()) is True
    assert op.declaration_enabled(_declaration(enabled=False)) is False
    assert op.declaration_enabled({"contract": "openpose.v1"}) is True  # absent flag means enabled
    assert op.declaration_enabled("garbage") is False
    assert op.declaration_enabled(None) is False
    assert op.declaration_enabled(_declaration(enabled="yes")) is False
