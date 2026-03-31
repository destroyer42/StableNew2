from __future__ import annotations

from collections import OrderedDict
import re
from typing import Literal, cast

from src.prompting.prompt_bucket_rules import PromptBucketRules
from src.prompting.prompt_classifier import classify_chunk_rule_based, classify_chunk_score_based
from src.prompting.prompt_deduper import dedupe_prompt_chunks
from src.prompting.prompt_normalizer import build_dedupe_key, normalize_for_match
from src.prompting.prompt_optimizer_config import PromptOptimizerConfig
from src.prompting.prompt_splitter import (
    detect_lora_syntax,
    detect_weight_syntax,
    split_prompt_chunks,
)
from src.prompting.prompt_types import (
    NEGATIVE_BUCKET_ORDER,
    POSITIVE_BUCKET_ORDER,
    PromptChunk,
    PromptOptimizationPairResult,
    PromptOptimizationResult,
)
from src.utils.embedding_prompt_utils import (
    extract_embedding_token_strings,
    strip_embedding_entries,
)

_EMBEDDING_TOKEN_RE = re.compile(r"<\s*embedding:[^>]+>", re.IGNORECASE)
_EMBEDDING_ONLY_RE = re.compile(r"^(?:\s*<\s*embedding:[^>]+>\s*)+$", re.IGNORECASE)
_LORA_TOKEN_RE = re.compile(r"<\s*lora\s*:[^>]+>", re.IGNORECASE)

ChunkList = list[PromptChunk]
BucketValues = ChunkList | list[str]
BucketMap = dict[str, BucketValues]


