from __future__ import annotations

import random
import string
from pathlib import Path

from PIL import Image

from src.utils.image_metadata import (
    ImageMetadataContractV26,
    build_payload_from_manifest,
    build_contract_kv,
    decode_payload,
    encode_payload,
    extract_embedded_metadata,
    read_image_metadata,
    resolve_model_vae_fields,
    resolve_prompt_fields,
    write_image_metadata,
)


def _write_png(path: Path, size: tuple[int, int] = (8, 8)) -> None:
    image = Image.new("RGB", size, color=(10, 20, 30))
    image.save(path)


def _write_jpg(path: Path, size: tuple[int, int] = (8, 8)) -> None:
    image = Image.new("RGB", size, color=(10, 20, 30))
    image.save(path, format="JPEG")


def test_png_roundtrip_metadata_contract(tmp_path: Path) -> None:
    image_path = tmp_path / "sample.png"
    _write_png(image_path)
    payload = {
        "job_id": "job-1",
        "run_id": "run-1",
        "stage": "txt2img",
        "image": {"path": "sample.png", "width": 8, "height": 8, "format": "png"},
        "seeds": {"requested_seed": -1, "actual_seed": 123, "actual_subseed": 456},
        "njr": {"snapshot_version": "2.6", "sha256": "abc"},
        "stage_manifest": {"name": "sample", "timestamp": "t", "config_hash": "h"},
    }
    kv = build_contract_kv(
        payload,
        job_id="job-1",
        run_id="run-1",
        stage="txt2img",
    )
    assert write_image_metadata(image_path, kv) is True
    stored = read_image_metadata(image_path)
    assert stored.get(ImageMetadataContractV26.KEY_SCHEMA) == ImageMetadataContractV26.SCHEMA
    decoded = decode_payload(stored)
    assert decoded.status == "ok"
    assert decoded.payload == payload
    assert "txt2img" in stored[ImageMetadataContractV26.PUBLIC_KEY_COMMENT]
    assert "StableNew" == stored[ImageMetadataContractV26.PUBLIC_KEY_SOFTWARE]
    assert "\"media_type\": \"image\"" in stored[ImageMetadataContractV26.PUBLIC_KEY_DESCRIPTION]
    assert "Steps:" not in stored[ImageMetadataContractV26.PUBLIC_KEY_PARAMETERS]


def test_png_metadata_uses_compression_when_over_soft_limit(tmp_path: Path) -> None:
    image_path = tmp_path / "compressed.png"
    _write_png(image_path)
    payload = {"data": "x" * (ImageMetadataContractV26.SOFT_LIMIT_BYTES + 1024)}
    encoded = encode_payload(payload)
    assert encoded.mode == ImageMetadataContractV26.KEY_PAYLOAD_GZ_B64
    kv = build_contract_kv(payload, job_id="job-2", run_id="run-2", stage="txt2img")
    assert write_image_metadata(image_path, kv) is True
    stored = read_image_metadata(image_path)
    assert ImageMetadataContractV26.KEY_PAYLOAD_GZ_B64 in stored
    decoded = decode_payload(stored)
    assert decoded.status == "ok"
    assert decoded.payload == payload


def test_jpg_roundtrip_preserves_stablenew_and_public_metadata(tmp_path: Path) -> None:
    image_path = tmp_path / "sample.jpg"
    _write_jpg(image_path)
    payload = {
        "job_id": "job-jpg-1",
        "run_id": "run-jpg-1",
        "stage": "upscale",
        "image": {"path": "sample.jpg", "width": 8, "height": 8, "format": "jpg"},
        "generation": {
            "prompt": "cinematic portrait",
            "negative_prompt": "blurry",
            "steps": 15,
            "cfg_scale": 6.5,
            "width": 8,
            "height": 8,
            "sampler_name": "DPM++ 2M",
            "scheduler": "Karras",
            "model": "model-x",
            "vae": "Automatic",
        },
        "seeds": {"requested_seed": 111, "actual_seed": 222},
        "stage_manifest": {"name": "sample", "timestamp": "t", "config_hash": "h", "config": {"steps": 15}},
    }
    kv = build_contract_kv(payload, job_id="job-jpg-1", run_id="run-jpg-1", stage="upscale")
    assert write_image_metadata(image_path, kv) is True
    stored = read_image_metadata(image_path)
    decoded = extract_embedded_metadata(image_path)

    assert decoded.status == "ok"
    assert decoded.payload == payload
    assert stored[ImageMetadataContractV26.PUBLIC_KEY_SOFTWARE] == "StableNew"
    assert "cinematic portrait" in stored[ImageMetadataContractV26.PUBLIC_KEY_DESCRIPTION]
    assert "Sampler: DPM++ 2M" in stored[ImageMetadataContractV26.PUBLIC_KEY_PARAMETERS]
    assert "Stage: upscale" in stored[ImageMetadataContractV26.PUBLIC_KEY_PARAMETERS]


