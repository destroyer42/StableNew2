"""Deterministic prompt and pipeline config resolution helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.pipeline.prompt_pack_parser import PackRow

MAX_PREVIEW_PROMPT_LENGTH = 120


MATRIX_TOKEN_RE = re.compile(r"\[\[([a-zA-Z0-9_]+)\]\]")


def _truncate(value: str, limit: int) -> str:
    if not value:
        return ""
    return value if len(value) <= limit else value[:limit] + "..."


@dataclass(frozen=True)
class ResolvedPrompt:
    """Immutable metadata describing how a prompt was resolved."""

    positive: str
    negative: str
    positive_preview: str
    negative_preview: str
    global_negative_applied: bool

    @classmethod
    def empty(cls) -> ResolvedPrompt:
        return cls(
            positive="",
            negative="",
            positive_preview="",
            negative_preview="",
            global_negative_applied=False,
        )


@dataclass(frozen=True)
class PromptResolution:
    positive: str
    negative: str
    positive_preview: str
    negative_preview: str
    positive_embeddings: tuple[str, ...]
    negative_embeddings: tuple[str, ...]
    lora_tags: tuple[tuple[str, float], ...]
    global_negative_applied: bool


@dataclass(frozen=True)
class StageResolution:
    """Per-stage resolution summary used for UI/DTO display."""

    name: str
    enabled: bool
    details: dict[str, Any] = None


@dataclass(frozen=True)
class ResolvedPipelineConfig:
    """Canonical representation of a resolved pipeline configuration."""

    model_name: str
    sampler_name: str
    scheduler_name: str
    steps: int
    cfg_scale: float
    width: int
    height: int
    final_size: tuple[int, int]
    seed: int | None
    batch_size: int
    batch_count: int
    stages: dict[str, StageResolution]
    randomizer_summary: dict[str, Any] | None = None

    def enabled_stage_names(self) -> list[str]:
        return [name for name, stage in self.stages.items() if stage.enabled]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "sampler_name": self.sampler_name,
            "scheduler_name": self.scheduler_name,
            "steps": self.steps,
            "cfg_scale": self.cfg_scale,
            "width": self.width,
            "height": self.height,
            "final_width": self.final_size[0],
            "final_height": self.final_size[1],
            "seed": self.seed,
            "batch_size": self.batch_size,
            "batch_count": self.batch_count,
            "stages": {
                name: {"enabled": stage.enabled, **(stage.details or {})}
                for name, stage in self.stages.items()
            },
            "randomizer_summary": self.randomizer_summary,
        }


class UnifiedPromptResolver:
    """Deterministic merger for GUI prompt inputs, pack prompts, and negatives."""

    def __init__(
        self, *, max_preview_length: int = MAX_PREVIEW_PROMPT_LENGTH, safety_negative: str = ""
    ) -> None:
        self._max_preview_length = max_preview_length
        self._safety_negative = safety_negative.strip()

    def resolve(
        self,
        *,
        gui_prompt: str,
        pack_prompt: str | None = None,
        prepend_text: str | None = None,
        global_negative: str = "",
        apply_global_negative: bool = True,
        negative_override: str | None = None,
        pack_negative: str | None = None,
        preset_negative: str | None = None,
    ) -> ResolvedPrompt:
        positives = []
        for part in (prepend_text, gui_prompt, pack_prompt):
            if part:
                cleaned = part.strip()
                if cleaned and (not positives or positives[-1] != cleaned):
                    positives.append(cleaned)
        positive = " ".join(positives).strip()

        negative_parts = []
        if negative_override:
            negative_parts.append(negative_override.strip())
        global_applied = False
        if apply_global_negative and global_negative:
            negative_parts.append(global_negative.strip())
            global_applied = True
        if pack_negative:
            negative_parts.append(pack_negative.strip())
        if preset_negative:
            negative_parts.append(preset_negative.strip())
        if self._safety_negative:
            negative_parts.append(self._safety_negative)
        negative = ", ".join(part for part in negative_parts if part).strip()

        positive_preview = _truncate(positive, self._max_preview_length)
        negative_preview = _truncate(negative, self._max_preview_length)

        return ResolvedPrompt(
            positive=positive,
            positive_preview=positive_preview,
            negative=negative,
            negative_preview=negative_preview,
            global_negative_applied=global_applied,
        )

    @staticmethod
    def _substitute_matrix_tokens(template: str, slots: Mapping[str, str] | None) -> str:
        if not template or not slots:
            return template

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            return slots.get(name, match.group(0))

        return MATRIX_TOKEN_RE.sub(replace, template)

    def resolve_from_pack(
        self,
        *,
        pack_row: PackRow,
        matrix_slot_values: Mapping[str, str] | None = None,
        pack_negative: str | None = None,
        global_negative: str = "",
        apply_global_negative: bool = True,
    ) -> PromptResolution:
        # Apply matrix token substitution to both quality_line and subject_template
        subject = self._substitute_matrix_tokens(pack_row.subject_template, matrix_slot_values)
        quality = self._substitute_matrix_tokens(pack_row.quality_line, matrix_slot_values)
        
        lora_tokens = " ".join(f"<lora:{name}:{weight}>" for name, weight in pack_row.lora_tags)
        positive_parts = []
        # Fix: Wrap embeddings in <embedding:> syntax
        if pack_row.embeddings:
            positive_parts.extend(f"<embedding:{emb}>" for emb in pack_row.embeddings)
        if quality:  # Use substituted quality_line
            positive_parts.append(quality)
        if subject:
            positive_parts.append(subject)
        if lora_tokens:
            positive_parts.append(lora_tokens)

        positive = " ".join(part for part in positive_parts if part).strip()

        negative_parts = []
        global_applied = False
        if apply_global_negative and global_negative:
            negative_parts.append(global_negative.strip())
            global_applied = True
        # Fix: Add pack_negative BEFORE pack row negative embeddings/phrases
        if pack_negative:
            negative_parts.append(pack_negative.strip())
        # Fix: Wrap negative embeddings in <embedding:> syntax
        if pack_row.negative_embeddings:
            negative_parts.extend(f"<embedding:{tag}>" for tag in pack_row.negative_embeddings)
        negative_parts.extend(phrase for phrase in pack_row.negative_phrases if phrase)
        if self._safety_negative:
            negative_parts.append(self._safety_negative)

        negative = ", ".join(part for part in negative_parts if part).strip()

        positive_preview = _truncate(positive, self._max_preview_length)
        negative_preview = _truncate(negative, self._max_preview_length)

        return PromptResolution(
            positive=positive,
            negative=negative,
            positive_preview=positive_preview,
            negative_preview=negative_preview,
            positive_embeddings=pack_row.embeddings,
            negative_embeddings=pack_row.negative_embeddings,
            lora_tags=pack_row.lora_tags,
            global_negative_applied=global_applied,
        )


class UnifiedConfigResolver:
    """Resolves stage toggles, seeds, and sizing into a single config snapshot."""

    DEFAULT_STAGE_ORDER: list[str] = ["txt2img", "img2img", "upscale", "adetailer"]
    DEFAULT_FLAGS: dict[str, bool] = {
        "txt2img": True,
        "img2img": False,
        "upscale": False,
        "adetailer": False,
    }

    def resolve(
        self,
        *,
        config_snapshot: Any,
        stage_flags: Mapping[str, bool] | None = None,
        batch_count: int | None = None,
        seed_value: int | None = None,
        randomizer_summary: dict[str, Any] | None = None,
        final_size_override: tuple[int, int] | None = None,
    ) -> ResolvedPipelineConfig:
        flags = dict(self.DEFAULT_FLAGS)
        if stage_flags:
            for name, enabled in stage_flags.items():
                if name in flags and isinstance(enabled, bool):
                    flags[name] = enabled

        width = getattr(config_snapshot, "width", 512) if config_snapshot else 512
        height = getattr(config_snapshot, "height", 512) if config_snapshot else 512
        final_size = final_size_override or (width, height)
        batch_size = getattr(config_snapshot, "batch_size", 1) if config_snapshot else 1
        batch_runs = (
            batch_count if batch_count is not None else getattr(config_snapshot, "batch_count", 1)
        )
        seed = (
            seed_value if seed_value is not None else getattr(config_snapshot, "seed_value", None)
        )
        randomizer = randomizer_summary or getattr(config_snapshot, "randomizer_config", None)

        stages: dict[str, StageResolution] = {}
        for stage_name in self.DEFAULT_STAGE_ORDER:
            details = {
                "model": getattr(config_snapshot, "model_name", None),
                "sampler": getattr(config_snapshot, "sampler_name", None),
                "scheduler": getattr(config_snapshot, "scheduler_name", None),
            }
            stages[stage_name] = StageResolution(
                name=stage_name,
                enabled=flags.get(stage_name, False),
                details={k: v for k, v in details.items() if v},
            )

        return ResolvedPipelineConfig(
            model_name=getattr(config_snapshot, "model_name", "unknown"),
            sampler_name=getattr(config_snapshot, "sampler_name", "unknown"),
            scheduler_name=getattr(config_snapshot, "scheduler_name", "unknown"),
            steps=getattr(config_snapshot, "steps", 20),
            cfg_scale=getattr(config_snapshot, "cfg_scale", 7.0),
            width=width,
            height=height,
            final_size=final_size,
            seed=seed,
            batch_size=batch_size,
            batch_count=batch_runs,
            stages=stages,
            randomizer_summary=randomizer,
        )
