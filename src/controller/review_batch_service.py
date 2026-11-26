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
from src.image_backends.image_backend_types import configured_image_backend_id
from src.image_backends.operation_compatibility import (
    OperationAssessment,
    OperationNotSupportedError,
    assess_njr,
)
from src.pipeline.adetailer_contract import classify_detector
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.policy_warnings import with_pending_warnings
from src.pipeline.reprocess_builder import ReprocessJobBuilder, ReprocessSourceItem
from src.review.archive import configured_output_root, job_queue_of
from src.review.assist.contracts import AssistError
from src.review.assist.identity import current_file_sha256
from src.review.correction_advice import (
    GuidedReprocess,
    detectors_for,
    resolve_target,
    target_refusal,
    target_verdict,
)
from src.review.findings import CORRECTION_KEY, Action, correction_context
from src.review.workflow_adapter import ReviewWorkflowAdapter
from src.utils.image_metadata import (
    ImageMetadataContractV26,
    extract_embedded_metadata,
    read_image_metadata,
)


@dataclass(frozen=True)
class AdetailerPasses:
    """Which of the executor's ADetailer passes run, each with the detectors usable for it (empty: the pass is off).

    A pass keeps the detector the source recorded (or the current ADetailer settings name) when it is usable, and
    otherwise uses the first usable one, so a job never names a detector the backend does not list.
    """

    face: tuple[str, ...] = ()
    hands: tuple[str, ...] = ()

    def apply(self, recorded: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
        block = dict(recorded)
        chosen = {**fallback, **recorded}
        block["enable_face_pass"] = bool(self.face)
        block["enable_hands_pass"] = block["ad_hands_enabled"] = bool(self.hands)
        for key, usable in (("adetailer_model", self.face), ("adetailer_hands_model", self.hands)):
            if usable:
                current = chosen.get(key)
                block[key] = current if current in usable else usable[0]
        return block


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
    guided: bool = False

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
            hash_source = current_file_sha256 if self.guided else _source_sha256
            if hash_source(Path(item.path)) != item.source_sha256:
                raise ValueError(f"Source content changed; preview again: {item.path}")


def review_output_dir(controller: Any) -> str:
    """The configured output root a Review re-work job writes under (``<root>/Reprocess/...``).

    One authority, the one Pipeline jobs and the Review archive use: the ``output_dir`` setting of the controller's
    config manager, route folders stripped. Without a config manager (a bare test double) the builder default stays.
    """

    manager = getattr(controller, "_config_manager", None)
    return str(configured_output_root(manager)) if manager is not None else "output"


def parent_job_model(controller: Any, job_id: Any) -> str:
    """The checkpoint the job that wrote an artifact ran with, for artifacts that recorded none of their own.

    Re-work children written before the stage manifest carried the checkpoint embed no model. The immutable job
    snapshot does, so the model is carried forward from the parent job rather than dropped to ``unknown``.
    """

    queue = job_queue_of(controller)
    getter = getattr(queue, "get_job", None)
    if not callable(getter) or not job_id:
        return ""
    try:
        job = getter(str(job_id))
    except Exception:  # noqa: BLE001 - an unreadable job only means the artifact stays without a recorded model
        return ""
    snapshot = getattr(job, "snapshot", None)
    value = snapshot.get("base_model") if isinstance(snapshot, dict) else None
    return value.strip() if isinstance(value, str) and value.strip().lower() not in {"", "unknown", "n/a"} else ""


def _source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_history_iterate_identity(
    metadata: dict[str, Any], embedded_job_id: Any, source_sha256: str
) -> None:
    """An Iterate-from-History handoff names the job and bytes it came from; the file must still be exactly that.

    A different embedded job id or a changed image is a refusal, never a silent re-attribution to another parent.
    """

    claim = metadata.get("history_iterate")
    if not isinstance(claim, dict):
        return
    expected_job = str(claim.get("job_id") or metadata.get("source_job_id") or "")
    if embedded_job_id and expected_job and str(embedded_job_id) != expected_job:
        raise ValueError("Image identity contradicts the History job it was opened from; refusing to re-attribute it")
    expected_artifact = str(metadata.get("source_artifact_id") or "")
    if expected_artifact and expected_artifact != f"sha256:{source_sha256}":
        raise ValueError("The recorded image changed since it was opened from History; reopen it from History")


require_history_iterate_identity = _require_history_iterate_identity


def prepare_review_batch(
    controller: Any, *, image_paths: list[str], stages: list[str], fallback_config: dict[str, Any],
    prompt_delta: str = "", negative_prompt_delta: str = "", prompt_mode: str = "append",
    negative_prompt_mode: str = "append", batch_size: int = 1,
    source_metadata_by_image: dict[str, dict[str, Any]] | None = None,
    group_by_model: bool = False,
    guided: GuidedReprocess | None = None,
    adetailer_passes: AdetailerPasses | None = None,
) -> ReviewBatchPreview:
    """Compile every source with the existing builder; report every refusal before admission.

    ``adetailer_passes`` sets which of the executor's ADetailer passes run, over whatever the source recorded
    (RG-140 phone fixes: face, hands or both on that exact image).
    """
    if not image_paths or not stages:
        raise ValueError("Images and target stages are required for reprocessing")
    if set(stages) - {"adetailer", "upscale", "img2img"}:
        raise ValueError(f"Invalid Review stages: {stages}")
    if prompt_mode not in {"append", "replace", "modify"} or negative_prompt_mode not in {"append", "replace", "modify"}:
        raise ValueError("Prompt modes must be append, replace or modify")
    if batch_size <= 0:
        raise ValueError("batch_size must be >= 1")
    if guided is not None and (
        guided.action not in (Action.REPROCESS, Action.FACE, Action.HANDS)
        or guided.resources is None
        or (guided.stage == "adetailer" and classify_detector(guided.detector) != (
            "face" if guided.action is Action.FACE else "hand"
        ))
        or len(image_paths) != 1 or batch_size != 1 or stages != [guided.stage]
    ):
        raise ValueError("A guided correction prepares exactly one source and one stage.")
    if adetailer_passes is not None and (
        guided is not None
        or stages != ["adetailer"]
        or not (adetailer_passes.face or adetailer_passes.hands)
    ):
        raise ValueError("ADetailer passes need the ADetailer stage alone and at least one pass.")
    batch_id = str(uuid.uuid4())
    builder, sources, rows, jobs = ReprocessJobBuilder(), [], [], []
    output_dir = review_output_dir(controller)
    hash_source = current_file_sha256 if guided is not None else _source_sha256

    def extra(chunk: list[ReprocessSourceItem], _output: str) -> dict[str, Any]:
        metadata = dict(chunk[0].metadata)
        result = build_review_chunk_lineage_block(metadata, target_stage=" -> ".join(stages))
        result.update(batch_id=batch_id, parent_job_id=metadata.get("source_job_id"),
                      parent_artifact_id=metadata.get("source_artifact_id"))
        if guided is not None:
            result[CORRECTION_KEY] = correction_context(
                guided.source, guided.category, guided.region, guided.action
            )
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
            source_sha256 = hash_source(path)
            if guided is not None and (
                path != guided.source.path or source_sha256 != guided.source.identity.file_sha256
            ):
                raise ValueError("The inspected source changed. Inspect it again before Preview.")
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
            embedded_job_id = kv.get(ImageMetadataContractV26.KEY_JOB_ID)
            _require_history_iterate_identity(metadata, embedded_job_id or baseline.get("job_id"), source_sha256)
            parent_job_id = embedded_job_id or baseline.get("job_id") or metadata.get("source_job_id")
            metadata.update(source_job_id=parent_job_id,
                            source_artifact_id=f"sha256:{source_sha256}",
                            source_path=str(path.resolve()))
            config = dict(baseline.get("config") or {})
            if guided is not None:
                target = resolve_target(baseline, fallback_config, guided.stage)
                if (
                    (target.model, target.backend) != (guided.model, guided.backend)
                    or target.backend != configured_image_backend_id()
                ):
                    raise ValueError("The correction target changed. Reopen Inspect & Improve.")
                assert guided.resources is not None
                refusal = target_refusal(
                    guided.action, target, guided.resources, source_size=guided.source.identity.size
                )
                if refusal:
                    raise ValueError(refusal)
                if guided.stage == "adetailer" and guided.detector not in detectors_for(
                    guided.action, guided.resources
                ):
                    raise ValueError("The selected detector is unavailable for this pass.")
                model = target.model
                if guided.stage == "adetailer":
                    face = guided.action is Action.FACE
                    config["adetailer"] = {
                        **dict(config.get("adetailer") or {}),
                        "enable_face_pass": face,
                        "enable_hands_pass": not face,
                        "ad_hands_enabled": not face,
                        ("adetailer_model" if face else "adetailer_hands_model"): guided.detector,
                    }
                    if not face:
                        if prompt_delta:
                            config["adetailer"]["adetailer_hands_prompt"] = prompt
                        if negative_prompt_delta:
                            config["adetailer"]["adetailer_hands_negative_prompt"] = negative
            if adetailer_passes is not None:
                config["adetailer"] = adetailer_passes.apply(
                    dict(config.get("adetailer") or {}),
                    dict(fallback_config.get("adetailer") or {}),
                )
            source = ReprocessSourceItem(
                input_image_path=str(path), prompt=prompt, negative_prompt=negative,
                model=model or None, vae=baseline.get("vae"), config=config,
                metadata=metadata,
            )
            plan = builder.build_grouped_reprocess_jobs(
                items=[source], stages=stages, fallback_config=fallback_config,
                batch_size=1, pack_name="ReviewReprocess", source="review_tab", extra_metadata_builder=extra,
                output_dir=output_dir,
            )
            record = plan.jobs[0]
            if guided is not None:  # N1b: the unclassified-target warning travels to Preview; Queue accepts it
                record = with_pending_warnings(record, target_verdict(guided.action, target).warnings)
            model = record.base_model
            assessment = assess_njr(record)
            if not assessment.ready:
                raise OperationNotSupportedError(assessment)
            after = path.stat()
            fingerprint = (after.st_size, after.st_mtime_ns)
            if fingerprint != (before.st_size, before.st_mtime_ns) or hash_source(path) != source_sha256:
                raise ValueError("Source changed while preparing; preview again")
            sources.append(source)
            jobs.extend(plan.jobs)
            rows.append(ReviewBatchItem(str(path), model, prompt, origin,
                                       fingerprint=fingerprint, source_sha256=source_sha256))
        except (ValueError, OSError, TypeError, AssistError) as exc:
            rows.append(ReviewBatchItem(str(path), model, prompt, origin, error=str(exc),
                                       assessment=exc.assessment if isinstance(exc, OperationNotSupportedError) else None))

    # Preserve explicitly requested legacy compatible multi-source jobs. Default remains one job per source.
    if batch_size > 1 and sources:
        plan = builder.build_grouped_reprocess_jobs(
            items=sources, stages=stages, fallback_config=fallback_config, batch_size=batch_size,
            pack_name="ReviewReprocess", source="review_tab", extra_metadata_builder=extra,
            output_dir=output_dir,
        )
        jobs = plan.jobs
    def group_key(job: NormalizedJobRecord) -> tuple[str, str]:
        profile = job.backend_options.get("image", {}).get("model_profile") or {}
        return job.base_model.casefold(), json.dumps(profile, sort_keys=True)

    group_count = len({group_key(job) for job in jobs})
    if group_by_model:
        jobs.sort(key=group_key)
    return ReviewBatchPreview(batch_id, tuple(rows), tuple(jobs), group_count, group_by_model, guided is not None)
