"""Manifest and history helpers for native SVD runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.video.svd_config import SVDConfig
from src.video.svd_models import SVDResult


def write_svd_run_manifest(*, run_dir: str | Path, config: SVDConfig, result: SVDResult) -> Path:
    root = Path(run_dir)
    manifest_dir = root / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_name = result.video_path.stem if result.video_path else result.source_image_path.stem
    manifest_path = manifest_dir / f"{manifest_name}.json"
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "source_image_path": str(result.source_image_path),
        "video_path": str(result.video_path) if result.video_path else None,
        "gif_path": str(result.gif_path) if result.gif_path else None,
        "frame_paths": [str(path) for path in result.frame_paths],
        "thumbnail_path": str(result.thumbnail_path) if result.thumbnail_path else None,
        "frame_count": result.frame_count,
        "fps": result.fps,
        "seed": result.seed,
        "model_id": result.model_id,
        "config": config.to_dict(),
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
    }
    manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest_path


def build_svd_history_record(*, config: SVDConfig, result: SVDResult) -> dict[str, object]:
    return {
        "artifact_type": "svd_native",
        "source_image_path": str(result.source_image_path),
        "output_paths": [str(result.video_path)] if result.video_path else [],
        "thumbnail_path": str(result.thumbnail_path) if result.thumbnail_path else None,
        "model_id": result.model_id,
        "frame_count": result.frame_count,
        "fps": result.fps,
        "seed": result.seed,
        "config": config.to_dict(),
    }
