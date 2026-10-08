"""Deterministic prompt and pipeline config resolution helpers."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any

from src.image_backends.forge_klein_lora import LoraResolver
from src.image_backends.model_policy import ModelPolicy
from src.pipeline.prompt_pack_parser import PackRow
from src.prompting.prompt_adaptation import (
    KIND_ACTOR,
    KIND_PACK,
    KIND_STYLE,
    LoraContribution,
    PromptAdaptationPlan,
    StructuredPromptInput,
    TriggerContribution,
    adapt_structured_prompt,
)
from src.utils.embedding_prompt_utils import render_embedding_reference
from src.utils.prompt_pack_utils import resolve_matrix_slot_value

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


def _actor_trigger_phrases(
    actor_resolutions: Iterable[Mapping[str, Any]] | None,
) -> tuple[str, ...]:
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


def _actor_lora_tags(
    actor_resolutions: Iterable[Mapping[str, Any]] | None,
) -> tuple[tuple[str, float], ...]:
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


@dataclass(frozen=True)
class PackPromptIntent:
    """Immutable, structured PromptPack prompt intent *before* any executable string exists (PR-PROMPT-140).

    Matrix tokens are already expanded. Every contribution keeps its role and ownership, so a target-aware adaptation can
    drop a LoRA together with the trigger phrase it structurally owns, and a negative-channel omission can drop every
    negative component, all before :func:`render_pack_intent` produces the final strings. The render order is exactly
    the historical one (positive: embeddings, triggers, quality, subject, LoRA tokens; negative: global, pack negative,
    negative embeddings, negative phrases, safety).
    """

    quality: str
    subject: str
    positive_embeddings: tuple[tuple[str, float], ...] = ()
    negative_embeddings: tuple[tuple[str, float], ...] = ()
    #: Execution order, de-duplicated by name (first wins): actor LoRAs, PromptPack-row LoRAs, Style Consistency.
    loras: tuple[LoraContribution, ...] = ()
    #: Render order: distinct actor trigger phrases, then the Style Consistency trigger phrase.
    triggers: tuple[TriggerContribution, ...] = ()
    pack_negative: str = ""
    global_negative: str = ""
    apply_global_negative: bool = True
    negative_phrases: tuple[str, ...] = ()
    safety_negative: str = ""
    #: ``False`` once a target's policy omitted the whole negative channel: nothing negative is rendered.
    negative_channel: bool = True

    @property
    def global_negative_applied(self) -> bool:
        return self.negative_channel and bool(self.apply_global_negative and self.global_negative)


@dataclass(frozen=True)
class AdaptedPackIntent:
    """A target-adapted :class:`PackPromptIntent` and the content-free plan that explains it."""

    intent: PackPromptIntent
    plan: PromptAdaptationPlan


PACK_PROMPT_INTENT_CONTRACT = "pack_prompt_intent/1"


def pack_prompt_intent_to_dict(intent: PackPromptIntent) -> dict[str, Any]:
    """JSON-safe, lossless data serialization; never resolves or adapts a prompt."""
    return {"contract": PACK_PROMPT_INTENT_CONTRACT, **json.loads(json.dumps(asdict(intent), allow_nan=False))}


def pack_prompt_intent_from_dict(payload: Mapping[str, Any]) -> PackPromptIntent:
    """Restore the exact versioned structure without interpreting source text."""
    data = dict(payload)
    if data.pop("contract", None) != PACK_PROMPT_INTENT_CONTRACT:
        raise ValueError("Unknown frozen PromptPack intent contract; rebuild preview")
    if set(data) != {item.name for item in fields(PackPromptIntent)}:
        raise ValueError("Malformed frozen PromptPack intent")
    for key in ("positive_embeddings", "negative_embeddings"):
        data[key] = tuple((name, weight) for name, weight in data[key])
    data["loras"] = tuple(LoraContribution(**item) for item in data["loras"])
    data["triggers"] = tuple(
        TriggerContribution(item["text"], item["kind"], tuple(item["owners"]))
        for item in data["triggers"]
    )
    data["negative_phrases"] = tuple(data["negative_phrases"])
    return PackPromptIntent(**data)


def _substitute_matrix_tokens(template: str, slots: Mapping[str, str] | None) -> str:
    if not template or not slots:
        return template

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        resolved = resolve_matrix_slot_value(name, dict(slots))
        return resolved if resolved is not None else match.group(0)

    return MATRIX_TOKEN_RE.sub(replace, template)


def _actor_lora_name(actor: Mapping[str, Any]) -> str:
    lora_name = str(actor.get("lora_name") or "").strip()
    if not lora_name:
        lora_path = str(actor.get("lora_path") or "").strip()
        lora_name = Path(lora_path).stem if lora_path else ""
    return lora_name


def _float_or_default(value: Any) -> float:
    try:
        return float(value or 1.0)
    except (TypeError, ValueError):
        return 1.0


def resolve_pack_intent(
    *,
    pack_row: PackRow,
    matrix_slot_values: Mapping[str, str] | None = None,
    actor_resolutions: Iterable[Mapping[str, Any]] | None = None,
    style_lora: Mapping[str, Any] | None = None,
    pack_negative: str | None = None,
    global_negative: str = "",
    apply_global_negative: bool = True,
    safety_negative: str = "",
) -> PackPromptIntent:
    """Structure the authored PromptPack row: Matrix expansion plus ownership, with no rendering."""

    subject = _substitute_matrix_tokens(pack_row.subject_template, matrix_slot_values)
    quality = _substitute_matrix_tokens(pack_row.quality_line, matrix_slot_values)
    actors = list(actor_resolutions or [])

    raw_loras: list[tuple[str, float, str]] = []
    for actor in actors:
        name = _actor_lora_name(actor)
        if name:
            raw_loras.append((name, _float_or_default(actor.get("weight")), KIND_ACTOR))
    raw_loras.extend((name, weight, KIND_PACK) for name, weight in pack_row.lora_tags)
    raw_loras.extend((name, weight, KIND_STYLE) for name, weight in _style_lora_tags(style_lora))
    loras: list[LoraContribution] = []
    seen: set[str] = set()
    for raw_name, raw_weight, kind in raw_loras:
        name = str(raw_name or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError):
            weight = 1.0
        loras.append(LoraContribution(name, weight, kind))

    # Distinct actor trigger phrases (case-insensitive), each owned by the actor LoRA(s) that carry it. A phrase that
    # any LoRA-less actor also carries is not LoRA-owned (it must survive any LoRA omission).
    phrases: dict[str, tuple[str, list[str], bool]] = {}
    for actor in actors:
        phrase = str(actor.get("trigger_phrase") or "").strip()
        if not phrase:
            continue
        text, owners, unowned = phrases.get(phrase.lower(), (phrase, [], False))
        lora_name = _actor_lora_name(actor)
        if lora_name:
            owners.append(lora_name)
        else:
            unowned = True
        phrases[phrase.lower()] = (text, owners, unowned)
    triggers = [
        TriggerContribution(text, KIND_ACTOR, () if unowned else tuple(owners))
        for text, owners, unowned in phrases.values()
    ]
    style_phrase = _style_trigger_phrase(style_lora)
    if style_phrase:
        style_tags = _style_lora_tags(style_lora)
        triggers.append(TriggerContribution(style_phrase, KIND_STYLE, (style_tags[0][0],) if style_tags else ()))

    return PackPromptIntent(
        quality=quality,
        subject=subject,
        positive_embeddings=pack_row.embeddings,
        negative_embeddings=pack_row.negative_embeddings,
        loras=tuple(loras),
        triggers=tuple(triggers),
        pack_negative=pack_negative or "",
        global_negative=global_negative or "",
        apply_global_negative=bool(apply_global_negative),
        negative_phrases=tuple(phrase for phrase in pack_row.negative_phrases if phrase),
        safety_negative=safety_negative or "",
    )


def adapt_pack_intent(
    intent: PackPromptIntent,
    policy: ModelPolicy,
    *,
    lora_resolver: LoraResolver | None = None,
    optimizer_enabled: bool = False,
    lora_selection: Any = None,
) -> AdaptedPackIntent:
    """Run the one 130C rule implementation over the structured intent (compile-safe) and re-assemble it.

    No rule lives here: this only maps components in and back out by role. The result is still a structured intent.
    """

    negative_slots: list[str] = []
    negative_texts: list[str] = []
    if intent.apply_global_negative and intent.global_negative:
        negative_slots.append("global")
        negative_texts.append(intent.global_negative.strip())
    if intent.pack_negative:
        negative_slots.append("pack")
        negative_texts.append(intent.pack_negative.strip())
    negative_slots.extend("phrase" for _ in intent.negative_phrases)
    negative_texts.extend(intent.negative_phrases)
    if intent.safety_negative:
        negative_slots.append("safety")
        negative_texts.append(intent.safety_negative)

    result = adapt_structured_prompt(
        policy,
        StructuredPromptInput(
            positive_prose=(intent.quality, intent.subject),
            negative_prose=tuple(negative_texts),
            positive_embeddings=intent.positive_embeddings,
            negative_embeddings=intent.negative_embeddings,
            loras=intent.loras,
            triggers=intent.triggers,
            optimizer_enabled=optimizer_enabled,
            global_negative_present=bool(intent.apply_global_negative and intent.global_negative.strip()),
        ),
        lora_resolver=lora_resolver,
        lora_selection=lora_selection,
    )
    global_negative = intent.global_negative
    pack_negative = intent.pack_negative
    safety_negative = intent.safety_negative
    phrases: list[str] = []
    for slot, text in zip(negative_slots, result.negative_prose, strict=True):
        if slot == "global":
            global_negative = text
        elif slot == "pack":
            pack_negative = text
        elif slot == "safety":
            safety_negative = text
        else:
            phrases.append(text)
    quality, subject = result.positive_prose
    return AdaptedPackIntent(
        replace(
            intent,
            quality=quality,
            subject=subject,
            positive_embeddings=result.positive_embeddings,
            negative_embeddings=result.negative_embeddings,
            loras=result.loras,
            triggers=result.triggers,
            pack_negative=pack_negative,
            global_negative=global_negative,
            negative_phrases=tuple(phrases),
            safety_negative=safety_negative,
            negative_channel=result.negative_channel,
        ),
        result.plan,
    )


def render_pack_intent(
    intent: PackPromptIntent, *, max_preview_length: int = MAX_PREVIEW_PROMPT_LENGTH
) -> PromptResolution:
    """Render a (possibly adapted) structured intent to the executable strings, in the historical order."""

    lora_tokens = " ".join(f"<lora:{lora.name}:{lora.weight}>" for lora in intent.loras)
    positive_parts: list[str] = []
    positive_parts.extend(render_embedding_reference(name, weight) for name, weight in intent.positive_embeddings)
    if intent.triggers:
        positive_parts.append(", ".join(trigger.text for trigger in intent.triggers))
    if intent.quality:
        positive_parts.append(intent.quality)
    if intent.subject:
        positive_parts.append(intent.subject)
    if lora_tokens:
        positive_parts.append(lora_tokens)
    positive = " ".join(part for part in positive_parts if part).strip()

    # BUGFIX: Ensure positive prompt is never empty - prevents negative becoming positive
    if not positive:
        positive = "professional photo, high quality"

    negative_parts: list[str] = []
    global_applied = intent.global_negative_applied
    if intent.negative_channel:
        if global_applied:
            negative_parts.append(intent.global_negative.strip())
        # Pack negative BEFORE the pack row's negative embeddings/phrases (historical order).
        if intent.pack_negative:
            negative_parts.append(intent.pack_negative.strip())
        negative_parts.extend(render_embedding_reference(name, weight) for name, weight in intent.negative_embeddings)
        negative_parts.extend(phrase for phrase in intent.negative_phrases if phrase)
        if intent.safety_negative:
            negative_parts.append(intent.safety_negative)
    negative = ", ".join(part for part in negative_parts if part).strip()

    return PromptResolution(
        positive=positive,
        negative=negative,
        positive_preview=_truncate(positive, max_preview_length),
        negative_preview=_truncate(negative, max_preview_length),
        positive_embeddings=intent.positive_embeddings,
        negative_embeddings=intent.negative_embeddings,
        lora_tags=tuple((lora.name, lora.weight) for lora in intent.loras),
        global_negative_applied=global_applied,
    )


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
        return _substitute_matrix_tokens(template, slots)

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
        """Compatibility wrapper: structure the row, then render it (no target adaptation)."""

        return render_pack_intent(
            resolve_pack_intent(
                pack_row=pack_row,
                matrix_slot_values=matrix_slot_values,
                actor_resolutions=actor_resolutions,
                style_lora=style_lora,
                pack_negative=pack_negative,
                global_negative=global_negative,
                apply_global_negative=apply_global_negative,
                safety_negative=self._safety_negative,
            ),
            max_preview_length=self._max_preview_length,
        )

    def resolve_intent(self, **kwargs: Any) -> PackPromptIntent:
        """:func:`resolve_pack_intent` with this resolver's safety negative."""

        return resolve_pack_intent(safety_negative=self._safety_negative, **kwargs)

    def render_intent(self, intent: PackPromptIntent) -> PromptResolution:
        return render_pack_intent(intent, max_preview_length=self._max_preview_length)


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
