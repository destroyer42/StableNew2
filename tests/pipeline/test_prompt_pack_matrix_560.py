"""PR-GUI-UX-560: the PromptPack compiler expands exactly what the shared Matrix plan says."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import pytest

from src.gui.app_state_v2 import PackJobEntry
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.job_models_v2 import UnifiedJobSummary
from src.pipeline.matrix_expansion_plan import plan_matrix_expansion
from src.pipeline.njr_core_v26 import NormalizedJobRecord
from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from tests.pipeline.test_prompt_pack_job_builder import (
    BASE_PACK_CONFIG,
    SequentialIdGenerator,
    StubConfigManager,
    _write_native_pack,
)

PROMPT = "A [[character]] in a [[location]] under [[lighting]]"
DIMENSIONS = {
    "character": ["knight", "ranger", "mage"],
    "location": ["forest", "castle", "market", "cave"],
    "lighting": ["dawn", "dusk"],
}


def _matrix(dimensions: dict[str, list[str]] | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "enabled": True,
        "slots": [{"name": n, "values": list(v)} for n, v in (dimensions or DIMENSIONS).items()],
        **extra,
    }


def _builder(
    tmp_path: Path, matrix: dict[str, Any], *, text: str = PROMPT, pipeline: dict | None = None
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    config_manager = StubConfigManager(tmp_path)
    if pipeline:
        config_manager._config = {  # noqa: SLF001
            **BASE_PACK_CONFIG,
            "pipeline": {**BASE_PACK_CONFIG["pipeline"], **pipeline},
        }
    pack = _write_native_pack(
        config_manager.packs_dir / "matrix-pack.json", text=text, matrix=matrix
    )
    builder = PromptPackNormalizedJobBuilder(
        config_manager=config_manager,
        job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
        packs_dir=config_manager.packs_dir,
    )
    return builder, pack


def _entry(pack: Path, *, row: int = 0, hint: int = 0) -> PackJobEntry:
    return PackJobEntry(
        pack_id=pack.name,
        pack_name="Matrix Pack",
        pack_row_index=row,
        prompt_text=PROMPT,
        config_snapshot={"randomization": {"enabled": False}},
        stage_flags={"txt2img": True},
        randomizer_metadata={"enabled": False, "max_variants": hint},
    )


def _compile(tmp_path: Path, matrix: dict[str, Any], **kwargs: Any) -> list[NormalizedJobRecord]:
    builder, pack = _builder(tmp_path, matrix, **kwargs)
    return builder.build_jobs([_entry(pack)])


def _selection(records: list[NormalizedJobRecord]) -> list[dict[str, Any]]:
    return [dict(record.matrix_slot_values) for record in records]


def test_compiler_expands_exactly_the_plans_selection_in_the_plans_order(tmp_path: Path) -> None:
    matrix = _matrix(limit=5, mode="fanout")
    records = _compile(tmp_path, matrix)
    plan = plan_matrix_expansion(matrix)

    assert len(records) == plan.selected_count == 5
    assert _selection(records) == [plan.combination_mapping(i) for i in plan.selected_indexes()]
    for record, index in zip(records, plan.selected_indexes(), strict=True):
        values = plan.combination_mapping(index)
        assert record.positive_prompt.startswith(
            f"A {values['character']} in a {values['location']} under {values['lighting']}"
        )
        expansion = record.provenance.metadata["matrix_expansion"]
        assert expansion["combination_index"] == index
        assert expansion["theoretical_count"] == 24
        assert expansion["effective_limit"] == 5
        assert expansion["selected_count"] == 5
    assert [r.provenance.metadata["matrix_expansion"]["selected_ordinal"] for r in records] == [
        0,
        1,
        2,
        3,
        4,
    ]


@pytest.mark.parametrize(
    "extra", [{"mode": "sequential"}, {"mode": "fanout"}, {}, {"mode": "grid"}]
)
def test_fanout_and_sequential_and_unset_compile_identically(tmp_path: Path, extra: dict) -> None:
    baseline = _compile(tmp_path / "baseline", _matrix(limit=6, mode="fanout"))
    other = _compile(tmp_path / "other", _matrix(limit=6, **extra))

    assert _selection(other) == _selection(baseline)
    assert [r.positive_prompt for r in other] == [r.positive_prompt for r in baseline]


def test_the_stored_mode_is_what_the_nj_records_report(tmp_path: Path) -> None:
    [record, *_] = _compile(tmp_path, _matrix(limit=2, mode="sequential"))

    assert record.matrix_mode == "sequential"
    assert record.provenance.metadata["matrix_expansion"]["mode"] == "sequential"
    assert record.provenance.metadata["matrix_expansion"]["selection"] == "ordered_prefix"


def test_seeded_random_reproduces_the_selection_and_the_prompts(tmp_path: Path) -> None:
    matrix = _matrix(limit=6, mode="random", sample_seed=2026)
    first = _compile(tmp_path / "a", matrix)
    second = _compile(tmp_path / "b", matrix)
    plan = plan_matrix_expansion(matrix)

    assert _selection(first) == _selection(second)
    assert [r.positive_prompt for r in first] == [r.positive_prompt for r in second]
    assert _selection(first) == [plan.combination_mapping(i) for i in plan.selected_indexes()]
    assert {r.provenance.metadata["matrix_expansion"]["sample_seed"] for r in first} == {2026}
    assert len({tuple(sorted(item.items())) for item in _selection(first)}) == 6  # no repeats


def test_different_sample_seeds_can_select_different_combinations(tmp_path: Path) -> None:
    selections = {
        tuple(
            map(
                tuple,
                (
                    sorted(s.items())
                    for s in _selection(
                        _compile(
                            tmp_path / str(seed), _matrix(limit=4, mode="random", sample_seed=seed)
                        )
                    )
                ),
            )
        )
        for seed in range(6)
    }
    assert len(selections) > 1


def test_seeded_compilation_ignores_and_preserves_the_process_random_state(tmp_path: Path) -> None:
    matrix = _matrix(limit=4, mode="random", sample_seed=5)
    random.seed(1)
    before = random.getstate()
    first = _compile(tmp_path / "a", matrix)
    after_first = random.getstate()
    random.seed(999)
    random.random()
    second = _compile(tmp_path / "b", matrix)

    assert after_first == before
    assert _selection(first) == _selection(second)


def test_unseeded_random_keeps_its_historical_shape_and_records_no_seed(tmp_path: Path) -> None:
    records = _compile(tmp_path, _matrix(limit=5, mode="random"))

    assert len(records) == 5
    assert len({tuple(sorted(item.items())) for item in _selection(records)}) == 5
    for record in records:
        expansion = record.provenance.metadata["matrix_expansion"]
        assert expansion["selection"] == "random_sample"
        assert expansion["sample_seed"] is None
        assert "sample_seed_invalid" not in expansion


def test_an_invalid_stored_seed_does_not_stop_compilation_and_is_recorded(tmp_path: Path) -> None:
    records = _compile(tmp_path, _matrix(limit=3, mode="random", sample_seed="soon"))

    assert len(records) == 3
    assert records[0].provenance.metadata["matrix_expansion"]["sample_seed_invalid"] is True


def test_limit_precedence_matches_the_documented_order(tmp_path: Path) -> None:
    builder, pack = _builder(tmp_path, _matrix(limit=0, mode="fanout"))
    assert len(builder.build_jobs([_entry(pack, hint=3)])) == 3  # randomizer hint
    assert len(builder.build_jobs([_entry(pack, hint=0)])) == 8  # built-in default

    [record, *_] = builder.build_jobs([_entry(pack, hint=3)])
    assert (
        record.provenance.metadata["matrix_expansion"]["limit_source"] == "randomizer.max_variants"
    )


def test_job_count_is_matrix_times_rows_times_batch_runs_and_images_stay_per_job(
    tmp_path: Path,
) -> None:
    builder, pack = _builder(
        tmp_path,
        _matrix(limit=3, mode="fanout"),
        pipeline={"loop_count": 2, "images_per_prompt": 4},
    )
    records = builder.build_jobs([_entry(pack)])

    assert len(records) == 3 * 2
    assert {r.images_per_prompt for r in records} == {4}  # images are per job, not extra jobs
    assert {r.provenance.config_variant_label for r in records} == {
        "base"
    }  # no config sweep is compiled

    twice = builder.build_jobs([_entry(pack), _entry(pack)])
    assert len(twice) == 2 * 3 * 2


def test_disabled_and_empty_matrices_compile_one_unexpanded_job_with_no_expansion_evidence(
    tmp_path: Path,
) -> None:
    disabled = _compile(tmp_path / "off", {**_matrix(), "enabled": False})
    empty = _compile(
        tmp_path / "empty", {"enabled": True, "mode": "random", "limit": 4, "slots": []}
    )

    for records in (disabled, empty):
        assert len(records) == 1
        assert "matrix_expansion" not in records[0].provenance.metadata
        assert records[0].matrix_expansion_label() == ""


def test_alias_tokens_resolve_and_unknown_tokens_stay_in_the_prompt(tmp_path: Path) -> None:
    matrix = _matrix({"hair color": ["red", "blue"]}, limit=2)
    records = _compile(
        tmp_path, matrix, text="[[hair-color]] hair, [[Hair_Color]] eyes, [[mood]] light"
    )

    assert [r.positive_prompt.split(" light")[0] for r in records] == [
        "red hair, red eyes, [[mood]]",
        "blue hair, blue eyes, [[mood]]",
    ]


def test_malformed_dimensions_are_skipped_not_expanded(tmp_path: Path) -> None:
    matrix = {
        "enabled": True,
        "limit": 4,
        "slots": [
            {"name": "character", "values": ["knight", "mage"]},
            {"name": "broken", "values": "a,b"},
            {"name": "", "values": ["orphan"]},
        ],
    }
    records = _compile(tmp_path, matrix, text="A [[character]]")

    assert _selection(records) == [{"character": "knight"}, {"character": "mage"}]


def test_nj_label_and_summary_describe_the_frozen_selection(tmp_path: Path) -> None:
    ordered = _compile(tmp_path / "o", _matrix(limit=4, mode="fanout"))
    seeded = _compile(tmp_path / "s", _matrix(limit=4, mode="random", sample_seed=8))
    unseeded = _compile(tmp_path / "u", _matrix(limit=4, mode="random"))

    assert ordered[1].matrix_expansion_label() == "Matrix combination 2 of 4 (24 possible)"
    assert seeded[0].matrix_expansion_label() == "Matrix sample 1 of 4 (24 possible, sample seed 8)"
    assert (
        unseeded[3].matrix_expansion_label() == "Matrix sample 4 of 4 (24 possible, no sample seed)"
    )
    summary = UnifiedJobSummary.from_normalized_record(seeded[2])
    assert summary.matrix_expansion_label == seeded[2].matrix_expansion_label()
    assert "character=" in summary.matrix_slot_values_preview


def test_frozen_expansion_evidence_survives_a_serialization_round_trip(tmp_path: Path) -> None:
    [record, *_] = _compile(tmp_path, _matrix(limit=2, mode="random", sample_seed=3))
    restored = NormalizedJobRecord.from_dict(record.to_dict())

    assert (
        restored.provenance.metadata["matrix_expansion"]
        == record.provenance.metadata["matrix_expansion"]
    )
    assert dict(restored.matrix_slot_values) == dict(record.matrix_slot_values)
    assert restored.matrix_expansion_label() == record.matrix_expansion_label()


def test_changing_the_source_pack_after_compilation_does_not_touch_frozen_records(
    tmp_path: Path,
) -> None:
    builder, pack = _builder(tmp_path, _matrix(limit=3, mode="random", sample_seed=4))
    frozen = builder.build_jobs([_entry(pack)])
    snapshot = [record.to_dict() for record in frozen]

    _write_native_pack(pack, text=PROMPT, matrix=_matrix(limit=2, mode="fanout"))
    rebuilt = builder.build_jobs([_entry(pack)])

    assert [record.to_dict() for record in frozen] == snapshot
    assert len(rebuilt) == 2


def test_an_unavailable_pack_source_expands_to_the_unchanged_entry(tmp_path: Path) -> None:
    builder, _pack = _builder(tmp_path, _matrix(limit=3))
    entry = PackJobEntry(
        pack_id="not-a-real-pack.json", pack_name="Missing", prompt_text=PROMPT, config_snapshot={}
    )

    assert builder._expand_entry_by_matrix(entry) == [entry]  # noqa: SLF001
    [record] = builder.build_jobs(
        [entry]
    )  # still one job: nothing to expand without the pack's Matrix
    assert "matrix_expansion" not in record.provenance.metadata
