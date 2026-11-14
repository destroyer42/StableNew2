"""How often each shared compile step runs per generic and PromptPack record (P4-2E, decision option 4).

The generic route builds ``RAW`` drafts: the core runs every shared step once per record. The PromptPack route prepares
its own values and hands the core ``EFFECTIVE`` drafts: one construction, one exact-profile check and one backend-option
normalization per record, one ADetailer compile per prepared prompt, one intent canonicalization per record.

The model compile policy deliberately runs twice for PromptPack work, once per configuration *shape*: on the nested
resolved configuration in ``_prepare_entry`` (once per prepared prompt: it feeds the stage chain and refuses before the
Klein review) and on the flat payload the record carries (once per record, through ``njr_compiler.prepare_image_config``:
it is what ``workload.config`` freezes). Neither can be removed without changing the record, which the characterization
tests below pin (``docs/work_packages/P4-2_unified_njr_compiler_migration.md``, P4-2E status).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pytest

import src.pipeline.prompt_pack_job_builder as pack_module
from src.pipeline import njr_compiler
from src.pipeline.config_variant_plan_v2 import ConfigVariant, ConfigVariantPlanV2
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.njr_compiler import CompileCheck
from tests.golden.test_njr_golden_generation import generic_config
from tests.helpers.pipeline_fixtures_v2 import make_batch_settings
from tests.pipeline.test_klein_compile_policy import KLEIN, _pack_job
from tests.pipeline.test_prompt_pack_job_builder import (
    BASE_PACK_CONFIG,
    SequentialIdGenerator,
    StubConfigManager,
    _write_native_pack,
)
from tests.pipeline.test_zimage_compile_policy import _pack as zimage_pack

CORE_STEPS = (
    "prepare_effective_config",
    "apply_model_compile_policy",
    "compile_adetailer",
    "normalize_image_backend_options",
    "canonicalize_intent_config",
)
PACK_STEPS = (
    "apply_model_compile_policy",
    "normalize_profile_owned_values",
    "compile_adetailer",
    "normalize_image_backend_options",
    "canonicalize_intent_config",
)


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> Counter[str]:
    """Count every shared step by where it runs: ``core.*`` in the assembly core, ``pack.*`` in the PromptPack planner."""

    counter: Counter[str] = Counter()

    def count(module: Any, name: str, label: str) -> None:
        original = getattr(module, name)

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            counter[label] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(module, name, wrapped)

    for name in CORE_STEPS:
        count(njr_compiler, name, f"core.{name}")
    for name in PACK_STEPS:
        count(pack_module, name, f"pack.{name}")
    count(njr_compiler, "NormalizedJobRecord", "construct")
    check = njr_compiler._CHECKS[CompileCheck.PROFILE_NJR]

    def profile_check(record: Any) -> None:
        counter["check.profile_njr"] += 1
        check(record)

    monkeypatch.setitem(njr_compiler._CHECKS, CompileCheck.PROFILE_NJR, profile_check)  # type: ignore[index]
    return counter


def _generic_builder() -> JobBuilderV2:
    return JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator())


def _pack_records(tmp_path: Path, *, loop_count: int = 1, matrix: dict[str, Any] | None = None) -> list[Any]:
    manager = StubConfigManager(tmp_path)
    manager._config = {**BASE_PACK_CONFIG, "pipeline": {**BASE_PACK_CONFIG["pipeline"], "loop_count": loop_count}}
    text = "A [[job]] in the snow" if matrix else "A fox in the snow"
    pack = _write_native_pack(manager.packs_dir / "count-pack.json", text=text, matrix=matrix)
    builder = pack_module.PromptPackNormalizedJobBuilder(
        config_manager=manager, job_builder=_generic_builder(), packs_dir=manager.packs_dir
    )
    entry = pack_module.PackJobEntry(
        pack_id=pack.name, pack_name="Count Pack", prompt_text=text, config_snapshot={},
        stage_flags={"txt2img": True}, randomizer_metadata={"enabled": False}, pack_row_index=0,
    )
    return builder.build_jobs([entry])


# ------------------------------------------------------------------------------------------------------------ generic


def test_a_generic_record_runs_each_shared_step_once_in_the_core(calls: Counter[str]) -> None:
    plan = ConfigVariantPlanV2(
        enabled=True,
        variants=[ConfigVariant("a", {"cfg_scale": 4.0}, 0), ConfigVariant("b", {"steps": 35}, 1)],
    )
    jobs = _generic_builder().build_jobs(
        base_config=generic_config(), config_variant_plan=plan, batch_settings=make_batch_settings(batch_runs=2)
    )

    assert len(jobs) == 4
    assert {name: calls[f"core.{name}"] for name in CORE_STEPS} == {
        "prepare_effective_config": 4,
        "apply_model_compile_policy": 4,
        "compile_adetailer": 0,  # stage-conditional: ADetailer is not enabled in this configuration
        "normalize_image_backend_options": 4,
        "canonicalize_intent_config": 4,
    }
    assert (calls["construct"], calls["check.profile_njr"]) == (4, 4)


def test_a_generic_record_with_adetailer_compiles_it_once(calls: Counter[str]) -> None:
    jobs = _generic_builder().build_jobs(
        base_config=generic_config(
            prompt="a portrait of three women at a table",
            pipeline={"txt2img_enabled": True, "adetailer_enabled": True},
            adetailer={"enabled": True, "face_mode": "auto"},
        )
    )

    assert [stage.stage_type for stage in jobs[0].stage_chain] == ["txt2img", "adetailer"]
    assert calls["core.compile_adetailer"] == 1
    assert calls["core.apply_model_compile_policy"] == 1


# --------------------------------------------------------------------------------------------------------- PromptPack


@pytest.mark.parametrize("loop_count", [1, 3])
def test_a_prompt_pack_record_is_constructed_checked_and_normalized_once(
    tmp_path: Path, calls: Counter[str], loop_count: int
) -> None:
    records = _pack_records(tmp_path, loop_count=loop_count)

    assert len(records) == loop_count
    assert calls["construct"] == loop_count  # no discarded intermediate record
    assert calls["check.profile_njr"] == loop_count
    assert calls["pack.normalize_image_backend_options"] == loop_count
    assert calls["core.normalize_image_backend_options"] == 0
    assert calls["pack.canonicalize_intent_config"] == loop_count
    assert calls["core.canonicalize_intent_config"] == 0
    # once per prepared prompt: the batch runs of one prompt share it
    assert calls["pack.compile_adetailer"] == 1
    assert calls["core.compile_adetailer"] == 0


@pytest.mark.parametrize("loop_count", [1, 3])
def test_the_prompt_pack_compile_policy_runs_once_per_configuration_shape(
    tmp_path: Path, calls: Counter[str], loop_count: int
) -> None:
    records = _pack_records(tmp_path, loop_count=loop_count)

    assert len(records) == loop_count
    assert calls["pack.apply_model_compile_policy"] == 1  # nested shape: once per prepared prompt
    assert calls["core.apply_model_compile_policy"] == loop_count  # flat payload: once per record
    assert calls["core.prepare_effective_config"] == loop_count


def test_each_matrix_variant_is_one_prepared_prompt(tmp_path: Path, calls: Counter[str]) -> None:
    matrix = {"enabled": True, "mode": "fanout", "limit": 8,
              "slots": [{"name": "job", "values": ["wizard", "knight", "bard"]}]}
    records = _pack_records(tmp_path, loop_count=2, matrix=matrix)

    assert len(records) == 6
    assert calls["pack.apply_model_compile_policy"] == 3
    assert calls["pack.compile_adetailer"] == 3
    assert calls["core.apply_model_compile_policy"] == 6
    assert (calls["construct"], calls["check.profile_njr"], calls["pack.normalize_image_backend_options"]) == (6, 6, 6)


# --------------------------------------------- characterization: what each of the two PromptPack applications produces


def test_the_nested_application_produces_the_stage_chain_profile_values(tmp_path: Path) -> None:
    """Klein: the stage chain is built from the nested configuration after its policy application (user values replaced)."""

    record = _pack_job(tmp_path, KLEIN)
    txt2img = record.stage_chain[0]

    assert (txt2img.stage_type, txt2img.scheduler, txt2img.steps, txt2img.cfg_scale) == ("txt2img", "Beta", 4, 1.0)


def test_the_flat_application_produces_the_records_profile_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Z-Image: ``workload.config`` holds what the policy adds to the flat payload: the flattening drops these keys."""

    builder, entry, _path, _original = zimage_pack(tmp_path, monkeypatch)
    config = builder.build_jobs([entry])[0].config

    assert config["backend_options"]["image"]["model_profile"] == {"id": "z_image_turbo_fp8_scaled", "version": 1}
    assert config["txt2img"]["distilled_cfg_scale"] == config["distilled_cfg_scale"] == 9.0
    assert config["sampler_name"] == config["txt2img"]["sampler_name"] == "Euler"
    assert config["global_prompt_policy_source"] == "frozen_njr"  # the planner had written "legacy_runtime_fallback"
    assert config["vae"] == ""  # effective-config preparation of the flat payload; the flattening copied None


def test_removing_the_nested_application_would_change_the_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
    expected = _pack_job(tmp_path / "a", KLEIN).to_dict()["stages"]
    monkeypatch.setattr(pack_module, "apply_model_compile_policy", lambda config: config)

    stages = _pack_job(tmp_path / "b", KLEIN).to_dict()["stages"]
    assert (stages[0]["scheduler"], stages[0]["steps"]) == ("DDIM", 24)  # the user's values would reach the stage
    assert (expected[0]["scheduler"], expected[0]["steps"]) == ("Beta", 4)


def test_removing_the_flat_application_would_change_the_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
    builder, entry, _path, _original = zimage_pack(tmp_path / "a", monkeypatch)
    expected = builder.build_jobs([entry])[0].config
    monkeypatch.setattr(njr_compiler, "apply_model_compile_policy", lambda config: config)
    builder, entry, _path, _original = zimage_pack(tmp_path / "b", monkeypatch)
    config = builder.build_jobs([entry])[0].config

    added = ("txt2img", "backend_options", "distilled_cfg_scale", "sampler_name")
    assert all(key in expected for key in added)
    assert [key for key in added if key in config] == []
    assert config["global_prompt_policy_source"] == "legacy_runtime_fallback"
