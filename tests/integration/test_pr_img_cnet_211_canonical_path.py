"""Canonical queue-first response classification, no real transport/runtime/GPU."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.queue.job_model import JobStatus
from tests.conditioning.openpose_fixtures_210 import write_controlnet_weights
from tests.helpers.fake_webui_transport import FakeResponse
from tests.integration.test_pr_img_cnet_210_canonical_path import (
    _forge_configured,  # noqa: F401 - pytest fixture
    _run,
    _transport,
    _unit,
    _variants,
)
from tests.integration.test_pr_img_cnet_210_canonical_path import (
    webui as source_webui,
)
from tests.pipeline.test_openpose_compile_210 import POSE_A, POSE_DISABLED, _slot


@pytest.fixture
def webui(tmp_path, monkeypatch):
    return source_webui.__wrapped__(tmp_path, monkeypatch)


def test_explicit_map_suppression_and_frozen_intent_survive_real_queue_execution(
    webui, tmp_path
) -> None:
    njr = webui.build([_slot(0, "a person", controlnet_openpose=POSE_A)])[0]
    frozen = copy.deepcopy(njr.config["controlnet_openpose"])
    transport = _transport(detect_maps=True)
    entry = _run(njr, transport, tmp_path)
    assert entry.status is JobStatus.COMPLETED, entry.error_message
    assert _unit(transport)["save_detected_map"] is False
    assert njr.config["controlnet_openpose"] == frozen
    facts = _variants(entry)[0]["controlnet_openpose"]
    assert facts["received_images"] == facts["generated_images"] == 1
    assert facts["control_images_discarded"] == 0 and facts["save_detected_map"] is False
    assert facts["input_diagnostics"]["width"] == frozen["image"]["width"]


def test_multi_image_generation_uses_every_seed_and_never_saves_the_grid(webui, tmp_path) -> None:
    njr = webui.build([_slot(0, "a person", controlnet_openpose=POSE_A)])[0]
    # The existing WebUI family adapter renders image_count as batch_size=1, n_iter=image_count.
    njr = replace(njr, workload=replace(njr.workload, images_per_prompt=4))
    transport = _transport()
    post = transport._post

    def with_grid(path, body):
        response = post(path, body)
        if path == "/sdapi/v1/txt2img":
            raw = response.json()
            info = json.loads(raw["info"])
            info["index_of_first_image"] = 1
            info["infotexts"].insert(0, "grid")
            raw["images"].insert(0, raw["images"][0])
            raw["info"] = json.dumps(info)
            return FakeResponse(raw)
        return response

    transport._post = with_grid
    entry = _run(njr, transport, tmp_path)
    assert entry.status is JobStatus.COMPLETED, entry.error_message
    request = transport.payloads["/sdapi/v1/txt2img"][0]
    assert request["batch_size"] * request["n_iter"] == 4
    variants = _variants(entry)
    # Canonical history has one stage aggregate; each generated image has its own artifact/manifest.
    assert len(variants) == 1 and len(variants[0]["all_paths"]) == 4
    manifests = [json.loads((Path(path).parent / "manifests" / f"{Path(path).stem}.json").read_text())
                 for path in variants[0]["all_paths"]]
    assert [manifest["actual_seed"] for manifest in manifests] == [transport.seed + i for i in range(4)]
    assert all(manifest["returned_images"] == manifest["saved_images"] == 4 for manifest in manifests)
    assert all(v["controlnet_openpose"]["grids_discarded"] == 1 for v in variants)


@pytest.mark.parametrize(
    "case,code",
    [
        ("pose_only", "pose_in_generation_slot"),
        ("unknown_extra", "unexpected_images"),
        ("no_info", "ambiguous_metadata"),
        ("missing", "missing_generations"),
    ],
)
def test_response_refusal_saves_no_result_and_does_not_replay(webui, tmp_path, case, code) -> None:
    njr = webui.build([_slot(0, "a person", controlnet_openpose=POSE_A)])[0]
    transport = _transport()
    post = transport._post

    def bad_response(path, body):
        response = post(path, body)
        if path == "/sdapi/v1/txt2img":
            raw = response.json()
            if case == "pose_only":
                raw["images"] = [body["alwayson_scripts"]["ControlNet"]["args"][0]["image"]]
            elif case == "unknown_extra":
                raw["images"].append(raw["images"][0])
            elif case == "no_info":
                raw["info"] = ""
            elif case == "missing":
                raw["images"] = []
            return FakeResponse(raw)
        return response

    transport._post = bad_response
    entry = _run(njr, transport, tmp_path)
    assert entry.status is JobStatus.FAILED and code in entry.error_message
    assert len(transport.generation_calls) == 1
    assert list((tmp_path / "run").rglob("*.png")) == []


@pytest.mark.parametrize("model", ["diffusers_xl_depth_full", "ttplanetSDXLControlnet_v20Fp16"])
def test_known_incompatible_sdxl_weights_are_refused_without_silently_changing_intent(
    webui, tmp_path, model
) -> None:
    pose = {**POSE_A, "model": model}
    njr = webui.build([_slot(0, "a person", controlnet_openpose=pose)])[0]
    frozen = copy.deepcopy(njr.config["controlnet_openpose"])
    write_controlnet_weights(
        tmp_path / "webui" / "models" / "ControlNet" / f"{model}.safetensors", "sdxl"
    )
    transport = _transport(models=[model])
    entry = _run(njr, transport, tmp_path)
    assert entry.status is JobStatus.FAILED and "not an OpenPose model" in entry.error_message
    assert transport.generation_calls == [] and njr.config["controlnet_openpose"] == frozen


def test_disabled_incompatible_selection_is_not_conditioned_or_reclassified(
    webui, tmp_path
) -> None:
    pose = {**POSE_DISABLED, "model": "diffusers_xl_depth_full"}
    njr = webui.build([_slot(0, "ordinary portrait", controlnet_openpose=pose)])[0]
    transport = _transport()
    entry = _run(njr, transport, tmp_path)
    assert entry.status is JobStatus.COMPLETED
    assert "alwayson_scripts" not in transport.payloads["/sdapi/v1/txt2img"][0]
    assert "controlnet_openpose" not in json.dumps(_variants(entry)[0])
