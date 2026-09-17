"""Pure experiment-wide review projection and navigation rules."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReviewSample:
    variant_index: int
    image_index: int
    variant_id: str
    value: Any
    image_ref: str
    rating: int | None


@dataclass(frozen=True)
class ReviewVariantSummary:
    variant_index: int
    variant_id: str
    value: Any
    status: str
    sample_count: int
    rated_count: int
    samples: tuple[ReviewSample, ...]


@dataclass(frozen=True)
class ExperimentReviewProjection:
    variants: tuple[ReviewVariantSummary, ...]
    samples: tuple[ReviewSample, ...]
    execution_complete: bool
    review_complete: bool

    @property
    def next_unrated(self) -> ReviewSample | None:
        return next((sample for sample in self.samples if sample.rating is None), None)


def build_review_projection(
    variants: list[Any] | tuple[Any, ...],
    rating_lookup: Callable[[str], int | None],
) -> ExperimentReviewProjection:
    summaries: list[ReviewVariantSummary] = []
    samples: list[ReviewSample] = []
    for variant_index, variant in enumerate(variants):
        variant_samples: list[ReviewSample] = []
        for image_index, image_ref in enumerate(list(getattr(variant, "image_refs", []) or [])):
            ref = str(image_ref)
            sample = ReviewSample(
                variant_index=variant_index,
                image_index=image_index,
                variant_id=str(getattr(variant, "variant_id", "") or ""),
                value=getattr(variant, "param_value", None),
                image_ref=ref,
                rating=rating_lookup(ref),
            )
            variant_samples.append(sample)
            samples.append(sample)
        summaries.append(
            ReviewVariantSummary(
                variant_index=variant_index,
                variant_id=str(getattr(variant, "variant_id", "") or ""),
                value=getattr(variant, "param_value", None),
                status=str(getattr(variant, "status", "pending") or "pending"),
                sample_count=len(variant_samples),
                rated_count=sum(sample.rating is not None for sample in variant_samples),
                samples=tuple(variant_samples),
            )
        )
    execution_complete = bool(variants) and all(
        str(getattr(variant, "status", "") or "").lower() in {"completed", "failed"}
        for variant in variants
    )
    review_complete = execution_complete and bool(samples) and all(
        sample.rating is not None for sample in samples
    )
    return ExperimentReviewProjection(
        variants=tuple(summaries),
        samples=tuple(samples),
        execution_complete=execution_complete,
        review_complete=review_complete,
    )