class SDXLPromptOptimizer:
    def __init__(
        self,
        config: PromptOptimizerConfig,
        rules: PromptBucketRules,
    ) -> None:
        self.config = config
        self.rules = rules

    def optimize_positive(self, prompt: str) -> PromptOptimizationResult:
        return self._build_positive_result(prompt)

    def optimize_negative(self, prompt: str) -> PromptOptimizationResult:
        return self._build_negative_result(prompt)

    def optimize_pair(
        self,
        positive_prompt: str,
        negative_prompt: str,
    ) -> PromptOptimizationPairResult:
        return PromptOptimizationPairResult(
            positive=self.optimize_positive(positive_prompt),
            negative=self.optimize_negative(negative_prompt),
        )

    def _classify(self, chunk: str, polarity: Literal["positive", "negative"]) -> str:
        if self.config.enable_score_based_classification:
            return classify_chunk_score_based(chunk, polarity, self.rules)
        return classify_chunk_rule_based(chunk, polarity, self.rules)

    def _build_positive_result(self, prompt: str) -> PromptOptimizationResult:
        original = str(prompt or "")
        chunks = split_prompt_chunks(original)
        if not chunks or not self.config.optimize_positive:
            return PromptOptimizationResult(
                original_prompt=original,
                optimized_prompt=original,
                polarity="positive",
                changed=False,
            )
        prompt_chunks, prefix_embeddings = self._build_prompt_chunks(chunks, "positive")
        buckets = self._bucketize(prompt_chunks, POSITIVE_BUCKET_ORDER)
        if prefix_embeddings:
            buckets["embedding_tokens"] = prefix_embeddings
        if self.config.allow_subject_anchor_boost and len(prompt_chunks) >= self.config.subject_anchor_boost_min_chunk_count:
            buckets = self._apply_subject_anchor_boost(buckets)
        dropped: list[str] = []
        if self.config.dedupe_enabled:
            buckets, dropped = self._dedupe_bucket_map(buckets, POSITIVE_BUCKET_ORDER)
        optimized = self._join_positive_buckets(buckets)
        return PromptOptimizationResult(
            original_prompt=original,
            optimized_prompt=optimized,
            polarity="positive",
            buckets=_stringify_bucket_map(buckets),
            dropped_duplicates=dropped,
            changed=optimized != original,
        )

    def _build_negative_result(self, prompt: str) -> PromptOptimizationResult:
        original = str(prompt or "")
        chunks = split_prompt_chunks(original)
        if not chunks or not self.config.optimize_negative:
            return PromptOptimizationResult(
                original_prompt=original,
                optimized_prompt=original,
                polarity="negative",
                changed=False,
            )
        prompt_chunks, prefix_embeddings = self._build_prompt_chunks(chunks, "negative")
        buckets = self._bucketize(prompt_chunks, NEGATIVE_BUCKET_ORDER)
        if prefix_embeddings:
            buckets["embedding_tokens"] = prefix_embeddings
        dropped: list[str] = []
        if self.config.dedupe_enabled:
            buckets, dropped = self._dedupe_bucket_map(buckets, NEGATIVE_BUCKET_ORDER)
        optimized = self._join_negative_buckets(buckets)
        return PromptOptimizationResult(
            original_prompt=original,
            optimized_prompt=optimized,
            polarity="negative",
            buckets=_stringify_bucket_map(buckets),
            dropped_duplicates=dropped,
            changed=optimized != original,
        )

    def _build_prompt_chunks(
        self,
        chunks: list[str],
        polarity: Literal["positive", "negative"],
    ) -> tuple[list[PromptChunk], list[str]]:
        result: list[PromptChunk] = []
        prefix_embeddings: list[str] = []
        sequence_index = 0
        for chunk in chunks:
            original = str(chunk or "").strip()
            if not original:
                continue
            working_chunk = original
            embedding_tokens = extract_embedding_token_strings(original)
            if embedding_tokens:
                prefix_embeddings.extend(embedding_tokens)
                working_chunk = strip_embedding_entries(working_chunk)
                if not working_chunk:
                    continue
            if polarity == "positive":
                working_chunk, lora_tokens = _extract_lora_tokens(original)
                if embedding_tokens:
                    working_chunk = strip_embedding_entries(working_chunk)
                for token in lora_tokens:
                    result.append(
                        PromptChunk(
                            sequence_index=sequence_index,
                            original_text=token,
                            normalized_text=normalize_for_match(token),
                            dedupe_key=build_dedupe_key(token),
                            polarity=polarity,
                            bucket="lora_tokens",
                            weight_syntax_detected=detect_weight_syntax(token),
                            lora_syntax_detected=True,
                        )
                    )
                    sequence_index += 1
            if not working_chunk:
                continue
            result.append(
                PromptChunk(
                    sequence_index=sequence_index,
                    original_text=working_chunk,
                    normalized_text=normalize_for_match(working_chunk),
                    dedupe_key=build_dedupe_key(working_chunk),
                    polarity=polarity,
                    bucket=self._classify(working_chunk, polarity),
                    weight_syntax_detected=detect_weight_syntax(working_chunk),
                    lora_syntax_detected=detect_lora_syntax(working_chunk),
                )
            )
            sequence_index += 1
        return result, prefix_embeddings

    def _bucketize(self, chunks: list[PromptChunk], ordered_buckets: tuple[str, ...]) -> BucketMap:
        buckets: BucketMap = OrderedDict((bucket, []) for bucket in ordered_buckets)
        for chunk in chunks:
            bucket = chunk.bucket if chunk.bucket in buckets else "leftover_unknown"
            bucket_items = buckets.setdefault(bucket, [])
            cast_bucket = cast(list[PromptChunk], bucket_items)
            cast_bucket.append(chunk)
            buckets[bucket] = cast_bucket
        return {bucket: values for bucket, values in buckets.items() if values}

    def _dedupe_bucket_map(
        self,
        buckets: BucketMap,
        ordered_buckets: tuple[str, ...],
    ) -> tuple[BucketMap, list[str]]:
        seen: set[str] = set()
        kept_map: BucketMap = OrderedDict()
        dropped: list[str] = []
        embedding_tokens = [str(item) for item in buckets.get("embedding_tokens") or []]
        if embedding_tokens:
            kept_map["embedding_tokens"] = dedupe_bucket_failsafe(embedding_tokens, dropped)
            for item in kept_map["embedding_tokens"]:
                dedupe_key = build_dedupe_key(str(item))
                if dedupe_key:
                    seen.add(dedupe_key)
        for bucket in ordered_buckets:
            items = [item for item in buckets.get(bucket, []) if isinstance(item, PromptChunk)]
            kept_bucket: list[PromptChunk] = []
            for item in items:
                dedupe_key = item.dedupe_key or build_dedupe_key(item.original_text)
                if dedupe_key and dedupe_key in seen:
                    dropped.append(item.original_text)
                    continue
                if dedupe_key:
                    seen.add(dedupe_key)
                kept_bucket.append(item)
            if kept_bucket:
                kept_map[bucket] = kept_bucket
        return kept_map, dropped

    def _join_positive_buckets(self, buckets: BucketMap) -> str:
        values: list[str] = []
        values.extend([str(item) for item in buckets.get("embedding_tokens", [])])
        values.extend(self._ordered_positive_text_chunks(buckets))
        values.extend(_chunk_text_list(buckets.get("lora_tokens", [])))
        return ", ".join(values)

    def _join_negative_buckets(self, buckets: BucketMap) -> str:
        values: list[str] = []
        values.extend([str(item) for item in buckets.get("embedding_tokens", [])])
        if self.config.preserve_unknown_order:
            values.extend(self._ordered_negative_chunks_with_anchors(buckets))
            return ", ".join(values)
        for bucket in NEGATIVE_BUCKET_ORDER:
            values.extend(_chunk_text_list(buckets.get(bucket, [])))
        return ", ".join(values)

    def _ordered_positive_chunks_with_anchors(self, buckets: BucketMap) -> list[str]:
        ordered_chunks = _all_prompt_chunks(buckets, POSITIVE_BUCKET_ORDER)
        anchored_buckets: set[str] = set()
        if self.config.preserve_unknown_order:
            anchored_buckets.add("leftover_unknown")
        if self.config.preserve_lora_relative_order:
            anchored_buckets.add("lora_tokens")
        return _rebuild_chunk_order_with_anchors(ordered_chunks, POSITIVE_BUCKET_ORDER, anchored_buckets)

    def _ordered_positive_text_chunks(self, buckets: BucketMap) -> list[str]:
        ordered_buckets = tuple(bucket for bucket in POSITIVE_BUCKET_ORDER if bucket != "lora_tokens")
        if self.config.preserve_unknown_order:
            ordered_chunks = _all_prompt_chunks(buckets, ordered_buckets)
            return _rebuild_chunk_order_with_anchors(
                ordered_chunks,
                ordered_buckets,
                {"leftover_unknown"},
            )
        values: list[str] = []
        for bucket in ordered_buckets:
            values.extend(_chunk_text_list(buckets.get(bucket, [])))
        return values

    def _ordered_negative_chunks_with_anchors(self, buckets: BucketMap) -> list[str]:
        ordered_chunks = _all_prompt_chunks(buckets, NEGATIVE_BUCKET_ORDER)
        return _rebuild_chunk_order_with_anchors(ordered_chunks, NEGATIVE_BUCKET_ORDER, {"leftover_unknown"})

    def _apply_subject_anchor_boost(self, buckets: BucketMap) -> BucketMap:
        return dict(buckets)


