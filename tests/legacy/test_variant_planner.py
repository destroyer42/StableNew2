import pytest

from src.pipeline.variant_planner import (
    VariantSpec,
    apply_variant_to_config,
    build_variant_plan,
)


def test_plan_inactive_when_no_matrix_or_hypernets():
    config = {
        "pipeline": {},
        "txt2img": {"model": "base_model"},
    }
    plan = build_variant_plan(config)
    assert plan.mode == "fanout"
    assert not plan.active


def test_plan_uses_hypernet_sweeps_with_base_model():
    config = {
        "pipeline": {
            "hypernetworks": [
                {"name": "HN-A", "strength": 0.7},
                {"name": "HN-B", "strength": 1.2},
            ]
        },
        "txt2img": {"model": "JuggernautXL"},
    }
    plan = build_variant_plan(config)
    assert plan.active
    assert len(plan.variants) == 2
    assert {variant.hypernetwork for variant in plan.variants} == {"HN-A", "HN-B"}
    for variant in plan.variants:
        assert variant.model == "JuggernautXL"


def test_plan_product_of_models_and_hypernets():
    config = {
        "pipeline": {
            "variant_mode": "rotate",
            "model_matrix": ["modelA", "modelB"],
            "hypernetworks": [
                {"name": "None"},
                {"name": "HN-C", "strength": 0.5},
            ],
        },
        "txt2img": {"model": "ignored"},
    }
    plan = build_variant_plan(config)
    assert plan.mode == "rotate"
    assert plan.active
    assert len(plan.variants) == 4
    combos = {(v.model, v.hypernetwork) for v in plan.variants}
    assert combos == {
        ("modelA", None),
        ("modelA", "HN-C"),
        ("modelB", None),
        ("modelB", "HN-C"),
    }


def test_apply_variant_updates_stage_models_and_hypernets():
    base_config = {
        "pipeline": {},
        "txt2img": {"model": "base", "hypernetwork": None},
        "img2img": {"model": "base", "hypernetwork": None},
    }
    variant = VariantSpec(
        index=1,
        model="modelB",
        hypernetwork="HN-X",
        hypernetwork_strength=0.9,
    )
    applied = apply_variant_to_config(base_config, variant)
    assert applied["txt2img"]["model"] == "modelB"
    assert applied["img2img"]["hypernetwork"] == "HN-X"
    assert applied["img2img"]["hypernetwork_strength"] == pytest.approx(0.9)
    assert applied["pipeline"]["active_variant"]["index"] == 1
