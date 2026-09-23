"""Offline census of local A1111-style model files.

This operator tool is intentionally separate from StableNew's live WebUI resource
projection.  It never imports GPU libraries, loads model weights, calls a network,
or changes an A1111 installation.  Its input roots are explicit so an operator can
record the exact machine-local discovery policy that was examined.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HASH_CHUNK_SIZE = 1024 * 1024
MAX_SAFETENSORS_HEADER_BYTES = 64 * 1024 * 1024
MODEL_EXTENSIONS = frozenset({".bin", ".ckpt", ".gguf", ".onnx", ".pt", ".pth", ".safetensors"})
SHA256_RE = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class AssetRoot:
    """One explicitly supplied discovery root and its operator-defined kind."""

    kind: str
    path: Path


class HashCache:
    """File fingerprint to SHA-256 cache, safe to invalidate after a file changes."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.entries: dict[str, dict[str, Any]] = {}
        if path and path.exists():
            try:
                parsed = json.loads(path.read_text(encoding="utf-8"))
                self.entries = dict(parsed.get("entries") or {})
            except (OSError, ValueError, TypeError):
                self.entries = {}

    def sha256(self, file_path: Path) -> str:
        stat = file_path.stat()
        key = str(file_path.resolve())
        previous = self.entries.get(key)
        if (
            previous
            and previous.get("size") == stat.st_size
            and previous.get("mtime_ns") == stat.st_mtime_ns
        ):
            value = previous.get("sha256")
            if isinstance(value, str) and len(value) == 64:
                return value

        digest = hashlib.sha256()
        with file_path.open("rb") as source:
            for chunk in iter(lambda: source.read(HASH_CHUNK_SIZE), b""):
                digest.update(chunk)
        value = digest.hexdigest()
        self.entries[key] = {"mtime_ns": stat.st_mtime_ns, "sha256": value, "size": stat.st_size}
        return value

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"entries": {key: self.entries[key] for key in sorted(self.entries)}}
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_root(value: str) -> AssetRoot:
    """Parse ``KIND=PATH`` without treating drive-letter colons specially."""
    kind, separator, raw_path = value.partition("=")
    if not separator or not kind.strip() or not raw_path.strip():
        raise argparse.ArgumentTypeError("roots must use KIND=PATH")
    return AssetRoot(kind=kind.strip().lower(), path=Path(raw_path.strip()))


