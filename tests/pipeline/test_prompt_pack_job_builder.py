from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from src.gui.app_state_v2 import PackJobEntry
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.prompt_pack_parser import parse_prompt_pack_text
from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from src.training.lora_manager import LoRAManager
from src.training.style_lora_manager import StyleLoRAManager
from src.utils.config import ConfigManager
from src.utils.prompt_pack_utils import load_pack_metadata

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
    assert record.intent_config["prompt_source"] == "pack"
    assert record.intent_config["prompt_pack_id"] == "preview-pack"
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


def test_prompt_pack_job_builder_auto_limits_unbounded_matrix_expansion(tmp_path: Path) -> None:
    config_manager = StubConfigManager(tmp_path)
    pack_txt = config_manager.packs_dir / "unbounded-matrix-pack.txt"
    pack_txt.write_text("A [[job]] in a [[environment]] with [[lighting]]", encoding="utf-8")
    pack_txt.with_suffix(".json").write_text(
        json.dumps(
            {
                "pack_data": {
                    "matrix": {
                        "enabled": True,
                        "mode": "sequential",
                        "limit": 0,
                        "slots": [
                            {"name": "job", "values": [f"job{i}" for i in range(10)]},
                            {"name": "environment", "values": [f"env{i}" for i in range(10)]},
                            {"name": "lighting", "values": [f"light{i}" for i in range(10)]},
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
        pack_name="Unbounded Matrix Pack",
        prompt_text="A [[job]] in a [[environment]] with [[lighting]]",
        config_snapshot={"randomization": {"enabled": False}},
        stage_flags={"txt2img": True},
        randomizer_metadata={"enabled": False, "max_variants": 0},
    )

    expanded = builder._expand_entry_by_matrix(entry)  # noqa: SLF001

    assert len(expanded) == 8
    assert expanded[0].matrix_slot_values == {
        "job": "job0",
        "environment": "env0",
        "lighting": "light0",
    }


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


def test_prompt_pack_job_builder_caches_pack_rows_metadata_and_resolved_config(
    tmp_path: Path, monkeypatch
) -> None:
    config_manager = StubConfigManager(tmp_path)
    pack_txt = config_manager.packs_dir / "cached-pack.txt"
    pack_txt.write_text("A hero in a forest", encoding="utf-8")
    pack_txt.with_suffix(".json").write_text(
        json.dumps({"pack_data": {"matrix": {"enabled": False, "slots": []}}}),
        encoding="utf-8",
    )

    parse_calls = {"count": 0}
    metadata_calls = {"count": 0}
    load_config_calls = {"count": 0}
    resolve_calls = {"count": 0}

    original_parse = parse_prompt_pack_text
    original_metadata = load_pack_metadata
    original_load_config = config_manager.load_pack_config
    original_resolve = config_manager.resolve_config

    def counted_parse(content: str):
        parse_calls["count"] += 1
        return original_parse(content)

    def counted_metadata(path):
        metadata_calls["count"] += 1
        return original_metadata(path)

    def counted_load_config(pack_id: str):
        load_config_calls["count"] += 1
        return original_load_config(pack_id)

    def counted_resolve(*, pack_overrides=None, runtime_params=None):
        resolve_calls["count"] += 1
        return original_resolve(pack_overrides=pack_overrides, runtime_params=runtime_params)

    monkeypatch.setattr("src.pipeline.prompt_pack_job_builder.parse_prompt_pack_text", counted_parse)
    monkeypatch.setattr("src.pipeline.prompt_pack_job_builder.load_pack_metadata", counted_metadata)
    monkeypatch.setattr(config_manager, "load_pack_config", counted_load_config)
    monkeypatch.setattr(config_manager, "resolve_config", counted_resolve)

    builder = PromptPackNormalizedJobBuilder(
        config_manager=config_manager,
        job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
        packs_dir=config_manager.packs_dir,
    )
    entry = PackJobEntry(
        pack_id=pack_txt.name,
        pack_name="Cached Pack",
        prompt_text="A hero in a forest",
        config_snapshot={"randomization": {"enabled": False}},
        stage_flags={"txt2img": True},
        randomizer_metadata={"enabled": False, "max_variants": 1},
    )

    first = builder.build_jobs([entry])
    second = builder.build_jobs([entry])

    assert first and second
    assert parse_calls["count"] == 1
    assert metadata_calls["count"] == 1
    assert load_config_calls["count"] == 1
    assert resolve_calls["count"] == 1


def test_prompt_pack_job_builder_omits_inactive_txt2img_hires_fields_from_execution_config(
    tmp_path: Path,
) -> None:
    builder = PromptPackNormalizedJobBuilder(
        config_manager=StubConfigManager(tmp_path),
        job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
    )
    entry = PackJobEntry(
        pack_id="hires-disabled-pack",
        pack_name="Hires Disabled Pack",
        prompt_text="A portrait",
        config_snapshot={
            "txt2img": {
                "enable_hr": False,
                "hr_scale": 1.8,
                "hr_upscaler": "Latent",
                "denoising_strength": 0.42,
                "hr_second_pass_steps": 12,
            },
            "hires_fix": {
                "enabled": False,
                "upscale_factor": 1.8,
                "upscaler_name": "Latent",
                "denoise": 0.42,
                "steps": 12,
            },
        },
        stage_flags={"txt2img": True},
        randomizer_metadata={"enabled": False},
        pack_row_index=0,
        matrix_slot_values={},
    )

    records = builder.build_jobs([entry])

    assert records
    record = records[0]
    assert record.config["enable_hr"] is False
    assert "hr_scale" not in record.config
    assert "hr_upscaler" not in record.config
    assert "denoising_strength" not in record.config
    assert "hr_second_pass_steps" not in record.config
    assert record.config["hires_fix"]["denoise"] == 0.42
    assert record.stage_chain[0].denoising_strength is None
    assert "hires_steps" not in record.stage_chain[0].extra


def test_prompt_pack_job_builder_preserves_adaptive_refinement_intent(tmp_path: Path) -> None:
    builder = PromptPackNormalizedJobBuilder(
        config_manager=StubConfigManager(tmp_path),
        job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
    )
    entry = PackJobEntry(
        pack_id="refinement-pack",
        pack_name="Refinement Pack",
        prompt_text="A portrait",
        config_snapshot={
            "adaptive_refinement": {
                "schema": "stablenew.adaptive-refinement.v1",
                "enabled": True,
                "mode": "observe",
                "profile_id": "auto_v1",
                "detector_preference": "null",
                "record_decisions": True,
                "algorithm_version": "v1",
            }
        },
        stage_flags={"txt2img": True},
        randomizer_metadata={"enabled": False},
        pack_row_index=0,
        matrix_slot_values={},
    )

    records = builder.build_jobs([entry])

    assert records
    assert records[0].intent_config["adaptive_refinement"]["enabled"] is True
    assert records[0].intent_config["adaptive_refinement"]["mode"] == "observe"


def test_prompt_pack_job_builder_preserves_secondary_motion_intent(tmp_path: Path) -> None:
    builder = PromptPackNormalizedJobBuilder(
        config_manager=StubConfigManager(tmp_path),
        job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
    )
    entry = PackJobEntry(
        pack_id="motion-pack",
        pack_name="Motion Pack",
        prompt_text="A portrait",
        config_snapshot={
            "secondary_motion": {
                "schema": "stablenew.secondary-motion.v1",
                "enabled": True,
                "mode": "observe",
                "intent": "micro_sway",
                "regions": ["hair"],
                "allow_prompt_bias": False,
                "allow_native_backend": False,
                "record_decisions": True,
                "algorithm_version": "v1",
            }
        },
        stage_flags={"txt2img": True},
        randomizer_metadata={"enabled": False},
        pack_row_index=0,
        matrix_slot_values={},
    )

    records = builder.build_jobs([entry])

    assert records
    assert records[0].intent_config["secondary_motion"]["enabled"] is True
    assert records[0].intent_config["secondary_motion"]["mode"] == "observe"


def test_prompt_pack_job_builder_preserves_extended_adetailer_stage_contract(
    tmp_path: Path,
) -> None:
    builder = PromptPackNormalizedJobBuilder(
        config_manager=StubConfigManager(tmp_path),
        job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
    )
    entry = PackJobEntry(
        pack_id="adetailer-pack",
        pack_name="ADetailer Pack",
        prompt_text="A portrait",
        config_snapshot={
            "pipeline": {"adetailer_enabled": True},
            "adetailer": {
                "adetailer_enabled": True,
                "adetailer_checkpoint_model": "juggernautXL_ragnarokBy.safetensors",
                "enable_face_pass": False,
                "enable_hands_pass": True,
                "adetailer_hands_model": "hand_yolov8s.pt",
                "adetailer_hands_scheduler": "inherit",
                "ad_hands_inpaint_only_masked": False,
                "ad_hands_inpaint_width": 640,
                "ad_hands_inpaint_height": 896,
            },
        },
        stage_flags={"txt2img": True, "adetailer": True},
        randomizer_metadata={"enabled": False},
        pack_row_index=0,
        matrix_slot_values={},
    )

    records = builder.build_jobs([entry])

    assert records
    adetailer_stage = next(stage for stage in records[0].stage_chain if stage.stage_type == "adetailer")
    assert adetailer_stage.model is None
    assert adetailer_stage.scheduler is None
    assert adetailer_stage.extra["adetailer_checkpoint_model"] == "juggernautXL_ragnarokBy.safetensors"
    assert adetailer_stage.extra["enable_face_pass"] is False
    assert adetailer_stage.extra["enable_hands_pass"] is True
    assert adetailer_stage.extra["adetailer_hands_model"] == "hand_yolov8s.pt"
    assert adetailer_stage.extra["ad_hands_inpaint_only_masked"] is False
    assert adetailer_stage.extra["ad_hands_inpaint_width"] == 640
    assert adetailer_stage.extra["ad_hands_inpaint_height"] == 896


def test_prompt_pack_job_builder_injects_actor_tokens_and_actor_loras_from_plan_origin(
    tmp_path: Path,
) -> None:
    config_manager = StubConfigManager(tmp_path)
    pack_txt = config_manager.packs_dir / "actor-pack.txt"
    pack_txt.write_text(
        "cinematic quality\nportrait on a [[environment]]\n<lora:pack_style:0.45>",
        encoding="utf-8",
    )

    weights_dir = tmp_path / "weights"
    weights_dir.mkdir()
    ada_weight = weights_dir / "ada.safetensors"
    bran_weight = weights_dir / "bran.safetensors"
    ada_weight.write_bytes(b"ada")
    bran_weight.write_bytes(b"bran")
    lora_manager = LoRAManager(base_dir=tmp_path / "manifest")
    lora_manager.register(
        character_name="Ada",
        weight_path=ada_weight,
        metadata={"trigger_phrase": "ada person"},
    )
    lora_manager.register(
        character_name="Bran",
        weight_path=bran_weight,
        metadata={"trigger_phrase": "bran ranger"},
    )

    builder = PromptPackNormalizedJobBuilder(
        config_manager=config_manager,
        job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
        packs_dir=config_manager.packs_dir,
        lora_manager=lora_manager,
    )
    entry = PackJobEntry(
        pack_id=pack_txt.name,
        pack_name="Actor Pack",
        config_snapshot={
            "plan_origin": {
                "plan_id": "story-001",
                "scene_id": "scene-001",
                "shot_id": "shot-001",
                "actors": [
                    {"name": "Ada", "character_name": "Ada", "weight": 0.8},
                    {"name": "Bran", "character_name": "Bran"},
                ],
            }
        },
        stage_flags={"txt2img": True},
        randomizer_metadata={"enabled": False},
        pack_row_index=0,
        matrix_slot_values={"environment": "rooftop"},
    )

    records = builder.build_jobs([entry])

    assert records
    record = records[0]
    assert "ada person, bran ranger" in record.positive_prompt
    assert [tag.name for tag in record.lora_tags] == ["ada", "bran", "pack_style"]
    assert [tag.weight for tag in record.lora_tags] == [0.8, 1.0, 0.45]
    assert record.extra_metadata["actors"][0]["trigger_phrase"] == "ada person"
    assert record.extra_metadata["plan_origin"]["shot_id"] == "shot-001"
    assert record.intent_config["plan_origin"]["actors"][0]["character_name"] == "Ada"


def _write_style_catalog(tmp_path: Path, *, missing_file: bool = False) -> tuple[Path, Path]:
    weight_path = tmp_path / "style_cinematic_grit.safetensors"
    if not missing_file:
        weight_path.write_bytes(b"style")
    catalog_path = tmp_path / "style_loras.json"
    catalog_path.write_text(
        json.dumps(
            {
                "styles": [
                    {
                        "style_id": "cinematic_grit",
                        "display_name": "Cinematic Grit",
                        "trigger_phrase": "cinematic grit lighting",
                        "lora_name": "style_cinematic_grit",
                        "weight": 0.65,
                        "file_path": str(weight_path),
                        "compatible_model_families": ["sdxl"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return catalog_path, weight_path


def test_prompt_pack_job_builder_applies_pack_level_style_lora(tmp_path: Path) -> None:
    config_manager = StubConfigManager(tmp_path)
    config_manager._config["style_lora"] = {"enabled": True, "style_id": "cinematic_grit"}
    config_manager._config["txt2img"]["model"] = "juggernautXL.safetensors"
    catalog_path, _weight_path = _write_style_catalog(tmp_path)

    builder = PromptPackNormalizedJobBuilder(
        config_manager=config_manager,
        job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
        style_lora_manager=StyleLoRAManager(catalog_path=catalog_path, webui_root=None),
    )
    entry = PackJobEntry(
        pack_id="styled-pack",
        pack_name="Styled Pack",
        prompt_text="A portrait at dusk",
        config_snapshot={},
        stage_flags={"txt2img": True},
        randomizer_metadata={"enabled": False},
        pack_row_index=0,
        matrix_slot_values={},
    )

    records = builder.build_jobs([entry])

    assert records
    record = records[0]
    assert "cinematic grit lighting" in record.positive_prompt
    assert record.lora_tags[-1].name == "style_cinematic_grit"
    assert record.lora_tags[-1].weight == 0.65
    assert record.extra_metadata["style_lora"]["style_id"] == "cinematic_grit"
    assert record.extra_metadata["style_lora"]["applied"] is True
    assert record.config["style_lora"]["applied"] is True


def test_prompt_pack_job_builder_warns_when_pack_level_style_lora_is_unavailable(tmp_path: Path) -> None:
    config_manager = StubConfigManager(tmp_path)
    config_manager._config["style_lora"] = {"enabled": True, "style_id": "cinematic_grit"}
    config_manager._config["txt2img"]["model"] = "juggernautXL.safetensors"
    catalog_path, _weight_path = _write_style_catalog(tmp_path, missing_file=True)

    builder = PromptPackNormalizedJobBuilder(
        config_manager=config_manager,
        job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
        style_lora_manager=StyleLoRAManager(catalog_path=catalog_path, webui_root=None),
    )
    entry = PackJobEntry(
        pack_id="styled-pack",
        pack_name="Styled Pack",
        prompt_text="A portrait at dusk",
        config_snapshot={},
        stage_flags={"txt2img": True},
        randomizer_metadata={"enabled": False},
        pack_row_index=0,
        matrix_slot_values={},
    )

    records = builder.build_jobs([entry])

    assert records
    record = records[0]
    assert "cinematic grit lighting" not in record.positive_prompt
    assert all(tag.name != "style_cinematic_grit" for tag in record.lora_tags)
    assert record.extra_metadata["style_lora"]["applied"] is False
    assert "missing weight file" in str(record.extra_metadata["style_lora"]["warning"])
