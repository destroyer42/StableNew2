"""StableNew-owned post-video assembly orchestration.

PR-VIDEO-217: Accepts canonical sequence/video bundles, stitches segment clips,
optionally invokes an interpolation provider, and emits one provenance-aware
assembled-video result plus manifest.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Callable

from src.pipeline.artifact_contract import artifact_manifest_payload
from src.video.assembly_models import (
    AssembledSequenceInput,
    AssembledVideoResult,
    AssemblyRequest,
    ExportReadyOutputBundle,
    InterpolatedOutput,
    StitchedOutput,
)
from src.video.interpolation_contracts import (
    InterpolationRequest,
    InterpolationProvider,
    NoOpInterpolationProvider,
)
from src.video.video_artifact_helpers import build_video_artifact_bundle
from src.video.video_export import export_image_sequence_video, stitch_video_segments

logger = logging.getLogger(__name__)

ASSEMBLY_MANIFEST_SCHEMA = "stablenew_assembly_manifest_v1"
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}


class AssemblyService:
    """StableNew-owned sequence stitching and export orchestration."""

    def __init__(
        self,
        *,
        image_exporter: Callable[..., Path] | None = None,
        segment_stitcher: Callable[..., Path] | None = None,
        interpolation_provider: InterpolationProvider | None = None,
    ) -> None:
        self._image_exporter = image_exporter or export_image_sequence_video
        self._segment_stitcher = segment_stitcher or stitch_video_segments
        self._interpolation_provider = interpolation_provider or NoOpInterpolationProvider()

    def build_source_from_bundle(self, source_bundle: dict[str, Any]) -> AssembledSequenceInput:
        if not isinstance(source_bundle, dict):
            raise ValueError("source_bundle must be a dict")

        if isinstance(source_bundle.get("source"), dict):
            return AssembledSequenceInput.from_dict(source_bundle["source"])

        if isinstance(source_bundle.get("export_output"), dict):
            export_output = source_bundle["export_output"]
            artifact_bundle = export_output.get("artifact_bundle") or export_output
            return AssembledSequenceInput.from_video_artifact_bundle(
                artifact_bundle,
                source_kind="assembled_video",
            )

        if isinstance(source_bundle.get("segment_provenance"), list):
            return AssembledSequenceInput.from_sequence_artifact(source_bundle)

        return AssembledSequenceInput.from_video_artifact_bundle(source_bundle)

    def build_source_from_paths(self, source_paths: Sequence[str | Path]) -> AssembledSequenceInput:
        resolved_paths = [Path(item) for item in source_paths if item]
        if not resolved_paths:
            raise ValueError("source_paths must not be empty")

        suffixes = {path.suffix.lower() for path in resolved_paths}
        if suffixes and suffixes.issubset(_IMAGE_EXTENSIONS):
            return AssembledSequenceInput.from_paths(
                [str(path) for path in resolved_paths],
                source_kind="manual_frames",
                source_id="manual_frames",
            )
        return AssembledSequenceInput.from_paths(
            [str(path) for path in resolved_paths],
            source_kind="video_segments",
            source_id="video_segments",
        )

    def assemble(self, request: AssemblyRequest) -> AssembledVideoResult:
        errors = request.validate()
        if errors:
            return AssembledVideoResult.failure(
                "; ".join(errors),
                source=request.source,
                clip_name=request.clip_name,
                export_settings=request.export_settings_dict(),
            )

        output_dir = Path(request.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        clip_name = request.clip_name.strip() or "assembled_video"
        export_settings = request.export_settings_dict()
        source = request.source

        try:
            if self._source_uses_frame_export(source):
                frame_paths = [Path(item) for item in (source.resolved_frame_paths() or source.source_paths)]
                output_path = self._image_exporter(
                    image_paths=frame_paths,
                    output_path=output_dir / f"{clip_name}.mp4",
                    fps=request.fps,
                    codec=request.codec,
                    quality=request.quality,
                    mode=request.mode,
                    duration_per_image=request.duration_per_image,
                    transition_duration=request.transition_duration,
                )
                export_output = self._build_export_output(
                    primary_path=str(output_path),
                    output_paths=[str(output_path)],
                    manifest_path=None,
                    source_image_path=str(frame_paths[0]) if frame_paths else None,
                )
                result = AssembledVideoResult(
                    success=True,
                    source=source,
                    export_settings=export_settings,
                    export_output=export_output,
                    clip_name=clip_name,
                )
            else:
                segment_paths = [Path(item) for item in source.resolved_segment_output_paths()]
                if not segment_paths:
                    return AssembledVideoResult.failure(
                        "No segment outputs available for stitched assembly",
                        source=source,
                        clip_name=clip_name,
                        export_settings=export_settings,
                    )

                stitched_path = self._segment_stitcher(
                    segment_paths=segment_paths,
                    output_path=output_dir / f"{clip_name}.mp4",
                )
                stitched_bundle = self._build_artifact_bundle(
                    primary_path=str(stitched_path),
                    output_paths=[str(stitched_path)],
                    manifest_path=None,
                    source_image_path=source.source_image_path(),
                )
                stitched_output = StitchedOutput(
                    primary_path=str(stitched_path),
                    output_paths=[str(stitched_path)],
                    source_segment_paths=[str(path) for path in segment_paths],
                    artifact_bundle=stitched_bundle,
                )
                export_output = ExportReadyOutputBundle(
                    primary_path=str(stitched_path),
                    output_paths=[str(stitched_path)],
                    manifest_path=None,
                    artifact_bundle=dict(stitched_bundle),
                )
                interpolated_output: InterpolatedOutput | None = None

                if request.interpolation_enabled:
                    interpolation_result = self._interpolation_provider.interpolate(
                        InterpolationRequest(
                            input_paths=list(export_output.output_paths),
                            output_dir=str(output_dir),
                            clip_name=clip_name,
                            factor=request.interpolation_factor,
                            metadata={
                                "source_kind": source.source_kind,
                                "source_id": source.source_id,
                            },
                        )
                    )
                    interpolated_output = InterpolatedOutput(
                        provider_id=interpolation_result.provider_id,
                        applied=interpolation_result.applied,
                        primary_path=interpolation_result.primary_path,
                        input_paths=list(interpolation_result.input_paths),
                        output_paths=list(interpolation_result.output_paths),
                        manifest_path=interpolation_result.manifest_path,
                        metadata=dict(interpolation_result.metadata),
                    )
                    final_paths = list(interpolation_result.output_paths)
                    if not final_paths and interpolation_result.primary_path:
                        final_paths = [str(interpolation_result.primary_path)]
                    final_primary = interpolation_result.primary_path or (
                        final_paths[0] if final_paths else export_output.primary_path
                    )
                    export_output = self._build_export_output(
                        primary_path=final_primary,
                        output_paths=final_paths or list(export_output.output_paths),
                        manifest_path=interpolation_result.manifest_path,
                        source_image_path=source.source_image_path(),
                    )

                result = AssembledVideoResult(
                    success=True,
                    source=source,
                    export_settings=export_settings,
                    stitched_output=stitched_output,
                    interpolated_output=interpolated_output,
                    export_output=export_output,
                    clip_name=clip_name,
                )

            manifest_path = self._write_manifest(result, output_dir=output_dir, clip_name=clip_name)
            result.manifest_path = str(manifest_path)
            if result.export_output is not None:
                export_bundle = self._build_artifact_bundle(
                    primary_path=result.export_output.primary_path,
                    output_paths=result.export_output.output_paths,
                    manifest_path=str(manifest_path),
                    source_image_path=source.source_image_path(),
                )
                result.export_output = ExportReadyOutputBundle(
                    primary_path=result.export_output.primary_path,
                    output_paths=list(result.export_output.output_paths),
                    manifest_path=str(manifest_path),
                    artifact_bundle=export_bundle,
                )
            return result
        except Exception as exc:
            logger.exception("[AssemblyService] Failed to assemble video")
            return AssembledVideoResult.failure(
                f"Assembly failed: {exc}",
                source=source,
                clip_name=clip_name,
                export_settings=export_settings,
            )

    def _source_uses_frame_export(self, source: AssembledSequenceInput) -> bool:
        if source.source_kind == "manual_frames":
            return True
        if source.source_kind == "video_bundle" and source.resolved_frame_paths():
            return True
        if source.source_kind == "assembled_video":
            return False
        if source.segment_sources:
            return False
        suffixes = {Path(item).suffix.lower() for item in source.source_paths if item}
        return bool(suffixes) and suffixes.issubset(_IMAGE_EXTENSIONS)

    def _build_artifact_bundle(
        self,
        *,
        primary_path: str | None,
        output_paths: list[str],
        manifest_path: str | None,
        source_image_path: str | None,
    ) -> dict[str, Any]:
        artifact_record = artifact_manifest_payload(
            stage="assembled_video",
            image_or_output_path=primary_path or "assembled_video",
            manifest_path=manifest_path,
            output_paths=output_paths,
            input_image_path=source_image_path,
            artifact_type="video",
        )
        return build_video_artifact_bundle(
            stage="assembled_video",
            backend_id="stablenew",
            primary_path=primary_path,
            output_paths=output_paths,
            manifest_path=manifest_path,
            source_image_path=source_image_path,
            artifact_records=[artifact_record],
        )

    def _build_export_output(
        self,
        *,
        primary_path: str | None,
        output_paths: list[str],
        manifest_path: str | None,
        source_image_path: str | None,
    ) -> ExportReadyOutputBundle:
        return ExportReadyOutputBundle(
            primary_path=primary_path,
            output_paths=list(output_paths),
            manifest_path=manifest_path,
            artifact_bundle=self._build_artifact_bundle(
                primary_path=primary_path,
                output_paths=list(output_paths),
                manifest_path=manifest_path,
                source_image_path=source_image_path,
            ),
        )

    def _write_manifest(self, result: AssembledVideoResult, *, output_dir: Path, clip_name: str) -> Path:
        manifest_path = output_dir / f"{clip_name}_assembly_manifest.json"
        export_output = result.export_output.to_dict() if result.export_output else None
        assembly_result_payload = result.to_dict()
        assembly_result_payload.pop("created_at", None)
        payload = {
            "schema": ASSEMBLY_MANIFEST_SCHEMA,
            "schema_version": "1.0",
            "clip_name": clip_name,
            "output_path": result.primary_path,
            "source_images": list(result.source.resolved_frame_paths()) if result.source else [],
            "source_paths": list(result.source.resolved_segment_output_paths()) if result.source else [],
            "settings": dict(result.export_settings),
            "frame_count": len(result.source.resolved_frame_paths()) if result.source else 0,
            "duration_seconds": 0.0,
            "source_kind": result.source.source_kind if result.source else None,
            "source_bundle": result.source.to_dict() if result.source else None,
            "stitched_output": result.stitched_output.to_dict() if result.stitched_output else None,
            "interpolated_output": (
                result.interpolated_output.to_dict() if result.interpolated_output else None
            ),
            "export_output": export_output,
            "artifact_bundle": export_output.get("artifact_bundle") if export_output else {},
            "assembly_result": assembly_result_payload,
            "created_at": result.created_at,
        }
        normalized_payload = self._relativize_manifest_payload(payload, output_dir)
        manifest_path.write_text(json.dumps(normalized_payload, indent=2), encoding="utf-8")
        return manifest_path

    def _relativize_manifest_payload(self, payload: dict[str, Any], base_dir: Path) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in payload.items():
            normalized[key] = self._relativize_manifest_value(key, value, base_dir)
        return normalized

    def _relativize_manifest_value(self, key: str, value: Any, base_dir: Path) -> Any:
        if isinstance(value, dict):
            return {
                item_key: self._relativize_manifest_value(item_key, item_value, base_dir)
                for item_key, item_value in value.items()
            }
        if isinstance(value, list):
            if key.endswith("_paths") or key in {"source_images", "source_paths", "input_paths"}:
                return [self._relativize_path(item, base_dir) for item in value]
            return [self._relativize_manifest_value(key, item, base_dir) for item in value]
        if isinstance(value, str) and (key.endswith("_path") or key == "output_path"):
            return self._relativize_path(value, base_dir)
        return value

    def _relativize_path(self, value: Any, base_dir: Path) -> Any:
        if not value:
            return value
        path = Path(str(value))
        if not path.is_absolute():
            return path.as_posix()
        try:
            return Path(os.path.relpath(path, base_dir)).as_posix()
        except Exception:
            return str(value)