def test_png_metadata_omits_payload_when_over_hard_limit(tmp_path: Path) -> None:
    image_path = tmp_path / "omitted.png"
    _write_png(image_path)
    rng = random.Random(4)
    chars = string.ascii_letters + string.digits
    raw = "".join(rng.choice(chars) for _ in range(400_000))
    payload = {"data": raw}
    encoded = encode_payload(payload)
    assert encoded.omitted is True
    kv = build_contract_kv(payload, job_id="job-3", run_id="run-3", stage="txt2img")
    assert kv.get(ImageMetadataContractV26.KEY_PAYLOAD_OMITTED) == "true"
    assert kv.get(ImageMetadataContractV26.KEY_PAYLOAD_REASON) == "SIZE_LIMIT"
    assert write_image_metadata(image_path, kv) is True
    stored = read_image_metadata(image_path)
    assert stored.get(ImageMetadataContractV26.KEY_PAYLOAD_OMITTED) == "true"


def test_corrupt_payload_is_ignored(tmp_path: Path) -> None:
    image_path = tmp_path / "corrupt.png"
    _write_png(image_path)
    payload = {"job_id": "job-4", "run_id": "run-4", "stage": "txt2img"}
    kv = build_contract_kv(payload, job_id="job-4", run_id="run-4", stage="txt2img")
    assert write_image_metadata(image_path, kv) is True
    stored = read_image_metadata(image_path)
    stored[ImageMetadataContractV26.KEY_PAYLOAD] = "{}"
    assert write_image_metadata(image_path, stored) is True
    decoded = extract_embedded_metadata(image_path)
    assert decoded.status == "corrupt"


def test_resolve_prompt_fields_uses_final_and_config_fallbacks() -> None:
    prompt, negative = resolve_prompt_fields(
        {
            "stage_manifest": {
                "config": {
                    "prompt": "config prompt",
                    "negative_prompt": "config negative",
                },
                "final_prompt": "final stage prompt",
            },
            "generation": {
                "original_prompt": "original generation prompt",
                "original_negative_prompt": "original generation negative",
            },
        }
    )

    assert prompt == "final stage prompt"
    assert negative == "config negative"


def test_resolve_model_vae_fields_uses_history_and_config_fallbacks() -> None:
    model, vae = resolve_model_vae_fields(
        {
            "stage_manifest": {
                "config": {
                    "txt2img": {
                        "model": "model-from-txt2img",
                    },
                    "sd_vae": "vae-from-config",
                }
            },
            "stage_history": [
                {"model": "history-model", "vae": "history-vae"},
            ],
        }
    )

    assert model == "model-from-txt2img"
    assert vae == "vae-from-config"


def test_build_payload_from_manifest_preserves_prompt_and_model_fields(tmp_path: Path) -> None:
    image_path = tmp_path / "sample.png"
    _write_png(image_path)
    run_dir = tmp_path
    payload = build_payload_from_manifest(
        image_path=image_path,
        run_dir=run_dir,
        stage="img2img",
        manifest={
            "name": "img2img_sample",
            "stage": "img2img",
            "timestamp": "20260310_120000",
            "original_prompt": "base prompt",
            "final_prompt": "final prompt",
            "original_negative_prompt": "base negative",
            "final_negative_prompt": "final negative",
            "config": {
                "prompt": "config prompt",
                "negative_prompt": "config negative",
                "steps": 24,
                "cfg_scale": 6.5,
                "sampler_name": "Euler a",
                "scheduler": "Karras",
                "model": "modelA",
                "sd_vae": "vaeA",
            },
        },
        image_size=(8, 8),
    )

    assert payload["generation"]["final_prompt"] == "final prompt"
    assert payload["generation"]["original_negative_prompt"] == "base negative"
    assert payload["stage_manifest"]["final_prompt"] == "final prompt"
    assert payload["stage_manifest"]["model"] == "modelA"
    assert payload["stage_manifest"]["vae"] == "vaeA"
