"""Deterministic prompt and pipeline config resolution helpers."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.utils.prompt_pack_utils import resolve_matrix_slot_value

from src.pipeline.prompt_pack_parser import PackRow
from src.utils.embedding_prompt_utils import render_embedding_reference

MAX_PREVIEW_PROMPT_LENGTH = 120


MATRIX_TOKEN_RE = re.compile(r"\[\[([a-zA-Z0-9_\- ]+)\]\]")


def _truncate(value: str, limit: int) -> str:
    if not value:
        return ""
    return value if len(value) <= limit else value[:limit] + "..."


def _dedupe_lora_tags(tags: Iterable[tuple[str, float]]) -> tuple[tuple[str, float], ...]:
    deduped: list[tuple[str, float]] = []
    seen: set[str] = set()
    for raw_name, raw_weight in tags:
        name = str(raw_name or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError):
            weight = 1.0
        deduped.append((name, weight))
    return tuple(deduped)


def _actor_trigger_phrases(actor_resolutions: Iterable[Mapping[str, Any]] | None) -> tuple[str, ...]:
    phrases: list[str] = []
    seen: set[str] = set()
    for actor in list(actor_resolutions or []):
        phrase = str(actor.get("trigger_phrase") or "").strip()
        if not phrase:
            continue
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        phrases.append(phrase)
    return tuple(phrases)


def _style_trigger_phrase(style_lora: Mapping[str, Any] | None) -> str:
    payload = dict(style_lora or {}) if isinstance(style_lora, Mapping) else {}
    if not payload:
        return ""
    if not bool(payload.get("applied", payload.get("enabled", True))):
        return ""
    return str(payload.get("trigger_phrase") or "").strip()


def _style_lora_tags(style_lora: Mapping[str, Any] | None) -> tuple[tuple[str, float], ...]:
    payload = dict(style_lora or {}) if isinstance(style_lora, Mapping) else {}
    if not payload:
        return ()
    if not bool(payload.get("applied", payload.get("enabled", True))):
        return ()
    lora_name = str(payload.get("lora_name") or "").strip()
    if not lora_name:
        return ()
    try:
        weight = float(payload.get("weight") or 1.0)
    except (TypeError, ValueError):
        weight = 1.0
    return ((lora_name, weight),)


def _actor_lora_tags(actor_resolutions: Iterable[Mapping[str, Any]] | None) -> tuple[tuple[str, float], ...]:
    tags: list[tuple[str, float]] = []
    for actor in list(actor_resolutions or []):
        lora_name = str(actor.get("lora_name") or "").strip()
        if not lora_name:
            lora_path = str(actor.get("lora_path") or "").strip()
            lora_name = Path(lora_path).stem if lora_path else ""
        if not lora_name:
            continue
        try:
            weight = float(actor.get("weight") or 1.0)
        except (TypeError, ValueError):
            weight = 1.0
        tags.append((lora_name, weight))
    return _dedupe_lora_tags(tags)


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
    positive_embeddings: tuple[tuple[str, float], ...]
    negative_embeddings: tuple[tuple[str, float], ...]
    lora_tags: tuple[tuple[str, float], ...]
    global_negative_applied: bool


@dataclass(frozen=True)
class StageResolution:
    """Per-stage resolution summary used for UI/DTO display."""

    name: str
    enabled: bool
    details: dict[str, Any] | None = None


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
        positives: list[str] = []
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
            resolved = resolve_matrix_slot_value(name, dict(slots))
            return resolved if resolved is not None else match.group(0)

        return MATRIX_TOKEN_RE.sub(replace, template)

    def resolve_from_pack(
        self,
        *,
        pack_row: PackRow,
        matrix_slot_values: Mapping[str, str] | None = None,
        actor_resolutions: Iterable[Mapping[str, Any]] | None = None,
        style_lora: Mapping[str, Any] | None = None,
        pack_negative: str | None = None,
        global_negative: str = "",
        apply_global_negative: bool = True,
    ) -> PromptResolution:
        # Apply matrix token substitution to both quality_line and subject_template
        subject = self._substitute_matrix_tokens(pack_row.subject_template, matrix_slot_values)
        quality = self._substitute_matrix_tokens(pack_row.quality_line, matrix_slot_values)
        
        actor_trigger_phrases = list(_actor_trigger_phrases(actor_resolutions))
        style_trigger_phrase = _style_trigger_phrase(style_lora)
        if style_trigger_phrase:
            actor_trigger_phrases.append(style_trigger_phrase)
        merged_lora_tags = _dedupe_lora_tags(
            list(_actor_lora_tags(actor_resolutions))
            + list(pack_row.lora_tags)
            + list(_style_lora_tags(style_lora))
        )
        lora_tokens = " ".join(f"<lora:{name}:{weight}>" for name, weight in merged_lora_tags)
        positive_parts: list[str] = []
        # Render embeddings with weights
        if pack_row.embeddings:
            positive_parts.extend(render_embedding_reference(name, weight) for name, weight in pack_row.embeddings)
        if actor_trigger_phrases:
            positive_parts.append(", ".join(actor_trigger_phrases))
        if quality:  # Use substituted quality_line
            positive_parts.append(quality)
        if subject:
            positive_parts.append(subject)
        if lora_tokens:
            positive_parts.append(lora_tokens)

        positive = " ".join(part for part in positive_parts if part).strip()
        
        # BUGFIX: Ensure positive prompt is never empty - prevents negative becoming positive
        if not positive:
            positive = "professional photo, high quality"

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
            negative_parts.extend(render_embedding_reference(name, weight) for name, weight in pack_row.negative_embeddings)
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
            lora_tags=merged_lora_tags,
            global_negative_applied=global_applied,
        )


class UnifiedConfigResolver:
    """Resolves stage toggles, seeds, and sizing into a single config snapshot."""

    DEFAULT_STAGE_ORDER: list[str] = ["txt2img", "img2img", "adetailer", "upscale"]
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
