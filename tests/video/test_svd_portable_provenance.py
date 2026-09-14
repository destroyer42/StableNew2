from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

from src.utils.image_metadata import (
    ImageMetadataContractV26,
    build_contract_kv,
    read_image_metadata,
    write_image_metadata,
)
from src.video import svd_portable_provenance as provenance


def _write_source(path: Path) -> None:
    Image.new("RGB", (32, 48), color=(12, 34, 56)).save(path)


def _source_payload() -> dict[str, object]:
    return {
        "job_id": "image-job-1",
        "run_id": "image-run-1",
        "stage": "txt2img",
        "njr": {"sha256": "source-njr-sha"},
        "generation": {
            "prompt": "portrait in golden light",
            "negative_prompt": "blurry",
            "model": "portrait-model",
            "vae": "portrait-vae",
        },
        "seeds": {"actual_seed": 1234},
        "stage_history": [{"stage": "txt2img", "config": {"steps": 25}}],
        "artifact": {"path": "historic-source.png"},
    }


def _portable_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": provenance.PortableVideoProvenanceContractV26.SCHEMA,
        "media_type": "video",
        "video": {"media_content_sha256": "a" * 64},
        "svd": {"config": {}, "preprocess": {}, "postprocess": {}},
        "source": {"file_sha256": "b" * 64, "stable_new_provenance_status": "missing"},
        "lineage": {},
    }
    payload.update(overrides)
    return payload


def _read_from_tags(monkeypatch, tags: dict[str, str]) -> None:
    monkeypatch.setattr(provenance, "read_video_container_metadata", lambda _path: tags)


def test_small_raw_payload_round_trips_and_verifies_sha(monkeypatch, tmp_path: Path) -> None:
    payload = _portable_payload()
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        provenance,
        "write_video_container_metadata",
        lambda _path, _public, additional_tags: captured.update(additional_tags) or True,
    )
    _read_from_tags(monkeypatch, captured)

    encoded = provenance.write_portable_svd_video_provenance(
        video_path=tmp_path / "clip.mp4",
        public_metadata={"stage": "svd_native"},
        payload=payload,
    )

    result = provenance.read_portable_svd_video_provenance(tmp_path / "clip.mp4")
    assert encoded.mode == "raw"
    assert result.status == "ok"
    assert result.payload == payload
    assert result.payload_sha256 == encoded.payload_sha256


def test_large_payload_uses_gzip_base64_and_round_trips(monkeypatch, tmp_path: Path) -> None:
    payload = _portable_payload(source={"notes": "x" * 40_000})
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        provenance,
        "write_video_container_metadata",
        lambda _path, _public, additional_tags: captured.update(additional_tags) or True,
    )
    _read_from_tags(monkeypatch, captured)

    encoded = provenance.write_portable_svd_video_provenance(
        video_path=tmp_path / "clip.mp4",
        public_metadata={"stage": "svd_native"},
        payload=payload,
    )

    assert encoded.mode == "gzip+base64"
    assert provenance.PortableVideoProvenanceContractV26.KEY_PAYLOAD_GZ_B64 in captured
    assert provenance.read_portable_svd_video_provenance(tmp_path / "clip.mp4").payload == payload


def test_tampered_payload_is_rejected_by_sha(monkeypatch, tmp_path: Path) -> None:
    encoded = provenance.encode_portable_video_provenance(_portable_payload())
    tags = provenance.build_portable_video_provenance_tags(encoded)
    tags[provenance.PortableVideoProvenanceContractV26.KEY_PAYLOAD_SHA256] = "0" * 64
    _read_from_tags(monkeypatch, tags)

    result = provenance.read_portable_svd_video_provenance(tmp_path / "clip.mp4")

    assert result.status == "corrupt"
    assert result.error == "payload_sha256_mismatch"


