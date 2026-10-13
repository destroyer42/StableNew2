"""Compact, path-free diagnostics for AssetRegistry's persisted checkpoint evidence (PR-LEARN-COMPARE-145).

Pure value types only: nothing here reads a file, hashes or writes. They answer "why was this checkpoint evidence not
reusable, and what did a refresh actually pay for?" without ever carrying a local path, file name or digest, so the
counters are safe to log, show in a status line or attach to a bug report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CacheState(str, Enum):
    """Condition of the persisted cache file as last loaded."""

    UNLOADED = "unloaded"
    MISSING = "missing"
    OK = "ok"
    #: Present but not parseable JSON / not an object. The content is bad; the file is read fine.
    UNREADABLE = "unreadable"
    #: The file could not be read at all (held open by another process, permissions) even after bounded retries. Its
    #: content is unknown and may be perfectly valid, so it is never treated as empty or replaced.
    UNAVAILABLE = "unavailable"
    #: Parseable, but written by a schema version this build does not read.
    UNSUPPORTED_VERSION = "unsupported_version"


class CheckpointMiss(str, Enum):
    """Why one exact checkpoint's cached evidence is, or is not, directly reusable."""

    CURRENT = "current"
    #: The file cannot be statted, so nothing can be said about its evidence.
    FILE_UNAVAILABLE = "file_unavailable"
    # -- byte identity must be recomputed (a full SHA-256 read) --------------------------------------------------
    NO_ENTRY = "no_entry"
    KIND_CHANGED = "kind_changed"
    SIZE_CHANGED = "size_changed"
    MTIME_CHANGED = "mtime_changed"
    DIGEST_INVALID = "digest_invalid"
    # -- the byte identity is still trustworthy; only a bounded header/sidecar re-read is needed -----------------
    STRUCTURE_STALE = "structure_stale"
    SIDECAR_CHANGED = "sidecar_changed"

    @property
    def needs_hash(self) -> bool:
        return self in _HASH_REASONS

    @property
    def digest_reusable(self) -> bool:
        return self in (CheckpointMiss.CURRENT, CheckpointMiss.STRUCTURE_STALE, CheckpointMiss.SIDECAR_CHANGED)


_HASH_REASONS = frozenset(
    {
        CheckpointMiss.NO_ENTRY,
        CheckpointMiss.KIND_CHANGED,
        CheckpointMiss.SIZE_CHANGED,
        CheckpointMiss.MTIME_CHANGED,
        CheckpointMiss.DIGEST_INVALID,
    }
)


@dataclass(frozen=True, slots=True)
class CheckpointStatus:
    reason: CheckpointMiss
    #: How the cache stood when the status was computed (explains a ``NO_ENTRY`` after a lost cache).
    cache_state: CacheState = CacheState.OK

    @property
    def current(self) -> bool:
        return self.reason is CheckpointMiss.CURRENT

    @property
    def needs_hash(self) -> bool:
        return self.reason.needs_hash

    @property
    def digest_reusable(self) -> bool:
        return self.reason.digest_reusable


@dataclass(slots=True)
class RefreshCounters:
    """What one registry's refreshes cost so far; resettable, never persisted."""

    hashes_computed: int = 0
    hash_cache_hits: int = 0
    header_reads: int = 0
    sidecar_reads: int = 0
    bytes_hashed: int = 0
    hash_seconds: float = 0.0
    #: Count per ``CheckpointMiss`` value for the checkpoints a refresh examined.
    reasons: dict[str, int] = field(default_factory=dict)

    def note(self, reason: CheckpointMiss) -> None:
        self.reasons[reason.value] = self.reasons.get(reason.value, 0) + 1

    def snapshot(self) -> RefreshCounters:
        return RefreshCounters(
            self.hashes_computed, self.hash_cache_hits, self.header_reads, self.sidecar_reads, self.bytes_hashed,
            self.hash_seconds, dict(self.reasons),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "hashes_computed": self.hashes_computed,
            "hash_cache_hits": self.hash_cache_hits,
            "header_reads": self.header_reads,
            "sidecar_reads": self.sidecar_reads,
            "bytes_hashed": self.bytes_hashed,
            "hash_seconds": round(self.hash_seconds, 3),
            "reasons": dict(sorted(self.reasons.items())),
        }


@dataclass(frozen=True, slots=True)
class CacheDescription:
    """Read-only description of the persisted cache file (no paths, digests or file names)."""

    state: CacheState
    version: int | None = None
    entries: int = 0
    checkpoint_entries: int = 0
    checkpoints_with_digest: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "version": self.version,
            "entries": self.entries,
            "checkpoint_entries": self.checkpoint_entries,
            "checkpoints_with_digest": self.checkpoints_with_digest,
        }


__all__ = [
    "CacheDescription",
    "CacheState",
    "CheckpointMiss",
    "CheckpointStatus",
    "RefreshCounters",
]
