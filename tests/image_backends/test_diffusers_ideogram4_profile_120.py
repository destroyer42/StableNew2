"""PR-IMG-120: the immutable Ideogram 4 profile, its model policy, routing and compile contract (no runtime, no GPU)."""

from __future__ import annotations

import copy
import json
import random
from types import SimpleNamespace

import pytest

from src.image_backends.diffusers_ideogram4_profile import IDEOGRAM4_PROFILE_V1 as P
from src.image_backends.diffusers_ideogram4_profile import (
    Ideogram4ProfileError,
    apply_ideogram4_compile_policy,
    is_ideogram4_model_name,
    resolve_plan,
    validate_ideogram4_njr,
)
from src.image_backends.exact_model_profile import model_profile_for_model, resolve_model_profile
from src.image_backends.forge_klein_profile import KLEIN_PROFILE_V2, KleinProfileError
from src.image_backends.image_backend_types import normalize_image_backend_options
from src.image_backends.model_backend_routing import required_backend_for_model
from src.image_backends.model_policy import (
    FAMILY_IDEOGRAM4,
    ControlMode,
    apply_model_compile_policy,
    resolve_model_policy,
)
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.job_models_v2 import NormalizedJobRecord


def config(**changes):
    return {
        "model": P.model_name,
        "prompt": "A ceramic teapot on a wooden table.",
        "seed": 42,
        "steps": 20,
        "width": 1024,
        "height": 1024,
        "negative_prompt": "",
        "prompt_optimizer": {"enabled": False},
        **changes,
    }


def test_presets_match_the_official_schedules_reversed_for_diffusers() -> None:
    by_steps = {preset.steps: preset for preset in P.presets}
    assert P.allowed_steps == (12, 20, 48) and P.default_steps == 20
    assert (by_steps[12].mu, by_steps[12].std) == (0.5, 1.75)
    assert (by_steps[20].mu, by_steps[20].std) == (0.0, 1.75)
    assert (by_steps[48].mu, by_steps[48].std) == (0.0, 1.5)
    for preset, low in ((by_steps[12], 1), (by_steps[20], 2), (by_steps[48], 3)):
        assert len(preset.official_guidance) == preset.steps
        # Official index 0 is the last sampling step; Diffusers gets first-step-first.
        assert preset.diffusers_guidance()[-low:] == (3.0,) * low
        assert set(preset.diffusers_guidance()[:-low]) == {7.0}
    with pytest.raises(Ideogram4ProfileError, match="12 Turbo, 20 Default, 48 Quality"):
        P.preset_for_steps(30)
    with pytest.raises(Ideogram4ProfileError):
        P.preset_for_steps(20.0)


def test_residency_floors_and_timeout_are_the_recorded_values() -> None:
    r = P.residency
    assert (r.min_free_vram_mib, r.allocator_cap_mib, r.min_allocator_cap_mib) == (
        10_700,
        11_200,
        10_445,
    )
    assert r.min_available_host_ram_bytes == 16 * 1024**3 and r.child_memory_limit_mb == 36_864
    assert r.timeout_seconds(20, 1) == 700.0 and r.timeout_seconds(48, 4) == 300.0 + 4 * 48 * 20


def test_identity_is_one_exact_name_and_routes_to_diffusers() -> None:
    assert is_ideogram4_model_name(P.model_name)
    assert is_ideogram4_model_name("C:/models/" + P.model_name + " [12345678]")
    for name in ("ideogram-4", "ideogram-4-nf4-diffusers", "prefix-" + P.model_name, "", None):
        assert not is_ideogram4_model_name(name)
        assert required_backend_for_model(name) is None
    assert required_backend_for_model(P.model_name) == "diffusers"
    assert model_profile_for_model(P.model_name) == P.reference()
    assert resolve_model_profile({"image": {"model_profile": P.reference()}}) is P
    assert (
        resolve_model_profile({"image": {"model_profile": KLEIN_PROFILE_V2.reference()}})
        is KLEIN_PROFILE_V2
    )
    for reference in ({"id": P.profile_id, "version": 2}, {"id": P.profile_id, "version": True}):
        with pytest.raises(KleinProfileError):
            resolve_model_profile({"image": {"model_profile": reference}})


