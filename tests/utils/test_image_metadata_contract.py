from __future__ import annotations

import random
import string
from pathlib import Path

from PIL import Image

from src.utils.image_metadata import (
    ImageMetadataContractV26,
    build_contract_kv,
    decode_payload,
    encode_payload,
    extract_embedded_metadata,
    read_image_metadata,
    write_image_metadata,
)


def _write_png(path: Path, size: tuple[int, int] = (8, 8)) -> None:
    image = Image.new("RGB", size, color=(10, 20, 30))
    image.save(path)


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
