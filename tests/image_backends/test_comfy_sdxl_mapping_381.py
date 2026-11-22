"""PR-IMG-COMFY-381: the pure Forge->ComfyUI vocabulary maps, SDXL admission/plan and the frozen ``sdxl_t2i`` graph."""

from __future__ import annotations

import random
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily
from src.image_backends.comfy_image_graphs import (
    SAVE_NODE_ID,
    SDXL_T2I,
    ComfyImageGraphError,
    SdxlGraphSlots,
)
from src.image_backends.comfy_image_readiness import probe_sdxl_graph
from src.image_backends.comfy_sdxl_mapping import (
    ComfySdxlMappingError,
    map_sampling,
    translate_prompt,
)
from src.image_backends.comfy_sdxl_profile import (
    SdxlComfyError,
    resolve_sdxl_comfy_plan,
    validate_sdxl_comfy_njr,
)
from tests.helpers.comfy_image_fakes import sdxl_object_info

SDXL_LOOKUP = Mock(
    return_value=CompatibilityProfile(CompatibilityStatus.RESOLVED, ModelFamily.SDXL, ())
)
SD15_LOOKUP = Mock(
    return_value=CompatibilityProfile(CompatibilityStatus.RESOLVED, ModelFamily.SD1, ())
)


# -- sampler / scheduler ------------------------------------------------------------------------------------------------


def test_sampler_and_scheduler_map_to_comfy_ids_and_record_the_approximations() -> None:
    mapped = map_sampling("Euler a", "Karras")
    assert (mapped.sampler, mapped.scheduler) == ("euler_ancestral", "karras")
    assert any("euler_ancestral" in item for item in mapped.approximations)


def test_automatic_scheduler_is_the_explicit_closest_value_and_is_recorded() -> None:
    mapped = map_sampling("DPM++ 2M", "Automatic")
    assert (mapped.sampler, mapped.scheduler) == ("dpmpp_2m", "normal")
    assert any("Automatic" in item for item in mapped.approximations)


def test_a1111_combined_sampler_names_carry_their_scheduler_and_conflicts_are_refused() -> None:
    assert map_sampling("DPM++ 2M Karras", "Automatic").scheduler == "karras"
    assert map_sampling("DPM++ 2M Karras", "Karras").scheduler == "karras"
    with pytest.raises(ComfySdxlMappingError, match="conflicts"):
        map_sampling("DPM++ 2M Karras", "Beta")


@pytest.mark.parametrize(
    ("sampler", "scheduler", "named"),
    [("Mystery", "Karras", "Mystery"), ("Euler", "Weird", "Weird")],
)
def test_an_unmapped_name_is_refused_with_the_name_in_the_message(
    sampler, scheduler, named
) -> None:
    with pytest.raises(ComfySdxlMappingError, match=named):
        map_sampling(sampler, scheduler)


# -- prompt -------------------------------------------------------------------------------------------------------------


def test_lora_tags_are_extracted_with_their_weights_and_removed_from_the_text() -> None:
    result = translate_prompt("a castle, <lora:detail:0.7>, mist <lora:Style Pack> (gold:1.2)")
    assert [(item.name, item.weight) for item in result.loras] == [
        ("detail", 0.7),
        ("Style Pack", 1.0),
    ]
    assert result.text == "a castle, mist (gold:1.2)"


def test_embeddings_become_comfy_embedding_names_by_tag_and_by_bare_name() -> None:
    result = translate_prompt(
        "portrait <embedding:easynegative> badhands", embedding_names=["badhands"]
    )
    assert result.text == "portrait embedding:easynegative embedding:badhands"
    assert result.embeddings == ("easynegative", "badhands")


@pytest.mark.parametrize(
    "text",
    [
        "a [cat:dog:0.5] sitting",
        "a [cat|dog] sitting",
        "a [cat] sitting",
        "one BREAK two",
        "red AND blue",
    ],
)
def test_a1111_only_syntax_is_refused(text: str) -> None:
    with pytest.raises(ComfySdxlMappingError, match="A1111-only syntax"):
        translate_prompt(text)


