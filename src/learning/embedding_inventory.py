"""Registry-backed embedding identity and compatibility projection for Learning embedding experiments.

Pure over existing ``AssetRegistry`` evidence. The cache-only resolver reads the persisted snapshot and verifies the
cached SHA-256 against the file's size/mtime fingerprint with a ``stat`` only (never a scan, hash or file read), so it
is safe on the Tk thread. Structural SDXL evidence comes only from the accepted header-only safetensors reader
(``src/assets/observation.py``, ``classify_embedding``) inside the explicit, tracked discovery worker. Pickle-based
containers (``.pt``/``.bin``) are never opened or deserialized here, so their compatibility stays *unverified*.
``ModelPolicy`` and the backend keep final admission authority.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from src.learning.embedding_experiment import (
    STATUS_AMBIGUOUS,
    STATUS_COMPATIBLE,
    STATUS_INCOMPATIBLE,
    STATUS_MISSING,
    STATUS_STALE,
    STATUS_UNVERIFIED,
    AssetResolver,
    EmbeddingAsset,
)

#: Container suffixes the pinned Forge Neo embedding loader reads (``backend/text_processing/textual_inversion.py``).
BACKEND_SUFFIXES = frozenset({".safetensors", ".pt", ".bin"})
#: The only suffix whose structure is read without deserializing a pickle.
INSPECTABLE_SUFFIXES = frozenset({".safetensors"})
STRUCTURE_SDXL = "sdxl_clip_l_g"

STATUS_LABELS = {
    STATUS_COMPATIBLE: "Available; SDXL text-encoder structure verified from the safetensors header",
    STATUS_UNVERIFIED: "Compatibility unverified (no safe structural evidence for the target model)",
    STATUS_INCOMPATIBLE: "Incompatible with the target model or backend",
    STATUS_MISSING: "Missing or stale inventory",
    STATUS_AMBIGUOUS: "Ambiguous name (matches more than one local file)",
    STATUS_STALE: "Changed on disk since the last verified inventory",
}


@dataclass(frozen=True)
class EmbeddingResource:
    """What the explicit discovery worker learned about one installed embedding name (path-free)."""

    name: str
    sha256: str = ""
    file_format: str = ""
    locations: int = 1
    structure: str = ""
    suitability: str = ""
    vectors: int | None = None
    error: str = ""
    fingerprint_current: bool = True
    #: In-memory only (never persisted into a snapshot): the exact file the discovery hashed, to detect later change.
    path: str = ""
    size: int = -1
    mtime_ns: int = -1


def asset_from_resource(resource: EmbeddingResource, family: str) -> EmbeddingAsset:
    """Classify one discovered embedding against the target family; filenames never decide compatibility."""
    name, sha, fmt = resource.name, resource.sha256, resource.file_format
    if resource.locations > 1:
        return EmbeddingAsset(
            name,
            STATUS_AMBIGUOUS,
            sha,
            file_format=fmt,
            reason="several files share this invocation name",
        )
    if not resource.fingerprint_current:
        return EmbeddingAsset(
            name, STATUS_STALE, sha, file_format=fmt, reason="size or timestamp changed"
        )
    if fmt not in BACKEND_SUFFIXES:
        return EmbeddingAsset(
            name,
            STATUS_INCOMPATIBLE,
            sha,
            file_format=fmt,
            reason=f"the backend does not load {fmt or 'this'} files as textual inversions",
        )
    if fmt not in INSPECTABLE_SUFFIXES:
        return EmbeddingAsset(
            name,
            STATUS_UNVERIFIED,
            sha,
            file_format=fmt,
            reason="pickle-based container; StableNew does not deserialize it to inspect compatibility",
        )
    if resource.error or not resource.structure:
        return EmbeddingAsset(
            name,
            STATUS_UNVERIFIED,
            sha,
            file_format=fmt,
            reason=resource.error or "tensor layout is not a recognized embedding signature",
        )
    if resource.structure == STRUCTURE_SDXL and resource.suitability == family:
        return EmbeddingAsset(
            name, STATUS_COMPATIBLE, sha, family, resource.structure, fmt, resource.vectors
        )
    detected = resource.suitability if resource.suitability not in ("", "unknown") else ""
    if detected and detected != family:
        return EmbeddingAsset(
            name,
            STATUS_INCOMPATIBLE,
            sha,
            detected,
            resource.structure,
            fmt,
            resource.vectors,
            f"{detected} text-encoder structure",
        )
    return EmbeddingAsset(
        name,
        STATUS_UNVERIFIED,
        sha,
        detected,
        resource.structure,
        fmt,
        resource.vectors,
        "structure does not establish the target family",
    )


def find_embedding_records(snapshot: Any, name: str) -> list[Any]:
    """Registry records with a location whose file stem (the backend's invocation name) equals ``name``."""
    from src.assets import AssetKind

    wanted = str(name or "").strip().casefold()
    return [
        record
        for record in snapshot.records_for(AssetKind.EMBEDDING)
        if any(
            location.kind is AssetKind.EMBEDDING
            and str(location.display_name).strip().casefold() == wanted
            for location in record.locations
        )
    ]


def registry_resolver(family: str, registry: Any | None = None) -> AssetResolver:
    """Cache-only identity resolver over the existing AssetRegistry; refresh is a separate, tracked worker.

    Identity (presence, uniqueness, an unchanged cached SHA-256) is established here; structure is not, so a usable
    answer is never ``compatible``: Preview needs an explicit discovery, Run only re-checks identity.
    """

    def resolve(name: str) -> EmbeddingAsset:
        from src.assets import AssetKind, AssetRegistry

        reg = registry or AssetRegistry()
        if reg.webui_root is None:
            return EmbeddingAsset(name, STATUS_MISSING, reason="no local WebUI root is configured")
        snapshot = reg.cached_snapshot()
        records = find_embedding_records(snapshot, name)
        locations = [
            location
            for record in records
            for location in record.locations
            if location.kind is AssetKind.EMBEDDING
            and str(location.display_name).strip().casefold() == str(name).strip().casefold()
        ]
        if not locations:
            return EmbeddingAsset(name, STATUS_MISSING, reason="not in the local asset registry")
        if len(locations) > 1:
            return EmbeddingAsset(
                name, STATUS_AMBIGUOUS, reason="several files share this invocation name"
            )
        location, record = locations[0], records[0]
        suffix = Path(location.path).suffix.lower()
        fresh = reg.verified_sha256(Path(location.path))
        if fresh is None or fresh != record.sha256:
            return EmbeddingAsset(
                name,
                STATUS_STALE,
                record.sha256,
                file_format=suffix,
                reason="fingerprint no longer matches",
            )
        return EmbeddingAsset(
            name,
            STATUS_UNVERIFIED,
            record.sha256,
            file_format=suffix,
            reason="structure is verified only by an explicit embedding discovery",
        )

    del family
    return resolve


def _still_current(resource: EmbeddingResource) -> bool:
    """A ``stat`` only: the discovered file still has the size and timestamp that were hashed."""
    if not resource.path:
        return resource.fingerprint_current
    try:
        stat = Path(resource.path).stat()
    except OSError:
        return False
    return (stat.st_size, stat.st_mtime_ns) == (resource.size, resource.mtime_ns)


def inventory_resolver(resources: Mapping[str, EmbeddingResource], family: str) -> AssetResolver:
    """Identity from the explicitly refreshed in-memory discovery (no persistence, no scan, no hashing here)."""
    by_key = {name.casefold(): resource for name, resource in resources.items()}

    def resolve(name: str) -> EmbeddingAsset:
        resource = by_key.get(str(name).strip().casefold())
        if resource is None:
            return EmbeddingAsset(
                name,
                STATUS_MISSING,
                reason="not in the last embedding discovery; refresh the installed embeddings",
            )
        return asset_from_resource(
            replace(resource, fingerprint_current=_still_current(resource)), family
        )

    return resolve


@dataclass(frozen=True)
class InventoryRow:
    name: str
    asset: EmbeddingAsset
    fixed: bool
    in_baseline: bool

    @property
    def selectable(self) -> bool:
        return self.asset.usable and not self.fixed

    @property
    def label(self) -> str:
        place = (
            "Fixed embedding (unchanged)"
            if self.fixed
            else "In baseline prompt"
            if self.in_baseline
            else "Installed"
        )
        return f"{place}. {STATUS_LABELS[self.asset.status]}"


def inventory_rows(
    resources: Mapping[str, EmbeddingResource],
    family: str,
    *,
    query: str = "",
    fixed: Iterable[str] = (),
    baseline: Iterable[str] = (),
    visible: Callable[[str], bool] = lambda _name: True,
) -> list[InventoryRow]:
    """Case-insensitively sorted rows for the installed inventory, honoring the content-visibility policy."""
    fixed_keys = {str(name).casefold() for name in fixed}
    baseline_keys = {str(name).casefold() for name in baseline}
    rows = []
    for name, resource in sorted(resources.items(), key=lambda item: item[0].casefold()):
        if query.casefold() not in name.casefold() or not visible(name):
            continue
        rows.append(
            InventoryRow(
                name,
                asset_from_resource(resource, family),
                name.casefold() in fixed_keys,
                name.casefold() in baseline_keys,
            )
        )
    return rows


def discover_embeddings(
    cancelled: Callable[[], bool], registry: Any | None = None
) -> dict[str, EmbeddingResource]:
    """Read-only discovery for the tracked background worker (never call on the Tk thread).

    Refreshes embedding identity without persisting (the user's cache and files stay untouched) and reads only the
    safetensors *header* of each file through the accepted observation reader.
    """
    from src.assets import AssetKind, AssetRegistry
    from src.assets.observation import ScanLimits, inspect_file

    reg = registry or AssetRegistry()
    if reg.webui_root is None or not (reg.webui_root / "embeddings").is_dir():
        raise FileNotFoundError("Local embeddings directory unavailable")
    snapshot = reg.refresh(kinds={AssetKind.EMBEDDING}, persist=False, cancelled=cancelled).snapshot
    grouped: dict[str, list[tuple[Any, Any]]] = {}
    for record in snapshot.records_for(AssetKind.EMBEDDING):
        for location in record.locations:
            if location.kind is AssetKind.EMBEDDING:
                grouped.setdefault(str(location.display_name), []).append((record, location))
    limits = ScanLimits()
    result: dict[str, EmbeddingResource] = {}
    for name, items in grouped.items():
        if cancelled():
            raise InterruptedError("Embedding discovery cancelled")
        record, location = items[0]
        path = Path(location.path)
        suffix = path.suffix.lower()
        structure = suitability = error = ""
        vectors: int | None = None
        if suffix in INSPECTABLE_SUFFIXES:
            observed = inspect_file(path, "embedding", limits)
            evidence = observed.embedding
            if observed.error:
                error = observed.error
            elif evidence is not None and evidence.kind != "unrecognized":
                structure, suitability, vectors = (
                    evidence.kind,
                    evidence.suitability,
                    evidence.vector_count,
                )
        try:
            stat = path.stat()
            size, mtime_ns = stat.st_size, stat.st_mtime_ns
        except OSError:
            size = mtime_ns = -1
        result[name] = EmbeddingResource(
            name,
            record.sha256,
            suffix,
            len(items),
            structure,
            suitability,
            vectors,
            error,
            True,
            str(path),
            size,
            mtime_ns,
        )
    return result
