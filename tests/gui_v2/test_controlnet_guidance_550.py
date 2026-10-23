"""PR-GUI-UX-550: guidance labels and editor-level readiness are pure and never over-claim."""

from __future__ import annotations

import pytest

from src.assets.controlnet_structure import ControlNetEvidence, ControlNetModelOption
from src.conditioning.controlnet import CONTRACT, UNIT_CONTRACT, declaration_problems, parse_units
from src.conditioning.openpose import (
    DEFAULT_CONTROL_MODE,
    DEFAULT_GUIDANCE_END,
    DEFAULT_GUIDANCE_START,
    DEFAULT_RESIZE_MODE,
    DEFAULT_WEIGHT,
)
from src.gui_v2 import controlnet_guidance as g
from src.image_backends.model_policy import EVIDENCE_REGISTRY

MAP = "Standing/relaxed.png"
POSE_MODEL = "xinsir_openpose_sdxl"
DEPTH_MODEL = "diffusers_xl_depth_full"


class _Target:
    def __init__(self, executable: bool = True, evidence: str = EVIDENCE_REGISTRY) -> None:
        self.executable = executable
        self.evidence = evidence


def _model(name: str, status: str = "sdxl", detail: str = "header") -> ControlNetModelOption:
    return ControlNetModelOption(name, ControlNetEvidence(status, detail))


def _raw(*units: dict) -> dict:
    return {"contract": CONTRACT, "units": list(units)}


def _unit(modality: str = "openpose", model: str = POSE_MODEL, **extra) -> dict:
    return {**g.new_unit(modality, asset=MAP, model=model), **extra}


def _ready(raw, **kwargs):
    kwargs.setdefault("target", _Target())
    kwargs.setdefault("library_identities", frozenset({MAP}))
    kwargs.setdefault("models", [_model(POSE_MODEL), _model(DEPTH_MODEL)])
    kwargs.setdefault("resources_loaded", True)
    return g.describe_readiness(raw, **kwargs)


def test_friendly_labels_are_presentation_only_and_round_trip_to_the_stored_ids():
    assert [guide.label for guide in g.MODALITY_GUIDES] == [
        "Pose / Body Position",
        "Edges / Structure",
        "Depth / Spatial Layout",
    ]
    assert [g.modality_from_label(label) for label in g.MODALITY_LABELS] == [
        "openpose",
        "canny",
        "depth",
    ]
    assert g.modality_from_label("depth") is None
    assert g.modality_label("canny") == "Edges / Structure"
    assert g.modality_label("future") == "future"  # an unknown stored value is shown, never renamed
    assert "Unsupported" in g.guide_text("future")
    for guide in g.MODALITY_GUIDES:
        text = g.guide_text(guide.modality)
        assert "pre-rendered" in text and "does not" in text


@pytest.mark.parametrize("modality", ["openpose", "canny", "depth"])
def test_a_new_unit_carries_the_canonical_defaults(modality):
    unit = g.new_unit(modality)
    assert unit["modality"] == modality and unit["contract"] == UNIT_CONTRACT
    assert (
        unit["weight"],
        unit["guidance_start"],
        unit["guidance_end"],
        unit["control_mode"],
        unit["resize_mode"],
        unit["preprocessor"],
    ) == (
        DEFAULT_WEIGHT,
        DEFAULT_GUIDANCE_START,
        DEFAULT_GUIDANCE_END,
        DEFAULT_CONTROL_MODE,
        DEFAULT_RESIZE_MODE,
        "None",
    )
    assert not g.advanced_is_customized(unit)
    assert g.advanced_is_customized({**unit, "guidance_end": 0.5})
    # Valid as soon as a map is chosen: no invented tuning values.
    assert declaration_problems(_raw({**unit, "asset": MAP})) == ()
    with pytest.raises(ValueError):
        g.new_unit("scribble")


def test_recommendation_needs_exactly_one_verified_documented_model():
    assert g.recommended_model("openpose", [_model(POSE_MODEL), _model(DEPTH_MODEL)]) == POSE_MODEL
    assert g.recommended_model("depth", [_model(POSE_MODEL), _model(DEPTH_MODEL)]) == DEPTH_MODEL
    # Two verified pose models: the operator chooses.
    assert (
        g.recommended_model("openpose", [_model(POSE_MODEL), _model("thibaud_xl_openpose")]) is None
    )
    # Header evidence and documented identity are separate requirements.
    assert g.recommended_model("openpose", [_model(POSE_MODEL, "unverified")]) is None
    assert g.recommended_model("openpose", [_model(POSE_MODEL, "not_sdxl")]) is None
    assert g.recommended_model("openpose", [_model("my_renamed_openpose")]) is None
    assert g.recommended_model("canny", [_model(POSE_MODEL)]) is None
    # Same model name in two folders is ambiguous, never recommended.
    assert g.recommended_model("openpose", [_model(POSE_MODEL), _model(POSE_MODEL.upper())]) is None
    assert g.recommended_model("openpose", []) is None


def test_model_choices_report_each_installed_weight_without_hiding_any():
    choices = {
        c.name: c
        for c in g.model_choices("depth", [_model(POSE_MODEL), _model(DEPTH_MODEL, "unverified")])
    }
    assert set(choices) == {POSE_MODEL, DEPTH_MODEL}
    assert "openpose" in choices[POSE_MODEL].problem  # documented for another purpose
    assert choices[DEPTH_MODEL].problem and not choices[DEPTH_MODEL].compatible  # unverified header


