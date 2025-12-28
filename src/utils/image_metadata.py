"""StableNew image metadata contract (v2.6)."""

from __future__ import annotations

import base64
import gzip
import json
import logging
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, PngImagePlugin

logger = logging.getLogger(__name__)


class ImageMetadataContractV26:
    SCHEMA = "stablenew.image-metadata.v2.6"

    KEY_SCHEMA = "stablenew:schema"
    KEY_JOB_ID = "stablenew:job_id"
    KEY_RUN_ID = "stablenew:run_id"
    KEY_STAGE = "stablenew:stage"
    KEY_CREATED_UTC = "stablenew:created_utc"
    KEY_PAYLOAD_SHA256 = "stablenew:payload_sha256"
    KEY_PAYLOAD = "stablenew:payload"
    KEY_PAYLOAD_GZ_B64 = "stablenew:payload_gz_b64"
    KEY_PAYLOAD_OMITTED = "stablenew:payload_omitted"
    KEY_PAYLOAD_REASON = "stablenew:payload_reason"
    KEY_NJR_SHA256 = "stablenew:njr_sha256"
    KEY_HISTORY_REF = "stablenew:history_ref"

    SOFT_LIMIT_BYTES = 32 * 1024
    HARD_LIMIT_BYTES = 256 * 1024


@dataclass(frozen=True)
class EncodedPayload:
    mode: str
    text_value: str | None
    sha256: str
    raw_size: int
    compressed_size: int | None
    omitted: bool
    reason: str | None


@dataclass(frozen=True)
class ReadPayloadResult:
    payload: dict[str, Any] | None
    status: str
    error: str | None = None


def canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encode_payload(payload: dict[str, Any]) -> EncodedPayload:
    raw = canonical_json_bytes(payload)
    sha = sha256_hex(raw)
    raw_size = len(raw)
    if raw_size <= ImageMetadataContractV26.SOFT_LIMIT_BYTES:
        return EncodedPayload(
            mode=ImageMetadataContractV26.KEY_PAYLOAD,
            text_value=raw.decode("utf-8"),
            sha256=sha,
            raw_size=raw_size,
            compressed_size=None,
            omitted=False,
            reason=None,
        )
    compressed = gzip.compress(raw, compresslevel=6)
    compressed_size = len(compressed)
    if compressed_size <= ImageMetadataContractV26.HARD_LIMIT_BYTES:
        encoded = base64.b64encode(compressed).decode("ascii")
        return EncodedPayload(
            mode=ImageMetadataContractV26.KEY_PAYLOAD_GZ_B64,
            text_value=encoded,
            sha256=sha,
            raw_size=raw_size,
            compressed_size=compressed_size,
            omitted=False,
            reason=None,
        )
    return EncodedPayload(
        mode=ImageMetadataContractV26.KEY_PAYLOAD_OMITTED,
        text_value=None,
        sha256=sha,
        raw_size=raw_size,
        compressed_size=compressed_size,
        omitted=True,
        reason="SIZE_LIMIT",
    )


def build_contract_kv(
    payload: dict[str, Any],
    *,
    job_id: str,
    run_id: str,
    stage: str,
    created_utc: str | None = None,
    njr_sha256: str | None = None,
    history_ref: dict[str, Any] | str | None = None,
) -> dict[str, str]:
    created_value = created_utc or datetime.now(timezone.utc).isoformat()
    encoded = encode_payload(payload)
    kv: dict[str, str] = {
        ImageMetadataContractV26.KEY_SCHEMA: ImageMetadataContractV26.SCHEMA,
        ImageMetadataContractV26.KEY_JOB_ID: job_id,
        ImageMetadataContractV26.KEY_RUN_ID: run_id,
        ImageMetadataContractV26.KEY_STAGE: stage,
        ImageMetadataContractV26.KEY_CREATED_UTC: created_value,
        ImageMetadataContractV26.KEY_PAYLOAD_SHA256: encoded.sha256,
    }
    if encoded.mode == ImageMetadataContractV26.KEY_PAYLOAD:
        kv[ImageMetadataContractV26.KEY_PAYLOAD] = encoded.text_value or ""
    elif encoded.mode == ImageMetadataContractV26.KEY_PAYLOAD_GZ_B64:
        kv[ImageMetadataContractV26.KEY_PAYLOAD_GZ_B64] = encoded.text_value or ""
    else:
        kv[ImageMetadataContractV26.KEY_PAYLOAD_OMITTED] = "true"
        kv[ImageMetadataContractV26.KEY_PAYLOAD_REASON] = encoded.reason or "SIZE_LIMIT"
    if njr_sha256:
        kv[ImageMetadataContractV26.KEY_NJR_SHA256] = njr_sha256
    if history_ref is not None:
        if isinstance(history_ref, str):
            kv[ImageMetadataContractV26.KEY_HISTORY_REF] = history_ref
        else:
            kv[ImageMetadataContractV26.KEY_HISTORY_REF] = canonical_json_bytes(history_ref).decode("utf-8")
    return kv


def write_image_metadata(path: Path, kv: dict[str, str]) -> bool:
    suffix = path.suffix.lower()
    if suffix in {".png"}:
        return write_png_metadata(path, kv)
    if suffix in {".jpg", ".jpeg"}:
        return write_jpg_metadata(path, kv)
    return False


def read_image_metadata(path: Path) -> dict[str, str]:
    suffix = path.suffix.lower()
    if suffix in {".png"}:
        return read_png_metadata(path)
    if suffix in {".jpg", ".jpeg"}:
        return read_jpg_metadata(path)
    return {}


