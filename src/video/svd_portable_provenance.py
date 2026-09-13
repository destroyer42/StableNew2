"""Portable, immutable provenance for native-SVD MP4 artifacts."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.pipeline.video import resolve_ffmpeg_executable
from src.utils.image_metadata import canonical_json_bytes, extract_embedded_metadata, sha256_hex
from src.video.container_metadata import (
    read_video_container_metadata,
    write_video_container_metadata,
)


class PortableVideoProvenanceContractV26:
    """Stable tag names and bounded encoding for native-SVD MP4 provenance."""

    SCHEMA = "stablenew.video-provenance.v2.6"
    RAW_SOFT_LIMIT_BYTES = 32 * 1024
    COMPRESSED_HARD_LIMIT_BYTES = 512 * 1024

    KEY_SCHEMA = "stablenew_provenance_schema"
    KEY_ENCODING = "stablenew_provenance_encoding"
    KEY_PAYLOAD = "stablenew_provenance_payload"
    KEY_PAYLOAD_GZ_B64 = "stablenew_provenance_payload_gz_b64"
    KEY_PAYLOAD_SHA256 = "stablenew_provenance_payload_sha256"


class PortableVideoProvenanceError(RuntimeError):
    """The required portable provenance could not be encoded or verified."""


@dataclass(frozen=True)
class EncodedPortableVideoProvenance:
    mode: str
    value: str
    payload_sha256: str
    raw_size: int
    compressed_size: int | None


@dataclass(frozen=True)
class PortableVideoProvenanceReadResult:
    payload: dict[str, Any] | None
    status: str
    error: str | None = None
    encoding: str | None = None
    payload_sha256: str | None = None


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_video_media_content_sha256(path: str | Path) -> str:
    """Hash copied video-stream bytes, excluding container metadata and paths."""
    ffmpeg_executable = resolve_ffmpeg_executable()
    if ffmpeg_executable is None:
        raise PortableVideoProvenanceError("FFmpeg is unavailable for video media-content hashing")
    command = [
        str(ffmpeg_executable),
        "-v",
        "error",
        "-i",
        str(path),
        "-map",
        "0:v:0",
        "-c",
        "copy",
        "-f",
        "hash",
        "-hash",
        "sha256",
        "-",
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
    except Exception as exc:
        raise PortableVideoProvenanceError(f"Unable to hash video media content: {exc}") from exc
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "unknown FFmpeg hash failure").strip()
        raise PortableVideoProvenanceError(f"Unable to hash video media content: {message}")
    for line in (completed.stdout or "").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip().upper() == "SHA256" and len(value.strip()) == 64:
            return value.strip().lower()
    raise PortableVideoProvenanceError("FFmpeg did not return a SHA256 media-content hash")


def build_svd_portable_provenance(
    *,
    source_image_path: str | Path,
    job_id: str,
    run_id: str,
    model_id: str,
    seed: int | None,
    frame_count: int,
    fps: int,
    config: Mapping[str, Any],
    preprocess: Mapping[str, Any],
    postprocess: Mapping[str, Any] | None,
    media_content_sha256: str,
    execution_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build immutable portable evidence from actual native-SVD execution facts."""
    source_path = Path(source_image_path)
    embedded_source = extract_embedded_metadata(source_path)
    source: dict[str, Any] = {
        "path_hint": str(source_path),
        "file_sha256": sha256_file(source_path),
        "stable_new_provenance_status": embedded_source.status,
    }
    if embedded_source.payload is not None:
        source["stable_new_provenance"] = embedded_source.payload

    context = dict(execution_context or {})
    source_descriptor = context.get("source_descriptor")
    lineage: dict[str, Any] = {}
    current_njr_sha256 = str(context.get("current_njr_sha256") or "").strip()
    if current_njr_sha256:
        lineage["current_njr_sha256"] = current_njr_sha256
    if isinstance(source_descriptor, Mapping):
        descriptor = {
            key: value
            for key, value in dict(source_descriptor).items()
            if value not in (None, "", [], {})
        }
        if descriptor:
            lineage["source_descriptor"] = descriptor
        for field_name in ("parent_job_id", "parent_artifact_id"):
            value = str(source_descriptor.get(field_name) or "").strip()
            if value:
                lineage[field_name] = value

    return {
        "schema": PortableVideoProvenanceContractV26.SCHEMA,
        "media_type": "video",
        "video": {
            "job_id": job_id,
            "run_id": run_id,
            "stage": "svd_native",
            "backend_id": "svd_native",
            "model_id": model_id,
            "seed": seed,
            "frame_count": frame_count,
            "fps": fps,
            "media_content_sha256": media_content_sha256,
        },
        "svd": {
            "config": dict(config),
            "preprocess": dict(preprocess),
            "postprocess": dict(postprocess or {}),
        },
        "source": source,
        "lineage": lineage,
    }


def encode_portable_video_provenance(payload: Mapping[str, Any]) -> EncodedPortableVideoProvenance:
    raw = canonical_json_bytes(dict(payload))
    payload_sha256 = sha256_hex(raw)
    if len(raw) <= PortableVideoProvenanceContractV26.RAW_SOFT_LIMIT_BYTES:
        return EncodedPortableVideoProvenance("raw", raw.decode("utf-8"), payload_sha256, len(raw), None)
    compressed = gzip.compress(raw, compresslevel=6)
    encoded = base64.b64encode(compressed).decode("ascii")
    if len(encoded.encode("ascii")) > PortableVideoProvenanceContractV26.COMPRESSED_HARD_LIMIT_BYTES:
        raise PortableVideoProvenanceError("Portable SVD provenance exceeds the supported embedded size limit")
    return EncodedPortableVideoProvenance(
        "gzip+base64", encoded, payload_sha256, len(raw), len(compressed)
    )


