from __future__ import annotations

from src.learning.experiment_freeze import (
    apply_frozen_seed_policy,
    freeze_seed_policy,
    seed_vector_matches,
)


def test_random_baseline_freezes_one_concrete_requested_seed_once() -> None:
    policy = freeze_seed_policy(
        {"txt2img": {"seed": -1}}, 3, seed_supplier=lambda _upper: 12345
    )
    assert policy["requested_base_seed"] == 12345
    assert policy["requested_sample_count"] == 3
    assert not seed_vector_matches(policy, [12345, 12346, 12347])


def test_explicit_seed_and_active_subseed_are_preserved() -> None:
    policy = freeze_seed_policy(
        {"txt2img": {"seed": 91, "subseed": -1, "subseed_strength": 0.5}},
        2,
        seed_supplier=lambda _upper: 700,
    )
    config = {"txt2img": {"seed": -1, "subseed": -1}}
    apply_frozen_seed_policy(config, policy)
    assert config["txt2img"]["seed"] == 91
    assert config["txt2img"]["subseed"] == 700
    assert not seed_vector_matches(policy, [91, 92], [700, 701])


def test_mismatched_backend_vector_is_uncontrolled() -> None:
    policy = freeze_seed_policy(
        {"txt2img": {"seed": 42}}, 2, seed_supplier=lambda _upper: 1
    )
    observed = {**policy, "observed_seed_vector": [42, 43]}
    assert not seed_vector_matches(observed, [42, 99])
    assert not seed_vector_matches(observed, [42])