def test_source_file_sha_and_valid_stablenew_image_lineage_are_preserved(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    _write_source(source)
    source_payload = _source_payload()
    assert write_image_metadata(
        source,
        build_contract_kv(
            source_payload, job_id="image-job-1", run_id="image-run-1", stage="txt2img"
        ),
    )

    payload = provenance.build_svd_portable_provenance(
        source_image_path=source,
        job_id="video-job-1",
        run_id="video-run-1",
        model_id="stabilityai/stable-video-diffusion-img2vid-xt",
        seed=7,
        frame_count=28,
        fps=14,
        config={"inference": {"fps": 7}},
        preprocess={"source_dimensions": {"width": 32, "height": 48}},
        postprocess={"interpolation": {"output_frame_count": 28, "output_fps": 14}},
        media_content_sha256="c" * 64,
        execution_context={
            "current_njr_sha256": "current-njr-sha",
            "source_descriptor": {
                "kind": "video_workflow",
                "parent_job_id": "parent-job-1",
                "parent_artifact_id": "parent-artifact-1",
            },
        },
    )

    assert payload["source"]["file_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert payload["source"]["stable_new_provenance_status"] == "ok"
    assert payload["source"]["stable_new_provenance"] == source_payload
    assert payload["lineage"]["current_njr_sha256"] == "current-njr-sha"
    assert payload["lineage"]["parent_job_id"] == "parent-job-1"
    assert payload["lineage"]["parent_artifact_id"] == "parent-artifact-1"
    assert payload["svd"]["config"] == {"inference": {"fps": 7}}
    assert payload["svd"]["preprocess"] == {"source_dimensions": {"width": 32, "height": 48}}
    assert payload["svd"]["postprocess"]["interpolation"]["output_fps"] == 14


def test_missing_and_corrupt_source_metadata_are_explicit_and_do_not_block(tmp_path: Path) -> None:
    missing = tmp_path / "missing.png"
    corrupt = tmp_path / "corrupt.png"
    _write_source(missing)
    _write_source(corrupt)
    corrupt_kv = build_contract_kv(
        _source_payload(), job_id="image-job-1", run_id="image-run-1", stage="txt2img"
    )
    assert write_image_metadata(corrupt, corrupt_kv)
    stored = read_image_metadata(corrupt)
    stored[ImageMetadataContractV26.KEY_PAYLOAD] = "{}"
    assert write_image_metadata(corrupt, stored)

    def _build(source: Path) -> dict[str, object]:
        return provenance.build_svd_portable_provenance(
            source_image_path=source,
            job_id="video-job",
            run_id="video-run",
            model_id="plain-xt",
            seed=1,
            frame_count=14,
            fps=7,
            config={},
            preprocess={},
            postprocess={},
            media_content_sha256="d" * 64,
        )

    missing_payload = _build(missing)
    corrupt_payload = _build(corrupt)
    assert missing_payload["source"]["stable_new_provenance_status"] == "missing"
    assert "stable_new_provenance" not in missing_payload["source"]
    assert corrupt_payload["source"]["stable_new_provenance_status"] == "corrupt"
    assert "stable_new_provenance" not in corrupt_payload["source"]


def test_absent_parent_artifact_id_is_not_fabricated(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    _write_source(source)
    payload = provenance.build_svd_portable_provenance(
        source_image_path=source,
        job_id="video-job",
        run_id="video-run",
        model_id="plain-xt",
        seed=None,
        frame_count=14,
        fps=7,
        config={},
        preprocess={},
        postprocess={},
        media_content_sha256="e" * 64,
        execution_context={"source_descriptor": {"parent_job_id": "parent-job"}},
    )

    assert payload["lineage"]["parent_job_id"] == "parent-job"
    assert "parent_artifact_id" not in payload["lineage"]


def test_media_hash_verification_uses_embedded_video_media_identity(
    monkeypatch, tmp_path: Path
) -> None:
    payload = _portable_payload(video={"media_content_sha256": "f" * 64})
    monkeypatch.setattr(
        provenance,
        "read_portable_svd_video_provenance",
        lambda _path: provenance.PortableVideoProvenanceReadResult(payload, "ok"),
    )
    monkeypatch.setattr(provenance, "compute_video_media_content_sha256", lambda _path: "f" * 64)

    assert provenance.verify_portable_svd_video_media_content(tmp_path / "clip.mp4").status == "ok"
    monkeypatch.setattr(provenance, "compute_video_media_content_sha256", lambda _path: "0" * 64)
    assert (
        provenance.verify_portable_svd_video_media_content(tmp_path / "clip.mp4").error
        == "media_content_sha256_mismatch"
    )