def test_new_work_is_stamped_for_diffusers_but_explicit_identity_is_never_rewritten() -> None:
    assert normalize_image_backend_options({}, model_name=P.model_name)["image"] == {
        "backend_id": "diffusers",
        "model_profile": P.reference(),
    }
    explicit = normalize_image_backend_options(
        {"image": {"backend_id": "forge_webui"}}, model_name=P.model_name
    )
    assert explicit["image"]["backend_id"] == "forge_webui"
    # ...and the profile then refuses the conflict instead of switching backends.
    with pytest.raises(Ideogram4ProfileError, match="never switches or falls back"):
        apply_ideogram4_compile_policy(
            config(backend_options={"image": {"backend_id": "forge_webui"}})
        )
    ordinary = normalize_image_backend_options({}, model_name="sdxl_base.safetensors")
    assert ordinary["image"]["backend_id"] != "diffusers"


def test_policy_is_txt2img_only_with_presets_sizes_and_nothing_optional() -> None:
    policy = resolve_model_policy(P.model_name)
    assert policy.family == FAMILY_IDEOGRAM4 and policy.required_backend == "diffusers"
    assert policy.allowed_backends == ("diffusers",) and policy.profile_ref == P.reference()
    assert policy.stages == ("txt2img",) and policy.qualified and policy.explicit_capabilities
    assert policy.control("steps").allowed == (20, 12, 48)
    assert policy.control("geometry").allowed == P.geometries
    for name in ("sampler", "scheduler", "cfg_scale", "vae"):
        assert policy.control(name).mode is ControlMode.FIXED
    for feature in (
        "lora",
        "hires",
        "refiner",
        "adetailer",
        "upscale",
        "negative_prompt",
        "embeddings",
    ):
        assert not policy.feature(feature).supported
    assert "Non-commercial" in policy.note and "Not yet physically qualified" in policy.note
    assert policy.learning_variables() == ()


def test_compile_freezes_the_profile_and_stage_values_win() -> None:
    data = config(
        steps=None,
        txt2img={"steps": 12, "width": 768, "height": 1024},
        sampler_name="Euler a",
        cfg_scale=4.5,
        vae="sdxl_vae.safetensors",
        global_positive_prompt="masterpiece",
    )
    apply_ideogram4_compile_policy(data)
    image = data["backend_options"]["image"]
    assert image == {"backend_id": "diffusers", "model_profile": P.reference()}
    assert (data["steps"], data["width"], data["height"]) == (12, 768, 1024)
    assert data["txt2img"]["steps"] == 12
    assert (
        data["sampler_name"] == P.sampler and data["cfg_scale"] == P.cfg_scale and data["vae"] == ""
    )
    assert (
        data["global_positive_prompt"] == ""
        and data["pipeline"]["apply_global_positive_txt2img"] is False
    )
    # Idempotent: compiling the compiled result changes nothing.
    again = copy.deepcopy(data)
    assert apply_ideogram4_compile_policy(again) == data
    # Other models are untouched.
    other = {"model": "sdxl_base.safetensors", "steps": 30}
    assert apply_ideogram4_compile_policy(dict(other)) == other


@pytest.mark.parametrize(
    "change",
    [
        {"steps": 30},
        {"steps": 20.0},
        {"width": 1536, "height": 1536},
        {"width": 640},
        {"batch_size": 5},
        {"images_per_prompt": 0},
        {"n_iter": 2},
        {"subseed_strength": 0.5},
        {"seed": 4_294_967_296},
        {"seed": 1.5},
        {"enable_hr": True},
        {"use_refiner": True},
        {"adetailer": {"enabled": True}},
        {"upscale": {"enabled": True}},
        {"img2img_enabled": True},
        {"hypernetwork": "foo"},
        {"controlnet": {"enabled": True}},
        {"restore_faces": True},
        {"tiling": True},
        {"styles": ["cinematic"]},
        {"stages": ["txt2img", "upscale"]},
        {"lora_strengths": [{"name": "x", "strength": 1}]},
        {"positive_embeddings": ["x"]},
        {"txt2img": {"model": "sdxl_base.safetensors"}},
    ],
)
def test_compile_refuses_conflicts_and_leaves_the_config_unchanged(change) -> None:
    data = config(**change)
    if "txt2img" in change:
        data["txt2img"] = {**change["txt2img"]}
    with pytest.raises(Ideogram4ProfileError):
        apply_model_compile_policy(
            data
        ) if "txt2img" not in change else apply_ideogram4_compile_policy(data)
    assert data["model"] == P.model_name


