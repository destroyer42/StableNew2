from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.prompting.prompt_bucket_rules import build_default_prompt_bucket_rules
from src.prompting.prompt_classifier import classify_chunk_rule_based
from src.prompting.prompt_splitter import detect_lora_syntax, split_prompt_chunks
from src.utils.embedding_prompt_utils import extract_embedding_entries


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
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        positive_text = str(positive or "")
        negative_text = str(negative or "")
        positive_chunks = split_prompt_chunks(positive_text)
        negative_chunks = split_prompt_chunks(negative_text)

        positive_buckets = [
            {"chunk": chunk, "bucket": classify_chunk_rule_based(chunk, "positive", self._rules)}
            for chunk in positive_chunks
        ]
        negative_buckets = [
            {"chunk": chunk, "bucket": classify_chunk_rule_based(chunk, "negative", self._rules)}
            for chunk in negative_chunks
        ]

        lower = positive_text.lower()
        wants_full_body = "full body" in lower
        wants_portrait = any(token in lower for token in ("portrait", "close-up", "close up", "headshot"))
        wants_profile = any(
            token in lower
            for token in ("profile", "side view", "over shoulder", "over-the-shoulder", "looking back")
        )
        looking_at_viewer = "looking at viewer" in lower
        has_people_tokens = any(
            token in lower
            for token in ("woman", "man", "person", "people", "girl", "boy", "portrait", "face")
        )
        embedding_entries = extract_embedding_entries(positive_text)
        has_lora_tokens = any(detect_lora_syntax(chunk) for chunk in positive_chunks)
        wants_face_detail = bool(embedding_entries) or any(
            token in lower for token in ("detailed face", "detailed eyes", "sharp eyes", "face focus")
        )

        if not has_people_tokens:
            intent_band = "non_people"
        elif wants_full_body and not wants_portrait:
            intent_band = "full_body"
        else:
            intent_band = "portrait"

        requested_pose = "profile" if wants_profile else ("frontal" if looking_at_viewer else "unknown")

        conflicts: list[str] = []
        if self._cfg.enable_conflict_detection:
            if wants_full_body and wants_portrait:
                conflicts.append("prompt_contains_full_body_and_portrait_tokens")
            if wants_profile and looking_at_viewer:
                conflicts.append("prompt_contains_profile_and_looking_at_viewer_tokens")

        return {
            "intent_band": intent_band,
            "requested_pose": requested_pose,
            "wants_face_detail": wants_face_detail,
            "wants_full_body": wants_full_body,
            "wants_profile": wants_profile,
            "wants_portrait": wants_portrait,
            "has_people_tokens": has_people_tokens,
            "has_lora_tokens": has_lora_tokens,
            "positive_embedding_count": len(embedding_entries),
            "positive_chunks": positive_buckets,
            "negative_chunks": negative_buckets,
            "conflicts": conflicts,
            "context": dict(context or {}),
        }
