"""PR-IMG-COMFY-100: the two frozen Qwen-Image 2.1 profiles, their graphs, compile policy, model policy and routing."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.image_backends.comfy_image_graphs import (
    QWEN_IMAGE_21_T2I,
    QWEN_IMAGE_21_TURBO_SIGMAS,
    QWEN_IMAGE_21_TURBO_T2I,
    SAVE_NODE_ID,
    ComfyImageGraphError,
    graph_for_profile,
)
from src.image_backends.comfy_qwen_image_profile import (
    QWEN_IMAGE_21_PROFILE_V1 as BASE,
)
from src.image_backends.comfy_qwen_image_profile import (
    QWEN_IMAGE_21_TURBO_PROFILE_V1 as TURBO,
)
from src.image_backends.comfy_qwen_image_profile import (
    QWEN_IMAGE_PROFILES,
    QwenImageProfileError,
    apply_qwen_image_compile_policy,
    qwen_image_profile_for_model,
    qwen_image_profile_for_reference,
    resolve_qwen_image_plan,
    validate_qwen_image_config,
    validate_qwen_image_njr,
)
from src.image_backends.exact_model_profile import (
    model_profile_for_model,
    resolve_model_profile,
    validate_profile_intent,
)
from src.image_backends.image_backend_types import (
    COMFY_IMAGE_BACKEND_ID,
    normalize_image_backend_options,
    resolve_image_backend_id,
)
from src.image_backends.model_backend_routing import required_backend_for_model
from src.image_backends.model_policy import (
    FAMILY_QWEN_IMAGE,
    ControlMode,
    apply_model_compile_policy,
    compile_model_policy,
    resolve_model_policy,
)


def test_profiles_pin_the_public_comfy_org_files_and_the_official_template_values() -> None:
    assert COMFY_IMAGE_BACKEND_ID == "comfyui"
    assert {p.profile_id for p in QWEN_IMAGE_PROFILES} == {
        "qwen_image_21_int8_comfy",
        "qwen_image_21_turbo_int8_comfy",
    }
    for profile in QWEN_IMAGE_PROFILES:
        assert (
            profile.backend_id == "comfyui"
            and profile.modes == ("txt2img",)
            and profile.max_images == 1
        )
        assert profile.repo_id == "Comfy-Org/Qwen-Image-2.1"
        assert profile.revision == "aacf31a6d48e707f352ecba714cee0680da3479b"
        assert "non-commercial" in profile.licence
        assert profile.text_encoder.filename == "qwen3vl_8b_int8_convrot.safetensors"
        assert profile.vae.filename == "qwen_image_2.1_vae_bf16.safetensors"
        assert profile.cfg_scale == 1.0 and profile.sampler == "euler"
        for asset in profile.assets:
            assert len(asset.sha256) == 64 and asset.size > 0
        assert all(w % 16 == 0 and h % 16 == 0 for w, h in profile.geometries)
        assert profile.geometries[0] == (1024, 1024)
    assert (
        BASE.diffusion_model.size == 7_256_783_064
        and BASE.steps == 25
        and BASE.scheduler == "simple"
    )
    assert TURBO.diffusion_model.size == 7_256_787_829 and TURBO.steps == 8
    total = sum(a.size for a in BASE.assets) + TURBO.diffusion_model.size
    assert total == 24_539_878_941


def test_model_identity_is_a_whole_name_match_and_references_are_immutable() -> None:
    assert qwen_image_profile_for_model(BASE.model_name) is BASE
    assert qwen_image_profile_for_model("C:/models/" + TURBO.model_name.upper()) is TURBO
    assert (
        qwen_image_profile_for_model("qwen_image_2.1_int8_convrot") is BASE
    )  # the extension is not the identity
    assert qwen_image_profile_for_model("qwen_image_2.1_int8") is None
    for name in (
        "qwen_image_2.1_bf16.safetensors",
        "my_qwen_image_2.1_int8_convrot.safetensors",
        "",
        None,
    ):
        assert qwen_image_profile_for_model(name) is None
    assert qwen_image_profile_for_reference(BASE.reference()) is BASE
    assert qwen_image_profile_for_reference({"id": "other", "version": 1}) is None
    with pytest.raises(QwenImageProfileError, match="only immutable v1"):
        qwen_image_profile_for_reference({"id": BASE.profile_id, "version": 2})
    with pytest.raises(QwenImageProfileError):
        resolve_model_profile(
            {"image": {"model_profile": {"id": TURBO.profile_id, "version": "1"}}}
        )
    assert resolve_model_profile({"image": {"model_profile": TURBO.reference()}}) is TURBO
    assert model_profile_for_model(BASE.model_name) == BASE.reference()


def test_each_profile_has_one_frozen_graph_pinned_by_digest() -> None:
    assert (
        graph_for_profile(BASE) is QWEN_IMAGE_21_T2I
        and graph_for_profile(TURBO) is QWEN_IMAGE_21_TURBO_T2I
    )
    # Pinned: any change to a frozen graph must become a new version.
    assert (
        QWEN_IMAGE_21_T2I.template_sha256
        == "40c06e700e7c2ab9d49fcb45a0bb7514982a5a314d0900e2df3b036e2b025c3d"
    )
    assert QWEN_IMAGE_21_TURBO_T2I.template_sha256 == (
        "06fdb8e7bc5cbcecb9560dbcfffd5f2d2b7f1dcef5d7a4f8840735c96d9abeac"
    )
    assert QWEN_IMAGE_21_T2I.reference() == {
        "graph_id": "qwen_image_21_t2i", "version": "1.0.0", "template_sha256": QWEN_IMAGE_21_T2I.template_sha256,
    }  # fmt: skip


def _links_resolve(graph: dict[str, Any]) -> None:
    for node in graph.values():
        for value in node["inputs"].values():
            if isinstance(value, list):
                assert value[0] in graph, value


def test_base_graph_mirrors_the_official_template_and_substitutes_only_typed_slots() -> None:
    graph = QWEN_IMAGE_21_T2I.build(
        prompt="A red kite", seed=7, width=1200, height=896, filename_prefix="stablenew/j/n"
    )
    _links_resolve(graph)
    assert graph["1"]["inputs"]["unet_name"] == BASE.model_name
    assert graph["3"]["inputs"] == {
        "clip_name": BASE.text_encoder.filename,
        "type": "qwen_image",
        "device": "default",
    }
    assert (
        graph["5"]["inputs"]["prompt"] == "A red kite"
        and graph["5"]["inputs"]["negative_prompt"] == ""
    )
    assert graph["6"]["inputs"] == {"width": 1200, "height": 896, "batch_size": 1}
    sampler = graph["7"]
    assert sampler["class_type"] == "KSampler"
    assert {k: sampler["inputs"][k] for k in ("seed", "steps", "cfg", "sampler_name", "scheduler", "denoise")} == {
        "seed": 7, "steps": 25, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
    }  # fmt: skip
    assert graph[SAVE_NODE_ID] == {
        "class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "stablenew/j/n"},
    }  # fmt: skip


def test_turbo_graph_uses_the_official_eight_step_sigma_chain() -> None:
    graph = QWEN_IMAGE_21_TURBO_T2I.build(
        prompt="x", seed=9, width=1024, height=1024, filename_prefix="p"
    )
    _links_resolve(graph)
    assert graph["1"]["inputs"]["unet_name"] == TURBO.model_name
    assert graph["7"] == {"class_type": "RandomNoise", "inputs": {"noise_seed": 9}}
    assert graph["11"]["inputs"]["sigmas"] == QWEN_IMAGE_21_TURBO_SIGMAS
    assert len(QWEN_IMAGE_21_TURBO_SIGMAS.split(",")) == TURBO.steps + 1
    assert graph["12"]["inputs"]["cfg"] == 1.0
    assert graph["8"]["inputs"]["samples"] == ["13", 0]
    assert "KSampler" not in QWEN_IMAGE_21_TURBO_T2I.required_node_classes


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"prompt": "  "}, "non-empty prompt"),
        ({"seed": -1}, "seed must be resolved"),
        ({"seed": 2**32}, "seed must be resolved"),
        ({"width": 1000}, "not one of the supported sizes"),
        ({"filename_prefix": "../escape"}, "relative name"),
        ({"filename_prefix": "C:/abs"}, "relative name"),
    ],
)
def test_graph_build_refuses_anything_outside_its_typed_slots(
    changes: dict[str, Any], match: str
) -> None:
    values: dict[str, Any] = {
        "prompt": "x",
        "seed": 1,
        "width": 1024,
        "height": 1024,
        "filename_prefix": "p",
    }
    values.update(changes)
    with pytest.raises(ComfyImageGraphError, match=match):
        QWEN_IMAGE_21_T2I.build(**values)


@pytest.mark.parametrize(
    ("config", "fragment"),
    [
        ({"steps": 30}, "steps 30 conflicts"),
        ({"cfg_scale": 4.5}, "cfg_scale"),
        ({"sampler_name": "dpmpp_2m"}, "sampler_name"),
        ({"scheduler": "karras"}, "scheduler"),
        ({"width": 1024, "height": 768}, "size 1024x768"),
        ({"batch_size": 2}, "one image per job"),
        ({"n_iter": 3}, "one image per job"),
        ({"vae": "sdxl_vae.safetensors"}, "vae is unsupported"),
        ({"enable_hr": True}, "enable_hr"),
        ({"adetailer": {"enabled": True}}, "adetailer is unsupported"),
        ({"controlnet_units": [{"model": "x"}]}, "ControlNet"),
        ({"hypernetwork": "h"}, "hypernetwork"),
        ({"stages": ["txt2img", "upscale"]}, "only the txt2img stage"),
        ({"model": "sdxl.safetensors"}, "conflicting model"),
        ({"model": TURBO.model_name}, "conflicting model"),
        ({"seed": -2}, "seed must be"),
    ],
)
def test_config_conflicts_are_refused(config: dict[str, Any], fragment: str) -> None:
    with pytest.raises(QwenImageProfileError, match=fragment):
        validate_qwen_image_config(BASE, config)


def test_negative_prompt_is_refused_and_defaults_pass() -> None:
    with pytest.raises(QwenImageProfileError, match="negative prompt is unsupported"):
        validate_qwen_image_config(BASE, {}, negative="blurry")
    validate_qwen_image_config(
        BASE, {"model": BASE.model_name, "steps": 25, "width": 768, "height": 1376, "seed": -1}
    )
    validate_qwen_image_config(TURBO, {"steps": 8, "scheduler": TURBO.scheduler})


def test_plan_resolves_one_seed_and_refuses_batches() -> None:
    import random

    plan = resolve_qwen_image_plan(BASE, width=None, height=None, seed=-1, rng=random.Random(1))
    assert (plan.width, plan.height, plan.requested_seed) == (
        1024,
        1024,
        -1,
    ) and 0 <= plan.seed < 2**32
    assert resolve_qwen_image_plan(TURBO, width=848, height=1264, seed=42).seed == 42
    with pytest.raises(QwenImageProfileError, match="one image per job"):
        resolve_qwen_image_plan(BASE, width=1024, height=1024, seed=1, images=2)
    with pytest.raises(QwenImageProfileError, match="supported sizes"):
        resolve_qwen_image_plan(BASE, width=512, height=512, seed=1)


def _base_config(model: str = BASE.model_name, **extra: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "model": model,
        "prompt": "A lighthouse at dusk",
        "sampler_name": "DPM++ 2M",
        "scheduler": "Karras",
        "steps": 30,
        "cfg_scale": 6.5,
        "vae": "sdxl_vae.safetensors",
        "negative_prompt": "blurry",
        "global_negative_prompt": "lowres",
        "prompt_optimizer": {"enabled": True},
        "txt2img": {"model": model, "steps": 30, "width": 1264, "height": 848},
    }
    config.update(extra)
    return config


@pytest.mark.parametrize("profile", QWEN_IMAGE_PROFILES)
def test_compile_policy_freezes_the_profile_and_stamps_the_comfy_backend(profile) -> None:
    config = apply_model_compile_policy(_base_config(profile.model_name))
    image = config["backend_options"]["image"]
    assert image == {"backend_id": "comfyui", "model_profile": profile.reference()}
    for section in (config, config["txt2img"]):
        assert section["steps"] == profile.steps and section["cfg_scale"] == 1.0
        assert (
            section["sampler_name"] == profile.sampler and section["scheduler"] == profile.scheduler
        )
    assert (
        config["txt2img"]["width"] == 1264 and config["width"] == 1264
    )  # geometry kept, stage authoritative
    assert (
        config["negative_prompt"] == ""
        and config["global_negative_prompt"] == ""
        and config["vae"] == ""
    )
    assert config["prompt_optimizer"] == {"enabled": False}
    assert (
        compile_model_policy(_base_config(profile.model_name)).project_flat(
            {"model": profile.model_name}
        )["backend_options"]["image"]["backend_id"]
        == "comfyui"
    )


def test_compile_policy_refuses_genuine_conflicts_and_a_frozen_profile_without_its_model() -> None:
    with pytest.raises(QwenImageProfileError, match="size"):
        apply_qwen_image_compile_policy(
            _base_config(txt2img={"model": BASE.model_name, "width": 512, "height": 512})
        )
    with pytest.raises(QwenImageProfileError, match="requires its exact model selection"):
        apply_qwen_image_compile_policy({"model": "sdxl.safetensors",
                                         "backend_options": {"image": {"model_profile": BASE.reference()}}})  # fmt: skip
    with pytest.raises(QwenImageProfileError, match="conflicts with the frozen"):
        apply_qwen_image_compile_policy({"model": TURBO.model_name,
                                         "backend_options": {"image": {"model_profile": BASE.reference()}}})  # fmt: skip
    with pytest.raises(QwenImageProfileError, match="runs only on the 'comfyui'"):
        apply_qwen_image_compile_policy({"model": BASE.model_name,
                                         "backend_options": {"image": {"backend_id": "forge_webui"}}})  # fmt: skip
    untouched = {"model": "sdxl.safetensors", "steps": 30}
    assert apply_qwen_image_compile_policy(dict(untouched)) == untouched


def test_construction_routes_the_model_to_comfy_and_never_rewrites_an_explicit_identity() -> None:
    assert required_backend_for_model(BASE.model_name) == "comfyui"
    assert required_backend_for_model("sdxl.safetensors") is None
    options = normalize_image_backend_options(None, model_name=TURBO.model_name)
    assert (
        resolve_image_backend_id(options) == "comfyui"
        and options["image"]["model_profile"] == TURBO.reference()
    )
    explicit = normalize_image_backend_options(
        {"image": {"backend_id": "forge_webui"}}, model_name=BASE.model_name
    )
    assert (
        explicit["image"]["backend_id"] == "forge_webui"
    )  # a persisted identity is kept; the profile refuses it


@pytest.mark.parametrize("profile", QWEN_IMAGE_PROFILES)
def test_model_policy_projects_a_txt2img_only_comfy_profile(profile) -> None:
    policy = resolve_model_policy(profile.model_name)
    assert policy.family == FAMILY_QWEN_IMAGE and policy.required_backend == "comfyui"
    assert policy.stages == ("txt2img",) and policy.profile_ref == profile.reference()
    for name, value in (
        ("sampler", profile.sampler),
        ("steps", profile.steps),
        ("cfg_scale", 1.0),
        ("vae", ""),
    ):
        assert (
            policy.control(name).mode is ControlMode.FIXED and policy.control(name).value == value
        )
    assert policy.control("geometry").allowed == profile.geometries
    assert not any(
        policy.feature(name).supported
        for name in ("lora", "negative_prompt", "adetailer", "embeddings")
    )
    assert "Not yet physically qualified" in policy.note and "Non-commercial" in policy.note
    assert policy.learning_variables() == ()


def _njr(profile=BASE, **changes: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "base_model": profile.model_name,
        "backend_options": {
            "image": {"backend_id": "comfyui", "model_profile": profile.reference()}
        },
        "stage_chain": [SimpleNamespace(stage_type="txt2img", enabled=True)],
        "config": {"model": profile.model_name, "steps": profile.steps},
        "positive_prompt": "A fox",
        "negative_prompt": "",
        "steps": profile.steps,
        "width": 1024,
        "height": 1024,
        "seed": 3,
        "images_per_prompt": 1,
    }
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"backend_options": {"image": {"backend_id": "forge_webui", "model_profile": BASE.reference()}}}, "frozen v1"),
        ({"backend_options": {"image": {"backend_id": "comfyui"}}}, "frozen v1"),
        ({"base_model": "sdxl.safetensors"}, "frozen v1"),
        ({"stage_chain": [SimpleNamespace(stage_type="txt2img", enabled=True),
                          SimpleNamespace(stage_type="adetailer", enabled=True)]}, "only txt2img"),
        ({"lora_tags": ["x"]}, "no input images, LoRAs"),
        ({"input_image_paths": ["a.png"]}, "no input images"),
        ({"negative_prompt": "ugly"}, "negative prompt"),
        ({"steps": 20}, "steps 20"),
        ({"images_per_prompt": 2}, "one image per job"),
    ],
)  # fmt: skip
def test_njr_admission_refuses_out_of_envelope_records(
    changes: dict[str, Any], fragment: str
) -> None:
    with pytest.raises(QwenImageProfileError, match=fragment):
        validate_qwen_image_njr(_njr(**changes))


def test_njr_admission_is_a_no_op_for_other_models_and_passes_a_frozen_record() -> None:
    validate_qwen_image_njr(SimpleNamespace(base_model="sdxl.safetensors", backend_options={}))
    validate_qwen_image_njr(_njr())
    validate_qwen_image_njr(_njr(TURBO))


def test_profile_intent_validation_matches_the_compiler() -> None:
    intent = {
        "backend_id": "comfyui", "stage_names": ["txt2img"], "model_name": BASE.model_name, "sampler": "euler",
        "scheduler": "simple", "steps": 25, "cfg_scale": 1.0, "width": 1024, "height": 1024, "negative_prompt": "",
    }  # fmt: skip
    assert validate_profile_intent(BASE, **intent) == "txt2img"
    with pytest.raises(QwenImageProfileError, match="only txt2img on the 'comfyui'"):
        validate_profile_intent(BASE, **{**intent, "backend_id": "forge_webui"})
    with pytest.raises(QwenImageProfileError, match="unsupported features"):
        validate_profile_intent(BASE, **intent, unsupported_features=["LoRA"])
    with pytest.raises(QwenImageProfileError, match="steps"):
        validate_profile_intent(BASE, **{**intent, "steps": 8})