def _safe_json_file(path: Path) -> tuple[Any | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def read_safetensors_metadata(path: Path) -> tuple[dict[str, Any], str | None]:
    """Read only the safetensors header; no tensors or ML libraries are loaded."""
    try:
        with path.open("rb") as source:
            prefix = source.read(8)
            if len(prefix) != 8:
                return {}, "truncated safetensors header length"
            header_length = struct.unpack("<Q", prefix)[0]
            if header_length > MAX_SAFETENSORS_HEADER_BYTES:
                return {}, f"safetensors header exceeds {MAX_SAFETENSORS_HEADER_BYTES} bytes"
            header = source.read(header_length)
        if len(header) != header_length:
            return {}, "truncated safetensors header"
        parsed = json.loads(header.decode("utf-8"))
        if not isinstance(parsed, dict):
            return {}, "safetensors header is not an object"
        metadata = parsed.get("__metadata__", {})
        return (metadata if isinstance(metadata, dict) else {}), None
    except (OSError, UnicodeDecodeError, ValueError, struct.error) as exc:
        return {}, f"{type(exc).__name__}: {exc}"


def _read_sidecar_metadata(path: Path) -> tuple[dict[str, Any], str | None]:
    candidates = (
        path.with_suffix(path.suffix + ".civitai.info"),
        path.with_name(f"{path.stem}.civitai.info"),
    )
    for candidate in candidates:
        if candidate.exists():
            data, error = _safe_json_file(candidate)
            return (data if isinstance(data, dict) else {}), error
    return {}, None


def _first_string(mapping: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def infer_family(metadata: dict[str, Any], filename: str) -> dict[str, Any]:
    """Return a conservative technical-family hint with factual provenance."""
    values = " ".join(str(value) for value in metadata.values()).lower()
    filename_value = filename.lower()
    family_needles = (
        ("sdxl", "SDXL"),
        ("sd 1", "SD 1.x"),
        ("sd1", "SD 1.x"),
        ("flux", "Flux"),
        ("sd3", "SD3"),
    )
    for needle, family in family_needles:
        if needle in values:
            return {"confidence": "metadata", "family": family, "provenance": "embedded_metadata"}
    if "xl" in filename_value:
        return {"confidence": "filename_hint", "family": "SDXL", "provenance": "filename"}
    return {"confidence": "unknown", "family": None, "provenance": None}


def _cache_record_format(data: Any) -> str:
    if isinstance(data, list):
        return "legacy_keyword_list"
    if isinstance(data, dict):
        return "rich_object"
    return "unrecognized"


def _hash_from_filename(path: Path) -> str | None:
    value = path.stem.lower()
    if len(value) == 64 and set(value) <= SHA256_RE:
        return value
    return None


def load_lora_keyword_enrichment(cache_roots: Iterable[Path]) -> dict[str, list[dict[str, Any]]]:
    """Read extension caches as optional evidence, preserving cache format/provenance."""
    records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    supplied_roots = sorted(
        (Path(root) for root in cache_roots), key=lambda item: str(item).lower()
    )
    for supplied_root in supplied_roots:
        candidates = [supplied_root]
        if supplied_root.name not in {"known", "metadata_cache"}:
            candidates = [supplied_root / "metadata_cache", supplied_root / "known"]
        for directory in candidates:
            if not directory.is_dir():
                continue
            for cache_file in sorted(directory.rglob("*.json"), key=lambda item: str(item).lower()):
                digest = _hash_from_filename(cache_file)
                if not digest:
                    continue
                data, error = _safe_json_file(cache_file)
                record: dict[str, Any] = {
                    "cache_format": _cache_record_format(data),
                    "cache_path": str(cache_file),
                    "metadata": data,
                    "provenance": "lora-keywords-finder cache",
                }
                if error:
                    record["error"] = error
                records[digest].append(record)
    return {digest: records[digest] for digest in sorted(records)}


def _asset_record(
    file_path: Path,
    root: AssetRoot,
    cache: HashCache,
    keyword_enrichment: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    stat = file_path.stat()
    embedded_metadata: dict[str, Any] = {}
    metadata_error: str | None = None
    if file_path.suffix.lower() == ".safetensors":
        embedded_metadata, metadata_error = read_safetensors_metadata(file_path)
    sidecar_metadata, sidecar_error = _read_sidecar_metadata(file_path)
    digest = cache.sha256(file_path)
    record: dict[str, Any] = {
        "active_or_available": True,
        "asset_kind": root.kind,
        "byte_size": stat.st_size,
        "discovery_root": str(root.path),
        "display_name": file_path.stem,
        "embedded_metadata": embedded_metadata,
        "extension": file_path.suffix.lower(),
        "inferred_technical_family": infer_family(embedded_metadata, file_path.name),
        "local_path": str(file_path),
        "modified_utc": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        "sha256": digest,
        "sidecar_metadata": sidecar_metadata,
        "source_provenance": [
            source
            for source, present in (
                ("safetensors_header", bool(embedded_metadata)),
                ("civitai_sidecar", bool(sidecar_metadata)),
            )
            if present
        ],
    }
    if metadata_error:
        record["embedded_metadata_error"] = metadata_error
    if sidecar_error:
        record["sidecar_metadata_error"] = sidecar_error
    if root.kind in {"lora", "lycoris"}:
        record["lora_keyword_enrichment"] = keyword_enrichment.get(digest, [])
        record["lora_metadata"] = {
            "base_model": _first_string(
                embedded_metadata, "ss_base_model_version", "modelspec.architecture"
            ),
            "creator": _first_string(sidecar_metadata, "creator", "username"),
            "model_id": sidecar_metadata.get("modelId") or sidecar_metadata.get("model_id"),
            "model_name": _first_string(sidecar_metadata, "modelName", "name"),
            "source_url": _first_string(sidecar_metadata, "modelUrl", "url"),
            "trained_words": sidecar_metadata.get("trainedWords")
            or sidecar_metadata.get("trained_words"),
            "version_id": sidecar_metadata.get("id") or sidecar_metadata.get("version_id"),
        }
    return record


def census(
    roots: Iterable[AssetRoot],
    *,
    cache_roots: Iterable[Path] = (),
    hash_cache: HashCache | None = None,
) -> dict[str, Any]:
    """Census recognized model files under explicit roots in deterministic order."""
    selected_roots = sorted(roots, key=lambda root: (root.kind, str(root.path).lower()))
    hashing = hash_cache or HashCache(None)
    enrichment = load_lora_keyword_enrichment(cache_roots)
    assets: list[dict[str, Any]] = []
    root_status: list[dict[str, Any]] = []
    for root in selected_roots:
        if not root.path.is_dir():
            root_status.append(
                {"asset_kind": root.kind, "path": str(root.path), "status": "missing"}
            )
            continue
        root_status.append({"asset_kind": root.kind, "path": str(root.path), "status": "scanned"})
        files = sorted(
            (
                path
                for path in root.path.rglob("*")
                if path.is_file() and path.suffix.lower() in MODEL_EXTENSIONS
            ),
            key=lambda path: str(path).lower(),
        )
        for file_path in files:
            assets.append(_asset_record(file_path, root, hashing, enrichment))

    assets.sort(key=lambda item: (item["asset_kind"], item["local_path"].lower()))
    by_hash: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for asset in assets:
        by_hash[asset["sha256"]].append(asset)
        by_name[asset["display_name"].casefold()].append(asset)
    duplicates = [
        {"sha256": digest, "assets": by_hash[digest]}
        for digest in sorted(by_hash)
        if len(by_hash[digest]) > 1
    ]
    same_name_conflicts = [
        {"display_name": by_name[key][0]["display_name"], "assets": by_name[key]}
        for key in sorted(by_name)
        if len({asset["sha256"] for asset in by_name[key]}) > 1
    ]
    counts: dict[str, int] = defaultdict(int)
    for asset in assets:
        counts[asset["asset_kind"]] += 1
    return {
        "asset_count_by_kind": {kind: counts[kind] for kind in sorted(counts)},
        "assets": assets,
        "duplicate_sha256_groups": duplicates,
        "lora_keyword_cache_hashes": sorted(enrichment),
        "root_status": root_status,
        "same_name_different_hash_groups": same_name_conflicts,
        "schema_version": 1,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline A1111-compatible model-file census")
    parser.add_argument(
        "--root", action="append", required=True, type=parse_root, help="KIND=PATH (repeatable)"
    )
    parser.add_argument(
        "--lora-keyword-cache-root",
        action="append",
        default=[],
        type=Path,
        help="lora-keywords-finder extension or cache root (repeatable)",
    )
    parser.add_argument(
        "--out", required=True, type=Path, help="machine-local JSON inventory output"
    )
    parser.add_argument("--hash-cache", type=Path, help="optional machine-local hash cache JSON")
    args = parser.parse_args(argv)
    cache_path = args.hash_cache or args.out.with_name(f"{args.out.stem}.hash-cache.json")
    hash_cache = HashCache(cache_path)
    result = census(args.root, cache_roots=args.lora_keyword_cache_root, hash_cache=hash_cache)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    hash_cache.save()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