def test_other_angle_tags_are_refused_and_emphasis_passes_through() -> None:
    with pytest.raises(ComfySdxlMappingError, match="hypernet"):
        translate_prompt("a cat <hypernet:x:1>")
    assert translate_prompt("a (red:1.3) cat, (blue)").text == "a (red:1.3) cat, (blue)"


# -- admission and plan -------------------------------------------------------------------------------------------------


def _plan(**changes):
    values = {
        "model_name": "juggernaut.safetensors", "stage_config": {"clip_skip": 2}, "execution_config": {},
        "prompt": "a castle <lora:detail:0.8>", "negative_prompt": "blurry", "sampler": "Euler a", "scheduler": "Karras",
        "steps": 24, "cfg_scale": 6.5, "width": 1024, "height": 1024, "seed": 7, "family_lookup": SDXL_LOOKUP,
    }  # fmt: skip
    values.update(changes)
    return resolve_sdxl_comfy_plan(**values)


def test_the_plan_resolves_every_typed_value() -> None:
    plan = _plan()
    assert (plan.steps, plan.cfg_scale, plan.clip_skip, plan.seed, plan.requested_seed) == (
        24,
        6.5,
        2,
        7,
        7,
    )
    assert (plan.sampling.sampler, plan.sampling.scheduler) == ("euler_ancestral", "karras")
    assert plan.positive == "a castle" and plan.negative == "blurry"
    assert [(item.name, item.weight) for item in plan.loras] == [("detail", 0.8)]
    assert plan.vae == ""


def test_a_missing_seed_is_drawn_once_and_recorded() -> None:
    plan = _plan(seed=-1, rng=random.Random(3))
    assert plan.requested_seed == -1 and 0 <= plan.seed < 2**32
    assert plan.seed == _plan(seed=None, rng=random.Random(3)).seed


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"model_name": "sd15.safetensors", "family_lookup": SD15_LOOKUP},
            "switch the Image backend to Forge",
        ),
        (
            {"model_name": "unknown.safetensors", "family_lookup": Mock(return_value=None)},
            "not a registry-classified",
        ),
        ({"stage_config": {"enable_hr": True}}, "enable_hr is unsupported"),
        ({"stage_config": {"adetailer": {"enabled": True}}}, "adetailer is unsupported"),
        ({"execution_config": {"controlnet_units": [{"x": 1}]}}, "ControlNet is unsupported"),
        ({"images": 2}, "one image per job"),
        ({"width": 1020}, "multiple of 8"),
        ({"steps": 0}, "steps"),
        ({"sampler": "Mystery"}, "Mystery"),
        ({"prompt": "a [b:c:2]"}, "A1111-only syntax"),
        ({"negative_prompt": "bad <lora:x:1>"}, "LoRA tags belong in the positive prompt"),
    ],
)
def test_unsupported_work_is_refused_with_actionable_text(changes, message) -> None:
    with pytest.raises(SdxlComfyError, match=message):
        _plan(**changes)


def _njr(**changes):
    values = {
        "backend_options": {"image": {"backend_id": "comfyui"}}, "base_model": "juggernaut.safetensors", "config": {"txt2img": {}},
        "stage_chain": [SimpleNamespace(stage_type="txt2img", enabled=True)], "positive_prompt": "a castle", "negative_prompt": "",
        "input_image_paths": (), "images_per_prompt": 1, "sampler_name": "Euler", "scheduler": "Automatic",
    }  # fmt: skip
    values.update(changes)
    return SimpleNamespace(**values)


def test_njr_admission_is_a_noop_off_comfy_and_refuses_extra_stages_on_comfy() -> None:
    validate_sdxl_comfy_njr(
        _njr(backend_options={"image": {"backend_id": "forge_webui"}}), family_lookup=SD15_LOOKUP
    )
    validate_sdxl_comfy_njr(_njr(), family_lookup=SDXL_LOOKUP)
    chain = [SimpleNamespace(stage_type=name, enabled=True) for name in ("txt2img", "adetailer")]
    with pytest.raises(SdxlComfyError, match="supports only txt2img"):
        validate_sdxl_comfy_njr(_njr(stage_chain=chain), family_lookup=SDXL_LOOKUP)
    with pytest.raises(SdxlComfyError, match="enable_hr"):
        validate_sdxl_comfy_njr(
            _njr(config={"txt2img": {"enable_hr": True}}), family_lookup=SDXL_LOOKUP
        )


