"""Tiny synthetic fixtures for the curated readiness tests (PR-ASSET-130): no real model, network or GPU."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import Any

from src.assets.registry import AssetRegistry
from src.assets.resource_catalog import Catalog, parse_catalog


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_safetensors(path: Path, payload: bytes = b"\x00\x00\x00\x00") -> Path:
    header = b'{"t":{"dtype":"F32","shape":[1],"data_offsets":[0,4]}}'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(header)) + header + payload[:4].ljust(4, b"\x00"))
    return path


def write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def variant(name: str, digest: str | None, *, upstream: str | None = None) -> dict[str, Any]:
    return {
        "variant_id": upstream or name,
        "upstream_path": upstream or name,
        "suggested_filename": name,
        "sha256": digest,
        "size_bytes": None,
        "hash_status": "verified_upstream" if digest else "pending_verification",
        "hash_basis": "hub_lfs_oid" if digest else None,
    }


def resource(
    rid: str,
    files: list[dict[str, Any]],
    *,
    root: str = "auxiliary",
    capability: dict[str, Any] | None = None,
    prerequisites: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": rid,
        "title": rid,
        "category": "test",
        "capability": capability
        or {
            "id": "segmentation.test",
            "policy": "needs_integration",
            "modality": None,
            "reason_codes": ["feature_not_built"],
            "basis": "test",
        },
        "source": {
            "publisher_repo": "example/repo",
            "url": "https://huggingface.co/example/repo",
            "revision": "a" * 40,
            "revision_status": "pinned",
            "license": {
                "model_card_tag": "mit",
                "spdx": "MIT",
                "status": "model_card_declared",
                "note": "",
            },
            "verified_on": "2026-10-23",
            "verified_via": "test",
        },
        "placement": {
            "root": root,
            "directory": rid if root == "auxiliary" else "",
            "instructions": "Place the files, then refresh.",
        },
        "files": files,
        "external_prerequisites": prerequisites or [],
        "notes": [],
    }


def file_spec(
    role: str, variants: list[dict[str, Any]], *, required: bool = True
) -> dict[str, Any]:
    return {"role": role, "required": required, "description": role, "variants": variants}


def controlnet_capability(modality: str = "canny") -> dict[str, Any]:
    return {
        "id": f"controlnet_unit.{modality}",
        "policy": "supported_now",
        "modality": modality,
        "reason_codes": ["policy_allows_prerendered_map_unit"],
        "basis": "test",
    }


def make_catalog(*resources: dict[str, Any]) -> Catalog:
    return parse_catalog(
        {
            "contract": "curated_asset_catalog/1",
            "catalog_version": "test.1",
            "description": "test",
            "hash_semantics": "test",
            "resources": list(resources),
        }
    )


def make_registry(tmp_path: Path) -> AssetRegistry:
    return AssetRegistry(
        tmp_path / "webui", cache_path=tmp_path / "state" / "asset_registry_v1.json"
    )


def controlnet_dir(registry: AssetRegistry) -> Path:
    assert registry.webui_root is not None
    return registry.webui_root / "models" / "ControlNet"


def aux_dir(registry: AssetRegistry) -> Path:
    assert registry.webui_root is not None
    return registry.webui_root / "models" / "StableNewAux"
