"""PR-IMG-CNET-230: a created map is an ordinary library map once saved - same compile, same NJR, same refusals.

Real service, library and PromptPack compiler over fakes (no Forge, GPU, model or network).
"""

from __future__ import annotations

import copy
import io
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from src.assets import AssetRegistry
from src.conditioning.controlnet import CONTRACT, UNIT_CONTRACT, FrozenControlNet
from src.conditioning.openpose_snapshot import verify_frozen
from src.conditioning.reference_map.contracts import MapRequest
from src.pipeline.njr_core_v26 import thaw_json
from src.pipeline.replay_input_verification import frozen_input_checks, verify_inputs
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.queue.job_model import JobStatus
from tests.conditioning.reference_map_fixtures_230 import pure_service
from tests.integration import test_pr_img_cnet_220 as base
from tests.integration.test_pr_img_cnet_210_canonical_path import _run
from tests.integration.test_pr_img_cnet_220 import MODELS, build, transport
from tests.pipeline.test_openpose_compile_210 import _slot

JOBS = {"openpose": MODELS[0], "canny": MODELS[1], "depth": MODELS[2]}


def _source(path: Path, width: int, height: int, seed: int) -> Path:
    rng = np.random.default_rng(seed)
    array = rng.integers(0, 255, size=(height, width, 3), dtype=np.uint8)
    array[8:40, 8:40] = 255
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="PNG")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buffer.getvalue())
    return path


@pytest.fixture
def harness(tmp_path, monkeypatch):
    return base.harness.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture
def created(harness, tmp_path):
    """Two real Canny maps saved into the harness library through the service (the production publication path)."""

    registry = AssetRegistry(tmp_path / "webui", cache_path=tmp_path / "state" / "registry.json")
    service = pure_service(registry)
    maps = []
    for index, size in enumerate(((128, 96), (160, 120))):
        prepared = service.prepare(
            MapRequest(_source(tmp_path / "src" / f"s{index}.png", *size, index), "canny")
        )
        maps.append((prepared, service.save(prepared)))
    return maps


def _units(created, *modalities: str) -> dict:
    """A declaration whose units reference the created maps (the map is attached explicitly, as the UI does)."""

    units = []
    for index, modality in enumerate(modalities):
        _, saved = created[index]
        units.append(
            {
                "contract": UNIT_CONTRACT,
                "modality": modality,
                "enabled": True,
                "asset": saved.identity,
                "model": JOBS[modality],
                "weight": 1.0 if index == 0 else 0.6,
                "guidance_start": 0.0,
                "guidance_end": 1.0 if index == 0 else 0.8,
                "control_mode": "Balanced",
                "resize_mode": "Resize and Fill",
                "preprocessor": "None",
            }
        )
    return {"contract": CONTRACT, "units": units}


def test_a_created_map_compiles_to_the_same_njr_as_the_identical_hand_supplied_map(
    harness, created
):
    prepared, saved = created[0]
    njr = build(harness, _units(created, "canny"))
    frozen = FrozenControlNet.from_config(njr.config["controlnet_units"])
    unit = frozen.units[0].image
    assert unit.asset == saved.identity and unit.asset_sha256 == prepared.sha256
    assert unit.preprocessor == "None" and (unit.width, unit.height) == (
        prepared.width,
        prepared.height,
    )
    assert verify_frozen(unit) == prepared.png
    # the very same bytes supplied by hand compile to an identical record apart from the library name
    manual = harness.library / "Manual" / "same.png"
    manual.parent.mkdir()
    manual.write_bytes(prepared.png)
    declared = _units(created, "canny")
    declared["units"][0]["asset"] = "Manual/same.png"
    by_hand = (
        FrozenControlNet.from_config(build(harness, declared).config["controlnet_units"])
        .units[0]
        .image
    )
    assert replace(by_hand, asset="") == replace(unit, asset="")


def test_replacing_the_library_map_cannot_change_a_compiled_or_replayed_njr(
    harness, created, tmp_path
):
    prepared, saved = created[0]
    njr = build(harness, _units(created, "canny", "depth"))
    before = thaw_json(njr.config)
    folder = tmp_path / "webui" / "models" / "OpenPose"
    for _, item in created:
        (folder / item.identity).write_bytes(b"replaced after compile")
    assert thaw_json(njr.config) == before
    frozen = FrozenControlNet.from_config(njr.config["controlnet_units"])
    assert verify_frozen(frozen.units[0].image) == prepared.png
    replay = compile_replay_intent(ReplayIntent(njr), id_fn=lambda: "replay-230")
    assert thaw_json(replay.config["controlnet_units"]) == before["controlnet_units"]
    assert not verify_inputs(frozen_input_checks(replay))
    entry = _run(replay, transport(), tmp_path)
    assert entry.status is JobStatus.COMPLETED, entry.error_message


def test_multi_unit_order_weights_and_the_two_unit_limit_hold_for_created_maps(harness, created):
    declared = _units(created, "depth", "canny")
    frozen = FrozenControlNet.from_config(build(harness, declared).config["controlnet_units"])
    assert [(u.modality, u.image.weight, u.image.guidance_end) for u in frozen.units] == [
        ("depth", 1.0, 1.0),
        ("canny", 0.6, 0.8),
    ]
    third = copy.deepcopy(declared)
    third["units"].append(copy.deepcopy(third["units"][0]))
    with pytest.raises(ValueError):
        build(harness, third)
    with pytest.raises(ValueError, match="either legacy"):
        from tests.pipeline.test_openpose_compile_210 import POSE_A

        harness.build([_slot(0, "p", controlnet_units=declared, controlnet_openpose=POSE_A)])


@pytest.mark.parametrize(
    "model", ["mystery.safetensors", "sd15_model.safetensors", "flux-2-klein-4b-fp8.safetensors"]
)
def test_non_sdxl_and_unknown_targets_refuse_a_created_map_at_compile(harness, created, model):
    with pytest.raises(ValueError):
        harness.build(
            [_slot(0, "a portrait", controlnet_units=_units(created, "canny"))], model=model
        )


@pytest.mark.parametrize("change", ["a1111", "zimage", "missing_model", "wrong_modality"])
def test_negative_dispatch_targets_fail_before_any_generation_post(
    harness, created, tmp_path, change
):
    njr = build(harness, _units(created, "canny"))
    wire = transport()
    raw = thaw_json(njr.config)
    if change == "a1111":
        njr = replace(
            njr,
            workload=replace(
                njr.workload, backend_options={"image": {"backend_id": "a1111_webui"}}
            ),
        )
    elif change == "zimage":
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
    elif change == "missing_model":
        wire.controlnet_models = [MODELS[0]]  # the canny weight is not installed
    else:
        raw["controlnet_units"]["units"][0]["model"] = MODELS[2]  # a depth weight on a canny unit
        njr = replace(njr, workload=replace(njr.workload, config=raw))
    entry = _run(njr, wire, tmp_path)
    assert entry.status is JobStatus.FAILED
    assert not wire.generation_calls
