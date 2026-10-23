"""Offline local-file identity registry; never contacts A1111 or a network."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any

from src.assets.cache_diagnostics import (
    CacheDescription,
    CacheState,
    CheckpointMiss,
    CheckpointStatus,
    RefreshCounters,
)
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
from src.assets.observation import ObservationRoot, ObservationScan, ScanLimits, observe_roots
from src.state.workspace_paths import workspace_paths

_EXTENSIONS = frozenset({".bin", ".ckpt", ".onnx", ".pt", ".pth", ".safetensors"})
#: Reference images (PR-IMG-CNET-210). Deliberately a different, per-kind filter: image files must never be indexed as
#: model weights, and weight files must never be indexed as reference images.
_IMAGE_EXTENSIONS = frozenset({".jpeg", ".jpg", ".png", ".webp"})
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
    #: Pre-rendered OpenPose reference images under ``models/OpenPose`` (conditioning input, never a model weight).
    OPENPOSE_IMAGE = "openpose_image"
    #: Auxiliary model files (preprocessor, vision and processor assets) under ``models/StableNewAux`` (PR-ASSET-130).
    #: Identity only: nothing here is a selectable checkpoint, and it is never part of a default ``refresh()``.
    AUXILIARY_MODEL = "auxiliary_model"


_IMAGE_KINDS = frozenset({AssetKind.OPENPOSE_IMAGE})
_AUXILIARY_KINDS = frozenset({AssetKind.AUXILIARY_MODEL})
#: Auxiliary files are indexed by byte identity only. Pickle-based containers (``.pt``/``.pth``/``.bin``/``.ckpt``) are
#: deliberately absent, and the small JSON/text members exist so a processor bundle can be verified as a group.
_AUXILIARY_EXTENSIONS = frozenset({".json", ".onnx", ".safetensors", ".txt"})
#: A single auxiliary file larger than this is refused rather than streamed (no auxiliary asset approaches it).
AUXILIARY_MAX_BYTES = 16 * 1024**3
#: Kinds a default (``kinds=None``) refresh covers; auxiliary files are hashed only when explicitly requested.
_DEFAULT_REFRESH_KINDS = frozenset(set(AssetKind) - _AUXILIARY_KINDS)


def _extensions_for(kind: AssetKind) -> frozenset[str]:
    if kind in _AUXILIARY_KINDS:
        return _AUXILIARY_EXTENSIONS
    return _IMAGE_EXTENSIONS if kind in _IMAGE_KINDS else _EXTENSIONS


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
    #: Path-free cost/miss accounting of this refresh (see ``cache_diagnostics``).
    counters: RefreshCounters = field(default_factory=RefreshCounters)


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


_CHECKPOINT_NAME_SUFFIXES = (".safetensors", ".sft", ".ckpt", ".pt", ".pth")


def _checkpoint_name_key(value: str) -> str:
    """Case-insensitive identity of a selected model name: path-free, no ``[hash]`` suffix, no weight extension."""

    base = str(value or "").strip().replace("\\", "/")
    base = base.rsplit("/", 1)[-1]
    if base.endswith("]") and " [" in base:
        base = base[: base.rindex(" [")]
    lowered = base.strip().lower()
    for suffix in _CHECKPOINT_NAME_SUFFIXES:
        if lowered.endswith(suffix):
            return lowered[: -len(suffix)]
    return lowered


def _sidecar_candidates(path: Path) -> tuple[Path, Path]:
    """Deterministic sidecar precedence, matching tools/asset_census.py."""

    return (
        path.with_suffix(path.suffix + ".civitai.info"),
        path.with_name(f"{path.stem}.civitai.info"),
    )


_NO_SIDECAR: dict[str, Any] = {
    "sidecar_path": None,
    "sidecar_metadata": {},
    "sidecar_provenance": None,
    "sidecar_error": None,
    "sidecar_fingerprint": None,
}


def _contained(kind: AssetKind, root: Path, path: Path) -> bool:
    """Reference images and auxiliary files must resolve inside their library: a link that leaves it is never indexed.

    Model-weight kinds are deliberately unchanged (their existing scan semantics are not part of this contract).
    """

    if kind not in _IMAGE_KINDS and kind not in _AUXILIARY_KINDS:
        return True
    try:
        return path.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def _sidecar_fingerprint(path: Path) -> dict[str, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _read_sidecar_json(path: Path) -> tuple[dict[str, Any], str | None]:
    try:
        with path.open("rb") as stream:
            raw = stream.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            return {}, "sidecar exceeds read limit"
        text = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
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
        self._cache_state = CacheState.UNLOADED
        #: Accounting of the most recent ``refresh`` (kept even when that refresh was cancelled or failed).
        self.last_refresh = RefreshCounters()

    @property
    def cache_state(self) -> CacheState:
        """Condition of the persisted cache as last loaded; ``UNLOADED`` before any read."""

        return self._cache_state

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
            (AssetKind.OPENPOSE_IMAGE, models / "OpenPose"),
            (AssetKind.AUXILIARY_MODEL, models / "StableNewAux"),
        )

    def observation_roots(self) -> tuple[ObservationRoot, ...]:
        """Roots the header-only observational inventory covers (a superset of ``supported_roots``).

        Text encoders, transformer packages and ``models/embeddings`` are *observation-only*: they are deliberately not
        ``AssetKind`` members, so the hashing ``refresh()`` path never reads them and no second identity set appears.
        """

        if self.webui_root is None:
            return ()
        models = self.webui_root / "models"
        layout = (
            ("checkpoint", models / "Stable-diffusion", "models/Stable-diffusion"),
            ("text_encoder", models / "text_encoder", "models/text_encoder"),
            ("text_encoder", models / "text_encoders", "models/text_encoders"),
            ("transformer", models / "transformer", "models/transformer"),
            ("vae", models / "VAE", "models/VAE"),
            ("lora", models / "Lora", "models/Lora"),
            ("lora", models / "LyCORIS", "models/LyCORIS"),
            ("embedding", self.webui_root / "embeddings", "embeddings"),
            ("embedding", models / "embeddings", "models/embeddings"),
        )
        return tuple(ObservationRoot(kind, path, label) for kind, path, label in layout)

    def verified_sha256(self, path: Path) -> str | None:
        """The cached SHA-256 of one exact file, only while its size/mtime fingerprint still matches; never hashes."""

        self._load()
        cached = self._entries.get(str(path.resolve()))
        try:
            stat = path.stat()
        except OSError:
            return None
        digest = cached.get("sha256") if cached else None
        if (
            cached
            and (cached.get("size"), cached.get("mtime_ns")) == (stat.st_size, stat.st_mtime_ns)
            and isinstance(digest, str)
            and re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            return digest
        return None

    def observe(
        self,
        *,
        limits: ScanLimits | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> ObservationScan:
        """Provisional, header-only inventory of every observation root: no hashing and no cache write.

        Identity stays ``pending`` unless the existing hash cache already holds a fingerprint-validated SHA-256.
        """

        self._loaded = False  # read the persisted cache as it is now, not a stale in-memory copy
        self._load()
        return observe_roots(
            self.observation_roots(),
            limits=limits,
            cancelled=cancelled,
            identity_lookup=lambda path, _size, _mtime: self.verified_sha256(path),
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
        persist: bool = True,
    ) -> RefreshResult:
        """Refresh selected kinds, or only exact served checkpoints (never scan in that mode).

        Every writer reloads under the shared cache lock. A cancelled/failed
        transaction publishes no partial snapshot, including across instances.
        """
        # Hash outside the writer lock: existing LoRA/embedding readers must
        # not wait behind multi-GB checkpoint reads. Only cache commit is locked.
        self._loaded = False
        self._load()
        # An unreadable-for-now cache is not an empty one: stop before paying for hashes that could not be published.
        self._require_readable_cache()
        counters = self.last_refresh = RefreshCounters()
        entries, computed, hits = self._prepare_refresh(
            kinds, checkpoint_paths, cancelled, progress, counters, read_only=not persist,
        )
        selected = set(kinds) if kinds is not None else set(_DEFAULT_REFRESH_KINDS)
        if persist:
            self._commit_entries(
                entries,
                cancelled=cancelled,
                prune_kinds={item.value for item in selected} if checkpoint_paths is None else None,
            )
        else:
            # Browsing uses the same identity/evidence reader without modifying user cache files.
            # This instance's snapshot is a disposable projection, never executable admission.
            if cancelled and cancelled():
                raise InterruptedError("Asset discovery cancelled")
            retained = {
                key: value for key, value in self._entries.items()
                if checkpoint_paths is not None or value.get("kind") not in {item.value for item in selected}
            }
            self._entries = {**retained, **entries}
            self._snapshot = self._make_snapshot()
        return RefreshResult(self._snapshot, computed, hits, counters.snapshot())

    def _require_readable_cache(self) -> None:
        if self._cache_state is CacheState.UNAVAILABLE:
            raise TimeoutError("AssetRegistry cache is temporarily unreadable; retry Preview")

    def _commit_entries(
        self,
        entries: dict[str, dict[str, Any]],
        *,
        cancelled: Callable[[], bool] | None,
        prune_kinds: set[str] | None = None,
    ) -> None:
        """Merge verified entries into the latest persisted cache under the cross-process writer lock."""

        with registry_cache_lock(self.cache_path, cancelled=cancelled):
            self._loaded = False
            self._load()
            self._require_readable_cache()
            if prune_kinds is not None:
                self._entries = {
                    key: value
                    for key, value in self._entries.items()
                    if value.get("kind") not in prune_kinds
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

    def _identity_reason(
        self, cached: dict[str, Any] | None, kind: AssetKind, stat: os.stat_result
    ) -> CheckpointMiss:
        """Whether a cached entry's byte identity still applies to a file with this fingerprint (never hashes)."""

        if not cached:
            return CheckpointMiss.NO_ENTRY
        if cached.get("kind") != kind.value:
            return CheckpointMiss.KIND_CHANGED
        if cached.get("size") != stat.st_size:
            return CheckpointMiss.SIZE_CHANGED
        if cached.get("mtime_ns") != stat.st_mtime_ns:
            return CheckpointMiss.MTIME_CHANGED
        digest = cached.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            return CheckpointMiss.DIGEST_INVALID
        return CheckpointMiss.CURRENT

    def checkpoint_status(self, path: Path) -> CheckpointStatus:
        """Worker-only, read-only explanation of one exact checkpoint's cached evidence.

        Distinguishes the misses that really need a full SHA-256 read (no entry, different size/mtime/kind, invalid
        digest) from those that only need a bounded header or sidecar re-read while the fingerprint-bound digest
        stays valid. No directory traversal, no hashing, no write.
        """

        self._load()
        try:
            stat = path.stat()
        except OSError:
            return CheckpointStatus(CheckpointMiss.FILE_UNAVAILABLE, self._cache_state)
        cached = self._entries.get(str(path.resolve()))
        reason = self._identity_reason(cached, AssetKind.CHECKPOINT, stat)
        if reason is not CheckpointMiss.CURRENT:
            return CheckpointStatus(reason, self._cache_state)
        assert cached is not None
        if not _structure_is_current(cached):
            return CheckpointStatus(CheckpointMiss.STRUCTURE_STALE, self._cache_state)
        for candidate in _sidecar_candidates(path):
            fingerprint = _sidecar_fingerprint(candidate)
            if fingerprint is not None:
                current = (
                    cached.get("sidecar_path") == str(candidate)
                    and cached.get("sidecar_fingerprint") == fingerprint
                )
                return CheckpointStatus(
                    CheckpointMiss.CURRENT if current else CheckpointMiss.SIDECAR_CHANGED,
                    self._cache_state,
                )
        reason = CheckpointMiss.CURRENT if cached.get("sidecar_path") is None else CheckpointMiss.SIDECAR_CHANGED
        return CheckpointStatus(reason, self._cache_state)

    def checkpoint_is_current(self, path: Path) -> bool:
        """Worker-only fingerprint check of one exact path; no directory traversal or hash."""
        return self.checkpoint_status(path).current

    def describe_cache(self) -> CacheDescription:
        """Read-only description of the persisted cache file; independent of (and not changing) in-memory state."""

        state, version, entries = self._read_cache_file()
        checkpoints = [
            item
            for item in entries.values()
            if isinstance(item, dict) and item.get("kind") == AssetKind.CHECKPOINT.value
        ]
        with_digest = sum(
            1
            for item in checkpoints
            if isinstance(item.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
        )
        return CacheDescription(state, version, len(entries), len(checkpoints), with_digest)

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

    def locate_checkpoint(self, model_name: str) -> Path | None:
        """The single local checkpoint file a selected model name identifies, or ``None`` (no match or ambiguous).

        Worker-only and read-only: it lists ``models/Stable-diffusion`` by name (stat only, no hashing, no header read
        and no cache write). A name that matches more than one file is ambiguous and is never resolved by picking one.
        """

        if self.webui_root is None:
            return None
        key = _checkpoint_name_key(model_name)
        root = self.webui_root / "models" / "Stable-diffusion"
        if not key or not root.is_dir():
            return None
        matches = [
            path
            for path in root.rglob("*")
            if path.suffix.lower() in _CHECKPOINT_NAME_SUFFIXES
            and _checkpoint_name_key(path.name) == key
            and path.is_file()
        ]
        return matches[0] if len(matches) == 1 else None

    def inspect_named_checkpoint(self, model_name: str) -> CheckpointInspection | None:
        """Header-only family evidence for the checkpoint a model name identifies (see ``locate_checkpoint``).

        No byte identity is produced or persisted; ``None`` when the file is absent, ambiguous or unreadable.
        """

        path = self.locate_checkpoint(model_name)
        if path is None:
            return None
        try:
            return self.inspect_checkpoint(path)
        except (OSError, ValueError):
            return None

    def _prepare_refresh(
        self,
        kinds: Iterable[AssetKind] | None,
        checkpoint_paths: Iterable[Path] | None,
        cancelled: Callable[[], bool] | None,
        progress: Callable[[Path, int, int], None] | None,
        counters: RefreshCounters,
        *, read_only: bool = False,
    ) -> tuple[dict[str, dict[str, Any]], int, int]:
        selected = set(kinds) if kinds is not None else set(_DEFAULT_REFRESH_KINDS)
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
                            for path in self._refresh_paths(root, read_only, cancelled)
                            if path.is_file()
                            and path.suffix.lower() in _extensions_for(kind)
                            and _contained(kind, root, path)
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
                if path.suffix.lower() not in _extensions_for(kind):
                    raise ValueError("Unsupported checkpoint file type")
                key = str(path.resolve())
                stat = path.stat()
                if kind in _AUXILIARY_KINDS and stat.st_size > AUXILIARY_MAX_BYTES:
                    raise ValueError("Auxiliary asset exceeds the size limit")
                cached = self._entries.get(key)
                if read_only:
                    # Browsing never follows model/sidecar aliases outside the configured library.
                    if not path.resolve().is_relative_to(root.resolve()):
                        raise ValueError("Asset outside local library")
                    if any(not item.resolve().is_relative_to(root.resolve()) for item in _sidecar_candidates(path)):
                        raise ValueError("Sidecar outside local library")
                reason = self._identity_reason(cached, kind, stat)
                model_valid = reason is CheckpointMiss.CURRENT
                # A reference image or auxiliary file has no sidecar contract: never searched for, read or fingerprinted.
                sidecar_fields = (
                    dict(_NO_SIDECAR)
                    if kind in _IMAGE_KINDS or kind in _AUXILIARY_KINDS
                    else _resolve_sidecar(path, cached if model_valid else None)
                )
                sidecar_changed = model_valid and cached is not None and (
                    sidecar_fields["sidecar_path"] != cached.get("sidecar_path")
                    or sidecar_fields["sidecar_fingerprint"] != cached.get("sidecar_fingerprint")
                )
                structure_stale = (
                    kind is AssetKind.CHECKPOINT
                    and model_valid
                    and cached is not None
                    and not _structure_is_current(cached)
                )
                if model_valid:
                    # The digest is reusable; record why (if at all) the evidence needed any refresh.
                    counters.note(
                        CheckpointMiss.STRUCTURE_STALE if structure_stale
                        else CheckpointMiss.SIDECAR_CHANGED if sidecar_changed
                        else CheckpointMiss.CURRENT
                    )
                else:
                    counters.note(reason)
                if sidecar_fields["sidecar_path"] and (not model_valid or sidecar_changed):
                    counters.sidecar_reads += 1
                header_fields = (
                    checkpoint_header_evidence(path)
                    if kind is AssetKind.CHECKPOINT and (not model_valid or structure_stale) else None
                )
                if header_fields is not None:
                    counters.header_reads += 1
                if model_valid and cached is not None:
                    entry = dict(cached)
                    entry.update(sidecar_fields)
                    if header_fields is not None:
                        entry.update(header_fields)
                    next_entries[key] = entry
                    hits += 1
                    counters.hash_cache_hits += 1
                    continue
                digest = hashlib.sha256()
                read_bytes = 0
                started = time.monotonic()
                try:
                    with path.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(_CHUNK), b""):
                            if cancelled and cancelled():
                                raise InterruptedError("Checkpoint evidence refresh cancelled")
                            digest.update(chunk)
                            read_bytes += len(chunk)
                            if progress:
                                progress(path, read_bytes, stat.st_size)
                finally:
                    counters.hash_seconds += time.monotonic() - started
                    counters.bytes_hashed += read_bytes
                if kind in _IMAGE_KINDS:
                    metadata, error = {}, None  # an image carries no model metadata
                elif header_fields is not None:
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
                counters.hashes_computed += 1
        if cancelled and cancelled():
            raise InterruptedError("Checkpoint evidence refresh cancelled")
        return next_entries, computed, hits

    @staticmethod
    def _refresh_paths(root: Path, read_only: bool, cancelled: Callable[[], bool] | None) -> Iterable[Path]:
        if not read_only:
            yield from root.rglob("*")
            return
        # pathlib.rglob suppresses directory errors; that could turn an inaccessible folder into
        # an authoritative empty browser. Fail the projection instead, preserving working choices.
        def failed(error: OSError) -> None:
            raise error
        for directory, folders, files in root.walk(on_error=failed, follow_symlinks=False):
            if cancelled and cancelled():
                raise InterruptedError("Asset discovery cancelled")
            folders[:] = [name for name in folders if not (directory / name).is_junction()]
            yield from (directory / name for name in files)

    def _read_cache_file(self) -> tuple[CacheState, int | None, dict[str, dict[str, Any]]]:
        """Parse the persisted cache without touching in-memory state; says why when it yields nothing.

        A *transient* read error (another process replacing the file, a scanner holding it open) is retried briefly
        rather than being mistaken for an empty cache: an empty cache means every checkpoint is rehashed in full.
        """

        for attempt in range(4):
            try:
                text = self.cache_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                return CacheState.MISSING, None, {}
            except OSError:
                if attempt == 3:
                    return CacheState.UNAVAILABLE, None, {}
                time.sleep(0.05 * (attempt + 1))
                continue
            try:
                data = json.loads(text)
            except (ValueError, TypeError):
                return CacheState.UNREADABLE, None, {}
            if not isinstance(data, dict):
                return CacheState.UNREADABLE, None, {}
            version = data.get("version")
            version = version if isinstance(version, int) and not isinstance(version, bool) else None
            if version not in _SUPPORTED_CACHE_VERSIONS:
                return CacheState.UNSUPPORTED_VERSION, version, {}
            entries = data.get("entries", {})
            if not isinstance(entries, dict):
                return CacheState.UNREADABLE, version, {}
            return CacheState.OK, version, entries
        return CacheState.UNAVAILABLE, None, {}  # pragma: no cover - the loop always returns

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._cache_state, _version, self._entries = self._read_cache_file()
        self._snapshot = self._make_snapshot()

    @staticmethod
    def _retry_os(action: Callable[[], Any]) -> None:
        """Run a file operation, retrying a brief refusal (Windows: the file is momentarily held open)."""

        for attempt in range(5):
            try:
                action()
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))

    def _save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"version": _CACHE_VERSION, "entries": self._entries}, sort_keys=True),
            encoding="utf-8",
        )
        try:
            if self._cache_state in (CacheState.UNREADABLE, CacheState.UNSUPPORTED_VERSION):
                # Never silently destroy a cache this build could not read (a newer schema, or evidence a person may
                # want to inspect). Copy it aside *before* replacing it, so the live path is never absent and a failed
                # copy aborts the save instead of losing the original.
                backup = self.cache_path.with_suffix(".unreadable")
                try:
                    self._retry_os(lambda: shutil.copyfile(self.cache_path, backup))
                except FileNotFoundError:
                    pass
            self._retry_os(lambda: temporary.replace(self.cache_path))
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        self._cache_state = CacheState.OK

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
        if ordered and all(item.kind in _IMAGE_KINDS for item in ordered):
            # A reference image has byte identity only: no family/compatibility evidence is meaningful for it.
            return AssetRecord(digest, ordered, {}, None, None, None, {})
        if ordered and all(item.kind in _AUXILIARY_KINDS for item in ordered):
            # Auxiliary files likewise carry identity only; a filename must never become a checkpoint-family hint.
            return AssetRecord(digest, ordered, {}, None, content[2], None, {})

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
