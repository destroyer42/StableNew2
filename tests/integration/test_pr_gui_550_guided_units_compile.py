"""PR-GUI-UX-550: units authored with the guided defaults reach the existing compiler unchanged (fakes only)."""

from __future__ import annotations

import json

import pytest

from src.conditioning.controlnet import CONTRACT, FrozenControlNet
from src.conditioning.openpose_snapshot import verify_frozen
from src.gui_v2.controlnet_guidance import new_unit
from src.pipeline.njr_core_v26 import thaw_json
from tests.integration import test_pr_img_cnet_220 as cnet_220
from tests.pipeline.test_openpose_compile_210 import _slot

harness = (
    cnet_220.harness
)  # the shared deterministic fixture (library, weights, fake policy lookup)
build = cnet_220.build


def _authored() -> dict:
    return {
        "contract": CONTRACT,
        "units": [
            new_unit("depth", asset="Walking/forward.png", model="diffusers_xl_depth_full"),
            {
                **new_unit("openpose", asset="Standing/relaxed.png", model="xinsir_openpose_sdxl"),
                "weight": 0.8,
            },
        ],
    }


def test_guided_units_freeze_in_authored_order_with_independent_settings_and_no_image_bytes(
    harness,
):
    raw = _authored()
    njr = build(harness, raw)
    frozen = FrozenControlNet.from_config(njr.config["controlnet_units"])
    assert [unit.modality for unit in frozen.units] == ["depth", "openpose"]
    assert [unit.image.weight for unit in frozen.units] == [1.0, 0.8]
    assert [unit.image.asset for unit in frozen.units] == [
        "Walking/forward.png",
        "Standing/relaxed.png",
    ]
    assert (
        len({unit.image.asset_sha256 for unit in frozen.units}) == 2
    )  # each reference is frozen on its own
    config_text = json.dumps(thaw_json(njr.config), default=str)
    for unit in frozen.units:
        assert verify_frozen(unit.image)[:4] == b"\x89PNG"
        assert "iVBOR" not in config_text  # base64 PNG header: no bytes in the NJR
    assert raw == _authored()  # compiling never edits the authored declaration


def test_a_disabled_guided_unit_is_kept_by_the_pack_but_not_frozen(harness):
    raw = _authored()
    raw["units"][0]["enabled"] = False
    njr = build(harness, raw)
    assert [
        u.modality for u in FrozenControlNet.from_config(njr.config["controlnet_units"]).units
    ] == ["openpose"]
    assert raw["units"][0]["enabled"] is False and raw["units"][0]["asset"] == "Walking/forward.png"


@pytest.mark.parametrize("broken", ["", "Gone/vanished.png"])
def test_a_unit_awaiting_or_missing_its_map_refuses_the_whole_job(harness, broken):
    raw = _authored()
    raw["units"][1]["asset"] = broken
    with pytest.raises(ValueError):
        harness.build([_slot(0, "a portrait", controlnet_units=raw)])