def write_png_metadata(path: Path, kv: dict[str, str]) -> bool:
    try:
        with Image.open(path) as img:
            existing = read_png_metadata(path)
            info = PngImagePlugin.PngInfo()
            for key, value in existing.items():
                if key in kv:
                    continue
                info.add_itxt(key, value, zip=False)
            for key, value in kv.items():
                info.add_itxt(key, value, zip=False)
            temp_path = path.with_name(f"{path.stem}.tmp{path.suffix}")
            img.save(temp_path, pnginfo=info)
        temp_path.replace(path)
        return True
    except Exception as exc:
        logger.debug("Failed to write PNG metadata for %s: %s", path, exc)
        return False


def read_png_metadata(path: Path) -> dict[str, str]:
    try:
        with Image.open(path) as img:
            info: dict[str, str] = {}
            if hasattr(img, "text"):
                for key, value in img.text.items():
                    if isinstance(value, str):
                        info[key] = value
                    elif isinstance(value, bytes):
                        info[key] = value.decode("utf-8", errors="replace")
            for key, value in img.info.items():
                if key in info:
                    continue
                if isinstance(value, str):
                    info[key] = value
                elif isinstance(value, bytes):
                    info[key] = value.decode("utf-8", errors="replace")
            return info
    except Exception:
        return {}


def write_jpg_metadata(path: Path, kv: dict[str, str]) -> bool:
    try:
        payload = canonical_json_bytes(kv)
        encoded = base64.b64encode(payload).decode("ascii")
        comment = f"SNMETA:{encoded}".encode("ascii")
        with Image.open(path) as img:
            exif = img.getexif()
            exif[37510] = comment
            temp_path = path.with_name(f"{path.stem}.tmp{path.suffix}")
            img.save(temp_path, exif=exif)
        temp_path.replace(path)
        return True
    except Exception as exc:
        logger.debug("Failed to write JPG metadata for %s: %s", path, exc)
        return False


def read_jpg_metadata(path: Path) -> dict[str, str]:
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            comment = exif.get(37510)
            if not comment:
                return {}
            if isinstance(comment, bytes):
                data = comment
            else:
                data = str(comment).encode("ascii", errors="ignore")
            if not data.startswith(b"SNMETA:"):
                return {}
            encoded = data[len(b"SNMETA:") :].decode("ascii", errors="ignore")
            raw = base64.b64decode(encoded)
            payload = json.loads(raw.decode("utf-8"))
            if isinstance(payload, dict):
                return {str(k): str(v) for k, v in payload.items()}
            return {}
    except Exception:
        return {}


def decode_payload(kv: dict[str, str]) -> ReadPayloadResult:
    if not kv:
        return ReadPayloadResult(None, "missing")
    if kv.get(ImageMetadataContractV26.KEY_PAYLOAD_OMITTED) == "true":
        return ReadPayloadResult(None, "omitted")
    payload_raw = kv.get(ImageMetadataContractV26.KEY_PAYLOAD)
    payload_gz = kv.get(ImageMetadataContractV26.KEY_PAYLOAD_GZ_B64)
    if payload_raw:
        raw_bytes = payload_raw.encode("utf-8")
    elif payload_gz:
        try:
            compressed = base64.b64decode(payload_gz)
            raw_bytes = gzip.decompress(compressed)
        except Exception as exc:
            return ReadPayloadResult(None, "corrupt", str(exc))
    else:
        return ReadPayloadResult(None, "missing")
    expected = kv.get(ImageMetadataContractV26.KEY_PAYLOAD_SHA256)
    actual = sha256_hex(raw_bytes)
    if expected and expected != actual:
        return ReadPayloadResult(None, "corrupt", "payload_sha256_mismatch")
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        return ReadPayloadResult(None, "corrupt", str(exc))
    if isinstance(payload, dict):
        return ReadPayloadResult(payload, "ok")
    return ReadPayloadResult(None, "corrupt", "payload_not_dict")


def extract_embedded_metadata(image_path: Path) -> ReadPayloadResult:
    kv = read_image_metadata(image_path)
    if kv.get(ImageMetadataContractV26.KEY_SCHEMA) != ImageMetadataContractV26.SCHEMA:
        return ReadPayloadResult(None, "missing")
    return decode_payload(kv)


def build_payload_from_manifest(
    *,
    image_path: Path,
    run_dir: Path,
    stage: str,
    manifest: dict[str, Any],
    image_size: tuple[int, int] | None,
    njr_sha256: str | None = None,
) -> dict[str, Any]:
    width = image_size[0] if image_size else None
    height = image_size[1] if image_size else None
    try:
        image_rel = str(image_path.relative_to(run_dir))
    except Exception:
        image_rel = image_path.name
    config_hash = ""
    config_value = manifest.get("config")
    if isinstance(config_value, dict):
        try:
            config_hash = sha256_hex(canonical_json_bytes(config_value))
        except Exception:
            config_hash = ""
    
    payload = {
        "job_id": manifest.get("job_id") or "",
        "run_id": run_dir.name,
        "stage": stage,
        "image": {
            "path": image_rel,
            "width": width,
            "height": height,
            "format": image_path.suffix.lstrip(".").lower(),
        },
        "seeds": {
            "requested_seed": manifest.get("requested_seed"),
            "actual_seed": manifest.get("actual_seed"),
            "actual_subseed": manifest.get("actual_subseed"),
        },
        "njr": {
            "snapshot_version": "2.6",
            "sha256": njr_sha256 or "",
        },
        "stage_manifest": {
            "name": manifest.get("name") or image_path.stem,
            "timestamp": manifest.get("timestamp") or "",
            "config_hash": config_hash,
        },
        # Include full stage history chain for complete pipeline tracking
        "stage_history": manifest.get("stage_history", []),
    }
    
    return payload
