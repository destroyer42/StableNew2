"""Shared container metadata helpers for StableNew video exports."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageSequence

from src.pipeline.video import resolve_ffmpeg_executable
from src.video.motion.secondary_motion_provenance import extract_secondary_motion_summary

logger = logging.getLogger(__name__)

VIDEO_CONTAINER_METADATA_SCHEMA = "stablenew.media-metadata.v2.6"
_FFPROBE_TIMEOUT_SECONDS = 30
_FFMPEG_TIMEOUT_SECONDS = 300
_PUBLIC_DESCRIPTION_SOFT_LIMIT = 64 * 1024
_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _first_non_empty_string(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    values: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            values.append(text)
    return values


def _truncate(text: str, limit: int) -> str:
    normalized = str(text or "").strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: max(0, limit - 3)].rstrip()}..."


def _resolve_ffprobe_executable() -> Path | None:
    ffmpeg_path = resolve_ffmpeg_executable()
    if ffmpeg_path is not None:
        ffprobe_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
        sibling = ffmpeg_path.with_name(ffprobe_name)
        if sibling.exists() and sibling.is_file():
            return sibling
    which_path = shutil.which("ffprobe")
    if which_path:
        return Path(which_path)
    return None


def build_public_media_payload(
    metadata_payload: Mapping[str, Any] | None,
    *,
    media_type: str,
    file_path: str | Path | None = None,
) -> dict[str, Any]:
    payload = dict(metadata_payload or {})
    config = _dict_or_empty(payload.get("config"))
    artifact = _dict_or_empty(payload.get("artifact"))
    generation = _dict_or_empty(payload.get("generation"))
    public_payload: dict[str, Any] = {
        "schema": VIDEO_CONTAINER_METADATA_SCHEMA,
        "media_type": media_type,
        "stage": _first_non_empty_string(payload.get("stage")),
        "backend_id": _first_non_empty_string(payload.get("backend_id")),
        "job_id": _first_non_empty_string(payload.get("job_id")),
        "run_id": _first_non_empty_string(payload.get("run_id")),
        "created_utc": _first_non_empty_string(
            payload.get("created_utc"),
            payload.get("timestamp"),
            datetime.now(timezone.utc).isoformat(),
        ),
        "title": _first_non_empty_string(
            payload.get("title"),
            Path(str(file_path)).stem if file_path else "",
            Path(_first_non_empty_string(payload.get("primary_path"), payload.get("output_path"))).stem,
        ),
        "prompt": _first_non_empty_string(
            payload.get("prompt"),
            payload.get("final_prompt"),
            generation.get("prompt"),
        ),
        "negative_prompt": _first_non_empty_string(
            payload.get("negative_prompt"),
            payload.get("final_negative_prompt"),
            generation.get("negative_prompt"),
        ),
        "source_image_path": _first_non_empty_string(
            payload.get("source_image_path"),
            payload.get("input_image_path"),
        ),
        "manifest_path": _first_non_empty_string(payload.get("manifest_path")),
        "thumbnail_path": _first_non_empty_string(payload.get("thumbnail_path")),
        "primary_path": _first_non_empty_string(
            payload.get("primary_path"),
            payload.get("output_path"),
            payload.get("video_path"),
            payload.get("gif_path"),
        ),
        "output_paths": _string_list(payload.get("output_paths")),
        "video_paths": _string_list(payload.get("video_paths")),
        "gif_paths": _string_list(payload.get("gif_paths")),
        "frame_path_count": int(payload.get("frame_path_count") or payload.get("frame_count") or 0),
        "fps": payload.get("fps"),
        "seed": payload.get("seed"),
        "model_id": _first_non_empty_string(payload.get("model_id"), generation.get("model")),
        "workflow_id": _first_non_empty_string(payload.get("workflow_id")),
        "workflow_version": _first_non_empty_string(payload.get("workflow_version")),
        "motion_profile": _first_non_empty_string(payload.get("motion_profile")),
        "config": config,
    }
    if artifact:
        public_payload["artifact"] = artifact
    compiled_inputs = _dict_or_empty(payload.get("compiled_inputs"))
    if compiled_inputs:
        public_payload["compiled_inputs"] = compiled_inputs
    end_anchor_path = _first_non_empty_string(payload.get("end_anchor_path"))
    if end_anchor_path:
        public_payload["end_anchor_path"] = end_anchor_path
    mid_anchor_paths = _string_list(payload.get("mid_anchor_paths"))
    if mid_anchor_paths:
        public_payload["mid_anchor_paths"] = mid_anchor_paths
    secondary_motion_summary = extract_secondary_motion_summary(payload)
    if secondary_motion_summary:
        public_payload["secondary_motion"] = secondary_motion_summary
    return {
        key: value
        for key, value in public_payload.items()
        if value not in (None, "", [], {})
    }


def build_video_container_tags(
    metadata_payload: Mapping[str, Any] | None,
    *,
    file_path: str | Path | None = None,
) -> dict[str, str]:
    public_payload = build_public_media_payload(metadata_payload, media_type="video", file_path=file_path)
    description = _canonical_json(public_payload)
    if len(description.encode("utf-8")) > _PUBLIC_DESCRIPTION_SOFT_LIMIT:
        reduced_payload = dict(public_payload)
        reduced_payload.pop("config", None)
        reduced_payload["metadata_truncated"] = True
        description = _canonical_json(reduced_payload)
    prompt = _truncate(str(public_payload.get("prompt") or ""), 180)
    comment_parts = [
        _first_non_empty_string(public_payload.get("stage")),
        _first_non_empty_string(public_payload.get("backend_id")),
        _first_non_empty_string(public_payload.get("model_id"), public_payload.get("workflow_id")),
        prompt,
    ]
    comment = " | ".join([part for part in comment_parts if part])
    tags = {
        "title": str(public_payload.get("title") or "video"),
        "description": description,
        "comment": comment or "StableNew video export",
        "software": "StableNew",
        "creation_time": str(public_payload.get("created_utc") or datetime.now(timezone.utc).isoformat()),
        "artist": "StableNew",
        "genre": "AI-generated video",
        "stablenew_schema": VIDEO_CONTAINER_METADATA_SCHEMA,
    }
    manifest_path = str(public_payload.get("manifest_path") or "").strip()
    if manifest_path:
        tags["stablenew_manifest_path"] = manifest_path
    stage = str(public_payload.get("stage") or "").strip()
    if stage:
        tags["stablenew_stage"] = stage
    backend_id = str(public_payload.get("backend_id") or "").strip()
    if backend_id:
        tags["stablenew_backend_id"] = backend_id
    return tags


def write_video_container_metadata(
    path: str | Path,
    metadata_payload: Mapping[str, Any] | None,
) -> bool:
    output_path = Path(path)
    suffix = output_path.suffix.lower()
    if suffix == ".gif":
        return _write_gif_metadata(output_path, metadata_payload)
    if suffix not in _VIDEO_SUFFIXES:
        return False
    ffmpeg_executable = resolve_ffmpeg_executable()
    if ffmpeg_executable is None:
        logger.debug("Skipping video container metadata for %s because FFmpeg is unavailable", output_path)
        return False
    tags = build_video_container_tags(metadata_payload, file_path=output_path)
    temp_path = output_path.with_name(f"{output_path.stem}.metadata_tmp{output_path.suffix}")
    command = [
        str(ffmpeg_executable),
        "-i",
        str(output_path),
        "-map",
        "0",
        "-codec",
        "copy",
    ]
    if suffix in {".mp4", ".mov", ".m4v"}:
        command.extend(["-movflags", "use_metadata_tags"])
    for key, value in tags.items():
        command.extend(["-metadata", f"{key}={value}"])
    command.extend(["-y", str(temp_path)])
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_FFMPEG_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            logger.warning(
                "Failed to embed video metadata into %s: %s",
                output_path,
                (result.stderr or result.stdout or "").strip(),
            )
            temp_path.unlink(missing_ok=True)
            return False
        temp_path.replace(output_path)
        return True
    except Exception as exc:
        logger.warning("Failed to embed video metadata into %s: %s", output_path, exc)
        temp_path.unlink(missing_ok=True)
        return False


def _write_gif_metadata(path: Path, metadata_payload: Mapping[str, Any] | None) -> bool:
    temp_path = path.with_name(f"{path.stem}.metadata_tmp{path.suffix}")
    comment_value = build_video_container_tags(metadata_payload, file_path=path).get("description", "")
    try:
        with Image.open(path) as image:
            frames = [frame.copy() for frame in ImageSequence.Iterator(image)]
            if not frames:
                return False
            save_kwargs: dict[str, Any] = {
                "format": "GIF",
                "save_all": True,
                "append_images": frames[1:],
                "comment": comment_value.encode("utf-8"),
            }
            if "duration" in image.info:
                save_kwargs["duration"] = image.info["duration"]
            if "loop" in image.info:
                save_kwargs["loop"] = image.info["loop"]
            if "disposal" in image.info:
                save_kwargs["disposal"] = image.info["disposal"]
            frames[0].save(temp_path, **save_kwargs)
        temp_path.replace(path)
        return True
    except Exception as exc:
        logger.warning("Failed to embed GIF metadata into %s: %s", path, exc)
        temp_path.unlink(missing_ok=True)
        return False


def read_video_container_metadata(path: str | Path) -> dict[str, str]:
    input_path = Path(path)
    if input_path.suffix.lower() == ".gif":
        return _read_gif_metadata(input_path)
    ffprobe_executable = _resolve_ffprobe_executable()
    if ffprobe_executable is None:
        return {}
    try:
        result = subprocess.run(
            [
                str(ffprobe_executable),
                "-v",
                "error",
                "-show_entries",
                "format_tags",
                "-of",
                "json",
                str(input_path),
            ],
            capture_output=True,
            text=True,
            timeout=_FFPROBE_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return {}
        payload = json.loads(result.stdout or "{}")
        tags = payload.get("format", {}).get("tags", {})
        if not isinstance(tags, dict):
            return {}
        return {str(key): str(value) for key, value in tags.items()}
    except Exception:
        return {}


def _read_gif_metadata(path: Path) -> dict[str, str]:
    try:
        with Image.open(path) as image:
            comment = image.info.get("comment")
            if isinstance(comment, bytes):
                return {"comment": comment.decode("utf-8", errors="replace")}
            if isinstance(comment, str):
                return {"comment": comment}
            return {}
    except Exception:
        return {}


__all__ = [
    "VIDEO_CONTAINER_METADATA_SCHEMA",
    "build_public_media_payload",
    "build_video_container_tags",
    "read_video_container_metadata",
    "write_video_container_metadata",
]
