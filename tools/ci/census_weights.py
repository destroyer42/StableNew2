"""Timing-informed, deterministic weighted partition of the census test files (PR-DEVEX-CENSUS-150).

The census is split into whole test files. This module is the one place that decides which shard a file belongs to:

* every active file gets an integer **weight in milliseconds**: its recorded duration from the committed timing manifest
  (``tools/ci/census_timings.json``) plus a small constant per-file overhead (collection and import cost that JUnit test
  durations do not include); a file the manifest has never seen (a new test file) gets the median recorded duration, so
  it is spread like a typical file instead of being ignored or piled up;
* files are assigned by **longest-processing-time-first**: sorted by ``(-weight, path)``, each goes to the currently
  lightest shard, ties to the lowest index. Integer arithmetic only, so the result is bit-identical on Linux and Windows
  and across processes, and it is a pure function of ``(active files, timing manifest, shard count)``. Any shard count
  >= 1 works; nothing here knows about "three".

The timing manifest is data, not authority: a missing, stale or incomplete manifest only makes the balance worse, never
the census incomplete (completeness is checked separately and fail-closed by ``census_shards.partition_problems`` and
``verify``). A *corrupt* manifest (wrong schema, a value that is not a plain non-negative integer, a digest that does
not match its content) is an error, not a silent fallback, so a hand edit or truncation cannot quietly change the plan.
The ``digest`` is an integrity check against accidental drift, not a security boundary; refresh the file with
``census_shards.py refresh-timings`` instead of editing it. Standard library only.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 1
UNIT = "milliseconds"
TIMINGS_RELATIVE_PATH = "tools/ci/census_timings.json"
#: Collection/import cost per file that JUnit test durations omit. Measured on the hosted census: shard pytest wall
#: minus summed test seconds was 0.06-0.08 s per file.
FILE_OVERHEAD_MS = 60
#: Upper bound on one recorded file duration (24 h): anything larger is a corrupt record, not a slow test.
MAX_FILE_MS = 86_400_000
_MANIFEST_KEYS = frozenset({"schema", "unit", "source", "files", "digest"})


class TimingsError(ValueError):
    """The timing manifest exists but is not a valid, intact manifest (fail closed)."""


@dataclass(frozen=True)
class Timings:
    """A validated timing manifest: repo-relative POSIX path -> recorded milliseconds."""

    files: Mapping[str, int]
    digest: str
    source: str


def normalize_path(path: str | Path) -> str:
    """Repo-relative POSIX form so Windows and Linux hash and compare the same string."""

    text = str(path).replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def canonical_digest(files: Mapping[str, int]) -> str:
    """sha256 over the canonical content (schema, unit, sorted files); the ``source`` note is not content."""

    payload = {
        "schema": SCHEMA_VERSION,
        "unit": UNIT,
        "files": {k: files[k] for k in sorted(files)},
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_manifest(files_ms: Mapping[str, int], source: str) -> dict[str, object]:
    """The serializable manifest for ``files_ms`` (validated, sorted, digested)."""

    cleaned = {normalize_path(k): v for k, v in files_ms.items()}
    if len(cleaned) != len(files_ms):
        raise TimingsError("two timing keys normalize to the same path")
    _validate_files(cleaned)
    return {
        "schema": SCHEMA_VERSION,
        "unit": UNIT,
        "source": str(source),
        "files": {k: cleaned[k] for k in sorted(cleaned)},
        "digest": canonical_digest(cleaned),
    }


def _validate_files(files: Mapping[object, object]) -> None:
    for key, value in files.items():
        if (
            not isinstance(key, str)
            or not key.endswith(".py")
            or normalize_path(key) != key
            or key.startswith("/")
        ):
            raise TimingsError(f"timing key {key!r} is not a repo-relative POSIX test path")
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_FILE_MS:
            raise TimingsError(
                f"timing for {key} is not an integer in 0..{MAX_FILE_MS} ms: {value!r}"
            )


def parse_manifest(data: object) -> Timings:
    """Validate a decoded manifest and return it; raises ``TimingsError`` on any deviation."""

    if not isinstance(data, dict):
        raise TimingsError("timing manifest is not a JSON object")
    if set(data) != _MANIFEST_KEYS:
        raise TimingsError(
            f"timing manifest keys are {sorted(data)}, expected {sorted(_MANIFEST_KEYS)}"
        )
    if data["schema"] != SCHEMA_VERSION or data["unit"] != UNIT:
        raise TimingsError(
            f"unsupported timing manifest schema/unit: {data['schema']!r}/{data['unit']!r}"
        )
    if not isinstance(data["source"], str):
        raise TimingsError("timing manifest source is not a string")
    files = data["files"]
    if not isinstance(files, dict):
        raise TimingsError("timing manifest files is not an object")
    _validate_files(files)
    digest = canonical_digest(files)
    if data["digest"] != digest:
        raise TimingsError(
            "timing manifest digest does not match its content (edited by hand? run refresh-timings)"
        )
    return Timings(files=dict(files), digest=digest, source=data["source"])


def load_timings(path: Path) -> Timings | None:
    """The validated manifest at ``path``; ``None`` only when the file does not exist (uniform weights then).

    An unreadable, non-JSON or invalid file raises ``TimingsError``: absence degrades balance, corruption fails closed.
    """

    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TimingsError(f"timing manifest {path} is unreadable: {exc}") from exc
    return parse_manifest(data)


@dataclass(frozen=True)
class WeightReport:
    """The weight of every active file plus how well the manifest covered them."""

    weights: Mapping[str, int]
    unmeasured: tuple[str, ...]  # active files the manifest has no record of (they get the median)
    stale: tuple[str, ...]  # manifest records for files that are no longer active (ignored)
    default_ms: int  # the duration assumed for an unmeasured file


def _median(values: Sequence[int]) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) // 2


def weigh(active: Iterable[str], timings: Timings | None) -> WeightReport:
    """Integer millisecond weight per active file (recorded or median duration, plus the per-file overhead)."""

    files = sorted({normalize_path(f) for f in active})
    recorded = dict(timings.files) if timings is not None else {}
    if not recorded:
        return WeightReport(
            dict.fromkeys(files, FILE_OVERHEAD_MS),
            tuple(files) if timings is not None else (),
            (),
            0,
        )
    default_ms = _median(list(recorded.values()))
    weights = {f: recorded.get(f, default_ms) + FILE_OVERHEAD_MS for f in files}
    unmeasured = tuple(f for f in files if f not in recorded)
    stale = tuple(sorted(set(recorded) - set(files)))
    return WeightReport(weights, unmeasured, stale, default_ms)


def weighted_partition(
    files: Iterable[str], shard_count: int, timings: Timings | None = None
) -> list[list[str]]:
    """Longest-processing-time-first partition into ``shard_count`` shards of whole files (each shard sorted)."""

    if shard_count < 1:
        raise ValueError("shard_count must be >= 1")
    ordered = sorted({normalize_path(f) for f in files})
    weights = weigh(ordered, timings).weights
    loads = [0] * shard_count
    shards: list[list[str]] = [[] for _ in range(shard_count)]
    for path in sorted(ordered, key=lambda p: (-weights[p], p)):
        target = min(range(shard_count), key=lambda k: (loads[k], k))
        shards[target].append(path)
        loads[target] += weights[path]
    return [sorted(shard) for shard in shards]


def shard_loads(shards: Sequence[Sequence[str]], weights: Mapping[str, int]) -> list[int]:
    """Predicted milliseconds per shard under ``weights``."""

    return [
        sum(weights.get(normalize_path(f), FILE_OVERHEAD_MS) for f in shard) for shard in shards
    ]


def plan_digest(shards: Sequence[Sequence[str]]) -> str:
    """sha256 over the exact ordered assignment, recorded in every shard manifest and re-derived by ``verify``."""

    canonical = [[normalize_path(f) for f in shard] for shard in shards]
    return hashlib.sha256(json.dumps(canonical, separators=(",", ":")).encode("utf-8")).hexdigest()
