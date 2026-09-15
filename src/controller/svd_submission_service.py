"""Thin form-data bridge for SVD submissions owned by AppController."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.controller.svd_controller import SVDController
from src.pipeline.config_contract_v26 import validate_svd_native_execution_config


def preview_folder_batch(controller: SVDController, folder_path: str | Path) -> dict[str, object]:
    discovery = controller.discover_folder_sources(folder_path)
    return {
        "folder": str(discovery.folder),
        "compatible_count": len(discovery.sources),
        "ignored_count": len(discovery.ignored_paths),
        "invalid_candidates": [
            {"path": str(path), "reason": reason} for path, reason in discovery.invalid_candidates
        ],
        "first_source_path": str(discovery.sources[0].path) if discovery.sources else None,
    }


def submit_single(
    controller: SVDController, source_image_path: str | Path, form_data: dict[str, Any]
) -> str:
    validated = validate_svd_native_execution_config(form_data)
    config = controller.build_svd_config(validated)
    valid, reason = controller.validate_source_image(source_image_path)
    if not valid:
        raise ValueError(reason or "SVD source image is invalid")
    pipeline = validated.get("pipeline")
    route = pipeline.get("output_route") if isinstance(pipeline, dict) else None
    return controller.submit_svd_job(
        source_image_path=source_image_path,
        config=config,
        output_route=str(route) if route else None,
    )


def submit_folder_batch(
    controller: SVDController,
    folder_path: str | Path,
    form_data: dict[str, Any],
    match_source_aspect: bool,
) -> list[str]:
    validated = validate_svd_native_execution_config(form_data)
    config = controller.build_svd_config(validated)
    pipeline = validated.get("pipeline")
    route = pipeline.get("output_route") if isinstance(pipeline, dict) else None
    return controller.submit_svd_folder_batch(
        folder=folder_path,
        config=config,
        match_source_aspect=match_source_aspect,
        output_route=str(route) if route else None,
    )
