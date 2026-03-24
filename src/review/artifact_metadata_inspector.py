"""Read-only artifact metadata inspection payload builder."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from src.review.review_metadata_service import ReviewMetadataService
from src.utils.image_metadata import (
    extract_embedded_metadata,
    read_embedded_review_metadata,
    read_review_sidecar,
    resolve_model_vae_fields,
    resolve_prompt_fields,
)


@dataclass(frozen=True)
class ArtifactMetadataInspection:
    artifact_path: str
    normalized_generation_summary: dict[str, Any]
    normalized_review_summary: dict[str, Any] | None
    source_diagnostics: dict[str, Any]
    raw_embedded_payload: dict[str, Any] | None
    raw_embedded_review_payload: dict[str, Any] | None
    raw_sidecar_review_payload: dict[str, Any] | None
    raw_internal_review_summary: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_path": self.artifact_path,
            "normalized_generation_summary": dict(self.normalized_generation_summary),
            "normalized_review_summary": dict(self.normalized_review_summary or {}) if self.normalized_review_summary else None,
            "source_diagnostics": dict(self.source_diagnostics),
            "raw_embedded_payload": dict(self.raw_embedded_payload or {}) if self.raw_embedded_payload else None,
            "raw_embedded_review_payload": dict(self.raw_embedded_review_payload or {}) if self.raw_embedded_review_payload else None,
            "raw_sidecar_review_payload": dict(self.raw_sidecar_review_payload or {}) if self.raw_sidecar_review_payload else None,
            "raw_internal_review_summary": dict(self.raw_internal_review_summary or {}) if self.raw_internal_review_summary else None,
        }


class ArtifactMetadataInspector:
    """Collect normalized and raw metadata signals for one artifact."""

    def __init__(self, review_metadata_service: ReviewMetadataService | None = None) -> None:
        self._review_metadata_service = review_metadata_service or ReviewMetadataService()

    @staticmethod
    def _build_generation_summary(payload: Mapping[str, Any] | None) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            return {
                "present": False,
                "manifest_present": False,
            }

        stage_manifest = payload.get("stage_manifest")
        if not isinstance(stage_manifest, Mapping):
            stage_manifest = {}
        generation = payload.get("generation")
        if not isinstance(generation, Mapping):
            generation = {}
        config = stage_manifest.get("config")
        if not isinstance(config, Mapping):
            config = {}
        prompt, negative_prompt = resolve_prompt_fields(dict(payload))
        model, vae = resolve_model_vae_fields(dict(payload))
        return {
            "present": True,
            "prompt": str(prompt or ""),
            "negative_prompt": str(negative_prompt or ""),
            "model": str(model or ""),
            "vae": str(vae or ""),
            "sampler": str(config.get("sampler_name") or config.get("sampler") or generation.get("sampler_name") or ""),
            "scheduler": str(config.get("scheduler") or generation.get("scheduler") or ""),
            "steps": config.get("steps") or generation.get("steps"),
            "cfg_scale": config.get("cfg_scale") or generation.get("cfg_scale"),
            "width": config.get("width") or generation.get("width"),
            "height": config.get("height") or generation.get("height"),
            "seed": stage_manifest.get("final_seed") or generation.get("seed") or config.get("seed"),
            "stage": str(stage_manifest.get("stage") or payload.get("stage") or ""),
            "manifest_present": bool(stage_manifest),
        }

    def inspect_artifact(
        self,
        image_path: str | Path,
        *,
        internal_review_summary: Mapping[str, Any] | None = None,
    ) -> ArtifactMetadataInspection:
        target_path = Path(image_path)
        embedded_generation = extract_embedded_metadata(target_path)
        embedded_review = read_embedded_review_metadata(target_path)
        sidecar_review = read_review_sidecar(target_path)

        generation_payload = (
            embedded_generation.payload
            if embedded_generation.status == "ok" and isinstance(embedded_generation.payload, dict)
            else None
        )
        embedded_review_payload = embedded_review.payload if isinstance(embedded_review.payload, dict) else None
        sidecar_review_payload = sidecar_review.payload if isinstance(sidecar_review.payload, dict) else None
        internal_summary = dict(internal_review_summary) if isinstance(internal_review_summary, Mapping) else None

        warnings: list[str] = []
        if embedded_generation.error:
            warnings.append(f"embedded_generation:{embedded_generation.error}")
        if embedded_review.error:
            warnings.append(f"embedded_review:{embedded_review.error}")
        if sidecar_review.error:
            warnings.append(f"sidecar_review:{sidecar_review.error}")

        internal_present = bool(internal_summary and str(internal_summary.get("source_type") or "") == "internal_learning_record")
        embedded_review_present = embedded_review_payload is not None
        sidecar_review_present = sidecar_review_payload is not None
        if internal_present:
            active_review_precedence = "internal_learning_record"
            normalized_review_summary = internal_summary
        elif embedded_review_present:
            active_review_precedence = "embedded_review_metadata"
            normalized_review = self._review_metadata_service.normalize_review_summary(
                embedded_review_payload,
                source_type="embedded_review_metadata",
            )
            normalized_review_summary = normalized_review.to_dict() if normalized_review is not None else None
        elif sidecar_review_present:
            active_review_precedence = "sidecar_review_metadata"
            normalized_review = self._review_metadata_service.normalize_review_summary(
                sidecar_review_payload,
                source_type="sidecar_review_metadata",
            )
            normalized_review_summary = normalized_review.to_dict() if normalized_review is not None else None
        else:
            active_review_precedence = "none"
            normalized_review_summary = None

        return ArtifactMetadataInspection(
            artifact_path=str(target_path),
            normalized_generation_summary=self._build_generation_summary(generation_payload),
            normalized_review_summary=normalized_review_summary,
            source_diagnostics={
                "embedded_generation_present": generation_payload is not None,
                "embedded_review_present": embedded_review_present,
                "sidecar_review_present": sidecar_review_present,
                "internal_review_present": internal_present,
                "active_review_precedence": active_review_precedence,
                "warnings": warnings,
            },
            raw_embedded_payload=generation_payload,
            raw_embedded_review_payload=embedded_review_payload,
            raw_sidecar_review_payload=sidecar_review_payload,
            raw_internal_review_summary=internal_summary,
        )