# -- the frozen graph ---------------------------------------------------------------------------------------------------


def _slots(**changes) -> SdxlGraphSlots:
    values = {
        "checkpoint": "juggernaut.safetensors", "positive": "a castle", "negative": "blurry", "seed": 7, "steps": 20, "cfg": 6.0,
        "sampler": "euler", "scheduler": "normal", "width": 1024, "height": 1024, "clip_skip": 2,
        "loras": (("detail.safetensors", 0.8),), "vae": "sdxl_vae.safetensors", "filename_prefix": "stablenew/j/t",
    }  # fmt: skip
    values.update(changes)
    return SdxlGraphSlots(**values)


def test_the_graph_template_is_pinned_and_covers_every_node_class() -> None:
    assert SDXL_T2I.required_node_classes == (
        "CLIPSetLastLayer", "CLIPTextEncode", "CheckpointLoaderSimple", "EmptyLatentImage", "KSampler",
        "LoraLoader", "SaveImage", "VAEDecode", "VAELoader",
    )  # fmt: skip
    assert SDXL_T2I.reference()["graph_id"] == "sdxl_t2i"
    assert (
        SDXL_T2I.template_sha256 == SDXL_T2I.template_sha256 and len(SDXL_T2I.template_sha256) == 64
    )


def test_the_graph_wires_loras_clip_skip_and_the_optional_vae() -> None:
    graph = SDXL_T2I.build(_slots(loras=(("a.safetensors", 0.5), ("b.safetensors", 1.0))))
    assert graph["20"]["inputs"]["model"] == ["1", 0] and graph["21"]["inputs"]["model"] == [
        "20",
        0,
    ]
    assert graph["3"]["inputs"] == {"clip": ["21", 1], "stop_at_clip_layer": -2}
    assert graph["7"]["inputs"]["model"] == ["21", 0]
    assert graph["8"]["inputs"]["vae"] == ["30", 0]
    assert graph[SAVE_NODE_ID]["class_type"] == "SaveImage"
    plain = SDXL_T2I.build(_slots(loras=(), vae=""))
    assert "20" not in plain and "30" not in plain
    assert plain["7"]["inputs"]["model"] == ["1", 0] and plain["8"]["inputs"]["vae"] == ["1", 2]


@pytest.mark.parametrize(
    "changes",
    [{"positive": " "}, {"seed": -1}, {"filename_prefix": "../x"}, {"filename_prefix": "/abs"}],
)
def test_the_graph_refuses_values_outside_its_typed_slots(changes) -> None:
    with pytest.raises(ComfyImageGraphError):
        SDXL_T2I.build(_slots(**changes))


def test_a_built_graph_validates_against_object_info_and_unlisted_files_are_reported() -> None:
    graph = SDXL_T2I.build(_slots())
    assert probe_sdxl_graph(graph, SDXL_T2I.required_node_classes, sdxl_object_info()) == ()
    problems = probe_sdxl_graph(
        graph,
        SDXL_T2I.required_node_classes,
        sdxl_object_info(checkpoints=["other.safetensors"], loras=[]),
    )
    assert any("juggernaut.safetensors" in item for item in problems) and any(
        "detail.safetensors" in item for item in problems
    )
    assert probe_sdxl_graph(
        graph, SDXL_T2I.required_node_classes, sdxl_object_info(missing_class="LoraLoader")
    )[0].startswith("ComfyUI has no 'LoraLoader'")
    slow = SDXL_T2I.build(_slots(sampler="dpmpp_3m_sde"))
    assert any(
        "dpmpp_3m_sde" in item
        for item in probe_sdxl_graph(slow, SDXL_T2I.required_node_classes, sdxl_object_info())
    )
