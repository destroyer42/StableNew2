"""PR-GUI-UX-560: the shared Matrix expansion plan (pure, no Tk, no compiler)."""

from __future__ import annotations

import itertools
import random

import pytest

from src.pipeline.matrix_expansion_plan import (
    DEFAULT_MATRIX_EXPANSION_LIMIT,
    LIMIT_SOURCE_DEFAULT,
    LIMIT_SOURCE_MATRIX,
    LIMIT_SOURCE_RANDOMIZER,
    MATRIX_EXPANSION_CONTRACT,
    matrix_randomizer_limit_hint,
    parse_sample_seed,
    plan_matrix_expansion,
    unresolved_matrix_tokens,
)
from src.utils.prompt_pack_utils import get_matrix_slots_dict


def _matrix(slots: dict[str, list[str]], **extra) -> dict:
    return {
        "enabled": True,
        "slots": [{"name": name, "values": list(values)} for name, values in slots.items()],
        **extra,
    }


THREE_DIMENSIONS = {
    "outfit": ["a", "b", "c"],
    "location": ["w", "x", "y", "z"],
    "lighting": ["d", "n"],
}


def _codes(plan) -> set[str]:
    return {issue.code for issue in plan.issues}


def test_counts_for_the_documented_example() -> None:
    plan = plan_matrix_expansion(_matrix(THREE_DIMENSIONS, limit=8))

    assert [len(item.values) for item in plan.dimensions] == [3, 4, 2]
    assert plan.theoretical_count == 24
    assert plan.effective_limit == 8
    assert plan.limit_source == LIMIT_SOURCE_MATRIX
    assert plan.selected_count == 8
    assert plan.excluded_count == 16
    assert plan.truncated is True


def test_ordered_selection_matches_the_cartesian_product_with_the_last_dimension_fastest() -> None:
    plan = plan_matrix_expansion(_matrix(THREE_DIMENSIONS, limit=24))
    oracle = list(itertools.product(*THREE_DIMENSIONS.values()))

    assert plan.selected_indexes() == tuple(range(24))
    assert [plan.combination_at(index) for index in plan.selected_indexes()] == oracle


def test_disabled_or_empty_matrix_expands_to_nothing() -> None:
    disabled = plan_matrix_expansion({**_matrix(THREE_DIMENSIONS), "enabled": False})
    empty = plan_matrix_expansion({"enabled": True, "slots": []})
    nameless = plan_matrix_expansion({"enabled": True, "slots": [{"name": "", "values": []}]})

    for plan in (disabled, empty, nameless):
        assert plan.expands is False
        assert plan.theoretical_count == 1
        assert plan.selected_count == 1
        assert plan.excluded_count == 0
        assert plan.selected_indexes() == ()


@pytest.mark.parametrize("mode", ["fanout", "sequential", None, "grid", "Random", "ALL"])
def test_every_non_random_mode_value_is_the_same_ordered_prefix(mode) -> None:
    extra = {} if mode is None else {"mode": mode}
    plan = plan_matrix_expansion(_matrix(THREE_DIMENSIONS, limit=5, **extra))

    assert plan.is_random is False
    assert plan.selected_indexes() == (0, 1, 2, 3, 4)


def test_mode_identity_is_reported_not_rewritten() -> None:
    sequential = plan_matrix_expansion(_matrix(THREE_DIMENSIONS, mode="sequential"))
    unset = plan_matrix_expansion(_matrix(THREE_DIMENSIONS))
    odd = plan_matrix_expansion(_matrix(THREE_DIMENSIONS, mode="grid"))

    assert sequential.mode == "sequential"
    assert unset.mode is None and unset.effective_mode == "sequential"
    assert "mode_unrecognized" in _codes(odd)
    assert "mode_unrecognized" not in _codes(sequential)


