from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.prompting.contracts import PromptContext, PromptIntentBundle
from src.prompting.prompt_bucket_rules import build_default_prompt_bucket_rules
from src.prompting.prompt_classifier import classify_chunk_rule_based
from src.prompting.prompt_splitter import detect_lora_syntax, split_prompt_chunks

_SENSITIVE_TOKEN_RE = re.compile(
    r"\b(nsfw|nude|naked|breast|breasts|nipples?|vagina|penis|cum|sex|explicit|lingerie)\b",
    re.IGNORECASE,
)
_LORA_NAME_RE = re.compile(r"<\s*lora\s*:([^:>]+):([^>]+)>", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class PromptIntentAnalyzerConfig:
    enable_conflict_detection: bool = True


class PromptIntentAnalyzer:
    def __init__(self, cfg: PromptIntentAnalyzerConfig | None = None) -> None:
        self._cfg = cfg or PromptIntentAnalyzerConfig()
        self._rules = build_default_prompt_bucket_rules()

    def infer(
        self,
        *,
        positive: str,
        negative: str,
        prompt_context: PromptContext,
        extra_context: dict[str, Any] | None = None,
    ) -> PromptIntentBundle:
        del extra_context
        positive_text = str(positive or "")
        negative_text = str(negative or "")
        positive_chunks = split_prompt_chunks(positive_text)
        negative_chunks = split_prompt_chunks(negative_text)
        positive_lower = positive_text.lower()
        negative_lower = negative_text.lower()

        wants_full_body = "full body" in positive_lower
        wants_portrait = any(token in positive_lower for token in ("portrait", "headshot", "close-up", "close up"))
        wants_profile = any(
            token in positive_lower
            for token in ("profile", "side view", "over shoulder", "over-the-shoulder", "looking back")
        )
        looking_at_viewer = any(
            token in positive_lower for token in ("looking at viewer", "looking toward camera", "looking directly into camera")
        )
        has_people_tokens = any(
            token in positive_lower
            for token in ("woman", "man", "girl", "boy", "person", "people", "face", "portrait")
        )
        wants_face_detail = any(
            token in positive_lower
            for token in ("detailed face", "detailed eyes", "sharp eyes", "face focus", "natural skin texture")
        ) or bool(prompt_context.embeddings)
        has_lora_tokens = any(detect_lora_syntax(chunk) for chunk in positive_chunks)
        style_mode = _infer_style_mode(positive_lower)
        shot_type = "full_body" if wants_full_body else ("portrait" if wants_portrait else "unknown")
        requested_pose = "profile" if wants_profile else ("frontal" if looking_at_viewer else "unknown")

        if not has_people_tokens:
            intent_band = "non_people"
        elif wants_full_body and not wants_portrait:
            intent_band = "full_body"
        else:
            intent_band = "portrait"

        sensitivity_reasons = sorted({match.group(1).lower() for match in _SENSITIVE_TOKEN_RE.finditer(positive_text)})
        prompt_tags = [str(tag).strip().lower() for tag in prompt_context.source.tags if str(tag).strip()]
        if any(tag in {"nsfw", "nude", "explicit"} for tag in prompt_tags):
            sensitivity_reasons.append("tagged_sensitive")
        sensitivity_reasons = sorted(set(sensitivity_reasons))

        conflicts: list[str] = []
        if self._cfg.enable_conflict_detection:
            if wants_full_body and wants_portrait:
                conflicts.append("prompt_contains_full_body_and_portrait_tokens")
            if wants_profile and looking_at_viewer:
                conflicts.append("prompt_contains_profile_and_camera_facing_tokens")
            if _has_style_conflict(positive_chunks, negative_chunks):
                conflicts.append("positive_negative_style_conflict")
            if _has_lora_weight_conflict(positive_text):
                conflicts.append("duplicate_lora_name_with_different_weights")

        return PromptIntentBundle(
            intent_band=intent_band,
            shot_type=shot_type,
            style_mode=style_mode,
            requested_pose=requested_pose,
            wants_face_detail=wants_face_detail,
            wants_full_body=wants_full_body,
            wants_portrait=wants_portrait,
            has_people_tokens=has_people_tokens,
            has_lora_tokens=has_lora_tokens,
            sensitive=bool(sensitivity_reasons),
            sensitivity_reasons=sensitivity_reasons,
            conflicts=conflicts,
        )


def _infer_style_mode(positive_lower: str) -> str:
    if any(token in positive_lower for token in ("photoreal", "photo realistic", "realistic", "photograph")):
        return "photoreal"
    if any(token in positive_lower for token in ("anime", "cartoon", "illustration", "painting", "cgi", "3d render")):
        return "stylized"
    return "unknown"


def _has_style_conflict(positive_chunks: list[str], negative_chunks: list[str]) -> bool:
    style_tokens = {"anime", "cartoon", "painting", "cgi", "3d"}
    positive_hits = {token for token in style_tokens if any(token in chunk.lower() for chunk in positive_chunks)}
    negative_hits = {token for token in style_tokens if any(token in chunk.lower() for chunk in negative_chunks)}
    return bool(positive_hits & negative_hits)


def _has_lora_weight_conflict(positive_text: str) -> bool:
    weights_by_name: dict[str, set[str]] = {}
    for match in _LORA_NAME_RE.finditer(positive_text):
        name = match.group(1).strip().lower()
        weight = match.group(2).strip().lower()
        if not name:
            continue
        weights_by_name.setdefault(name, set()).add(weight)
    return any(len(weights) > 1 for weights in weights_by_name.values())
