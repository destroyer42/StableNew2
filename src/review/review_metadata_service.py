"""Portable review metadata stamping for reviewed image artifacts."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from src.learning.learning_record import LearningRecord
from src.utils.image_metadata import (
    read_portable_review_metadata,
    write_portable_review_metadata,
)

logger = logging.getLogger(__name__)

REVIEW_METADATA_SCHEMA = "stablenew.review.v2.6"
INTERNAL_REVIEW_SUMMARY_SCHEMA = "stablenew.internal-review-summary.v2.6"


@dataclass(frozen=True)
class PortableReviewSummary:
    source_type: str
    schema: str
    review_timestamp: str = ""
    user_rating: int | float | None = None
    user_rating_raw: int | float | None = None
    quality_label: str = ""
    subscores: dict[str, Any] | None = None
    weighted_score: int | float | None = None
    user_notes: str = ""
    prompt_before: str = ""
    prompt_after: str = ""
    negative_prompt_before: str = ""
    negative_prompt_after: str = ""
    prompt_delta: str = ""
    negative_prompt_delta: str = ""
    prompt_mode: str = ""
    negative_prompt_mode: str = ""
    stages: list[str] | None = None
    review_context: dict[str, Any] | None = None
    review_record_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "schema": self.schema,
            "review_timestamp": self.review_timestamp,
            "user_rating": self.user_rating,
            "user_rating_raw": self.user_rating_raw,
            "quality_label": self.quality_label,
            "subscores": dict(self.subscores or {}),
            "weighted_score": self.weighted_score,
            "user_notes": self.user_notes,
            "prompt_before": self.prompt_before,
            "prompt_after": self.prompt_after,
            "negative_prompt_before": self.negative_prompt_before,
            "negative_prompt_after": self.negative_prompt_after,
            "prompt_delta": self.prompt_delta,
            "negative_prompt_delta": self.negative_prompt_delta,
            "prompt_mode": self.prompt_mode,
            "negative_prompt_mode": self.negative_prompt_mode,
            "stages": list(self.stages or []),
            "review_context": dict(self.review_context or {}),
            "review_record_id": self.review_record_id,
        }


@dataclass(frozen=True)
class ReviewMetadataStampResult:
    success: bool
    storage: str
    stamped_path: str | None
    sidecar_path: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class ReviewMetadataReadResult:
    payload: dict[str, Any] | None
    source: str
    path: str | None = None
    error: str | None = None


class ReviewMetadataService:
    """Builds, stamps, and reads portable review metadata for image artifacts."""

    @staticmethod
    def _clean_text(value: Any) -> str:
        return str(value or "")

    def normalize_review_summary(
        self,
        payload: Mapping[str, Any],
        *,
        source_type: str,
    ) -> PortableReviewSummary | None:
        if not isinstance(payload, Mapping):
            return None
        subscores = payload.get("subscores")
        if not isinstance(subscores, Mapping):
            subscores = {}
        review_context = payload.get("review_context")
        if not isinstance(review_context, Mapping):
            review_context = {}
        stages = payload.get("stages")
        if not isinstance(stages, list):
            stages = []
        schema = self._clean_text(payload.get("schema") or REVIEW_METADATA_SCHEMA)
        return PortableReviewSummary(
            source_type=source_type,
            schema=schema,
            review_timestamp=self._clean_text(payload.get("review_timestamp") or payload.get("timestamp")),
            user_rating=payload.get("user_rating") if payload.get("user_rating") is not None else payload.get("rating"),
            user_rating_raw=payload.get("user_rating_raw"),
            quality_label=self._clean_text(payload.get("quality_label")),
            subscores=dict(subscores),
            weighted_score=payload.get("weighted_score"),
            user_notes=self._clean_text(payload.get("user_notes") or payload.get("notes")),
            prompt_before=self._clean_text(payload.get("prompt_before")),
            prompt_after=self._clean_text(payload.get("prompt_after")),
            negative_prompt_before=self._clean_text(payload.get("negative_prompt_before")),
            negative_prompt_after=self._clean_text(payload.get("negative_prompt_after")),
            prompt_delta=self._clean_text(payload.get("prompt_delta")),
            negative_prompt_delta=self._clean_text(payload.get("negative_prompt_delta")),
            prompt_mode=self._clean_text(payload.get("prompt_mode")),
            negative_prompt_mode=self._clean_text(payload.get("negative_prompt_mode")),
            stages=[str(stage) for stage in stages if str(stage or "").strip()],
            review_context=dict(review_context),
            review_record_id=self._clean_text(payload.get("review_record_id") or payload.get("run_id")),
        )

    def build_review_payload(
        self,
        *,
        image_path: str | Path,
        feedback: Mapping[str, Any],
        record: LearningRecord,
    ) -> dict[str, Any]:
        metadata = dict(getattr(record, "metadata", {}) or {})
        review_context = dict(metadata.get("review_context") or {})
        subscores = dict(metadata.get("subscores") or {})

        payload: dict[str, Any] = {
            "schema": REVIEW_METADATA_SCHEMA,
            "review_timestamp": str(getattr(record, "timestamp", "") or metadata.get("review_timestamp") or ""),
            "source": str(metadata.get("source") or "review_tab"),
            "image_path": str(image_path),
            "user_rating": metadata.get("user_rating"),
            "user_rating_raw": metadata.get("user_rating_raw"),
            "quality_label": str(metadata.get("quality_label") or ""),
            "subscores": {
                "anatomy": subscores.get("anatomy"),
                "composition": subscores.get("composition"),
                "prompt_adherence": subscores.get("prompt_adherence"),
            },
            "weighted_score": metadata.get("weighted_score"),
            "user_notes": str(metadata.get("user_notes") or ""),
            "prompt_before": str(metadata.get("prompt_before") or ""),
            "prompt_after": str(metadata.get("prompt_after") or ""),
            "negative_prompt_before": str(metadata.get("negative_prompt_before") or ""),
            "negative_prompt_after": str(metadata.get("negative_prompt_after") or ""),
            "prompt_delta": str(metadata.get("prompt_delta") or ""),
            "negative_prompt_delta": str(metadata.get("negative_prompt_delta") or ""),
            "prompt_mode": str(metadata.get("prompt_mode") or "append"),
            "negative_prompt_mode": str(metadata.get("negative_prompt_mode") or "append"),
            "stages": list(metadata.get("stages") or []),
            "review_context": review_context,
            "review_actor": str(review_context.get("actor") or "user"),
            "review_record_id": str(getattr(record, "run_id", "") or ""),
            "run_id": str(getattr(record, "run_id", "") or ""),
            "record_kind": str(metadata.get("record_kind") or "review_tab_feedback"),
        }

        optional_fields = {
            "model": metadata.get("model") or getattr(record, "primary_model", ""),
            "sampler": feedback.get("sampler") or getattr(record, "primary_sampler", ""),
            "scheduler": feedback.get("scheduler") or getattr(record, "primary_scheduler", ""),
            "steps": feedback.get("steps") or getattr(record, "primary_steps", None),
            "cfg_scale": feedback.get("cfg_scale") or getattr(record, "primary_cfg_scale", None),
            "review_tags": list(feedback.get("review_tags") or []),
            "lineage": feedback.get("lineage"),
            "selection_event": feedback.get("selection_event"),
            "curation_decision": feedback.get("curation_decision"),
            "source_candidate_id": feedback.get("source_candidate_id"),
            "derived_candidate_id": feedback.get("derived_candidate_id"),
        }
        for key, value in optional_fields.items():
            if value in (None, "", [], {}):
                continue
            payload[key] = value

        payload["subscores"] = {
            key: value
            for key, value in dict(payload.get("subscores") or {}).items()
            if value is not None
        }
        return payload

    def stamp_review_metadata(
        self,
        *,
        image_path: str | Path,
        feedback: Mapping[str, Any],
        record: LearningRecord,
    ) -> ReviewMetadataStampResult:
        target_path = Path(image_path)
        payload = self.build_review_payload(image_path=target_path, feedback=feedback, record=record)

        embedded_result = write_portable_review_metadata(target_path, payload)
        if embedded_result.success:
            return ReviewMetadataStampResult(
                success=True,
                storage=embedded_result.storage,
                stamped_path=embedded_result.path,
                sidecar_path=embedded_result.sidecar_path,
            )

        logger.warning(
            "Portable review metadata stamping failed for %s: %s",
            target_path,
            embedded_result.error,
        )
        return ReviewMetadataStampResult(
            success=False,
            storage=embedded_result.storage,
            stamped_path=embedded_result.path,
            sidecar_path=embedded_result.sidecar_path,
            error=embedded_result.error,
        )

    def read_review_metadata(self, image_path: str | Path) -> ReviewMetadataReadResult:
        result = read_portable_review_metadata(Path(image_path))
        return ReviewMetadataReadResult(
            payload=result.payload,
            source=result.source,
            path=result.path,
            error=result.error,
        )

    def read_review_summary(self, image_path: str | Path) -> PortableReviewSummary | None:
        result = self.read_review_metadata(image_path)
        if not isinstance(result.payload, dict):
            return None
        source_map = {
            "embedded": "embedded_review_metadata",
            "sidecar": "sidecar_review_metadata",
        }
        return self.normalize_review_summary(
            result.payload,
            source_type=source_map.get(result.source, result.source or "portable_review_metadata"),
        )