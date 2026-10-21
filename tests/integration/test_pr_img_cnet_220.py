"""Ordered ControlNet through PromptPack -> NJR -> SQLite queue -> Forge (fakes only)."""

from __future__ import annotations

import base64
import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.conditioning.controlnet import CONTRACT, UNIT_CONTRACT, FrozenControlNet, parse_units
from src.conditioning.openpose import OpenPoseDeclarationError
from src.conditioning.openpose_snapshot import verify_frozen
from src.image_backends import forge_controlnet_units as adapter
from src.image_backends import model_policy
from src.image_backends.forge_controlnet import ControlNetCatalog, OpenPoseDispatchError
from src.pipeline.njr_core_v26 import thaw_json
from src.pipeline.replay_input_verification import frozen_input_checks, verify_inputs
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.queue.job_model import JobStatus
from tests.conditioning.openpose_fixtures_210 import write_controlnet_weights
from tests.helpers.fake_webui_transport import FakeWebUITransport
from tests.integration.test_pr_img_cnet_210_canonical_path import _run
from tests.pipeline.test_openpose_compile_210 import (
    POSE_A,
    POSE_B,
    SDXL,
    Harness,
    _slot,
    family_lookup,
)

MODELS = ("xinsir_openpose_sdxl", "diffusers_xl_canny_full", "diffusers_xl_depth_full")


def declaration(*modalities: str) -> dict:
    return {
        "contract": CONTRACT,
        "units": [
            {
                **(POSE_A if index == 0 else POSE_B),
                "contract": UNIT_CONTRACT,
                "modality": modality,
                "model": MODELS[("openpose", "canny", "depth").index(modality)],
            }
            for index, modality in enumerate(modalities)
        ],
    }


@pytest.fixture
def harness(tmp_path, monkeypatch):
    # Application readiness may inspect optional SVD while an image job is submitted.
    # Keep that incidental capability check entirely on CPU, even on a GPU host.
    try:
        import torch
    except ImportError:
        pass
    else:
        monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
        monkeypatch.setattr(torch.cuda, "device_count", lambda: 0)
    result = Harness(tmp_path)
    monkeypatch.setenv("STABLENEW_WEBUI_ROOT", str(tmp_path / "webui"))
    monkeypatch.setattr(
        "src.image_backends.image_backend_types.configured_image_backend_id", lambda: "forge_webui"
    )
    # The persisted registry lookup is deterministic; no real checkpoint or runtime is opened.
    monkeypatch.setattr(
        adapter,
        "resolve_model_policy",
        lambda model: model_policy.resolve_model_policy(model, family_lookup=family_lookup),
    )
    for model in MODELS:
        write_controlnet_weights(
            tmp_path / "webui" / "models" / "ControlNet" / f"{model}.safetensors"
        )
    return result


def build(harness, raw=None):
    return harness.build(
        [
            _slot(
                0, "a structural portrait", controlnet_units=raw or declaration("openpose", "depth")
            )
        ]
    )[0]


def transport(**options):
    return FakeWebUITransport(
        flavor="forge",
        checkpoint=SDXL,
        controlnet_models=options.pop("models", list(MODELS)),
        controlnet_modules=options.pop("modules", ["None"]),
        append_controlnet_detect_maps=True,
        **options,
    )


