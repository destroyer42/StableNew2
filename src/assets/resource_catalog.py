"""Checked-in, versioned catalog of curated model resources (PR-ASSET-130).

The catalog is acquisition *guidance*: where an operator can obtain vetted files, which bytes to expect and what else a
resource needs. It is not a runtime, model-policy or identity authority: ``AssetRegistry`` owns byte identity and product
code owns what can be used. Nothing here reads a file other than the catalog JSON, contacts a hub or imports a model.

A ``sha256`` is present only where an upstream digest was independently verified for a pinned revision. ``None`` means
``pending_verification`` and an installed copy can then never be reported as verified.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CATALOG_CONTRACT = "curated_asset_catalog/1"
DEFAULT_CATALOG_PATH = Path(__file__).resolve().parents[2] / "config" / "curated_asset_catalog.json"
MAX_CATALOG_BYTES = 1024 * 1024

#: Where a resource's files are expected, by catalog placement root.
ROOT_CONTROLNET = "controlnet"
ROOT_AUXILIARY = "auxiliary"
ROOT_EXTENSIONS: dict[str, frozenset[str]] = {
    ROOT_CONTROLNET: frozenset({".safetensors"}),
    ROOT_AUXILIARY: frozenset({".json", ".onnx", ".safetensors", ".txt"}),
}
ROOT_LABELS: dict[str, str] = {
    ROOT_CONTROLNET: "models/ControlNet",
    ROOT_AUXILIARY: "models/StableNewAux",
}
POLICIES = frozenset({"supported_now", "needs_integration", "unsupported"})

_SHA256 = re.compile(r"[0-9a-f]{64}")
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+\- ()]*")
_ID = re.compile(r"[a-z0-9][a-z0-9\-]*")


class CatalogError(ValueError):
    """The catalog is malformed; it is refused as a whole rather than partly trusted."""


@dataclass(frozen=True)
class FileVariant:
    variant_id: str
    upstream_path: str
    suggested_filename: str
    sha256: str | None
    size_bytes: int | None
    hash_status: str
    hash_basis: str | None


@dataclass(frozen=True)
class ResourceFile:
    role: str
    required: bool
    description: str
    variants: tuple[FileVariant, ...]

    @property
    def pinned_digests(self) -> frozenset[str]:
        return frozenset(item.sha256 for item in self.variants if item.sha256)

    @property
    def has_unpinned_variant(self) -> bool:
        return any(item.sha256 is None for item in self.variants)


@dataclass(frozen=True)
class Capability:
    id: str
    policy: str
    modality: str | None
    reason_codes: tuple[str, ...]
    basis: str


@dataclass(frozen=True)
class Prerequisite:
    id: str
    kind: str
    state: str
    description: str


@dataclass(frozen=True)
class CatalogResource:
    id: str
    title: str
    category: str
    capability: Capability
    source: dict[str, Any]
    placement_root: str
    placement_directory: str
    placement_instructions: str
    files: tuple[ResourceFile, ...]
    external_prerequisites: tuple[Prerequisite, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class Catalog:
    contract: str
    version: str
    description: str
    hash_semantics: str
    resources: tuple[CatalogResource, ...]

    def pinned_digests(self, root: str) -> frozenset[str]:
        return frozenset(
            digest
            for resource in self.resources
            if resource.placement_root == root
            for spec in resource.files
            for digest in spec.pinned_digests
        )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CatalogError(message)


def _text(raw: Any, field: str) -> str:
    _require(
        isinstance(raw, str) and bool(raw.strip()),
        f"catalog field {field!r} must be non-empty text",
    )
    return str(raw)


def _variant(raw: Any, root: str) -> FileVariant:
    _require(isinstance(raw, dict), "catalog variant must be an object")
    name = _text(raw.get("suggested_filename"), "suggested_filename")
    _require(
        _SAFE_NAME.fullmatch(name) is not None and ".." not in name,
        f"unsafe suggested filename {name!r}",
    )
    _require(
        Path(name).suffix.lower() in ROOT_EXTENSIONS[root],
        f"suggested filename {name!r} has an extension the {root} root does not accept",
    )
    digest = raw.get("sha256")
    _require(
        digest is None or (isinstance(digest, str) and _SHA256.fullmatch(digest) is not None),
        "sha256 must be 64 lowercase hex digits or null",
    )
    size = raw.get("size_bytes")
    _require(
        size is None or (isinstance(size, int) and not isinstance(size, bool) and size > 0),
        "bad size_bytes",
    )
    status = raw.get("hash_status")
    _require(
        status == ("verified_upstream" if digest else "pending_verification"),
        "hash_status must be verified_upstream exactly when a sha256 is present",
    )
    return FileVariant(
        _text(raw.get("variant_id"), "variant_id"),
        _text(raw.get("upstream_path"), "upstream_path"),
        name,
        digest,
        size,
        status,
        raw.get("hash_basis") if digest else None,
    )


def _resource(raw: Any) -> CatalogResource:
    _require(isinstance(raw, dict), "catalog resource must be an object")
    rid = _text(raw.get("id"), "id")
    _require(_ID.fullmatch(rid) is not None, f"unsafe resource id {rid!r}")
    placement = raw.get("placement")
    _require(isinstance(placement, dict), f"{rid}: placement missing")
    root = placement.get("root")
    _require(root in ROOT_EXTENSIONS, f"{rid}: unknown placement root {root!r}")
    directory = placement.get("directory", "")
    _require(
        isinstance(directory, str) and (directory == "" or _ID.fullmatch(directory) is not None),
        f"{rid}: unsafe placement directory",
    )
    _require(
        (root == ROOT_AUXILIARY) == bool(directory), f"{rid}: auxiliary resources need a directory"
    )
    capability = raw.get("capability")
    _require(isinstance(capability, dict), f"{rid}: capability missing")
    policy = capability.get("policy")
    _require(policy in POLICIES, f"{rid}: unknown capability policy {policy!r}")
    source = raw.get("source")
    _require(isinstance(source, dict), f"{rid}: source missing")
    url = _text(source.get("url"), "source.url")
    _require(
        url.startswith("https://huggingface.co/"),
        f"{rid}: acquisition links must be official Hub pages",
    )
    _require(
        source.get("revision_status") in {"pinned", "pending_verification"}
        and (source.get("revision_status") != "pinned" or bool(source.get("revision"))),
        f"{rid}: revision_status/revision disagree",
    )
    files = []
    for entry in raw.get("files", []):
        _require(isinstance(entry, dict), f"{rid}: file entry must be an object")
        variants = tuple(_variant(item, root) for item in entry.get("variants", []))
        _require(bool(variants), f"{rid}: file entry without variants")
        files.append(
            ResourceFile(
                _text(entry.get("role"), "role"),
                bool(entry.get("required")),
                _text(entry.get("description"), "description"),
                variants,
            )
        )
    _require(bool(files), f"{rid}: a resource needs at least one file")
    _require(len({item.role for item in files}) == len(files), f"{rid}: duplicate file role")
    _require(any(item.required for item in files), f"{rid}: no required file")
    prerequisites = tuple(
        Prerequisite(
            _text(item.get("id"), "prerequisite id"),
            _text(item.get("kind"), "prerequisite kind"),
            _text(item.get("state"), "prerequisite state"),
            _text(item.get("description"), "prerequisite description"),
        )
        for item in raw.get("external_prerequisites", [])
    )
    return CatalogResource(
        rid,
        _text(raw.get("title"), "title"),
        _text(raw.get("category"), "category"),
        Capability(
            _text(capability.get("id"), "capability id"),
            str(policy),
            capability.get("modality"),
            tuple(str(code) for code in capability.get("reason_codes", [])),
            _text(capability.get("basis"), "capability basis"),
        ),
        dict(source),
        str(root),
        directory,
        _text(placement.get("instructions"), "placement instructions"),
        tuple(files),
        prerequisites,
        tuple(str(note) for note in raw.get("notes", [])),
    )


def parse_catalog(raw: Any) -> Catalog:
    """Validate a decoded catalog document; raises ``CatalogError`` for anything unsafe or inconsistent."""

    _require(
        isinstance(raw, dict) and raw.get("contract") == CATALOG_CONTRACT,
        "unsupported catalog contract",
    )
    resources = tuple(_resource(item) for item in raw.get("resources", []))
    _require(bool(resources), "catalog has no resources")
    _require(len({item.id for item in resources}) == len(resources), "duplicate resource id")
    return Catalog(
        CATALOG_CONTRACT,
        _text(raw.get("catalog_version"), "catalog_version"),
        _text(raw.get("description"), "description"),
        _text(raw.get("hash_semantics"), "hash_semantics"),
        resources,
    )


def load_catalog(path: Path | None = None) -> Catalog:
    """Load the checked-in catalog (or an explicit file); a bounded read of one JSON document, nothing else."""

    target = path or DEFAULT_CATALOG_PATH
    try:
        with target.open("rb") as stream:
            data = stream.read(MAX_CATALOG_BYTES + 1)
        _require(len(data) <= MAX_CATALOG_BYTES, "catalog exceeds the size limit")
        return parse_catalog(json.loads(data.decode("utf-8")))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        if isinstance(exc, CatalogError):
            raise
        raise CatalogError(f"catalog unreadable: {type(exc).__name__}") from exc
