"""ADetailer enablement truth for new work (PR-IMG-PROFILE-630, cases A-E). Deterministic; no GPU, no runtime.

The three representations (``pipeline.adetailer_enabled``, ``adetailer.enabled``, ``adetailer.adetailer_enabled``) and
the compiled stage chain of a new NJR must agree. Operator membership chosen at Add-to-Job wins; without it, an
explicit disable in any representation wins and a stale parameter section never infers enabled.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.contracts import PackJobEntry
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from src.pipeline.run_plan import build_run_plan_from_njr
from src.promptpacks.storage import CURRENT_PROMPTPACK_SCHEMA_VERSION
from src.utils.config import ConfigManager


def _build(tmp_path: Path, preset_data: dict, snapshot: dict, flags: dict):
    packs = tmp_path / "packs"
    packs.mkdir(exist_ok=True)
    (packs / "p.json").write_text(
        json.dumps(
            {
                "schema_version": CURRENT_PROMPTPACK_SCHEMA_VERSION,
                "pack_data": {
                    "name": "p",
                    "slots": [
                        {
                            "index": 0,
                            "text": "a cat",
                            "negative": "",
                            "positive_embeddings": [],
                            "negative_embeddings": [],
                            "loras": [],
                        }
                    ],
                    "matrix": {"enabled": False, "mode": "fanout", "limit": 8, "slots": []},
                },
                "preset_data": preset_data,
            }
        ),
        encoding="utf-8",
    )
    counter = iter(range(1, 100))
    builder = PromptPackNormalizedJobBuilder(
        config_manager=ConfigManager(presets_dir=tmp_path / "presets", packs_dir=packs),
        job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=lambda: f"job-{next(counter)}"),
    )
    entry = PackJobEntry(
        pack_id="p",
        pack_name="p",
        prompt_text="a cat",
        config_snapshot=snapshot,
        stage_flags=flags,
        randomizer_metadata={"enabled": False},
        pack_row_index=0,
        matrix_slot_values={},
    )
    return builder.build_jobs([entry])[0]


def _view(record) -> dict:
    config = record.config if isinstance(record.config, dict) else {}
    stage = next(s for s in record.stage_chain if s.stage_type == "adetailer")
    return {
        "stage": stage.enabled,
        "pipeline": (config.get("pipeline") or {}).get("adetailer_enabled"),
        "section": (config.get("adetailer") or {}).get("enabled"),
        "legacy": (config.get("adetailer") or {}).get("adetailer_enabled"),
    }


def _assert_consistent(view: dict, expected: bool) -> None:
    assert view["stage"] is expected
    for key in ("pipeline", "section", "legacy"):
        assert view[key] in (expected, None), f"{key} contradicts the stage chain: {view}"
    assert any(view[key] is expected for key in ("pipeline", "section", "legacy")) or not expected


def test_case_a_fresh_off_everywhere(tmp_path: Path) -> None:
    record = _build(
        tmp_path,
        {},
        {
            "pipeline": {"adetailer_enabled": False},
            "adetailer": {"enabled": False, "adetailer_enabled": False},
        },
        {"txt2img": True, "adetailer": False},
    )
    _assert_consistent(_view(record), False)


def test_case_b_contradictory_snapshot_without_membership_explicit_disable_wins(
    tmp_path: Path,
) -> None:
    record = _build(
        tmp_path, {}, {"pipeline": {"adetailer_enabled": True}, "adetailer": {"enabled": False}}, {}
    )
    _assert_consistent(_view(record), False)


def test_case_b2_pack_saved_section_true_but_pipeline_false_stays_off_and_consistent(
    tmp_path: Path,
) -> None:
    record = _build(
        tmp_path,
        {"pipeline": {"adetailer_enabled": False}, "adetailer": {"enabled": True}},
        {},
        {"txt2img": True, "adetailer": False},
    )
    _assert_consistent(_view(record), False)


def test_case_b3_operator_turns_adetailer_off_over_a_pack_that_saved_it_on(tmp_path: Path) -> None:
    record = _build(
        tmp_path,
        {
            "pipeline": {"adetailer_enabled": True},
            "adetailer": {"enabled": True, "adetailer_enabled": True},
        },
        {"pipeline": {"adetailer_enabled": False}},
        {"txt2img": True, "adetailer": False},
    )
    _assert_consistent(_view(record), False)


def test_case_d_operator_turns_adetailer_on_over_a_pack_that_saved_it_off(tmp_path: Path) -> None:
    record = _build(
        tmp_path,
        {
            "pipeline": {"adetailer_enabled": False},
            "adetailer": {"enabled": False, "adetailer_enabled": False},
        },
        {"pipeline": {"adetailer_enabled": True}},
        {"txt2img": True, "adetailer": True},
    )
    _assert_consistent(_view(record), True)


def test_stale_parameter_section_alone_never_enables_the_stage(tmp_path: Path) -> None:
    record = _build(
        tmp_path,
        {"adetailer": {"enabled": True, "adetailer_checkpoint_model": "x.safetensors"}},
        {},
        {"txt2img": True},
    )
    view = _view(record)
    assert view["stage"] is False
    assert view["section"] in (
        False,
        None,
    )  # inert settings may stay saved, but not as an enabled claim


def test_inert_adetailer_settings_stay_saved_when_the_stage_is_off(tmp_path: Path) -> None:
    record = _build(
        tmp_path,
        {
            "pipeline": {"adetailer_enabled": False},
            "adetailer": {"adetailer_checkpoint_model": "face.safetensors"},
        },
        {},
        {"txt2img": True, "adetailer": False},
    )
    assert record.config["adetailer"]["adetailer_checkpoint_model"] == "face.safetensors"


@pytest.mark.parametrize("flag", [True, False])
def test_case_e_run_plan_follows_the_compiled_stage_chain(tmp_path: Path, flag: bool) -> None:
    record = _build(
        tmp_path,
        {"pipeline": {"adetailer_enabled": not flag}, "adetailer": {"enabled": not flag}},
        {},
        {"txt2img": True, "adetailer": flag},
    )
    plan = build_run_plan_from_njr(record)
    assert ("adetailer" in plan.enabled_stages) is flag
    assert ("txt2img" in plan.enabled_stages) is True
    _assert_consistent(_view(record), flag)