def build_portable_video_provenance_tags(
    encoded: EncodedPortableVideoProvenance,
) -> dict[str, str]:
    tags = {
        PortableVideoProvenanceContractV26.KEY_SCHEMA: PortableVideoProvenanceContractV26.SCHEMA,
        PortableVideoProvenanceContractV26.KEY_ENCODING: encoded.mode,
        PortableVideoProvenanceContractV26.KEY_PAYLOAD_SHA256: encoded.payload_sha256,
    }
    if encoded.mode == "raw":
        tags[PortableVideoProvenanceContractV26.KEY_PAYLOAD] = encoded.value
    else:
        tags[PortableVideoProvenanceContractV26.KEY_PAYLOAD_GZ_B64] = encoded.value
    return tags


def write_portable_svd_video_provenance(
    *,
    video_path: str | Path,
    public_metadata: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> EncodedPortableVideoProvenance:
    encoded = encode_portable_video_provenance(payload)
    if not write_video_container_metadata(
        video_path,
        public_metadata,
        additional_tags=build_portable_video_provenance_tags(encoded),
    ):
        raise PortableVideoProvenanceError("Failed to embed required portable SVD provenance")
    verified = read_portable_svd_video_provenance(video_path)
    if verified.status != "ok" or verified.payload_sha256 != encoded.payload_sha256:
        raise PortableVideoProvenanceError(
            f"Embedded portable SVD provenance did not verify: {verified.error or verified.status}"
        )
    return encoded


def read_portable_svd_video_provenance(path: str | Path) -> PortableVideoProvenanceReadResult:
    tags = {str(key).lower(): str(value) for key, value in read_video_container_metadata(path).items()}
    def _tag(name: str) -> str:
        return tags.get(name.lower(), "")

    schema = _tag(PortableVideoProvenanceContractV26.KEY_SCHEMA)
    if not schema:
        return PortableVideoProvenanceReadResult(None, "missing")
    if schema != PortableVideoProvenanceContractV26.SCHEMA:
        return PortableVideoProvenanceReadResult(None, "unsupported", "unsupported_schema")
    mode = _tag(PortableVideoProvenanceContractV26.KEY_ENCODING)
    expected_sha256 = _tag(PortableVideoProvenanceContractV26.KEY_PAYLOAD_SHA256)
    if mode == "raw":
        raw = _tag(PortableVideoProvenanceContractV26.KEY_PAYLOAD).encode("utf-8")
    elif mode == "gzip+base64":
        try:
            raw = gzip.decompress(
                base64.b64decode(
                    _tag(PortableVideoProvenanceContractV26.KEY_PAYLOAD_GZ_B64),
                    validate=True,
                )
            )
        except Exception as exc:
            return PortableVideoProvenanceReadResult(None, "corrupt", str(exc), mode, expected_sha256)
    else:
        return PortableVideoProvenanceReadResult(None, "unsupported", "unsupported_encoding", mode, expected_sha256)
    if not expected_sha256 or sha256_hex(raw) != expected_sha256:
        return PortableVideoProvenanceReadResult(None, "corrupt", "payload_sha256_mismatch", mode, expected_sha256)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        return PortableVideoProvenanceReadResult(None, "corrupt", str(exc), mode, expected_sha256)
    if not isinstance(payload, dict):
        return PortableVideoProvenanceReadResult(None, "corrupt", "payload_not_dict", mode, expected_sha256)
    if payload.get("schema") != PortableVideoProvenanceContractV26.SCHEMA:
        return PortableVideoProvenanceReadResult(None, "corrupt", "payload_schema_mismatch", mode, expected_sha256)
    return PortableVideoProvenanceReadResult(payload, "ok", None, mode, expected_sha256)


def verify_portable_svd_video_media_content(path: str | Path) -> PortableVideoProvenanceReadResult:
    read_result = read_portable_svd_video_provenance(path)
    if read_result.status != "ok" or read_result.payload is None:
        return read_result
    expected = str(dict(read_result.payload.get("video") or {}).get("media_content_sha256") or "").strip()
    if not expected:
        return PortableVideoProvenanceReadResult(None, "corrupt", "missing_media_content_sha256")
    try:
        actual = compute_video_media_content_sha256(path)
    except PortableVideoProvenanceError as exc:
        return PortableVideoProvenanceReadResult(read_result.payload, "corrupt", str(exc))
    if actual != expected:
        return PortableVideoProvenanceReadResult(None, "corrupt", "media_content_sha256_mismatch")
    return read_result


__all__ = [
    "EncodedPortableVideoProvenance",
    "PortableVideoProvenanceContractV26",
    "PortableVideoProvenanceError",
    "PortableVideoProvenanceReadResult",
    "build_portable_video_provenance_tags",
    "build_svd_portable_provenance",
    "compute_video_media_content_sha256",
    "encode_portable_video_provenance",
    "read_portable_svd_video_provenance",
    "sha256_file",
    "verify_portable_svd_video_media_content",
    "write_portable_svd_video_provenance",
]
