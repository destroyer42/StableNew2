"""Offline local-file identity registry; never contacts A1111 or a network."""

from __future__ import annotations

import hashlib
import json
import os
import struct
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any

from src.assets.cache_lock import registry_cache_lock
from src.assets.checkpoint_structure import STRUCTURE_CONTRACT, checkpoint_header_evidence
from src.assets.compatibility import (
    CompatibilityProfile,
    EvidenceConfidence,
    FamilyEvidence,
    ModelFamily,
    embedded_metadata_evidence,
    embedded_metadata_field_present,
    filename_hint_evidence,
    resolve_compatibility_profile,
    sidecar_metadata_evidence,
    sidecar_metadata_field_present,
)
from src.state.workspace_paths import workspace_paths

_EXTENSIONS = frozenset({".bin", ".ckpt", ".onnx", ".pt", ".pth", ".safetensors"})
_CHUNK = 1024 * 1024
_CACHE_VERSION = 2
_SUPPORTED_CACHE_VERSIONS = (1, 2)


def _structure_is_current(entry: dict[str, Any]) -> bool:
    structure = entry.get("structure")
    return isinstance(structure, dict) and structure.get("contract") == STRUCTURE_CONTRACT


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
    # Location-scoped local sidecar evidence: sidecars enrich one file
    # location, never the shared content identity (see AssetRecord).
    sidecar_path: Path | None = None
    sidecar_metadata: dict[str, Any] = field(default_factory=dict)
    sidecar_provenance: str | None = None
    sidecar_error: str | None = None


@dataclass(frozen=True)
class AssetRecord:
    sha256: str
    locations: tuple[AssetLocation, ...]
    embedded_metadata: dict[str, Any]
    metadata_provenance: str | None
    embedded_metadata_error: str | None = None
    compatibility: CompatibilityProfile | None = None
    structural_evidence: dict[str, Any] = field(default_factory=dict)

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


@dataclass(frozen=True)
class CheckpointInspection:
    """Header-only evidence; deliberately carries no checkpoint byte identity."""

    compatibility: CompatibilityProfile
    embedded_metadata: dict[str, Any]
    embedded_metadata_error: str | None
    locations: tuple[AssetLocation, ...]
    structural_evidence: dict[str, Any]


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


def _sidecar_candidates(path: Path) -> tuple[Path, Path]:
    """Deterministic sidecar precedence, matching tools/asset_census.py."""

    return (
        path.with_suffix(path.suffix + ".civitai.info"),
        path.with_name(f"{path.stem}.civitai.info"),
    )