def test_no_units_and_legacy_conflict_states():
    assert _ready(None).state == g.STATE_NONE
    assert "No ControlNet units" in _ready(None).text
    legacy = _ready(None, legacy_present=True)
    assert legacy.state == g.STATE_CONFLICT and "legacy OpenPose" in legacy.text
    both = _ready(_raw(_unit()), legacy_present=True)
    assert both.state == g.STATE_BLOCKED and "legacy OpenPose" in both.text


def test_invalid_declaration_is_reported_and_kept():
    report = _ready({"contract": "unknown", "units": "bad"})
    assert report.state == g.STATE_INVALID and report.text.startswith("Cannot execute:")
    assert "kept until you remove it" in report.text
    empty_asset = _ready(_raw({**g.new_unit("canny", model=DEPTH_MODEL)}))
    assert (
        empty_asset.state == g.STATE_INVALID and "no reference map chosen yet" in empty_asset.text
    )
    assert g.ordered_summary({"contract": "unknown"}) == ""


def test_local_ok_still_defers_to_preview_and_admission():
    report = _ready(_raw(_unit(), _unit("depth", DEPTH_MODEL)))
    assert report.state == g.STATE_LOCAL_OK
    assert report.text.count("Local resources compatible") == 2
    assert "Preview and Forge admission remain required" in report.text
    assert "Preview (the compiler)" in g.SCOPE_NOTE and "Forge admission" in g.SCOPE_NOTE


def test_a_disabled_unit_is_not_presented_as_active():
    report = _ready(_raw(_unit(enabled=False)))
    assert (
        report.state == g.STATE_DISABLED and "disabled" in report.text and "not sent" in report.text
    )
    summary = g.ordered_summary(_raw(_unit(enabled=False)))
    assert "[disabled: not sent]" in summary


@pytest.mark.parametrize(
    ("kwargs", "needle"),
    [
        ({"library_identities": frozenset()}, "reference map 'Standing/relaxed.png' is missing"),
        ({"models": [_model(DEPTH_MODEL)]}, "is not installed in models/ControlNet"),
        ({"models": [_model(POSE_MODEL), _model(POSE_MODEL.upper())]}, "ambiguous"),
        (
            {"models": [_model(POSE_MODEL, "not_sdxl", "text-context width 768")]},
            "is not an SDXL ControlNet",
        ),
        ({"target": None}, "registry-verified SDXL checkpoint"),
        ({"target": _Target(executable=False)}, "registry-verified SDXL checkpoint"),
    ],
)
def test_definite_refusals_are_labelled_cannot_execute(kwargs, needle):
    report = _ready(_raw(_unit()), **kwargs)
    assert report.state == g.STATE_BLOCKED
    assert report.text.count("Cannot execute") == 1 and needle in report.text


def test_unverified_header_is_uncertainty_not_incompatibility():
    report = _ready(
        _raw(_unit()),
        models=[_model(POSE_MODEL, "unverified", "no recognizable SD architecture markers")],
    )
    assert report.state == g.STATE_BLOCKED  # admission requires positive evidence
    assert "unverified" in report.text and "is not an SDXL ControlNet" not in report.text


def test_modality_and_model_identity_mismatches_are_explained():
    wrong = _ready(_raw(_unit("depth", POSE_MODEL)))
    assert "documented for Pose / Body Position, not Depth / Spatial Layout" in wrong.text
    unknown = _ready(_raw(_unit("canny", "my_canny_xl")), models=[_model("my_canny_xl")])
    assert "not a documented Edges / Structure model" in unknown.text
    assert "diffusers_xl_canny_full" in unknown.text
    missing = _ready(_raw(_unit(model="")))
    assert "choose a ControlNet model" in missing.text


def test_unloaded_or_failed_refresh_is_not_reported_as_a_definite_failure():
    unloaded = _ready(_raw(_unit()), resources_loaded=False, library_identities=None, models=[])
    assert unloaded.state == g.STATE_UNCONFIRMED and "Cannot execute" not in unloaded.text
    failed = _ready(_raw(_unit()), library_error="disk offline", models=[])
    assert (
        failed.state == g.STATE_UNCONFIRMED
        and "resource refresh failed: disk offline" in failed.text
    )
    assert "Cannot execute" not in failed.text


def test_names_pass_through_the_redaction_hook():
    hide = lambda name: "[hidden]" if "nude" in name else name  # noqa: E731
    raw = _raw({**_unit(), "asset": "Poses/nude standing.png"})
    report = _ready(raw, library_identities=frozenset(), shown=hide)
    assert "nude" not in report.text and "[hidden]" in report.text
    assert "nude" not in g.ordered_summary(raw, hide)


def test_new_unit_acceptance_follows_the_two_unit_limit():
    assert g.accepts_new_unit(None)
    assert g.accepts_new_unit(_raw(_unit()))
    assert not g.accepts_new_unit(_raw(_unit(), _unit("depth", DEPTH_MODEL)))
    assert not g.accepts_new_unit({"contract": "unknown", "units": "bad"})
    assert [u.modality for u in parse_units(_raw(_unit(), _unit("depth", DEPTH_MODEL)))] == [
        "openpose",
        "depth",
    ]
