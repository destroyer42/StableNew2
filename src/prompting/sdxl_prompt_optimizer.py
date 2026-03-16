from __future__ import annotations

from collections import OrderedDict

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

    def _classify(self, chunk: str, polarity: str) -> str:
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
        prompt_chunks = self._build_prompt_chunks(chunks, "positive")
        buckets = self._bucketize(prompt_chunks, POSITIVE_BUCKET_ORDER)
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
            buckets=buckets,
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
        prompt_chunks = self._build_prompt_chunks(chunks, "negative")
        buckets = self._bucketize(prompt_chunks, NEGATIVE_BUCKET_ORDER)
        dropped: list[str] = []
        if self.config.dedupe_enabled:
            buckets, dropped = self._dedupe_bucket_map(buckets, NEGATIVE_BUCKET_ORDER)
        optimized = self._join_negative_buckets(buckets)
        return PromptOptimizationResult(
            original_prompt=original,
            optimized_prompt=optimized,
            polarity="negative",
            buckets=buckets,
            dropped_duplicates=dropped,
            changed=optimized != original,
        )

    def _build_prompt_chunks(self, chunks: list[str], polarity: str) -> list[PromptChunk]:
        result: list[PromptChunk] = []
        for chunk in chunks:
            original = str(chunk or "").strip()
            if not original:
                continue
            result.append(
                PromptChunk(
                    original_text=original,
                    normalized_text=normalize_for_match(original),
                    dedupe_key=build_dedupe_key(original),
                    polarity=polarity,  # type: ignore[arg-type]
                    bucket=self._classify(original, polarity),
                    weight_syntax_detected=detect_weight_syntax(original),
                    lora_syntax_detected=detect_lora_syntax(original),
                )
            )
        return result

    def _bucketize(self, chunks: list[PromptChunk], ordered_buckets: tuple[str, ...]) -> dict[str, list[str]]:
        buckets: dict[str, list[str]] = OrderedDict((bucket, []) for bucket in ordered_buckets)
        for chunk in chunks:
            bucket = chunk.bucket if chunk.bucket in buckets else "leftover_unknown"
            buckets[bucket].append(chunk.original_text)
        return {bucket: values for bucket, values in buckets.items() if values}

    def _dedupe_bucket_map(
        self,
        buckets: dict[str, list[str]],
        ordered_buckets: tuple[str, ...],
    ) -> tuple[dict[str, list[str]], list[str]]:
        seen: set[str] = set()
        kept_map: dict[str, list[str]] = OrderedDict()
        dropped: list[str] = []
        for bucket in ordered_buckets:
            items = list(buckets.get(bucket) or [])
            kept_bucket: list[str] = []
            for item in items:
                dedupe_key = build_dedupe_key(item)
                if dedupe_key and dedupe_key in seen:
                    dropped.append(item)
                    continue
                if dedupe_key:
                    seen.add(dedupe_key)
                kept_bucket.append(item)
            if kept_bucket:
                kept_map[bucket] = dedupe_bucket_failsafe(kept_bucket, dropped)
        return kept_map, dropped

    def _join_positive_buckets(self, buckets: dict[str, list[str]]) -> str:
        values: list[str] = []
        for bucket in POSITIVE_BUCKET_ORDER:
            values.extend(buckets.get(bucket, []))
        return ", ".join(values)

    def _join_negative_buckets(self, buckets: dict[str, list[str]]) -> str:
        values: list[str] = []
        for bucket in NEGATIVE_BUCKET_ORDER:
            values.extend(buckets.get(bucket, []))
        return ", ".join(values)

    def _apply_subject_anchor_boost(self, buckets: dict[str, list[str]]) -> dict[str, list[str]]:
        return dict(buckets)


def dedupe_bucket_failsafe(kept_bucket: list[str], dropped: list[str]) -> list[str]:
    kept, dropped_bucket = dedupe_prompt_chunks(kept_bucket)
    dropped.extend(dropped_bucket)
    return kept
