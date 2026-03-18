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
from src.pipeline.artifact_contract import artifact_manifest_payload

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


def _iter_history_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_entries = payload.get("stage_history")
    if not isinstance(raw_entries, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in reversed(raw_entries):
        if isinstance(item, dict):
            entries.append(item)
    return entries


def resolve_prompt_fields(metadata_payload: dict[str, Any] | None) -> tuple[str, str]:
    payload = metadata_payload if isinstance(metadata_payload, dict) else {}
    stage_manifest = _dict_or_empty(payload.get("stage_manifest"))
    generation = _dict_or_empty(payload.get("generation"))
    stage_config = _dict_or_empty(stage_manifest.get("config"))
    history_entries = _iter_history_entries(payload)
    history_prompts = [
        item
        for entry in history_entries
        for item in (
            entry.get("prompt"),
            entry.get("final_prompt"),
            entry.get("original_prompt"),
        )
    ]
    history_negative_prompts = [
        item
        for entry in history_entries
        for item in (
            entry.get("negative_prompt"),
            entry.get("final_negative_prompt"),
            entry.get("original_negative_prompt"),
        )
    ]

    prompt = _first_non_empty_string(
        stage_manifest.get("prompt"),
        stage_manifest.get("final_prompt"),
        stage_manifest.get("original_prompt"),
        stage_config.get("prompt"),
        generation.get("prompt"),
        generation.get("final_prompt"),
        generation.get("original_prompt"),
        *history_prompts,
        payload.get("prompt"),
        payload.get("final_prompt"),
        payload.get("original_prompt"),
    )
    negative_prompt = _first_non_empty_string(
        stage_manifest.get("negative_prompt"),
        stage_manifest.get("final_negative_prompt"),
        stage_manifest.get("original_negative_prompt"),
        stage_config.get("negative_prompt"),
        generation.get("negative_prompt"),
        generation.get("final_negative_prompt"),
        generation.get("original_negative_prompt"),
        *history_negative_prompts,
        payload.get("negative_prompt"),
        payload.get("final_negative_prompt"),
        payload.get("original_negative_prompt"),
    )
    return prompt, negative_prompt


def resolve_model_vae_fields(metadata_payload: dict[str, Any] | None) -> tuple[str, str]:
    payload = metadata_payload if isinstance(metadata_payload, dict) else {}
    stage_manifest = _dict_or_empty(payload.get("stage_manifest"))
    generation = _dict_or_empty(payload.get("generation"))
    stage_config = _dict_or_empty(stage_manifest.get("config"))
    txt2img_cfg = _dict_or_empty(stage_config.get("txt2img"))
    img2img_cfg = _dict_or_empty(stage_config.get("img2img"))
    history_entries = _iter_history_entries(payload)

    model = _first_non_empty_string(
        stage_manifest.get("model"),
        generation.get("model"),
        stage_config.get("model"),
        stage_config.get("model_name"),
        stage_config.get("sd_model_checkpoint"),
        img2img_cfg.get("model"),
        img2img_cfg.get("model_name"),
        txt2img_cfg.get("model"),
        txt2img_cfg.get("model_name"),
        *[entry.get("model") for entry in history_entries],
        payload.get("model"),
        payload.get("model_name"),
    )
    vae = _first_non_empty_string(
        stage_manifest.get("vae"),
        generation.get("vae"),
        stage_config.get("vae"),
        stage_config.get("sd_vae"),
        img2img_cfg.get("vae"),
        img2img_cfg.get("sd_vae"),
        txt2img_cfg.get("vae"),
        txt2img_cfg.get("sd_vae"),
        *[entry.get("vae") for entry in history_entries],
        payload.get("vae"),
        payload.get("sd_vae"),
    )
    return model, vae


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

    config_dict = config_value if isinstance(config_value, dict) else {}
    stage_history = manifest.get("stage_history")
    history_entries = stage_history if isinstance(stage_history, list) else []
    resolved_prompt = _first_non_empty_string(
        manifest.get("final_prompt"),
        manifest.get("original_prompt"),
        manifest.get("prompt"),
        config_dict.get("prompt"),
        *[
            entry.get("final_prompt") or entry.get("original_prompt") or entry.get("prompt")
            for entry in history_entries
            if isinstance(entry, dict)
        ],
    )
    resolved_negative = _first_non_empty_string(
        manifest.get("final_negative_prompt"),
        manifest.get("original_negative_prompt"),
        manifest.get("negative_prompt"),
        config_dict.get("negative_prompt"),
        *[
            entry.get("final_negative_prompt")
            or entry.get("original_negative_prompt")
            or entry.get("negative_prompt")
            for entry in history_entries
            if isinstance(entry, dict)
        ],
    )
    resolved_model = _first_non_empty_string(
        manifest.get("model"),
        config_dict.get("model"),
        config_dict.get("model_name"),
        config_dict.get("sd_model_checkpoint"),
        *[entry.get("model") for entry in history_entries if isinstance(entry, dict)],
    )
    resolved_vae = _first_non_empty_string(
        manifest.get("vae"),
        config_dict.get("vae"),
        config_dict.get("sd_vae"),
        *[entry.get("vae") for entry in history_entries if isinstance(entry, dict)],
    )

    generation_params = {
        "model": resolved_model or None,
        "vae": resolved_vae or None,
        "steps": config_dict.get("steps"),
        "cfg_scale": config_dict.get("cfg_scale"),
        "width": config_dict.get("width"),
        "height": config_dict.get("height"),
        "sampler_name": config_dict.get("sampler_name"),
        "scheduler": config_dict.get("scheduler"),
        "clip_skip": config_dict.get("clip_skip"),
        "denoising_strength": config_dict.get("denoising_strength"),
        "prompt": resolved_prompt,
        "negative_prompt": resolved_negative,
        "original_prompt": _first_non_empty_string(manifest.get("original_prompt"), config_dict.get("prompt")),
        "final_prompt": _first_non_empty_string(manifest.get("final_prompt"), resolved_prompt),
        "original_negative_prompt": _first_non_empty_string(
            manifest.get("original_negative_prompt"),
            config_dict.get("negative_prompt"),
        ),
        "final_negative_prompt": _first_non_empty_string(
            manifest.get("final_negative_prompt"),
            resolved_negative,
        ),
    }
    generation_params = {k: v for k, v in generation_params.items() if v is not None}
    
    # Extract seeds metadata (D-MANIFEST-001)
    seeds_data = manifest.get("seeds", {})
    if not isinstance(seeds_data, dict):
        seeds_data = {
            "requested_seed": manifest.get("requested_seed"),
            "actual_seed": manifest.get("actual_seed"),
            "actual_subseed": manifest.get("actual_subseed"),
        }
    
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
        "generation": generation_params,  # All parameters needed for reproducibility
        "seeds": seeds_data,
        "njr": {
            "snapshot_version": "2.6",
            "sha256": njr_sha256 or "",
        },
        "stage_manifest": {
            "stage": stage,
            "name": manifest.get("name") or image_path.stem,
            "timestamp": manifest.get("timestamp") or "",
            "config_hash": config_hash,
            # Include current stage's full config for reproducibility
            "config": config_dict,
            "model": resolved_model or "Unknown",
            "vae": resolved_vae or "Automatic",
            "seeds": seeds_data,
            "prompt": generation_params.get("prompt", ""),
            "negative_prompt": generation_params.get("negative_prompt", ""),
            "original_prompt": generation_params.get("original_prompt", ""),
            "final_prompt": generation_params.get("final_prompt", ""),
            "original_negative_prompt": generation_params.get("original_negative_prompt", ""),
            "final_negative_prompt": generation_params.get("final_negative_prompt", ""),
        },
        # Include full stage history chain for complete pipeline tracking
        "stage_history": manifest.get("stage_history", []),
    }
    payload["artifact"] = artifact_manifest_payload(
        stage=stage,
        image_or_output_path=image_path,
        manifest_path=manifest.get("artifact", {}).get("manifest_path") if isinstance(manifest.get("artifact"), dict) else None,
        output_paths=manifest.get("artifact", {}).get("output_paths") if isinstance(manifest.get("artifact"), dict) else manifest.get("all_paths"),
        thumbnail_path=manifest.get("artifact", {}).get("thumbnail_path") if isinstance(manifest.get("artifact"), dict) else None,
        input_image_path=manifest.get("input_image") or manifest.get("input_image_path") or manifest.get("source_image_path"),
    )
    
    # Add refiner info if present (PR-GUI-DATA-001)
    if "refiner" in manifest:
        payload["refiner"] = manifest["refiner"]
    
    return payload