@pytest.mark.parametrize(
    "modalities", [("openpose", "depth"), ("canny", "depth"), ("depth", "openpose"), ("canny",)]
)
def test_ordered_units_through_canonical_queue(harness, tmp_path, modalities):
    njr = build(harness, declaration(*modalities))
    original = thaw_json(njr.config["controlnet_units"])
    frozen = FrozenControlNet.from_config(njr.config["controlnet_units"])
    wire = transport(ignore_controlnet_save_detected_map=True)
    entry = _run(njr, wire, tmp_path)
    assert entry.status is JobStatus.COMPLETED, entry.error_message
    args = wire.payloads["/sdapi/v1/txt2img"][0]["alwayson_scripts"]["ControlNet"]["args"]
    assert len(args) == len(modalities)
    for unit, sent, modality in zip(frozen.units, args, modalities, strict=True):
        assert unit.modality == modality
        assert sent["model"] == unit.image.model
        assert sent["weight"] == unit.image.weight
        assert sent["guidance_end"] == unit.image.guidance_end
        assert base64.b64decode(sent["image"]) == verify_frozen(unit.image)
    assert thaw_json(njr.config["controlnet_units"]) == original
    assert njr.job_id == entry.job_id
    result = json.dumps(entry.result, default=str)
    for unit in frozen.units:
        assert base64.b64encode(verify_frozen(unit.image)).decode() not in result
    variant = entry.result["variants"][0]
    assert variant["controlnet_units"]["control_images_discarded"] == len(modalities)
    assert [
        item["modality"]
        for item in variant["image_backend_metadata"]["controlnet_conditioning"]["units"]
    ] == list(modalities)
    for artifact in (tmp_path / "run").rglob("*.json"):
        assert '"image": "iVBOR' not in artifact.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "change",
    [
        "model_missing",
        "ambiguous",
        "module_missing",
        "architecture",
        "unknown_architecture",
        "modality",
        "snapshot",
        "unknown_checkpoint",
        "backend",
        "profile",
    ],
)
def test_one_bad_unit_refuses_the_whole_job_before_generation(
    harness, tmp_path, monkeypatch, change
):
    njr = build(harness)
    wire = transport()
    raw = thaw_json(njr.config)
    if change == "model_missing":
        wire.controlnet_models = [MODELS[0]]
    elif change == "ambiguous":
        wire.controlnet_models = [MODELS[0], f"{MODELS[2]} [1111]", f"sub/{MODELS[2]} [2222]"]
    elif change == "module_missing":
        wire.controlnet_modules = ["canny"]
    elif change in {"architecture", "unknown_architecture"}:
        write_controlnet_weights(
            tmp_path / "webui" / "models" / "ControlNet" / f"{MODELS[2]}.safetensors",
            "sd15" if change == "architecture" else "unknown",
        )
    elif change == "modality":
        raw["controlnet_units"]["units"][1]["model"] = MODELS[1]
        njr = replace(njr, workload=replace(njr.workload, config=raw))
    elif change == "snapshot":
        frozen = FrozenControlNet.from_config(raw["controlnet_units"])
        Path(frozen.units[1].image.snapshot_path).write_bytes(b"changed")
    elif change == "unknown_checkpoint":
        monkeypatch.setattr(
            adapter,
            "resolve_model_policy",
            lambda model: model_policy.resolve_model_policy(
                "unknown", family_lookup=lambda _: None
            ),
        )
    elif change == "backend":
        njr = replace(
            njr,
            workload=replace(
                njr.workload, backend_options={"image": {"backend_id": "a1111_webui"}}
            ),
        )
    elif change == "profile":
        from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1

        njr = replace(
            njr,
            workload=replace(
                njr.workload,
                backend_options={
                    "image": {
                        "backend_id": "forge_webui",
                        "model_profile": {
                            "id": ZIMAGE_PROFILE_V1.profile_id,
                            "version": ZIMAGE_PROFILE_V1.version,
                        },
                    }
                },
            ),
        )
    entry = _run(njr, wire, tmp_path)
    assert entry.status is JobStatus.FAILED
    assert not wire.generation_calls


def test_replay_preserves_ordered_frozen_inputs_and_checks_every_digest(harness, tmp_path):
    njr = build(harness, declaration("canny", "depth"))
    replay = compile_replay_intent(ReplayIntent(njr), id_fn=lambda: "replay-220")
    assert replay.job_id != njr.job_id
    assert replay.source.parent_job_id == njr.job_id
    assert thaw_json(replay.config["controlnet_units"]) == thaw_json(njr.config["controlnet_units"])
    assert not verify_inputs(frozen_input_checks(replay))
    frozen = FrozenControlNet.from_config(replay.config["controlnet_units"])
    for unit in frozen.units:
        (harness.library / unit.image.asset).write_bytes(b"library changed")
    assert not verify_inputs(frozen_input_checks(replay))
    entry = _run(replay, transport(), tmp_path)
    assert entry.status is JobStatus.COMPLETED, entry.error_message
    Path(frozen.units[1].image.snapshot_path).write_bytes(b"wrong")
    assert any(
        "ControlNet unit 2" in issue.label for issue in verify_inputs(frozen_input_checks(replay))
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw["units"].append(copy.deepcopy(raw["units"][0])),
        lambda raw: raw["units"][0].update(modality="tile"),
        lambda raw: raw["units"][0].update(preprocessor="canny"),
        lambda raw: raw["units"][0].update(guidance_start=1.0),
        lambda raw: raw["units"][0].update(weight=float("nan")),
        lambda raw: raw["units"][0].update(asset="../escape.png"),
    ],
)
def test_invalid_new_declarations_are_refused_before_any_njr(harness, mutate):
    raw = declaration("canny", "depth")
    mutate(raw)
    with pytest.raises((ValueError, OpenPoseDeclarationError)):
        build(harness, raw)


