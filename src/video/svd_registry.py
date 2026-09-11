"""Manifest and history helpers for native SVD runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.pipeline.artifact_contract import artifact_manifest_payload
from src.utils.file_io import get_safe_filename
from src.video.svd_config import SVDConfig
from src.video.svd_models import SVDResult


def build_svd_artifact_stem(*, source_image_path: str | Path, job_id: str) -> str:
    """Build the deterministic, filesystem-safe stem for one SVD job."""
    source_stem = get_safe_filename(Path(source_image_path).stem)[:96] or "source"
    job_text = str(job_id or "").strip() or "job"
    job_fragment = get_safe_filename(job_text)[:24] or "job"
    identity_hash = hashlib.sha256(f"{source_stem}\0{job_text}".encode()).hexdigest()[:12]
    return f"svd_{source_stem}_{job_fragment}-{identity_hash}"


def write_svd_run_manifest(
    *,
    run_dir: str | Path,
    config: SVDConfig,
    result: SVDResult,
    artifact_stem: str,
    before_write: Callable[[Path], None] | None = None,
) -> Path:
    root = Path(run_dir)
    manifest_dir = root / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{artifact_stem}.json"
    video_paths = [str(result.video_path)] if result.video_path else []
    gif_paths = [str(result.gif_path)] if result.gif_path else []
    frame_paths = [str(path) for path in result.frame_paths]
    output_paths = video_paths or gif_paths or frame_paths
    primary_output = output_paths[0] if output_paths else None
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "source_image_path": str(result.source_image_path),
        "video_path": str(result.video_path) if result.video_path else None,
        "gif_path": str(result.gif_path) if result.gif_path else None,
        "video_paths": video_paths,
        "gif_paths": gif_paths,
        "frame_paths": frame_paths,
        "frame_path_count": len(frame_paths),
        "output_paths": output_paths,
        "manifest_paths": [str(manifest_path)],
        "thumbnail_path": str(result.thumbnail_path) if result.thumbnail_path else None,
        "frame_count": result.frame_count,
        "fps": result.fps,
        "seed": result.seed,
        "model_id": result.model_id,
        "count": len(output_paths),
        "config": config.to_dict(),
        "postprocess": result.postprocess,
        "preprocess": {
            "source_path": str(result.preprocess.source_path),
            "prepared_path": str(result.preprocess.prepared_path),
            "original_width": result.preprocess.original_width,
            "original_height": result.preprocess.original_height,
            "target_width": result.preprocess.target_width,
            "target_height": result.preprocess.target_height,
            "resize_mode": result.preprocess.resize_mode,
            "was_resized": result.preprocess.was_resized,
            "was_padded": result.preprocess.was_padded,
            "was_cropped": result.preprocess.was_cropped,
        },
        "artifact": artifact_manifest_payload(
            stage="svd_native",
            image_or_output_path=primary_output or "",
            manifest_path=manifest_path,
            output_paths=output_paths,
            thumbnail_path=str(result.thumbnail_path) if result.thumbnail_path else None,
            input_image_path=str(result.source_image_path),
            artifact_type="video",
        ),
    }
    secondary_motion = ((result.postprocess or {}).get("secondary_motion") if isinstance(result.postprocess, dict) else None)
    if isinstance(secondary_motion, dict):
        payload["secondary_motion"] = dict(secondary_motion)
    if before_write is not None:
        before_write(manifest_path)
    manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest_path


def build_svd_history_record(*, config: SVDConfig, result: SVDResult) -> dict[str, object]:
    video_paths = [str(result.video_path)] if result.video_path else []
    gif_paths = [str(result.gif_path)] if result.gif_path else []
    frame_paths = [str(path) for path in result.frame_paths]
    output_paths = video_paths or gif_paths or frame_paths
    return {
        "artifact_type": "svd_native",
        "source_image_path": str(result.source_image_path),
        "output_paths": output_paths,
        "video_paths": video_paths,
        "gif_paths": gif_paths,
        "manifest_paths": [str(result.metadata_path)] if result.metadata_path else [],
        "thumbnail_path": str(result.thumbnail_path) if result.thumbnail_path else None,
        "model_id": result.model_id,
        "frame_count": result.frame_count,
        "fps": result.fps,
        "seed": result.seed,
        "count": len(output_paths),
        "config": config.to_dict(),
        "postprocess": result.postprocess,
        "artifact": artifact_manifest_payload(
            stage="svd_native",
            image_or_output_path=output_paths[0] if output_paths else "",
            manifest_path=str(result.metadata_path) if result.metadata_path else None,
            output_paths=output_paths,
            thumbnail_path=str(result.thumbnail_path) if result.thumbnail_path else None,
            input_image_path=str(result.source_image_path),
            artifact_type="video",
        ),
    }