@pytest.mark.parametrize(
    ("stored", "hint", "expected", "source"),
    [
        (6, 3, 6, LIMIT_SOURCE_MATRIX),
        (0, 3, 3, LIMIT_SOURCE_RANDOMIZER),
        (None, 3, 3, LIMIT_SOURCE_RANDOMIZER),
        (-4, 0, DEFAULT_MATRIX_EXPANSION_LIMIT, LIMIT_SOURCE_DEFAULT),
        ("junk", None, DEFAULT_MATRIX_EXPANSION_LIMIT, LIMIT_SOURCE_DEFAULT),
        ("7", None, 7, LIMIT_SOURCE_MATRIX),
        (0, None, DEFAULT_MATRIX_EXPANSION_LIMIT, LIMIT_SOURCE_DEFAULT),
    ],
)
def test_limit_precedence_is_matrix_then_randomizer_then_default(
    stored, hint, expected, source
) -> None:
    matrix = _matrix(THREE_DIMENSIONS)
    if stored is not None:
        matrix["limit"] = stored
    plan = plan_matrix_expansion(matrix, randomizer_limit=hint)

    assert (plan.effective_limit, plan.limit_source) == (expected, source)
    assert plan.selected_count == min(24, expected)


def test_a_non_positive_stored_limit_is_never_unlimited_and_is_reported() -> None:
    for stored in (0, -1, "abc", 1.0 - 1.0):
        plan = plan_matrix_expansion(_matrix(THREE_DIMENSIONS, limit=stored))
        assert plan.selected_count == DEFAULT_MATRIX_EXPANSION_LIMIT
        assert "limit_unusable" in _codes(plan)
    assert "limit_unusable" not in _codes(plan_matrix_expansion(_matrix(THREE_DIMENSIONS)))


def test_limit_above_the_total_selects_everything_and_excludes_nothing() -> None:
    plan = plan_matrix_expansion(
        _matrix({"a": ["1", "2"], "b": ["x", "y"]}, limit=50, mode="random", sample_seed=1)
    )

    assert plan.theoretical_count == 4
    assert plan.selected_count == 4
    assert plan.excluded_count == 0
    assert plan.truncated is False
    assert plan.selected_indexes() == (0, 1, 2, 3)


def test_randomizer_hint_reads_metadata_first_then_the_config_snapshot() -> None:
    assert (
        matrix_randomizer_limit_hint({"max_variants": 4}, {"randomization": {"max_variants": 9}})
        == 4
    )
    assert (
        matrix_randomizer_limit_hint({"max_variants": 0}, {"randomization": {"max_variants": 9}})
        == 9
    )
    assert matrix_randomizer_limit_hint(None, None) == 0
    assert matrix_randomizer_limit_hint({"max_variants": "x"}, {"randomization": "nope"}) == 0


class TestSeededRandomSelection:
    MATRIX = _matrix(
        {"a": [str(i) for i in range(10)], "b": [str(i) for i in range(10)]}, mode="random", limit=5
    )

    def _plan(self, seed=None):
        extra = {} if seed is None else {"sample_seed": seed}
        return plan_matrix_expansion({**self.MATRIX, **extra})

    def test_same_seed_selects_the_same_combinations(self) -> None:
        assert self._plan(42).selected_indexes() == self._plan(42).selected_indexes()

    def test_different_seeds_can_select_different_subsets(self) -> None:
        selections = {self._plan(seed).selected_indexes() for seed in range(10)}
        assert len(selections) > 1

    def test_selection_is_unique_sorted_and_in_range(self) -> None:
        for seed in range(10):
            indexes = self._plan(seed).selected_indexes()
            assert len(indexes) == 5
            assert len(set(indexes)) == 5
            assert list(indexes) == sorted(indexes)
            assert all(0 <= index < 100 for index in indexes)

    def test_seeded_sampling_never_touches_or_depends_on_global_random_state(self) -> None:
        plan = self._plan(7)
        random.seed(1234)
        before = random.getstate()
        first = plan.selected_indexes()
        assert random.getstate() == before

        random.seed(99)
        random.random()
        random.random()
        assert plan.selected_indexes() == first

    def test_unseeded_sampling_does_not_mutate_global_state_either(self) -> None:
        random.seed(5)
        before = random.getstate()
        indexes = self._plan().selected_indexes()
        assert random.getstate() == before
        assert len(indexes) == 5

    def test_the_seed_only_matters_for_random_mode(self) -> None:
        ordered = plan_matrix_expansion({**self.MATRIX, "mode": "fanout", "sample_seed": 3})
        assert ordered.selected_indexes() == (0, 1, 2, 3, 4)
        assert ordered.sample_is_reproducible is False
        assert self._plan(3).sample_is_reproducible is True
        assert self._plan().sample_is_reproducible is False

    def test_injected_rng_makes_an_unseeded_draw_deterministic(self) -> None:
        plan = self._plan()
        assert plan.selected_indexes(random.Random(11)) == plan.selected_indexes(random.Random(11))

    def test_preview_rows_are_exact_when_seeded_and_bounded_when_not(self) -> None:
        seeded = self._plan(21)
        assert seeded.preview_indexes(3) == seeded.selected_indexes()[:3]
        unseeded = self._plan()
        assert len(unseeded.preview_indexes(3, random.Random(1))) == 3
        assert len(unseeded.preview_indexes(99, random.Random(1))) == 5