def dedupe_bucket_failsafe(kept_bucket: list[str], dropped: list[str]) -> list[str]:
    kept, dropped_bucket = dedupe_prompt_chunks(kept_bucket)
    dropped.extend(dropped_bucket)
    return kept


def _extract_lora_tokens(chunk: str) -> tuple[str, list[str]]:
    tokens = [match.group(0).strip() for match in _LORA_TOKEN_RE.finditer(chunk)]
    if not tokens:
        return chunk, []
    text_without_loras = _LORA_TOKEN_RE.sub(" ", chunk)
    cleaned = " ".join(text_without_loras.split()).strip(" ,")
    return cleaned, tokens


def _is_embedding_only_chunk(chunk: str) -> bool:
    stripped = strip_embedding_entries(str(chunk or "").strip())
    return bool((chunk or "").strip()) and not stripped


def _chunk_text_list(values: BucketValues) -> list[str]:
    return [item.original_text for item in values if isinstance(item, PromptChunk)]


def _stringify_bucket_map(buckets: BucketMap) -> dict[str, list[str]]:
    output: dict[str, list[str]] = OrderedDict()
    for key, values in buckets.items():
        if key == "embedding_tokens":
            output[key] = [str(item) for item in values]
        else:
            output[key] = _chunk_text_list(values)
    return output


def _all_prompt_chunks(buckets: BucketMap, ordered_buckets: tuple[str, ...]) -> list[PromptChunk]:
    chunks: list[PromptChunk] = []
    for bucket in ordered_buckets:
        chunks.extend(item for item in buckets.get(bucket, []) if isinstance(item, PromptChunk))
    return chunks


def _rebuild_chunk_order_with_anchors(
    chunks: list[PromptChunk],
    ordered_buckets: tuple[str, ...],
    anchored_buckets: set[str],
) -> list[str]:
    if not chunks:
        return []
    anchored_positions = {
        chunk.sequence_index: chunk
        for chunk in chunks
        if chunk.bucket in anchored_buckets
    }
    movable = sorted(
        [chunk for chunk in chunks if chunk.bucket not in anchored_buckets],
        key=lambda chunk: (ordered_buckets.index(chunk.bucket) if chunk.bucket in ordered_buckets else len(ordered_buckets), chunk.sequence_index),
    )
    movable_iter = iter(movable)
    ordered_text: list[str] = []
    for sequence_index in sorted(chunk.sequence_index for chunk in chunks):
        anchored = anchored_positions.get(sequence_index)
        if anchored is not None:
            ordered_text.append(anchored.original_text)
            continue
        ordered_text.append(next(movable_iter).original_text)
    return ordered_text
