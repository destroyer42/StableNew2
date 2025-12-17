"""Builder pipeline that converts PromptPack entries into NormalizedJobRecords."""

from __future__ import annotations

import copy
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from src.gui.app_state_v2 import PackJobEntry
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.job_models_v2 import (
    BatchSettings,
    LoRATag,
    NormalizedJobRecord,
    OutputSettings,
    PackUsageInfo,
    StageConfig,
)
from src.pipeline.prompt_pack_parser import PackRow, parse_prompt_pack_text
from src.pipeline.resolution_layer import UnifiedConfigResolver, UnifiedPromptResolver
from src.randomizer import RandomizationPlanV2, RandomizationSeedMode
from src.utils.config import ConfigManager

_logger = logging.getLogger(__name__)


class PromptPackNormalizedJobBuilder:
    """Orchestrates prompt pack → job construction pipeline."""

    def __init__(
        self,
        *,
        config_manager: ConfigManager,
        job_builder: JobBuilderV2,
        prompt_resolver: UnifiedPromptResolver | None = None,
        config_resolver: UnifiedConfigResolver | None = None,
        packs_dir: Path | str = "packs",
    ) -> None:
        self._config_manager = config_manager
        self._job_builder = job_builder
        self._prompt_resolver = prompt_resolver or UnifiedPromptResolver()
        self._config_resolver = config_resolver or UnifiedConfigResolver()
        self._packs_dir = Path(packs_dir)

    def build_jobs(self, entries: Iterable[PackJobEntry]) -> list[NormalizedJobRecord]:
        records: list[NormalizedJobRecord] = []
        for entry in entries:
            if not entry.pack_id:
                _logger.warning("Pack entry missing pack_id, skipping")
                continue
            jobs = self._build_jobs_for_entry(entry)
            if jobs:
                records.extend(jobs)
        return records

    def _build_jobs_for_entry(self, entry: PackJobEntry) -> list[NormalizedJobRecord]:
        pack_config = self._load_pack_config(entry.pack_id)
        if pack_config is None:
            _logger.error("Missing config for pack '%s', skipping entry", entry.pack_id)
            return []

        runtime_params = dict(entry.config_snapshot or {})
        merged_config = copy.deepcopy(
            self._config_manager.resolve_config(
                pack_overrides=pack_config, runtime_params=runtime_params
            )
        )
        stage_flags = self._normalize_stage_flags(
            merged_config.get("pipeline", {}), entry.stage_flags or {}
        )
        randomizer_metadata = entry.randomizer_metadata or {}

        stage_chain = self._build_stage_chain(merged_config, stage_flags)
        prompt_resolution = self._resolve_prompt(entry, merged_config)
        config_for_builder = self._build_config_payload(
            entry, merged_config, prompt_resolution, stage_chain
        )

        randomizer_plan = self._build_randomizer_plan(entry, merged_config)
        batch_settings = self._build_batch_settings(merged_config)

        jobs = self._job_builder.build_jobs(
            base_config=config_for_builder,
            randomization_plan=randomizer_plan,
            batch_settings=batch_settings,
            output_settings=OutputSettings(),
        )

        pipeline_section = merged_config.get("pipeline", {})
        aesthetic_section = merged_config.get("aesthetic", {})
        matrix_section = merged_config.get("randomization", {}).get("matrix", {})
        txt2img = merged_config.get("txt2img", {})
        pack_path = self._resolve_pack_text_path(entry.pack_id)

        for record in jobs:
            record.prompt_pack_id = entry.pack_id
            record.prompt_pack_name = entry.pack_name or entry.pack_id
            record.prompt_pack_row_index = entry.pack_row_index or 0
            record.prompt_pack_version = pack_config.get("version")
            record.positive_prompt = prompt_resolution.positive
            record.negative_prompt = prompt_resolution.negative
            record.positive_embeddings = list(prompt_resolution.positive_embeddings)
            record.negative_embeddings = list(prompt_resolution.negative_embeddings)
            record.lora_tags = [
                LoRATag(name=name, weight=weight) for name, weight in prompt_resolution.lora_tags
            ]
            record.matrix_slot_values = dict(entry.matrix_slot_values or {})
            record.stage_chain = copy.deepcopy(stage_chain)
            record.steps = int(txt2img.get("steps") or 0)
            record.cfg_scale = float(txt2img.get("cfg_scale") or 0.0)
            record.width = int(txt2img.get("width") or 0)
            record.height = int(txt2img.get("height") or 0)
            record.sampler_name = txt2img.get("sampler_name") or txt2img.get("sampler") or ""
            record.scheduler = txt2img.get("scheduler") or ""
            record.clip_skip = int(txt2img.get("clip_skip") or 0)
            record.base_model = txt2img.get("model") or ""
            record.vae = txt2img.get("vae") or None
            record.images_per_prompt = int(pipeline_section.get("images_per_prompt", 1))
            record.loop_type = pipeline_section.get("loop_type", "pipeline")
            record.loop_count = int(pipeline_section.get("loop_count", 1) or 1)
            record.variant_mode = pipeline_section.get("variant_mode", "standard") or "standard"
            record.randomization_enabled = bool(
                randomizer_metadata.get("enabled")
                or merged_config.get("randomization", {}).get("enabled")
            )
            record.matrix_mode = matrix_section.get("mode")
            record.matrix_prompt_mode = matrix_section.get("prompt_mode")
            record.matrix_name = matrix_section.get("name")
            record.aesthetic_enabled = bool(aesthetic_section.get("enabled"))
            record.aesthetic_weight = aesthetic_section.get("weight")
            record.aesthetic_text = aesthetic_section.get("text")
            record.aesthetic_embedding = aesthetic_section.get("embedding")
            record.extra_metadata = dict(merged_config.get("metadata") or {})
            record.pack_usage = [
                PackUsageInfo(
                    pack_name=record.prompt_pack_name,
                    pack_path=str(pack_path) if pack_path else None,
                    prompt_index=record.prompt_pack_row_index,
                )
            ]
            record.randomizer_summary = {
                "enabled": randomizer_plan.enabled,
                "max_variants": randomizer_plan.max_variants,
                "seed_mode": randomizer_plan.seed_mode.value if randomizer_plan.seed_mode else None,
                "base_seed": randomizer_plan.base_seed,
            }
        return jobs

    def _resolve_prompt(self, entry: PackJobEntry, config: dict[str, Any]) -> Any:
        pack_rows = self._load_pack_rows(entry.pack_id)
        row_index = entry.pack_row_index or 0
        pack_row = None
        if pack_rows:
            if row_index >= len(pack_rows):
                row_index = len(pack_rows) - 1
            pack_row = pack_rows[row_index]
        if pack_row is None:
            pack_row = PackRow(
                embeddings=(),
                quality_line=entry.prompt_text or "",
                subject_template=entry.prompt_text or "",
                lora_tags=(),
                negative_embeddings=(),
                negative_phrases=(entry.negative_prompt_text or "",),
            )
        matrix_values = entry.matrix_slot_values or {}
        pipeline_section = config.get("pipeline", {})
        negative_prompt = config.get("txt2img", {}).get("negative_prompt", "")
        apply_global = pipeline_section.get("apply_global_negative_txt2img", True)
        return self._prompt_resolver.resolve_from_pack(
            pack_row=pack_row,
            matrix_slot_values=matrix_values,
            pack_negative=negative_prompt,
            global_negative=self._config_manager.get_global_negative_prompt(),
            apply_global_negative=bool(apply_global),
        )

    def _build_config_payload(
        self,
        entry: PackJobEntry,
        merged_config: dict[str, Any],
        prompt_resolution: Any,
        stage_chain: list[StageConfig],
    ) -> dict[str, Any]:
        txt2img = merged_config.get("txt2img", {})
        pipeline_section = merged_config.get("pipeline", {})
        payload: dict[str, Any] = {
            "prompt": prompt_resolution.positive,
            "negative_prompt": prompt_resolution.negative,
            "model": txt2img.get("model"),
            "sampler": txt2img.get("sampler_name") or txt2img.get("sampler"),
            "scheduler": txt2img.get("scheduler"),
            "steps": txt2img.get("steps"),
            "cfg_scale": txt2img.get("cfg_scale"),
            "width": txt2img.get("width"),
            "height": txt2img.get("height"),
            "seed": txt2img.get("seed"),
            "clip_skip": txt2img.get("clip_skip"),
            "vae": txt2img.get("vae"),
            "stages": [stage.stage_type for stage in stage_chain if stage.enabled],
            "pipeline": pipeline_section,
            "randomization": merged_config.get("randomization"),
            "hires_fix": merged_config.get("hires_fix"),
            "refiner": merged_config.get("refiner"),
            "adetailer": merged_config.get("adetailer"),
            "upscale": merged_config.get("upscale"),
            "aesthetic": merged_config.get("aesthetic"),
        }
        payload["pack_name"] = entry.pack_name or entry.pack_id
        payload["pack_path"] = (
            str(self._resolve_pack_text_path(entry.pack_id))
            if self._resolve_pack_text_path(entry.pack_id)
            else None
        )
        payload["prompt_pack_id"] = entry.pack_id
        payload["prompt_pack_row_index"] = entry.pack_row_index or 0
        payload["matrix_slot_values"] = dict(entry.matrix_slot_values or {})
        return payload

    def _build_stage_chain(
        self, merged_config: dict[str, Any], stage_flags: dict[str, bool]
    ) -> list[StageConfig]:
        stage_sections = {
            "txt2img": merged_config.get("txt2img", {}),
            "img2img": merged_config.get("img2img", {}),
            "adetailer": merged_config.get("adetailer", {}),
            "upscale": merged_config.get("upscale", {}),
        }
        chain: list[StageConfig] = []
        for stage in ("txt2img", "img2img", "adetailer", "upscale"):
            data = stage_sections.get(stage, {}) or {}
            enabled = bool(stage_flags.get(stage, stage == "txt2img"))
            extra: dict[str, Any] = {}
            if stage == "txt2img":
                extra.update(
                    {
                        "clip_skip": data.get("clip_skip"),
                        "hr_upscaler": data.get("hr_upscaler"),
                        "refiner_model": merged_config.get("refiner", {}).get("model_name"),
                        "refiner_switch_at": data.get("refiner_switch_at"),
                        "hires_steps": data.get("hires_steps"),
                    }
                )
            if stage in {"img2img", "adetailer"}:
                extra["denoising_strength"] = data.get("denoising_strength") or data.get(
                    "adetailer_denoise"
                )
            if stage == "adetailer":
                extra["prompt"] = data.get("adetailer_prompt")
                extra["negative_prompt"] = data.get("adetailer_negative_prompt")
            if stage == "upscale":
                extra.update(
                    {
                        "upscaler": data.get("upscaler"),
                        "upscale_mode": data.get("upscale_mode"),
                        "resize": data.get("upscaling_resize"),
                    }
                )
            stage_cfg = StageConfig(
                stage_type=stage,
                enabled=enabled,
                steps=data.get("steps"),
                cfg_scale=data.get("cfg_scale"),
                denoising_strength=data.get("denoising_strength"),
                sampler_name=data.get("sampler_name") or data.get("sampler"),
                scheduler=data.get("scheduler"),
                model=data.get("model"),
                vae=data.get("vae"),
                extra={k: v for k, v in extra.items() if v not in (None, "", [])},
            )
            chain.append(stage_cfg)
        return chain

    def _build_batch_settings(self, merged_config: dict[str, Any]) -> BatchSettings:
        pipeline_section = merged_config.get("pipeline", {})
        batch_size = int(pipeline_section.get("images_per_prompt", 1) or 1)
        batch_runs = int(pipeline_section.get("loop_count", 1) or 1)
        return BatchSettings(batch_size=batch_size, batch_runs=batch_runs)

    def _build_randomizer_plan(
        self, entry: PackJobEntry, merged_config: dict[str, Any]
    ) -> RandomizationPlanV2:
        matrix_config = merged_config.get("randomization", {})
        metadata = entry.randomizer_metadata or {}
        enabled = bool(metadata.get("enabled") or matrix_config.get("enabled"))
        max_variants = int(metadata.get("max_variants", 1) or 1)
        plan = RandomizationPlanV2(
            enabled=enabled,
            max_variants=max_variants,
            seed_mode=RandomizationSeedMode.NONE,
            base_seed=matrix_config.get("seed"),
        )
        return plan

    def _load_pack_rows(self, pack_id: str) -> list[PackRow]:
        path = self._resolve_pack_text_path(pack_id)
        if not path:
            return []
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as exc:
            _logger.warning("Failed to read prompt pack '%s': %s", pack_id, exc)
            return []
        return parse_prompt_pack_text(content)

    def _resolve_pack_text_path(self, pack_id: str) -> Path | None:
        candidate = Path(pack_id)
        if candidate.is_absolute():
            if candidate.exists():
                return candidate
        base = Path(pack_id)
        stem = base.stem
        extensions = [".txt", ".tsv"]
        candidates = []
        if base.suffix:
            candidates.append(self._packs_dir / pack_id)
        else:
            for ext in extensions:
                candidates.append(self._packs_dir / f"{stem}{ext}")
        for path in candidates:
            if path.exists():
                return path
        return None

    def _load_pack_config(self, pack_id: str) -> dict[str, Any] | None:
        try:
            return self._config_manager.load_pack_config(pack_id)
        except Exception as exc:
            _logger.error("Failed to load pack config for '%s': %s", pack_id, exc)
            return None

    def _normalize_stage_flags(
        self, pipeline_section: dict[str, Any], overrides: dict[str, bool]
    ) -> dict[str, bool]:
        defaults = {
            "txt2img": bool(pipeline_section.get("txt2img_enabled", True)),
            "img2img": bool(pipeline_section.get("img2img_enabled", False)),
            "adetailer": bool(pipeline_section.get("adetailer_enabled", False)),
            "upscale": bool(pipeline_section.get("upscale_enabled", False)),
        }
        normalized = dict(defaults)
        for key, value in overrides.items():
            if key in normalized:
                normalized[key] = bool(value)
        return normalized