def test_huge_theoretical_counts_are_never_enumerated() -> None:
    slots = {f"d{i}": [str(v) for v in range(10)] for i in range(30)}
    ordered = plan_matrix_expansion(_matrix(slots, limit=3))
    sampled = plan_matrix_expansion(_matrix(slots, limit=4, mode="random", sample_seed=9))

    assert ordered.theoretical_count == 10**30
    assert ordered.excluded_count == 10**30 - 3
    assert ordered.selected_indexes() == (0, 1, 2)
    indexes = sampled.selected_indexes()
    assert len(set(indexes)) == 4 and all(0 <= index < 10**30 for index in indexes)
    assert indexes == sampled.selected_indexes()
    assert len(sampled.combination_at(indexes[0])) == 30
    with pytest.raises(IndexError):
        sampled.combination_at(10**30)


@pytest.mark.parametrize(
    ("raw", "seed", "invalid"),
    [
        (None, None, False),
        (0, 0, False),
        (42, 42, False),
        (2**32 - 1, 2**32 - 1, False),
        (-1, None, True),
        (2**32, None, True),
        ("42", None, True),
        (True, None, True),
        (4.0, None, True),
    ],
)
def test_sample_seed_parsing_never_coerces(raw, seed, invalid) -> None:
    assert parse_sample_seed(raw) == (seed, invalid)


def test_an_invalid_stored_seed_is_reported_for_random_mode_and_selection_stays_unseeded() -> None:
    plan = plan_matrix_expansion(
        _matrix(THREE_DIMENSIONS, mode="random", limit=4, sample_seed="oops")
    )

    assert plan.sample_seed is None and plan.sample_seed_invalid is True
    assert "sample_seed_invalid" in _codes(plan)
    assert plan.provenance(0, 0)["sample_seed_invalid"] is True
    assert "sample_seed_invalid" not in _codes(
        plan_matrix_expansion(_matrix(THREE_DIMENSIONS, mode="fanout", sample_seed="oops"))
    )


def test_malformed_declarations_are_reported_without_raising() -> None:
    assert "matrix_malformed" in _codes(plan_matrix_expansion(["not", "a", "dict"]))
    assert "slots_malformed" in _codes(plan_matrix_expansion({"enabled": True, "slots": "nope"}))
    plan = plan_matrix_expansion(
        {
            "enabled": True,
            "slots": [
                7,
                {"name": "ok", "values": ["1", "2"]},
                {"name": "text", "values": "a,b"},
                {"name": 5, "values": ["x"]},
                {"name": "novalues", "values": []},
            ],
        }
    )
    assert plan.dimension_names() == ("ok",)
    assert {"dimension_malformed", "dimension_incomplete"} <= _codes(plan)


