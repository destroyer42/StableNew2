"""Transient Review compilation/preflight; JobService remains the admission authority."""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from src.curation.curation_manifest import build_review_chunk_lineage_block
from src.gui.controllers.review_workflow_adapter import ReviewWorkflowAdapter
from src.image_backends.operation_compatibility import (
    OperationAssessment,
    OperationNotSupportedError,
    assess_njr,
)
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.reprocess_builder import ReprocessJobBuilder, ReprocessSourceItem
from src.utils.image_metadata import (
    ImageMetadataContractV26,
    extract_embedded_metadata,
    read_image_metadata,
)


@dataclass(frozen=True)
class ReviewBatchItem:
    path: str
    model: str = ""
    prompt: str = ""
    metadata_source: str = "fallback"
    error: str | None = None
    fingerprint: tuple[int, int] | None = None
    source_sha256: str | None = None
    assessment: OperationAssessment | None = None


@dataclass(frozen=True)
class ReviewBatchPreview:
    batch_id: str
    items: tuple[ReviewBatchItem, ...]
    jobs: tuple[NormalizedJobRecord, ...]
    group_count: int
    group_by_model: bool

    @property
    def blocked(self) -> tuple[ReviewBatchItem, ...]:
        return tuple(item for item in self.items if item.error)

    def require_queueable(self) -> None:
        if self.blocked:
            for item in self.blocked:
                if item.assessment is not None:
                    raise OperationNotSupportedError(item.assessment)
            raise ValueError("Nothing queued. Blocked sources:\n" + "\n".join(
                f"{item.path}: {item.error}" for item in self.blocked
            ))
        if not self.jobs:
            raise ValueError("Nothing queued: no compiled Review jobs")
        for item in self.items:
            stat = Path(item.path).stat()
            if (stat.st_size, stat.st_mtime_ns) != item.fingerprint:
                raise ValueError(f"Source changed; preview again: {item.path}")
            if _source_sha256(Path(item.path)) != item.source_sha256:
                raise ValueError(f"Source content changed; preview again: {item.path}")


def _source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare_review_batch(
    controller: Any, *, image_paths: list[str], stages: list[str], fallback_config: dict[str, Any],
    prompt_delta: str = "", negative_prompt_delta: str = "", prompt_mode: str = "append",
    negative_prompt_mode: str = "append", batch_size: int = 1,
    source_metadata_by_image: dict[str, dict[str, Any]] | None = None,
    group_by_model: bool = False,
) -> ReviewBatchPreview:
    """Compile every source with the existing builder; report every refusal before admission."""
    if not image_paths or not stages:
        raise ValueError("Images and target stages are required for reprocessing")
    if set(stages) - {"adetailer", "upscale", "img2img"}:
        raise ValueError(f"Invalid Review stages: {stages}")
    if prompt_mode not in {"append", "replace", "modify"} or negative_prompt_mode not in {"append", "replace", "modify"}:
        raise ValueError("Prompt modes must be append, replace or modify")
    if batch_size <= 0:
        raise ValueError("batch_size must be >= 1")
    batch_id = str(uuid.uuid4())
    builder, sources, rows, jobs = ReprocessJobBuilder(), [], [], []

    def extra(chunk: list[ReprocessSourceItem], _output: str) -> dict[str, Any]:
        metadata = dict(chunk[0].metadata)
        result = build_review_chunk_lineage_block(metadata, target_stage=" -> ".join(stages))
        result.update(batch_id=batch_id, parent_job_id=metadata.get("source_job_id"),
                      parent_artifact_id=metadata.get("source_artifact_id"))
        result["review_batch"] = {"batch_id": batch_id, "source_count": len(image_paths),
                                  "group_by_model": group_by_model}
        return result

    for value in image_paths:
        path = Path(value)
        model, prompt, origin = "", "", "fallback"
        try:
            if not path.is_file():
                raise ValueError("Input image not found")
            before = path.stat()
            source_sha256 = _source_sha256(path)
            with Image.open(path) as image:
                image.load()
            baseline = controller._extract_reprocess_baseline_from_image(path)
            origin = "embedded_metadata" if baseline else "fallback"
            metadata_result = extract_embedded_metadata(path)
            if not baseline and metadata_result.status not in {"missing", "ok"}:
                origin = f"fallback (metadata {metadata_result.status})"
            model = str(baseline.get("model") or "")
            prompt = ReviewWorkflowAdapter.apply_prompt_delta(str(baseline.get("prompt") or ""), prompt_delta, prompt_mode)
            negative = ReviewWorkflowAdapter.apply_prompt_delta(str(baseline.get("negative_prompt") or ""), negative_prompt_delta, negative_prompt_mode)
            metadata = {"baseline_source": origin}
            source_meta = (source_metadata_by_image or {}).get(str(path)) or (source_metadata_by_image or {}).get(str(path.resolve()))
            if isinstance(source_meta, dict):
                metadata.update(source_meta)
            kv = read_image_metadata(path)
            metadata.update(source_job_id=kv.get(ImageMetadataContractV26.KEY_JOB_ID) or baseline.get("job_id") or metadata.get("source_job_id"),
                            source_artifact_id=f"sha256:{source_sha256}",
                            source_path=str(path.resolve()))
            source = ReprocessSourceItem(
                input_image_path=str(path), prompt=prompt, negative_prompt=negative,
                model=model or None, vae=baseline.get("vae"), config=dict(baseline.get("config") or {}),
                metadata=metadata,
            )
            plan = builder.build_grouped_reprocess_jobs(
                items=[source], stages=stages, fallback_config=fallback_config,
                batch_size=1, pack_name="ReviewReprocess", source="review_tab", extra_metadata_builder=extra,
            )
            record = plan.jobs[0]
            model = record.base_model
            assessment = assess_njr(record)
            if not assessment.ready:
                raise OperationNotSupportedError(assessment)
            after = path.stat()
            fingerprint = (after.st_size, after.st_mtime_ns)
            if fingerprint != (before.st_size, before.st_mtime_ns) or _source_sha256(path) != source_sha256:
                raise ValueError("Source changed while preparing; preview again")
            sources.append(source)
            jobs.extend(plan.jobs)
            rows.append(ReviewBatchItem(str(path), model, prompt, origin,
                                       fingerprint=fingerprint, source_sha256=source_sha256))
        except (ValueError, OSError, TypeError) as exc:
            rows.append(ReviewBatchItem(str(path), model, prompt, origin, error=str(exc),
                                       assessment=exc.assessment if isinstance(exc, OperationNotSupportedError) else None))

    # Preserve explicitly requested legacy compatible multi-source jobs. Default remains one job per source.
    if batch_size > 1 and sources:
        plan = builder.build_grouped_reprocess_jobs(
            items=sources, stages=stages, fallback_config=fallback_config, batch_size=batch_size,
            pack_name="ReviewReprocess", source="review_tab", extra_metadata_builder=extra,
        )
        jobs = plan.jobs
    def group_key(job: NormalizedJobRecord) -> tuple[str, str]:
        profile = job.backend_options.get("image", {}).get("model_profile") or {}
        return job.base_model.casefold(), json.dumps(profile, sort_keys=True)

    group_count = len({group_key(job) for job in jobs})
    if group_by_model:
        jobs.sort(key=group_key)
    return ReviewBatchPreview(batch_id, tuple(rows), tuple(jobs), group_count, group_by_model)