def _sidecar_fingerprint(path: Path) -> dict[str, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _read_sidecar_json(path: Path) -> tuple[dict[str, Any], str | None]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    try:
        parsed = json.loads(text)
    except (ValueError, UnicodeDecodeError) as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    if not isinstance(parsed, dict):
        return {}, "sidecar JSON is not an object"
    return parsed, None


def _resolve_sidecar(path: Path, cached: dict[str, Any] | None) -> dict[str, Any]:
    """Resolve this exact location's sidecar evidence.

    Sidecar freshness is independent of model-byte freshness: this re-reads
    only when the selected candidate or its fingerprint (size/mtime_ns)
    differs from what is cached, so an unchanged sidecar never forces a
    model rehash and never gets re-parsed on every refresh either.
    """

    selected: Path | None = None
    fingerprint: dict[str, int] | None = None
    for candidate in _sidecar_candidates(path):
        candidate_fingerprint = _sidecar_fingerprint(candidate)
        if candidate_fingerprint is not None:
            selected, fingerprint = candidate, candidate_fingerprint
            break

    if selected is None:
        return {
            "sidecar_path": None,
            "sidecar_metadata": {},
            "sidecar_provenance": None,
            "sidecar_error": None,
            "sidecar_fingerprint": None,
        }

    if (
        cached is not None
        and cached.get("sidecar_path") == str(selected)
        and cached.get("sidecar_fingerprint") == fingerprint
    ):
        return {
            "sidecar_path": cached.get("sidecar_path"),
            "sidecar_metadata": cached.get("sidecar_metadata") or {},
            "sidecar_provenance": cached.get("sidecar_provenance"),
            "sidecar_error": cached.get("sidecar_error"),
            "sidecar_fingerprint": fingerprint,
        }

    metadata, error = _read_sidecar_json(selected)
    return {
        "sidecar_path": str(selected),
        "sidecar_metadata": metadata,
        "sidecar_provenance": "civitai_sidecar" if metadata else None,
        "sidecar_error": error,
        "sidecar_fingerprint": fingerprint,
    }


class AssetRegistry:
    """One local byte-identity authority, with a fingerprint-validated hash cache."""

    def __init__(
        self, webui_root: Path | str | None = None, *, cache_path: Path | str | None = None
    ) -> None:
        configured = os.environ.get("STABLENEW_WEBUI_ROOT", "")
        if webui_root is None and not configured:
            from src.config.app_config import STABLENEW_WEBUI_ROOT

            configured = STABLENEW_WEBUI_ROOT
        self.webui_root = (
            Path(webui_root or configured).expanduser() if webui_root or configured else None
        )
        self.cache_path = Path(cache_path) if cache_path else workspace_paths.asset_registry_cache()
        self._entries: dict[str, dict[str, Any]] = {}
        self._loaded = False
        self._snapshot = AssetRegistrySnapshot(())

    def supported_roots(self) -> tuple[tuple[AssetKind, Path], ...]:
        if self.webui_root is None:
            return ()
        models = self.webui_root / "models"
        return (
            (AssetKind.CHECKPOINT, models / "Stable-diffusion"),
            (AssetKind.VAE, models / "VAE"),
            (AssetKind.APPROXIMATE_VAE, models / "VAE-approx"),
            (AssetKind.LORA, models / "Lora"),
            (AssetKind.LORA, models / "LyCORIS"),
            (AssetKind.EMBEDDING, self.webui_root / "embeddings"),
            (AssetKind.UPSCALER, models / "ESRGAN"),
            (AssetKind.UPSCALER, models / "RealESRGAN"),
            (AssetKind.RESTORATION, models / "GFPGAN"),
            (AssetKind.RESTORATION, models / "Codeformer"),
            (AssetKind.CONTROLNET, models / "ControlNet"),
            (AssetKind.BLIP, models / "BLIP"),
            (AssetKind.ADETAILER, models / "adetailer"),
        )

    @property
    def snapshot(self) -> AssetRegistrySnapshot:
        return self._snapshot

    def cached_snapshot(self) -> AssetRegistrySnapshot:
        """The last persisted snapshot, without scanning or hashing anything (safe on a UI thread)."""

        self._load()
        return self._snapshot

    def refresh(
        self,
        *,
        kinds: Iterable[AssetKind] | None = None,
        checkpoint_paths: Iterable[Path] | None = None,
        cancelled: Callable[[], bool] | None = None,
        progress: Callable[[Path, int, int], None] | None = None,
    ) -> RefreshResult:
        """Refresh selected kinds, or only exact served checkpoints (never scan in that mode).

        Every writer reloads under the shared cache lock. A cancelled/failed
        transaction publishes no partial snapshot, including across instances.
        """
        # Hash outside the writer lock: existing LoRA/embedding readers must
        # not wait behind multi-GB checkpoint reads. Only cache commit is locked.
        self._loaded = False
        self._load()
        entries, computed, hits = self._prepare_refresh(
            kinds, checkpoint_paths, cancelled, progress
        )
        with registry_cache_lock(self.cache_path, cancelled=cancelled):
            self._loaded = False
            self._load()
            selected = set(kinds) if kinds is not None else set(AssetKind)
            if checkpoint_paths is None:
                self._entries = {
                    key: value
                    for key, value in self._entries.items()
                    if value.get("kind") not in {item.value for item in selected}
                }
            for entry in entries.values():
                stat = Path(entry["path"]).stat()
                if (stat.st_size, stat.st_mtime_ns) != (entry["size"], entry["mtime_ns"]):
                    raise ValueError("Asset changed before evidence publication; retry Preview")
            if cancelled and cancelled():
                raise InterruptedError("Checkpoint evidence refresh cancelled")
            self._entries.update(entries)
            self._snapshot = self._make_snapshot()
            self._save()
            return RefreshResult(self._snapshot, computed, hits)

    def checkpoint_is_current(self, path: Path) -> bool:
        """Worker-only fingerprint check of one exact path; no directory traversal or hash."""
        self._load()
        key = str(path.resolve())
        cached = self._entries.get(key)
        try:
            stat = path.stat()
        except OSError:
            return False
        if (
            not cached
            or cached.get("kind") != AssetKind.CHECKPOINT.value
            or (cached.get("size"), cached.get("mtime_ns")) != (stat.st_size, stat.st_mtime_ns)
            or not _structure_is_current(cached)
        ):
            return False
        for candidate in _sidecar_candidates(path):
            fingerprint = _sidecar_fingerprint(candidate)
            if fingerprint is not None:
                return (
                    cached.get("sidecar_path") == str(candidate)
                    and cached.get("sidecar_fingerprint") == fingerprint
                )
        return cached.get("sidecar_path") is None

    def inspect_checkpoint(self, path: Path) -> CheckpointInspection:
        """Worker-only header/sidecar preflight, without byte identity.

        Not persisted or exposed as executable identity. Unsupported candidates
        are rejected before an expensive hash; refresh still owns byte identity.
        """
        self._load()
        fields = checkpoint_header_evidence(path)
        sidecar = _resolve_sidecar(path, None)
        location = AssetLocation(
            AssetKind.CHECKPOINT, path, path.parent, path.stem, path.stat().st_size,
            Path(sidecar["sidecar_path"]) if sidecar["sidecar_path"] else None,
            sidecar["sidecar_metadata"], sidecar["sidecar_provenance"], sidecar["sidecar_error"],
        )
        record = self._build_record(
            "", [location], (fields["metadata"], "safetensors_header", fields["metadata_error"]),
            fields["structure"],
        )
        assert record.compatibility is not None
        return CheckpointInspection(
            record.compatibility, record.embedded_metadata, record.embedded_metadata_error,
            record.locations, record.structural_evidence,
        )

    def _prepare_refresh(
        self,
        kinds: Iterable[AssetKind] | None,
        checkpoint_paths: Iterable[Path] | None,
        cancelled: Callable[[], bool] | None,
        progress: Callable[[Path, int, int], None] | None,
    ) -> tuple[dict[str, dict[str, Any]], int, int]:
        selected = set(kinds) if kinds is not None else set(AssetKind)
        next_entries: dict[str, dict[str, Any]] = {}
        computed = hits = 0
        roots_and_paths: list[tuple[AssetKind, Path, Iterable[Path]]]
        if checkpoint_paths is not None:
            roots_and_paths = [
                (AssetKind.CHECKPOINT, path.parent, (path,))
                for path in sorted(set(checkpoint_paths), key=str)
            ]
        else:
            roots_and_paths = [
                (
                    kind,
                    root,
                    sorted(
                        (
                            path
                            for path in root.rglob("*")
                            if path.is_file() and path.suffix.lower() in _EXTENSIONS
                        ),
                        key=str,
                    ),
                )
                for kind, root in self.supported_roots()
                if kind in selected and root.is_dir()
            ]
        for kind, root, paths in roots_and_paths:
            for path in paths:
                if cancelled and cancelled():
                    raise InterruptedError("Checkpoint evidence refresh cancelled")
                if path.suffix.lower() not in _EXTENSIONS:
                    raise ValueError("Unsupported checkpoint file type")
                key = str(path.resolve())
                stat = path.stat()
                cached = self._entries.get(key)
                model_valid = bool(
                    cached
                    and cached.get("size") == stat.st_size
                    and cached.get("mtime_ns") == stat.st_mtime_ns
                    and cached.get("kind") == kind.value
                )
                sidecar_fields = _resolve_sidecar(path, cached if model_valid else None)
                header_fields = (
                    checkpoint_header_evidence(path)
                    if kind is AssetKind.CHECKPOINT and (
                        not model_valid
                        or cached is None
                        or not _structure_is_current(cached)
                    ) else None
                )
                if model_valid and cached is not None:
                    entry = dict(cached)
                    entry.update(sidecar_fields)
                    if header_fields is not None:
                        entry.update(header_fields)
                    next_entries[key] = entry
                    hits += 1
                    continue
                digest = hashlib.sha256()
                read_bytes = 0
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(_CHUNK), b""):
                        if cancelled and cancelled():
                            raise InterruptedError("Checkpoint evidence refresh cancelled")
                        digest.update(chunk)
                        read_bytes += len(chunk)
                        if progress:
                            progress(path, read_bytes, stat.st_size)
                if header_fields is not None:
                    metadata, error = header_fields["metadata"], header_fields["metadata_error"]
                else:
                    metadata, error = (
                        _safetensors_metadata(path)
                        if path.suffix.lower() == ".safetensors" else ({}, None)
                    )
                entry = {
                    "path": key,
                    "root": str(root.resolve()),
                    "kind": kind.value,
                    "name": path.stem,
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "sha256": digest.hexdigest(),
                    "metadata": metadata,
                    "provenance": "safetensors_header" if metadata else None,
                    "metadata_error": error,
                }
                entry.update(sidecar_fields)
                if header_fields is not None:
                    entry["structure"] = header_fields["structure"]
                after = path.stat()
                if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError("Checkpoint changed during evidence refresh; retry Preview")
                next_entries[key] = entry
                computed += 1
        if cancelled and cancelled():
            raise InterruptedError("Checkpoint evidence refresh cancelled")
        return next_entries, computed, hits

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        entries: Any = {}
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if data.get("version") in _SUPPORTED_CACHE_VERSIONS:
                entries = data.get("entries", {})
        except (OSError, ValueError, TypeError):
            entries = {}
        self._entries = entries if isinstance(entries, dict) else {}
        self._snapshot = self._make_snapshot()

    def _save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"version": _CACHE_VERSION, "entries": self._entries}, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(self.cache_path)

    def _make_snapshot(self) -> AssetRegistrySnapshot:
        grouped: dict[str, list[AssetLocation]] = {}
        content_metadata: dict[str, tuple[dict[str, Any], str | None, str | None]] = {}
        structures: dict[str, dict[str, Any]] = {}
        for entry in self._entries.values():
            try:
                digest = str(entry["sha256"])
                kind = AssetKind(entry["kind"])
                sidecar_path_raw = entry.get("sidecar_path")
                raw_sidecar_metadata = entry.get("sidecar_metadata")
                sidecar_metadata = (
                    raw_sidecar_metadata if isinstance(raw_sidecar_metadata, dict) else {}
                )
                location = AssetLocation(
                    kind,
                    Path(entry["path"]),
                    Path(entry["root"]),
                    str(entry["name"]),
                    int(entry["size"]),
                    Path(sidecar_path_raw) if sidecar_path_raw else None,
                    sidecar_metadata,
                    entry.get("sidecar_provenance"),
                    entry.get("sidecar_error"),
                )
            except (KeyError, TypeError, ValueError):
                continue
            grouped.setdefault(digest, []).append(location)
            if kind is AssetKind.CHECKPOINT and isinstance(entry.get("structure"), dict):
                structures[digest] = entry["structure"]
            raw_metadata = entry.get("metadata")
            content_metadata.setdefault(
                digest,
                (
                    raw_metadata if isinstance(raw_metadata, dict) else {},
                    entry.get("provenance"),
                    entry.get("metadata_error"),
                ),
            )
        records = tuple(
            self._build_record(digest, locations, content_metadata[digest], structures.get(digest, {}))
            for digest, locations in sorted(grouped.items())
        )
        return AssetRegistrySnapshot(records)

    @staticmethod
    def _build_record(
        digest: str,
        locations: list[AssetLocation],
        content: tuple[dict[str, Any], str | None, str | None],
        structure: dict[str, Any] | None = None,
    ) -> AssetRecord:
        ordered = tuple(sorted(locations, key=lambda item: str(item.path).lower()))
        metadata, provenance, metadata_error = content

        evidence: list[FamilyEvidence] = []
        evidence.extend(embedded_metadata_evidence(metadata))
        structure = structure or {}
        architecture = str(structure.get("architecture") or "unrecognized") if structure else None
        structural_family = {
            "sdxl_base": ModelFamily.SDXL, "sdxl_refiner": ModelFamily.SDXL,
            "sdxl_inpaint": ModelFamily.SDXL, "sd1": ModelFamily.SD1, "sd2": ModelFamily.SD2,
        }.get(architecture or "")
        if structural_family is not None:
            evidence.append(FamilyEvidence(
                structural_family, "safetensors_structure", architecture or "",
                EvidenceConfidence.STRUCTURAL,
            ))
        for location in ordered:
            if location.sidecar_metadata:
                evidence.extend(
                    sidecar_metadata_evidence(
                        location.sidecar_metadata, location=str(location.path)
                    )
                )
        for location in ordered:
            hint = filename_hint_evidence(location.display_name, location=str(location.path))
            if hint is not None:
                evidence.append(hint)

        # A supported field present but unrecognized (e.g. a derivative label)
        # is still real metadata evidence: it must block filename fallback
        # even though it produced no FamilyEvidence of its own.
        metadata_field_present = embedded_metadata_field_present(metadata) or any(
            sidecar_metadata_field_present(location.sidecar_metadata) for location in ordered
        )

        profile = resolve_compatibility_profile(
            tuple(evidence), metadata_field_present=metadata_field_present,
            checkpoint_architecture=architecture,
        )
        profile = replace(
            profile, checkpoint_architecture=architecture, structural_error=structure.get("error"),
        )
        return AssetRecord(digest, ordered, metadata, provenance, metadata_error, profile, structure)