def test_wire_conflict_and_admission_cannot_be_partial_or_reused_for_another_record(
    harness, tmp_path
):
    frozen = FrozenControlNet.from_config(build(harness).config["controlnet_units"])
    root = tmp_path / "webui" / "models" / "ControlNet"
    admission = adapter.admit_units(
        frozen, ControlNetCatalog(MODELS, ("None",)), controlnet_root=root
    )
    config = {
        "controlnet_units": frozen.to_config(),
        adapter.RUNTIME_KEY: {"models": admission.models, "record": admission.record},
    }
    payload = {"alwayson_scripts": {"ADetailer": {"args": [True]}}}
    result, _ = adapter.apply_wire_units(config, payload)
    assert result["alwayson_scripts"]["ADetailer"] == payload["alwayson_scripts"]["ADetailer"]
    assert set(payload["alwayson_scripts"]) == {"ADetailer"}
    with pytest.raises(OpenPoseDispatchError, match="already carries"):
        adapter.apply_wire_units(
            config, {"alwayson_scripts": {" controlnet ": {"args": ["independent"]}}}
        )
    changed = copy.deepcopy(config)
    changed["controlnet_units"]["units"].reverse()
    with pytest.raises(OpenPoseDispatchError, match="matching complete"):
        adapter.apply_wire_units(changed, {})
    config[adapter.RUNTIME_KEY]["models"] = admission.models[:1]
    with pytest.raises(OpenPoseDispatchError, match="incomplete"):
        adapter.apply_wire_units(config, {})


def test_disabled_units_and_legacy_conflicts(harness):
    raw = declaration("canny", "depth")
    raw["units"][0]["enabled"] = False
    njr = build(harness, raw)
    assert [
        unit.modality for unit in FrozenControlNet.from_config(njr.config["controlnet_units"]).units
    ] == ["depth"]
    raw["units"][1]["enabled"] = False
    assert "controlnet_units" not in build(harness, raw).config
    with pytest.raises(ValueError, match="either legacy"):
        harness.build(
            [
                _slot(
                    0, "a person", controlnet_units=declaration("canny"), controlnet_openpose=POSE_A
                )
            ]
        )
    assert parse_units(declaration("canny"))[0].modality == "canny"


def test_preview_to_queue_submits_the_same_frozen_multi_unit_njr(harness):
    from tests.controller.test_pipeline_preview_to_queue_v2 import _controller

    preview = build(harness)
    original = thaw_json(preview.config)
    controller = _controller()
    controller.get_preview_jobs = lambda: [preview]
    # Changing sources after Preview cannot trigger recompile or alter submitted conditioning.
    for unit in FrozenControlNet.from_config(preview.config["controlnet_units"]).units:
        (harness.library / unit.image.asset).write_bytes(b"source changed after Preview")
    assert controller.submit_preview_jobs_to_queue() == 1
    assert controller._job_service.submitted[0] is preview
    assert thaw_json(controller._job_service.submitted[0].config) == original


@pytest.mark.parametrize(
    "model", ["mystery.safetensors", "sd15_model.safetensors", "flux-2-klein-4b-fp8.safetensors"]
)
def test_compile_refuses_unknown_other_family_and_exact_profiles(harness, model):
    with pytest.raises(ValueError):
        harness.build([_slot(0, "a portrait", controlnet_units=declaration("canny"))], model=model)


def test_second_source_missing_aborts_build_and_a_new_build_reads_sources_again(harness):
    preview = build(harness)
    frozen = FrozenControlNet.from_config(preview.config["controlnet_units"])
    (harness.library / frozen.units[1].image.asset).unlink()
    with pytest.raises(ValueError, match="ControlNet unit 2.*not in the library"):
        build(harness)
    assert verify_frozen(frozen.units[1].image)
