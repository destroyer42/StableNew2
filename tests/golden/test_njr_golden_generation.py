"""P4-2A golden NJRs for the generic (Pipeline tab) and PromptPack compile routes.

Frozen as they are on unchanged ``main``: the diff of a golden file is the review artifact for the compiler migration
(``docs/work_packages/P4-2_unified_njr_compiler_migration.md``).  Every id is injected, so no snapshot masks a random
value.  The generic route labels its records ``"kind": "cli"`` (assessment finding X1); that is frozen here, not fixed.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from src.gui.app_state_v2 import PackJobEntry
from src.pipeline.config_variant_plan_v2 import ConfigVariant, ConfigVariantPlanV2
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from tests.golden.test_njr_golden_p4_2 import assert_golden
from tests.helpers.pipeline_fixtures_v2 import make_batch_settings
from tests.image_backends.test_forge_zimage_profile import config as zimage_config
from tests.pipeline.test_prompt_pack_job_builder import (
    SequentialIdGenerator,
    StubConfigManager,
    _write_native_pack,
)
from tests.pipeline.test_zimage_compile_policy import _pack as zimage_pack


def generic_config(**changes: Any) -> dict[str, Any]:
    """A flat, fully explicit merged configuration, as the Pipeline tab hands it to the builder."""

    base: dict[str, Any] = {
        "model": "golden-model.safetensors",
        "prompt": "a lighthouse at dusk",
        "negative_prompt": "blurry",
        "sampler": "Euler",
        "sampler_name": "Euler",
        "scheduler": "Normal",
        "steps": 20,
        "cfg_scale": 7.0,
        "width": 512,
        "height": 512,
        "seed": 4242,
        "txt2img": {
            "model": "golden-model.safetensors",
            "sampler_name": "Euler",
            "scheduler": "Normal",
            "steps": 20,
            "cfg_scale": 7.0,
        },
        "pipeline": {"txt2img_enabled": True},
    }
    base.update(changes)
    return base


def generic_builder() -> JobBuilderV2:
    return JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator())


def test_generic_with_config_variants(tmp_path: Path) -> None:
    plan = ConfigVariantPlanV2(
        enabled=True,
        variants=[
            ConfigVariant("cfg_low", {"txt2img.cfg_scale": 4.0, "cfg_scale": 4.0}, 0),
            ConfigVariant("steps_high", {"txt2img.steps": 35, "steps": 35}, 1),
        ],
    )
    jobs = generic_builder().build_jobs(
        base_config=generic_config(),
        config_variant_plan=plan,
        batch_settings=make_batch_settings(batch_runs=2),
    )
    assert [job.config_variant_label for job in jobs] == [
        "cfg_low",
        "cfg_low",
        "steps_high",
        "steps_high",
    ]
    assert_golden("generic_config_variants", [job.to_dict() for job in jobs], tmp_path)


def test_generic_with_adetailer(tmp_path: Path) -> None:
    base = generic_config(
        prompt="a portrait of three women at a table",
        pipeline={"txt2img_enabled": True, "adetailer_enabled": True},
        adetailer={
            "enabled": True,
            "adetailer_enabled": True,
            "face_mode": "auto",
            "adetailer_model": "face_yolov8n.pt",
            "adetailer_confidence": 0.4,
            "adetailer_steps": 12,
        },
    )
    jobs = generic_builder().build_jobs(base_config=base)
    assert [stage.stage_type for stage in jobs[0].stage_chain] == ["txt2img", "adetailer"]
    assert_golden("generic_adetailer", [job.to_dict() for job in jobs], tmp_path)


def test_generic_with_an_exact_profile(tmp_path: Path) -> None:
    jobs = generic_builder().build_jobs(base_config=zimage_config())
    assert jobs[0].backend_options["image"]["model_profile"]
    assert_golden("generic_exact_profile", [job.to_dict() for job in jobs], tmp_path)


# --------------------------------------------------------------------------------------------------- PromptPack


def _pack_builder(tmp_path: Path) -> tuple[PromptPackNormalizedJobBuilder, StubConfigManager]:
    manager = StubConfigManager(tmp_path)
    builder = PromptPackNormalizedJobBuilder(
        config_manager=manager,
        job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
        packs_dir=manager.packs_dir,
    )
    return builder, manager


def _entry(pack: Path, **changes: Any) -> PackJobEntry:
    values: dict[str, Any] = {
        "pack_id": pack.name,
        "pack_name": "Golden Pack",
        "config_snapshot": {},
        "stage_flags": {"txt2img": True},
        "randomizer_metadata": {"enabled": False},
        "pack_row_index": 0,
    }
    values.update(changes)
    return PackJobEntry(**values)


MATRIX_2X2: dict[str, Any] = {
    "enabled": True,
    "mode": "fanout",
    "limit": 8,
    "slots": [
        {"name": "job", "values": ["wizard", "knight"]},
        {"name": "place", "values": ["forest", "castle"]},
    ],
}


def test_prompt_pack_with_a_2x2_matrix(tmp_path: Path) -> None:
    builder, manager = _pack_builder(tmp_path)
    pack = _write_native_pack(
        manager.packs_dir / "matrix-pack.json", text="A [[job]] in a [[place]]", matrix=MATRIX_2X2
    )
    records = builder.build_jobs([_entry(pack, prompt_text="A [[job]] in a [[place]]")])
    assert [record.matrix_slot_values for record in records] == [
        {"job": "wizard", "place": "forest"},
        {"job": "wizard", "place": "castle"},
        {"job": "knight", "place": "forest"},
        {"job": "knight", "place": "castle"},
    ]
    assert_golden("prompt_pack_matrix_2x2", [record.to_dict() for record in records], tmp_path)


def test_prompt_pack_with_the_randomizer_on(tmp_path: Path) -> None:
    builder, manager = _pack_builder(tmp_path)
    pack = _write_native_pack(
        manager.packs_dir / "random-pack.json",
        text="A [[job]]",
        matrix={
            "enabled": True,
            "mode": "sequential",
            "limit": 2,
            "slots": [{"name": "job", "values": ["wizard", "knight"]}],
        },
    )
    records = builder.build_jobs(
        [
            _entry(
                pack,
                prompt_text="A [[job]]",
                config_snapshot={"randomization_enabled": True, "max_variants": 2, "seed": 123},
            )
        ]
    )
    assert [record.variant_index for record in records] == [0, 1]
    assert_golden("prompt_pack_randomizer", [record.to_dict() for record in records], tmp_path)


def test_prompt_pack_with_one_lora_and_one_embedding(tmp_path: Path) -> None:
    builder, manager = _pack_builder(tmp_path)
    pack = _write_native_pack(
        manager.packs_dir / "adapter-pack.json",
        text="A fox in the snow",
        loras=[["foxstyle", 0.8]],
    )
    data = json.loads(pack.read_text(encoding="utf-8"))
    data["pack_data"]["slots"][0]["positive_embeddings"] = [["goodtoken", 1.0]]
    pack.write_text(json.dumps(data), encoding="utf-8")
    records = builder.build_jobs([_entry(pack, prompt_text="A fox in the snow")])
    assert records[0].lora_tags and records[0].positive_embeddings
    assert_golden("prompt_pack_lora_embedding", [record.to_dict() for record in records], tmp_path)


def test_prompt_pack_with_an_exact_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    builder, entry, _path, _original = zimage_pack(tmp_path, monkeypatch)
    records = builder.build_jobs([entry])
    assert records[0].backend_options["image"]["model_profile"]
    assert_golden("prompt_pack_exact_profile", [record.to_dict() for record in records], tmp_path)


def test_prompt_pack_exact_profile_adapts_unsupported_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact profile drops what it cannot run; the frozen record shows the second policy application's result.

    This is the route where assessment finding X2 (the model policy runs in ``_prepare_entry`` and again in
    ``JobBuilderV2``) is observable, so the record is pinned with a LoRA and an embedding present.
    """

    builder, entry, _path, _original = zimage_pack(
        tmp_path,
        monkeypatch,
        loras=[["adapter", 0.7]],
        positive_embeddings=[["token", 1]],
    )
    records = builder.build_jobs([entry])
    assert not records[0].lora_tags
    assert_golden(
        "prompt_pack_exact_profile_adapted", [record.to_dict() for record in records], tmp_path
    )


def test_the_prompt_pack_goldens_are_built_from_unmodified_input(tmp_path: Path) -> None:
    config = generic_config()
    before = deepcopy(config)
    generic_builder().build_jobs(base_config=config)
    assert config == before
