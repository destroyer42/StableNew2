"""Offline local-file identity registry; never contacts A1111 or a network."""
from __future__ import annotations

import hashlib
import json
import os
import struct
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from src.state.workspace_paths import workspace_paths

_EXTENSIONS = frozenset({".bin", ".ckpt", ".onnx", ".pt", ".pth", ".safetensors"})
_CHUNK = 1024 * 1024


class AssetKind(str, Enum):
    CHECKPOINT = "checkpoint"
    VAE = "vae"
    APPROXIMATE_VAE = "approximate_vae"
    LORA = "lora"
    EMBEDDING = "embedding"
    UPSCALER = "upscaler"
    RESTORATION = "restoration"
    CONTROLNET = "controlnet"
    BLIP = "blip"
    ADETAILER = "adetailer"


@dataclass(frozen=True)
class AssetLocation:
    kind: AssetKind
    path: Path
    root: Path
    display_name: str
    byte_size: int


@dataclass(frozen=True)
class AssetRecord:
    sha256: str
    locations: tuple[AssetLocation, ...]
    embedded_metadata: dict[str, Any]
    metadata_provenance: str | None

    @property
    def kinds(self) -> tuple[AssetKind, ...]:
        return tuple(sorted({item.kind for item in self.locations}, key=lambda item: item.value))


@dataclass(frozen=True)
class AssetRegistrySnapshot:
    records: tuple[AssetRecord, ...]

    def records_for(self, kind: AssetKind) -> tuple[AssetRecord, ...]:
        return tuple(record for record in self.records if kind in record.kinds)


@dataclass(frozen=True)
class RefreshResult:
    snapshot: AssetRegistrySnapshot
    hashes_computed: int
    hash_cache_hits: int


def _safetensors_metadata(path: Path) -> tuple[dict[str, Any], str | None]:
    try:
        with path.open("rb") as stream:
            raw_size = stream.read(8)
            if len(raw_size) != 8:
                return {}, "truncated header length"
            size = struct.unpack("<Q", raw_size)[0]
            if size > 64 * 1024 * 1024:
                return {}, "header too large"
            header = stream.read(size)
        if len(header) != size:
            return {}, "truncated header"
        parsed = json.loads(header.decode("utf-8"))
        metadata = parsed.get("__metadata__") if isinstance(parsed, dict) else None
        return (metadata if isinstance(metadata, dict) else {}), None
    except (OSError, UnicodeDecodeError, ValueError, struct.error) as exc:
        return {}, f"{type(exc).__name__}: {exc}"


class AssetRegistry:
    """One local byte-identity authority, with a fingerprint-validated hash cache."""

    def __init__(self, webui_root: Path | str | None = None, *, cache_path: Path | str | None = None) -> None:
        configured = os.environ.get("STABLENEW_WEBUI_ROOT", "")
        if webui_root is None and not configured:
            from src.config.app_config import STABLENEW_WEBUI_ROOT
            configured = STABLENEW_WEBUI_ROOT
        self.webui_root = Path(webui_root or configured).expanduser() if webui_root or configured else None
        self.cache_path = Path(cache_path) if cache_path else workspace_paths.asset_registry_cache()
        self._entries: dict[str, dict[str, Any]] = {}
        self._loaded = False
        self._snapshot = AssetRegistrySnapshot(())

    def supported_roots(self) -> tuple[tuple[AssetKind, Path], ...]:
        if self.webui_root is None:
            return ()
        models = self.webui_root / "models"
        return (
            (AssetKind.CHECKPOINT, models / "Stable-diffusion"), (AssetKind.VAE, models / "VAE"),
            (AssetKind.APPROXIMATE_VAE, models / "VAE-approx"), (AssetKind.LORA, models / "Lora"),
            (AssetKind.LORA, models / "LyCORIS"), (AssetKind.EMBEDDING, self.webui_root / "embeddings"),
            (AssetKind.UPSCALER, models / "ESRGAN"), (AssetKind.UPSCALER, models / "RealESRGAN"),
            (AssetKind.RESTORATION, models / "GFPGAN"), (AssetKind.RESTORATION, models / "Codeformer"),
            (AssetKind.CONTROLNET, models / "ControlNet"), (AssetKind.BLIP, models / "BLIP"),
            (AssetKind.ADETAILER, models / "adetailer"),
        )

    @property
    def snapshot(self) -> AssetRegistrySnapshot:
        return self._snapshot

    def refresh(self, *, kinds: Iterable[AssetKind] | None = None) -> RefreshResult:
        self._load()
        selected = set(kinds) if kinds is not None else set(AssetKind)
        next_entries = {key: value for key, value in self._entries.items() if value.get("kind") not in {item.value for item in selected}}
        computed = hits = 0
        for kind, root in self.supported_roots():
            if kind not in selected or not root.is_dir():
                continue
            for path in sorted((p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in _EXTENSIONS), key=lambda p: str(p).lower()):
                key = str(path.resolve()); stat = path.stat(); cached = self._entries.get(key)
                valid = cached and cached.get("size") == stat.st_size and cached.get("mtime_ns") == stat.st_mtime_ns and cached.get("kind") == kind.value
                if valid:
                    next_entries[key] = cached; hits += 1; continue
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(_CHUNK), b""):
                        digest.update(chunk)
                metadata, error = _safetensors_metadata(path) if path.suffix.lower() == ".safetensors" else ({}, None)
                next_entries[key] = {"path": key, "root": str(root.resolve()), "kind": kind.value, "name": path.stem, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": digest.hexdigest(), "metadata": metadata, "provenance": "safetensors_header" if metadata else None, "metadata_error": error}
                computed += 1
        self._entries = next_entries; self._snapshot = self._make_snapshot(); self._save()
        return RefreshResult(self._snapshot, computed, hits)

    def _load(self) -> None:
        if self._loaded: return
        self._loaded = True
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            self._entries = data.get("entries", {}) if data.get("version") == 1 else {}
        except (OSError, ValueError, TypeError): self._entries = {}
        self._snapshot = self._make_snapshot()

    def _save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": 1, "entries": self._entries}, sort_keys=True), encoding="utf-8")
        temporary.replace(self.cache_path)

    def _make_snapshot(self) -> AssetRegistrySnapshot:
        grouped: dict[str, list[AssetLocation]] = {}
        metadata: dict[str, tuple[dict[str, Any], str | None]] = {}
        for entry in self._entries.values():
            try:
                digest = str(entry["sha256"]); kind = AssetKind(entry["kind"])
                location = AssetLocation(kind, Path(entry["path"]), Path(entry["root"]), str(entry["name"]), int(entry["size"]))
            except (KeyError, TypeError, ValueError): continue
            grouped.setdefault(digest, []).append(location)
            metadata.setdefault(digest, (entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}, entry.get("provenance")))
        records = tuple(AssetRecord(digest, tuple(sorted(locations, key=lambda item: str(item.path).lower())), *metadata[digest]) for digest, locations in sorted(grouped.items()))
        return AssetRegistrySnapshot(records)
