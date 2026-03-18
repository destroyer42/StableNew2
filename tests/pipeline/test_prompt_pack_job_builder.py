from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from src.gui.app_state_v2 import PackJobEntry
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from src.utils.config import ConfigManager

BASE_PACK_CONFIG: dict[str, Any] = {
    "pipeline": {
        "images_per_prompt": 1,
        "loop_count": 1,
        "loop_type": "pipeline",
        "variant_mode": "standard",
        "apply_global_negative_txt2img": True,
    },
    "txt2img": {
        "model": "model.safetensors",
        "sampler_name": "Euler",
        "scheduler": "DDIM",
        "steps": 24,
        "cfg_scale": 7.5,
        "width": 512,
        "height": 512,
        "negative_prompt": "",
    },
    "randomization": {"enabled": False},
    "aesthetic": {"enabled": False},
}


class StubConfigManager(ConfigManager):
    def __init__(self, tmp_path: Path) -> None:
        super().__init__(presets_dir=tmp_path / "presets")
        self.packs_dir = tmp_path / "packs"
        self.packs_dir.mkdir(parents=True, exist_ok=True)
        self._config = dict(BASE_PACK_CONFIG)

    def load_pack_config(self, pack_id: str) -> dict[str, Any] | None:
        return dict(self._config)

    def resolve_config(
        self,
        *,
        pack_overrides: dict[str, Any] | None = None,
        runtime_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        merged: dict[str, Any] = dict(self._config)
        if pack_overrides:
            merged.update(pack_overrides)
        if runtime_params:
            merged.update(runtime_params)
        return merged

    def get_global_negative_prompt(self) -> str:
        return "global-negative"


@dataclass
class SequentialIdGenerator:
    """Simple deterministic ID generator for JobBuilderV2 tests."""

    counter: int = 0

    def __call__(self) -> str:
        self.counter += 1
        return f"job-{self.counter}"


def test_prompt_pack_job_builder_creates_normalized_jobs() -> None:
    builder = PromptPackNormalizedJobBuilder(
        config_manager=ConfigManager(),
        job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
    )

    entry = PackJobEntry(
        pack_id="SDXL_angelic_warriors_Realistic",
        pack_name="SDXL_angelic_warriors_Realistic",
        config_snapshot={"randomization": {"enabled": False}},
        stage_flags={"txt2img": True},
        randomizer_metadata={"enabled": False, "max_variants": 1},
    )

    records = builder.build_jobs([entry])
    assert records, "Builder should produce at least one normalized job record"

    record = records[0]
    assert record.prompt_pack_id == entry.pack_id
    assert "angelic knight" in record.positive_prompt.lower()
    assert record.stage_chain[0].stage_type == "txt2img"
    assert record.randomization_enabled is False
    assert record.pack_usage and record.pack_usage[0].pack_name == entry.pack_name


def test_prompt_pack_job_builder_populates_preview_fields(tmp_path: Path) -> None:
    builder = PromptPackNormalizedJobBuilder(
        config_manager=StubConfigManager(tmp_path),
        job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
    )
    entry = PackJobEntry(
        pack_id="preview-pack",
        pack_name="Preview Pack",
        config_snapshot={"txt2img": {"model": "model.safetensors"}},
        prompt_text="A sorceress in lightning armor",
        stage_flags={"txt2img": True},
        randomizer_metadata={"enabled": False},
        pack_row_index=0,
        matrix_slot_values={},
    )
    records = builder.build_jobs([entry])
    assert records, "Builder should still produce records for preview tests"
    record = records[0]
    assert record.base_model == "model.safetensors"
    assert "sorceress" in record.positive_prompt.lower()
    assert any(stage.stage_type == "txt2img" for stage in record.stage_chain)


def test_prompt_pack_job_builder_random_matrix_mode_shuffles_combinations(tmp_path: Path) -> None:
    config_manager = StubConfigManager(tmp_path)
    pack_txt = config_manager.packs_dir / "random-matrix-pack.txt"
    pack_txt.write_text("A [[job]] in a [[environment]]", encoding="utf-8")
    pack_json = pack_txt.with_suffix(".json")
    pack_json.write_text(
        json.dumps(
            {
                "pack_data": {
                    "matrix": {
                        "enabled": True,
                        "mode": "random",
                        "limit": 3,
                        "slots": [
                            {"name": "job", "values": ["wizard", "knight", "archer"]},
                            {"name": "environment", "values": ["forest", "castle"]},
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    builder = PromptPackNormalizedJobBuilder(
        config_manager=config_manager,
        job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
        packs_dir=config_manager.packs_dir,
    )
    entry = PackJobEntry(
        pack_id=pack_txt.name,
        pack_name="Random Matrix Pack",
        prompt_text="A [[job]] in a [[environment]]",
        config_snapshot={"randomization": {"enabled": False}},
        stage_flags={"txt2img": True},
        randomizer_metadata={"enabled": False, "max_variants": 1},
    )

    expanded = builder._expand_entry_by_matrix(entry)  # noqa: SLF001

    assert len(expanded) == 3
    unique_pairs = {
        (item.matrix_slot_values.get("job"), item.matrix_slot_values.get("environment"))
        for item in expanded
    }
    assert len(unique_pairs) == 3


def test_prompt_pack_job_builder_orders_adetailer_before_upscale(tmp_path: Path) -> None:
    builder = PromptPackNormalizedJobBuilder(
        config_manager=StubConfigManager(tmp_path),
        job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
    )
    entry = PackJobEntry(
        pack_id="ordered-pack",
        pack_name="Ordered Pack",
        prompt_text="A portrait",
        config_snapshot={
            "pipeline": {
                "adetailer_enabled": True,
                "upscale_enabled": True,
            },
            "adetailer": {"enabled": True, "adetailer_enabled": True},
            "upscale": {"enabled": True, "upscaler": "R-ESRGAN 4x+"},
        },
        stage_flags={"txt2img": True, "adetailer": True, "upscale": True},
        randomizer_metadata={"enabled": False},
        pack_row_index=0,
        matrix_slot_values={},
    )

    records = builder.build_jobs([entry])

    assert records
    record = records[0]
    assert [stage.stage_type for stage in record.stage_chain if stage.enabled] == [
        "txt2img",
        "adetailer",
        "upscale",
    ]