def test_duplicate_names_keep_the_compiler_semantics_and_are_reported() -> None:
    plan = plan_matrix_expansion(
        {
            "enabled": True,
            "slots": [
                {"name": "a", "values": ["1"]},
                {"name": "b", "values": ["2"]},
                {"name": "a", "values": ["3", "4"]},
            ],
        }
    )

    assert plan.dimension_names() == ("a", "b")
    assert plan.dimensions[0].values == ("3", "4")
    assert "duplicate_name" in _codes(plan)


def test_normalized_alias_collisions_and_duplicate_values_are_reported() -> None:
    plan = plan_matrix_expansion(_matrix({"hair-color": ["red"], "hair_color": ["blue", "blue"]}))

    assert "ambiguous_alias" in _codes(plan)
    assert "duplicate_values" in _codes(plan)
    assert plan.theoretical_count == 2  # duplicates still count: the compiler would emit both


def test_dimension_parsing_agrees_with_the_legacy_slot_dictionary() -> None:
    cases = [
        _matrix(THREE_DIMENSIONS),
        _matrix({"x": ["1"], "y": ["2", "3"]}),
        {"enabled": True, "slots": [{"name": "a", "values": ["1"]}, {"name": "", "values": ["2"]}]},
        {"enabled": False, "slots": [{"name": "a", "values": ["1"]}]},
    ]
    for matrix in cases:
        legacy = get_matrix_slots_dict({"pack_data": {"matrix": matrix}})
        plan = plan_matrix_expansion(matrix)
        assert {item.name: list(item.values) for item in plan.dimensions} == legacy


def test_provenance_is_content_free_and_bounded() -> None:
    plan = plan_matrix_expansion(_matrix(THREE_DIMENSIONS, mode="random", limit=8, sample_seed=77))
    payload = plan.provenance(2, plan.selected_indexes()[2])

    assert payload == {
        "contract": MATRIX_EXPANSION_CONTRACT,
        "mode": "random",
        "selection": "random_sample",
        "theoretical_count": 24,
        "effective_limit": 8,
        "limit_source": LIMIT_SOURCE_MATRIX,
        "selected_count": 8,
        "selected_ordinal": 2,
        "combination_index": plan.selected_indexes()[2],
        "sample_seed": 77,
    }
    ordered = plan_matrix_expansion(
        _matrix(THREE_DIMENSIONS, mode="sequential", sample_seed=77)
    ).provenance(0, 0)
    assert ordered["selection"] == "ordered_prefix" and ordered["sample_seed"] is None


def test_unresolved_tokens_use_exact_names_then_normalized_aliases_and_never_rewrite() -> None:
    names = ("hair color", "location")
    text = "[[hair-color]] and [[Hair_Color]] in [[location]] with [[mood]] and [[mood]] [x]"

    assert unresolved_matrix_tokens(text, names) == ("mood",)
    assert unresolved_matrix_tokens("no tokens", names) == ()


def test_a_very_large_selection_is_warned_about_but_not_refused_or_changed() -> None:
    slots = {"a": [str(i) for i in range(50)], "b": [str(i) for i in range(50)]}
    large = plan_matrix_expansion(_matrix(slots, limit=500))
    modest = plan_matrix_expansion(_matrix(slots, limit=100))

    assert large.selected_count == 500
    assert "large_selection" in _codes(large)
    assert "large_selection" not in _codes(modest)


def test_a_seeded_plan_ignores_an_injected_generator_for_its_preview_rows() -> None:
    plan = plan_matrix_expansion(
        _matrix(
            {"a": [str(i) for i in range(10)], "b": [str(i) for i in range(10)]},
            mode="random",
            limit=6,
            sample_seed=21,
        )
    )

    assert (
        plan.preview_indexes(4, random.Random(1))
        == plan.preview_indexes(4, random.Random(2))
        == plan.selected_indexes()[:4]
    )