def test_frozen_profile_without_its_model_is_refused() -> None:
    with pytest.raises(Ideogram4ProfileError, match="exact model selection"):
        apply_ideogram4_compile_policy(
            {
                "model": "sdxl_base.safetensors",
                "backend_options": {"image": {"model_profile": P.reference()}},
            }
        )


def _njr(**changes):
    values = {
        "base_model": P.model_name,
        "positive_prompt": "A teapot.",
        "negative_prompt": "",
        "steps": 20,
        "width": 1024,
        "height": 1024,
        "seed": 7,
        "images_per_prompt": 1,
        "config": {},
        "backend_options": {"image": {"backend_id": "diffusers", "model_profile": P.reference()}},
        "stage_chain": [SimpleNamespace(stage_type="txt2img", enabled=True)],
        "input_image_paths": [],
        "lora_tags": [],
        "positive_embeddings": [],
        "negative_embeddings": [],
    }
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        (
            {
                "backend_options": {
                    "image": {"backend_id": "forge_webui", "model_profile": P.reference()}
                }
            },
            "frozen v1",
        ),
        ({"backend_options": {"image": {"backend_id": "diffusers"}}}, "frozen v1"),
        ({"base_model": "sdxl.safetensors"}, "frozen v1"),
        (
            {
                "stage_chain": [
                    SimpleNamespace(stage_type="txt2img", enabled=True),
                    SimpleNamespace(stage_type="upscale", enabled=True),
                ]
            },
            "only txt2img",
        ),
        ({"lora_tags": ["x"]}, "no input images, LoRAs"),
        ({"input_image_paths": ["a.png"]}, "no input images, LoRAs"),
        ({"negative_prompt": "blurry"}, "negative prompt is unsupported"),
        ({"positive_prompt": "{broken"}, "not a valid JSON object"),
        ({"steps": 25}, "steps 25"),
        ({"width": 2048, "height": 2048}, "outside the tested sizes"),
        ({"images_per_prompt": 5}, "images_per_prompt must be 1-4"),
    ],
)
def test_persisted_njr_admission_refuses_anything_outside_v1(change, fragment) -> None:
    validate_ideogram4_njr(_njr())
    with pytest.raises(Ideogram4ProfileError, match=None) as raised:
        validate_ideogram4_njr(_njr(**change))
    assert fragment in str(raised.value)
    # Ordinary NJRs are not Ideogram's business.
    validate_ideogram4_njr(SimpleNamespace(base_model="sdxl.safetensors", backend_options={}))


def test_cli_builder_and_serialized_replay_keep_the_exact_profile() -> None:
    source = config()
    record = JobBuilderV2(time_fn=lambda: 1, id_fn=lambda: "i4-cli").build_jobs(base_config=source)[
        0
    ]
    assert record.backend_options["image"] == {
        "backend_id": "diffusers",
        "model_profile": P.reference(),
    }
    validate_ideogram4_njr(record)
    restored = NormalizedJobRecord.from_dict(json.loads(json.dumps(record.to_dict())))
    assert restored.backend_options["image"]["model_profile"] == P.reference()
    validate_ideogram4_njr(restored)
    assert source == config()


def test_plan_resolves_presets_geometry_and_recorded_seeds() -> None:
    plan = resolve_plan(steps=48, width=768, height=768, seed=4_294_967_295, images=3)
    assert plan.preset.name == "V4_QUALITY_48" and (plan.width, plan.height) == (768, 768)
    assert plan.seeds == (4_294_967_295, 0, 1) and plan.requested_seed == 4_294_967_295
    drawn = resolve_plan(
        steps=None, width=None, height=None, seed=-1, images=None, rng=random.Random(5)
    )
    assert (
        drawn.preset.steps == 20
        and (drawn.width, drawn.height) == (1024, 1024)
        and len(drawn.seeds) == 1
    )
    assert drawn.requested_seed == -1
    for kwargs in ({"steps": 30}, {"width": 1536, "height": 1536}, {"images": 5}, {"seed": -2}):
        base = {"steps": 20, "width": 1024, "height": 1024, "seed": 1, "images": 1, **kwargs}
        with pytest.raises(Ideogram4ProfileError):
            resolve_plan(**base)
