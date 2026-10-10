"""PR-REFINE-160: ADetailer control truth and effectiveness evidence (contract, evidence module, executor dispatch)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from PIL import Image

from src.pipeline.adetailer_contract import (
    FRESH_PASS_DEFAULTS,
    SUPPORTED_ARG_KEYS,
    UNSUPPORTED_CONFIG_KEYS,
    classify_detector,
    detector_status,
    schema_issues,
    split_detectors,
)
from src.pipeline.adetailer_effectiveness import (
    SCHEMA,
    accepted_detectors,
    build_effectiveness,
    compare_images,
    response_infotexts,
)
from src.pipeline.executor import Pipeline

CONTRACT = json.loads(
    (Path(__file__).parents[1] / "data/contracts/adetailer_neo_af228eba_schema.json").read_text(
        encoding="utf-8"
    )
)
SCHEMA_PROPERTIES = CONTRACT["schema"]["properties"]

INFOTEXT_BOTH = "prompt\nSteps: 20, ADetailer model: face_yolov8n.pt, ADetailer confidence: 0.35, ADetailer model 2nd: hand_yolov8n.pt"


def png(path: Path, color=(10, 20, 30), size=(8, 6), pixel=None) -> Path:
    image = Image.new("RGB", size, color)
    if pixel:
        image.putpixel((1, 1), pixel)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


# ------------------------------------------------------------------------------------------------ contract


def test_supported_keys_match_the_frozen_pinned_extension_schema_exactly():
    assert CONTRACT["source_sha"] == "af228eba7a3f3691a25bcd1fc94aa95e600dd3e6"
    assert SUPPORTED_ARG_KEYS == set(SCHEMA_PROPERTIES)
    assert (
        not UNSUPPORTED_CONFIG_KEYS & SUPPORTED_ARG_KEYS
    )  # Max Detections and Mask Feather have no extension argument


def test_schema_issues_follow_the_frozen_enums_and_bounds():
    assert (
        schema_issues(
            {
                key: SCHEMA_PROPERTIES[key]["default"]
                for key in ("ad_confidence", "ad_mask_k", "ad_steps")
            }
        )
        == ()
    )
    for key in ("ad_mask_filter_method", "ad_mask_merge_invert"):
        for value in SCHEMA_PROPERTIES[key]["enum"]:
            assert schema_issues({key: value}) == ()
        assert schema_issues({key: "largest"})  # a legacy GUI value the extension would reject
    for key, spec in SCHEMA_PROPERTIES.items():
        for bound, delta in (("minimum", -1), ("maximum", 1)):
            if (
                bound in spec
                and spec.get("type") in ("integer", "number")
                and key
                in {
                    "ad_confidence",
                    "ad_mask_k",
                    "ad_mask_min_ratio",
                    "ad_mask_max_ratio",
                    "ad_mask_blur",
                    "ad_denoising_strength",
                    "ad_inpaint_only_masked_padding",
                    "ad_steps",
                    "ad_cfg_scale",
                }
            ):
                assert schema_issues({key: spec[bound]}) == (), key
                assert schema_issues({key: spec[bound] + delta}), (key, bound)
    assert schema_issues({"ad_mask_feather": 4, "ad_mask_k": 1}) == (
        "unsupported argument 'ad_mask_feather'",
    )


def test_fresh_defaults_enable_both_passes_and_never_the_overall_stage():
    assert dict(FRESH_PASS_DEFAULTS) == {"enable_face_pass": True, "enable_hands_pass": True}
    assert not any("adetailer_enabled" in key or key == "enabled" for key in FRESH_PASS_DEFAULTS)


def test_detector_lists_are_separated_by_kind_and_never_offer_mediapipe_or_body_models_as_hands():
    names = [
        "face_yolov8n.pt",
        "hand_yolov8n.pt",
        "person_yolov8n-seg.pt",
        "mediapipe_face_full",
        "hand_yolov8s.pt",
    ]
    face, hands = split_detectors(names)
    assert hands == ["hand_yolov8n.pt", "hand_yolov8s.pt"]
    assert "hand_yolov8n.pt" not in face and "person_yolov8n-seg.pt" not in face + hands
    assert [classify_detector(n) for n in ("face_x.pt", "hand_x.pt", "person_x.pt")] == [
        "face",
        "hand",
        "other",
    ]


def test_detector_status_never_substitutes_and_separates_unknown_from_unavailable():
    assert detector_status("hand_yolov8n.pt", ["hand_yolov8n.pt"], "hand") == "available"
    assert detector_status("hand_custom.pt", ["hand_yolov8n.pt"], "hand") == "unavailable"
    assert detector_status("hand_yolov8n.pt", None, "hand") == "unknown"
    assert detector_status("face_yolov8n.pt", ["face_yolov8n.pt"], "hand") == "wrong_role"
    assert detector_status("", ["hand_yolov8n.pt"], "hand") == "unavailable"


# ------------------------------------------------------------------------------------------------ evidence module


def test_identical_pixels_are_measured_as_unchanged_pixels_and_quality_stays_unreviewed(tmp_path):
    before = png(tmp_path / "a.png")
    after = png(tmp_path / "b.png")
    change = compare_images(before, after)
    assert change["status"] == "measured" and change["identical"] is True
    assert change["mean_abs_difference"] == 0.0 and change["changed_pixel_fraction"] == 0.0
    record = build_effectiveness(
        face_args={"ad_model": "face_yolov8n.pt", "ad_tab_enable": True},
        hand_args={"ad_model": "hand_yolov8n.pt", "ad_tab_enable": True},
        request_completed=True,
        input_image=before,
        output_image=after,
        infotexts=[INFOTEXT_BOTH],
    )
    assert record["schema"] == SCHEMA and record["improvement_claimed"] is False
    assert record["visual_review"]["face"] == record["visual_review"]["hands"] == "unreviewed"


def test_different_pixels_are_a_measured_change_not_an_improvement(tmp_path):
    change = compare_images(png(tmp_path / "a.png"), png(tmp_path / "b.png", pixel=(250, 20, 30)))
    assert change["status"] == "measured" and change["identical"] is False
    assert 0 < change["changed_pixel_fraction"] <= 1 and change["mean_abs_difference"] > 0
    assert "not a quality measure" in change["attribution"]


@pytest.mark.parametrize("case", ["missing_input", "none", "size", "decode"])
def test_non_comparable_pairs_are_reported_as_such_never_as_unchanged(tmp_path, case):
    after = png(tmp_path / "after.png")
    before: Path | None = tmp_path / "gone.png"
    if case == "none":
        before = None
    elif case == "size":
        before = png(tmp_path / "other.png", size=(9, 6))
    elif case == "decode":
        before = tmp_path / "broken.png"
        before.write_bytes(b"not an image")
    change = compare_images(before, after)
    assert change["status"] == "not_comparable" and change["reason"]
    assert change["identical"] is None and change["mean_abs_difference"] is None


def test_the_comparison_pixel_bound_is_enforced(tmp_path, monkeypatch):
    from src.pipeline import adetailer_effectiveness

    monkeypatch.setattr(adetailer_effectiveness, "MAX_COMPARE_PIXELS", 10)
    change = compare_images(png(tmp_path / "a.png"), png(tmp_path / "b.png"))
    assert change["status"] == "not_comparable" and "bound" in change["reason"]


def test_forge_detection_is_unknown_without_a_machine_readable_report_even_when_everything_succeeds(
    tmp_path,
):
    record = build_effectiveness(
        face_args={"ad_model": "face_yolov8n.pt", "ad_tab_enable": True},
        hand_args={"ad_model": "hand_yolov8n.pt", "ad_tab_enable": True},
        request_completed=True,
        input_image=png(tmp_path / "a.png"),
        output_image=png(tmp_path / "b.png", pixel=(1, 2, 3)),
        infotexts=None,
    )
    for region in ("face", "hands"):
        assert (
            record["detection"][region]["status"] == "unknown"
            and record["detection"][region]["count"] is None
        )
        assert (
            record["execution"][region]["acknowledged_by_extension"] is None
        )  # no infotext: unknown, not false
    assert record["execution"]["request"]["completed"] is True
    assert "combined request" in record["execution"]["attribution"]


def test_acknowledgement_is_attributed_only_by_detector_name(tmp_path):
    args = {
        "face_args": {"ad_model": "face_yolov8n.pt", "ad_tab_enable": True},
        "hand_args": {"ad_model": "hand_yolov8n.pt", "ad_tab_enable": True},
        "request_completed": True,
        "input_image": None,
        "output_image": None,
    }
    both = build_effectiveness(infotexts=[INFOTEXT_BOTH], **args)["execution"]
    assert (
        both["face"]["acknowledged_by_extension"] is True
        and both["hands"]["acknowledged_by_extension"] is True
    )
    face_only = build_effectiveness(
        infotexts=["x, ADetailer model: face_yolov8n.pt, ADetailer confidence: 0.3"], **args
    )["execution"]
    assert (
        face_only["face"]["acknowledged_by_extension"] is True
        and face_only["hands"]["acknowledged_by_extension"] is False
    )
    same = dict(args, hand_args={"ad_model": "face_yolov8n.pt", "ad_tab_enable": True})
    ambiguous = build_effectiveness(infotexts=["x, ADetailer model: face_yolov8n.pt"], **same)[
        "execution"
    ]
    assert (
        ambiguous["face"]["acknowledged_by_extension"] is None
        and ambiguous["hands"]["acknowledged_by_extension"] is None
    )
    assert accepted_detectors([]) is None and accepted_detectors(None) is None


def test_response_infotexts_reads_only_structured_info():
    assert response_infotexts({"info": json.dumps({"infotexts": ["a"]})}) == ["a"]
    assert response_infotexts({"info": {"infotexts": ["a"]}}) == ["a"]
    for bad in (
        {},
        {"info": "not json"},
        {"info": json.dumps({"infotexts": []})},
        {"info": json.dumps({"infotexts": [1]})},
        None,
    ):
        assert response_infotexts(bad) is None


def _adaptive(status, count):
    return {
        "decision_bundle": {
            "observation": {
                "subject_assessment": {
                    "detection_status": status,
                    "detection_count": count,
                    "detector_id": "opencv_yunet",
                }
            }
        }
    }


@pytest.mark.parametrize(
    ("status", "count", "expected", "detected"),
    [
        ("available", 2, "observed", True),
        ("available", 0, "observed", False),
        ("unavailable", 0, "unknown", None),
        ("error", 0, "unknown", None),
    ],
)
def test_yunet_observations_stay_separate_and_unavailable_is_not_confirmed_no_face(
    status, count, expected, detected
):
    record = build_effectiveness(
        face_args={"ad_model": "face_yolov8n.pt", "ad_tab_enable": True},
        hand_args={"ad_model": "h", "ad_tab_enable": False},
        request_completed=True,
        input_image=None,
        output_image=None,
        adaptive_refinement=_adaptive(status, count),
    )
    yunet = record["detection"]["stablenew_yunet"]
    assert (yunet["status"], yunet["face_detected"]) == (expected, detected)
    assert (
        record["detection"]["face"]["status"] == "unknown"
    )  # YuNet never becomes a Forge detection
    assert record["detection"]["hands"]["count"] is None


# ------------------------------------------------------------------------------------------------ executor dispatch


@pytest.fixture(autouse=True)
def _healthy(monkeypatch):
    monkeypatch.setattr(
        Pipeline,
        "_ensure_runtime_admissible",
        lambda *_a, **_k: {
            "schema": "stablenew.runtime-admission.v1",
            "status": "healthy",
            "reasons": [],
            "cause_codes": [],
        },
    )


def run(tmp_path, config, *, infotexts=None, output_pixel=None, input_exists=True):
    client = Mock()
    client.get_current_model.return_value = "model"
    client.get_current_vae.return_value = "Automatic"
    pipeline = Pipeline(client, Mock())
    source = png(tmp_path / "in.png") if input_exists else tmp_path / "in.png"

    def fake_save(_b64, path, metadata_builder=None):
        png(Path(path), pixel=output_pixel)
        return Path(path)

    info = {"seed": 7}
    if infotexts is not None:
        info["infotexts"] = infotexts
    with (
        patch.object(pipeline, "_load_image_base64", return_value="b64"),
        patch.object(
            pipeline,
            "_generate_images_with_progress",
            return_value={"images": ["r"], "info": json.dumps(info)},
        ) as generate,
        patch("src.pipeline.executor.save_image_from_base64", side_effect=fake_save),
    ):
        result = pipeline.run_adetailer(
            source,
            "prompt",
            "negative",
            {"adetailer_enabled": True, "seed": 7, **config},
            tmp_path / "out",
            "case",
        )
    args = generate.call_args.args[1]["alwayson_scripts"]["ADetailer"]["args"]
    return result, args[2], args[3]


def test_a_legacy_configuration_that_omits_the_hand_flag_keeps_its_historical_meaning(tmp_path):
    _result, face, hands = run(tmp_path, {"enable_face_pass": True})
    assert face["ad_tab_enable"] is True and hands["ad_tab_enable"] is False


@pytest.mark.parametrize(
    ("face", "hands"), [(True, True), (True, False), (False, True), (False, False)]
)
def test_explicit_pass_flags_are_honored_independently(tmp_path, face, hands):
    _result, face_args, hand_args = run(
        tmp_path, {"enable_face_pass": face, "enable_hands_pass": hands}
    )
    assert (face_args["ad_tab_enable"], hand_args["ad_tab_enable"]) == (face, hands)


def test_both_passes_keep_independent_settings_and_unsupported_gui_fields_are_never_transmitted(
    tmp_path,
):
    config = {
        "enable_face_pass": True,
        "enable_hands_pass": True,
        "adetailer_model": "face_yolov8n.pt",
        "adetailer_hands_model": "hand_yolov8n.pt",
        "adetailer_confidence": 0.41,
        "adetailer_hands_confidence": 0.27,
        "ad_mask_filter_method": "Confidence",
        "ad_hands_mask_filter_method": "Area",
        "ad_mask_k_largest": 2,
        "ad_hands_mask_k": 0,
        "ad_mask_min_ratio": 0.02,
        "ad_hands_mask_min_ratio": 0.001,
        "ad_mask_blur": 5,
        "ad_hands_mask_blur": 3,
        "ad_dilate_erode": 2,
        "ad_hands_dilate_erode": 7,
        "ad_inpaint_only_masked": False,
        "ad_hands_inpaint_only_masked": True,
        "adetailer_padding": 0,
        "ad_hands_padding": 24,
        "ad_use_inpaint_width_height": True,
        "ad_inpaint_width": 640,
        "ad_inpaint_height": 640,
        "adetailer_steps": 11,
        "adetailer_hands_steps": 13,
        "adetailer_cfg": 4.5,
        "adetailer_hands_cfg": 6.5,
        "adetailer_denoise": 0.0,
        "adetailer_hands_denoise": 0.2,
        "adetailer_prompt": "",
        "adetailer_hands_prompt": "hands",
        # historical, unsupported by the pinned extension: must never reach it
        "max_detections": 9,
        "mask_feather": 8,
        "adetailer_mask_feather": 8,
        "ad_mask_feather": 8,
        "ad_hands_mask_feather": 8,
    }
    _result, face, hands = run(tmp_path, config)
    for args in (face, hands):
        assert set(args) <= SUPPORTED_ARG_KEYS
        assert not (set(args) & UNSUPPORTED_CONFIG_KEYS)
        assert args["ad_use_steps"] and args["ad_use_cfg_scale"] and args["ad_use_sampler"]
        assert schema_issues(args) == ()
    assert (face["ad_confidence"], hands["ad_confidence"]) == (0.41, 0.27)
    assert (face["ad_mask_filter_method"], hands["ad_mask_filter_method"]) == ("Confidence", "Area")
    assert (face["ad_mask_k"], hands["ad_mask_k"]) == (
        2,
        0,
    )  # an explicit 0 is a value, not "missing"
    assert (face["ad_inpaint_only_masked_padding"], hands["ad_inpaint_only_masked_padding"]) == (
        0,
        24,
    )
    assert (face["ad_denoising_strength"], hands["ad_denoising_strength"]) == (0.0, 0.2)
    assert (face["ad_inpaint_only_masked"], hands["ad_inpaint_only_masked"]) == (False, True)
    assert (
        face["ad_use_inpaint_width_height"] is True
        and hands["ad_use_inpaint_width_height"] is False
    )
    assert (face["ad_steps"], hands["ad_steps"], face["ad_cfg_scale"], hands["ad_cfg_scale"]) == (
        11,
        13,
        4.5,
        6.5,
    )


def test_a_value_the_pinned_schema_rejects_is_logged_because_the_extension_would_drop_the_pass(
    tmp_path, caplog
):
    with caplog.at_level(logging.WARNING):
        run(tmp_path, {"enable_face_pass": True, "ad_mask_filter_method": "largest"})
    assert any(
        "[adetailer/contract]" in rec.message and "largest" in rec.message for rec in caplog.records
    )


def manifest_of(result):
    path = Path(result["artifact"]["manifest_path"])
    return json.loads(path.read_text(encoding="utf-8"))


def test_a_successful_stage_records_execution_evidence_without_claiming_improvement(tmp_path):
    result, _f, _h = run(
        tmp_path,
        {"enable_face_pass": True, "enable_hands_pass": True},
        infotexts=[INFOTEXT_BOTH],
        output_pixel=(200, 10, 10),
    )
    record = manifest_of(result)["adetailer_effectiveness"]
    assert record["schema"] == SCHEMA
    assert record["execution"]["request"]["completed"] is True
    assert record["execution"]["face"]["acknowledged_by_extension"] is True
    assert record["execution"]["hands"]["acknowledged_by_extension"] is True
    assert (
        record["image_change"]["status"] == "measured"
        and record["image_change"]["identical"] is False
    )
    assert (
        record["detection"]["face"]["status"] == "unknown"
        and record["improvement_claimed"] is False
    )
    assert record["visual_review"]["face"] == "unreviewed"
    assert "ad_prompt" not in json.dumps(record)  # prompts are never copied into the evidence


def test_identical_before_and_after_pixels_are_recorded_as_no_measurable_change_and_unreviewed(
    tmp_path,
):
    result, _f, _h = run(
        tmp_path, {"enable_face_pass": True}, infotexts=[INFOTEXT_BOTH], output_pixel=None
    )
    record = manifest_of(result)["adetailer_effectiveness"]
    assert record["image_change"]["identical"] is True
    assert (
        record["visual_review"]["hands"] == "unreviewed" and record["improvement_claimed"] is False
    )


def test_a_missing_input_image_is_not_comparable_and_a_missing_infotext_leaves_acknowledgement_unknown(
    tmp_path,
):
    result, _f, _h = run(
        tmp_path, {"enable_face_pass": True, "enable_hands_pass": True}, input_exists=False
    )
    record = manifest_of(result)["adetailer_effectiveness"]
    assert record["image_change"]["status"] == "not_comparable"
    assert record["execution"]["face"]["acknowledged_by_extension"] is None


def test_the_comparison_is_against_the_adetailer_input_not_a_later_stage(tmp_path):
    result, _f, _h = run(tmp_path, {"enable_face_pass": True}, output_pixel=(9, 9, 9))
    assert result["input_image"] == str(tmp_path / "in.png")
    assert Path(result["path"]).name != "in.png"
    assert manifest_of(result)["adetailer_effectiveness"]["image_change"]["size"] == [8, 6]
