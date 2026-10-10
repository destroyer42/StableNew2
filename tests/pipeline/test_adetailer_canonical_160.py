"""PR-REFINE-160: ADetailer settings cross the canonical path (immutable NJR snapshot -> run_njr -> executor -> Forge args)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from PIL import Image

from src.pipeline.adetailer_contract import (
    SUPPORTED_ARG_KEYS,
    UNSUPPORTED_CONFIG_KEYS,
    schema_issues,
)
from src.pipeline.executor import Pipeline
from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.pipeline.pipeline_runner import PipelineRunner
from tests.pipeline.test_pipeline_runner import _record_from_legacy_kwargs, _with_workload

FROZEN_SETTINGS = {
    "adetailer_enabled": True,
    "enable_face_pass": True,
    "enable_hands_pass": False,  # an explicit saved choice
    "adetailer_model": "face_yolov8n.pt",
    "adetailer_hands_model": "hand_yolov8n.pt",
    "adetailer_confidence": 0.44,
    "adetailer_hands_confidence": 0.19,
    "ad_mask_filter_method": "Confidence",
    "ad_mask_k_largest": 1,
    "ad_hands_mask_k": 0,
    "ad_hands_mask_min_ratio": 0.002,
    "adetailer_steps": 9,
    "adetailer_hands_steps": 17,
    "max_detections": 5,
    "mask_feather": 6,
    "ad_hands_mask_feather": 6,
}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    from src.api import healthcheck
    from src.video import comfy_healthcheck

    monkeypatch.setattr(healthcheck, "probe_webui_endpoint", lambda *a, **k: "free")
    monkeypatch.setattr(comfy_healthcheck, "probe_comfy_endpoint", lambda *a, **k: "free")
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


def _record(
    tmp_path: Path, settings: dict, *, intent: dict | None = None
) -> tuple[NormalizedJobRecord, Path]:
    source = tmp_path / "input.png"
    Image.new("RGB", (8, 6), (1, 2, 3)).save(source)
    record = _record_from_legacy_kwargs(
        job_id="adetailer-160",
        config={},
        path_output_dir=str(tmp_path / "output"),
        filename_template="{seed}",
        seed=42,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=0.0,
        stage_chain=[StageConfig(stage_type="adetailer", enabled=True, extra=dict(settings))],
        input_image_paths=[str(source)],
        start_stage="adetailer",
    )
    if intent is not None:
        record = _with_workload(record, positive_prompt="portrait", intent_config=intent)
    return record, source


def _roundtrip(record: NormalizedJobRecord) -> NormalizedJobRecord:
    """The immutable snapshot the queue persists, restored exactly as replay/dispatch would."""

    return NormalizedJobRecord.from_dict(json.loads(json.dumps(record.to_queue_snapshot())))


def _dispatch(tmp_path, record, *, infotexts=None):
    """Run the restored NJR through run_njr and the real executor, capturing the arguments Forge would receive."""

    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    client = Mock()
    client.get_current_model.return_value = "model"
    client.get_current_vae.return_value = "Automatic"
    pipeline = Pipeline(client, Mock())
    runner._pipeline = pipeline
    info = {"seed": 42}
    if infotexts is not None:
        info["infotexts"] = infotexts

    def fake_save(_b64, path, metadata_builder=None):
        Image.new("RGB", (8, 6), (9, 9, 9)).save(path)
        return Path(path)

    with (
        patch.object(pipeline, "_load_image_base64", return_value="b64"),
        patch.object(
            pipeline,
            "_generate_images_with_progress",
            return_value={"images": ["r"], "info": json.dumps(info)},
        ) as generate,
        patch("src.pipeline.executor.save_image_from_base64", side_effect=fake_save),
    ):
        result = runner.run_njr(record, cancel_token=None)
    return result, generate.call_args.args[1]["alwayson_scripts"]["ADetailer"]["args"]


def test_frozen_face_and_hand_settings_survive_the_nrj_snapshot_and_reach_forge_independently(
    tmp_path,
):
    record, _source = _record(tmp_path, FROZEN_SETTINGS)
    restored = _roundtrip(record)
    assert (
        restored.to_queue_snapshot() == record.to_queue_snapshot()
    )  # nothing was rewritten by the round trip
    result, args = _dispatch(tmp_path, restored)
    assert result.success is True
    enable_flag, skip_img2img, face, hands = args
    assert (enable_flag, skip_img2img) == (True, False)
    assert (face["ad_tab_enable"], hands["ad_tab_enable"]) == (
        True,
        False,
    )  # explicit false is preserved, not re-defaulted
    assert (face["ad_model"], hands["ad_model"]) == ("face_yolov8n.pt", "hand_yolov8n.pt")
    assert (face["ad_confidence"], hands["ad_confidence"]) == (0.44, 0.19)
    assert (face["ad_mask_filter_method"], face["ad_mask_k"], hands["ad_mask_k"]) == (
        "Confidence",
        1,
        0,
    )
    assert (face["ad_steps"], hands["ad_steps"]) == (9, 17)
    for unit in (face, hands):
        assert set(unit) <= SUPPORTED_ARG_KEYS and not (set(unit) & UNSUPPORTED_CONFIG_KEYS)
        assert schema_issues(unit) == ()


def test_a_historical_snapshot_without_the_hand_flag_still_replays_with_the_hand_pass_off(tmp_path):
    legacy = {key: value for key, value in FROZEN_SETTINGS.items() if key != "enable_hands_pass"}
    record, _source = _record(tmp_path, legacy)
    _result, args = _dispatch(tmp_path, _roundtrip(record))
    assert args[2]["ad_tab_enable"] is True and args[3]["ad_tab_enable"] is False


def test_an_explicitly_enabled_hand_pass_in_a_snapshot_stays_enabled(tmp_path):
    record, _source = _record(tmp_path, {**FROZEN_SETTINGS, "enable_hands_pass": True})
    _result, args = _dispatch(tmp_path, _roundtrip(record))
    assert args[3]["ad_tab_enable"] is True and args[3]["ad_confidence"] == 0.19


def _stub_service(applied: dict, status: str, count: int):
    class Service:
        def build_bundle(self, *, mode, prompt_intent, image_path, extra_observation=None):
            return {
                "schema": "stablenew.refinement-decision.v1",
                "algorithm_version": "v1",
                "mode": mode,
                "policy_id": "adetailer_micro_face_v1" if applied else None,
                "detector_id": "opencv_yunet",
                "observation": {
                    "prompt_intent": dict(prompt_intent),
                    "subject_assessment": {
                        "detector_id": "opencv_yunet",
                        "detection_status": status,
                        "detection_count": count,
                        "scale_band": "micro" if applied else "unknown",
                    },
                },
                "applied_overrides": applied,
                "prompt_patch": {},
                "notes": [],
            }

        def assess(self, _image_path):
            return {
                "detector_id": "opencv_yunet",
                "detection_status": status,
                "detection_count": count,
            }

    return Service()


INTENT = {
    "adaptive_refinement": {
        "schema": "stablenew.adaptive-refinement.v1",
        "enabled": True,
        "mode": "adetailer",
        "profile_id": "auto_v1",
        "detector_preference": "null",
        "record_decisions": True,
        "algorithm_version": "v1",
    }
}


def test_adaptive_face_policy_adjusts_only_the_face_arguments_and_yunet_is_not_forge_detection(
    tmp_path,
):
    settings = {**FROZEN_SETTINGS, "enable_hands_pass": True}
    record, _source = _record(tmp_path, settings, intent=INTENT)
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    runner._resolve_refinement_policy_service = lambda _pref: (  # type: ignore[method-assign]
        _stub_service(
            {
                "ad_confidence": 0.22,
                "ad_mask_min_ratio": 0.003,
                "ad_inpaint_only_masked_padding": 48,
            },
            "available",
            1,
        ),
        [],
    )
    client = Mock()
    client.get_current_model.return_value = "model"
    client.get_current_vae.return_value = "Automatic"
    pipeline = Pipeline(client, Mock())
    runner._pipeline = pipeline

    def fake_save(_b64, path, metadata_builder=None):
        Image.new("RGB", (8, 6), (9, 9, 9)).save(path)
        return Path(path)

    with (
        patch.object(pipeline, "_load_image_base64", return_value="b64"),
        patch.object(
            pipeline,
            "_generate_images_with_progress",
            return_value={"images": ["r"], "info": json.dumps({"seed": 42})},
        ) as generate,
        patch("src.pipeline.executor.save_image_from_base64", side_effect=fake_save),
    ):
        result = runner.run_njr(record, cancel_token=None)
    face, hands = generate.call_args.args[1]["alwayson_scripts"]["ADetailer"]["args"][2:]
    assert (
        face["ad_confidence"],
        face["ad_mask_min_ratio"],
        face["ad_inpaint_only_masked_padding"],
    ) == (0.22, 0.003, 48)
    assert (hands["ad_confidence"], hands["ad_mask_min_ratio"]) == (
        0.19,
        0.002,
    )  # hand settings are never touched by YuNet
    assert result.success is True
    evidence = result.variants[0]["adetailer_effectiveness"]
    assert evidence["detection"]["stablenew_yunet"]["status"] == "observed"
    assert evidence["detection"]["stablenew_yunet"]["face_detected"] is True
    assert (
        evidence["detection"]["face"]["status"] == "unknown"
    )  # YuNet is never reported as Forge's detection


def test_an_unavailable_yunet_changes_nothing_and_is_not_a_confirmed_no_face(tmp_path):
    settings = {**FROZEN_SETTINGS, "enable_hands_pass": True}
    record, _source = _record(tmp_path, settings, intent=INTENT)
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    runner._resolve_refinement_policy_service = lambda _pref: (
        _stub_service({}, "unavailable", 0),
        [],
    )  # type: ignore[method-assign]
    captured: list[dict] = []
    pipeline = Mock()
    pipeline.client = Mock()
    pipeline.run_adetailer_stage.side_effect = lambda **kw: captured.append(dict(kw["config"])) or {
        "path": str(tmp_path / "o.png")
    }
    runner._pipeline = pipeline
    runner.run_njr(record, cancel_token=None)
    assert captured and captured[0]["adetailer_confidence"] == 0.44
    from src.pipeline.adetailer_effectiveness import build_effectiveness

    bundle = _stub_service({}, "unavailable", 0).build_bundle(
        mode="adetailer", prompt_intent={}, image_path=None
    )
    record_ev = build_effectiveness(
        face_args={"ad_model": "face_yolov8n.pt", "ad_tab_enable": True},
        hand_args={"ad_model": "h", "ad_tab_enable": False},
        request_completed=True,
        input_image=None,
        output_image=None,
        adaptive_refinement={"decision_bundle": bundle},
    )
    assert record_ev["detection"]["stablenew_yunet"]["face_detected"] is None
    assert record_ev["detection"]["stablenew_yunet"]["status"] == "unknown"
