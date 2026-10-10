"""Tier-1 observational inventory (PR-IMG-MODELS-152): bounded, cancellable, header-only, no hashing.

This is the *provisional observation* tier of the one asset subsystem. It records, per physical file, where it is, how big
it is, what its bounded header/container says and which logical package it belongs to. It is deliberately a different type
from ``AssetRecord``: an ``ObservedFile`` carries **no** SHA-256 unless the existing registry cache already holds a
fingerprint-validated one (``IdentityStatus``), so nothing here can be mistaken for verified byte identity. It never reads a
tensor, hashes, loads a weight, writes the hash cache, opens a pickle, follows a link out of its root or starts a process.

Safety envelope: every directory/file/depth quota is explicit (``ScanLimits``); links and junctions are never descended into
and a file link must resolve inside its root; one physical file is observed once (aliases are recorded); a file whose
fingerprint changes while it is read yields an error, not evidence; cancellation returns a partial, clearly incomplete scan.
Diffusers shard indexes are validated and grouped into logical packages before anything pairs components.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import stat as stat_module
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.assets.adapter_evidence import (
    CLAIM_KEYS,
    EmbeddingEvidence,
    LoraEvidence,
    classify_embedding,
    classify_lora,
)
from src.assets.checkpoint_structure import (
    checkpoint_variant_from_metadata,
    classify_checkpoint_shapes,
    read_tensor_table,
)
from src.assets.component_evidence import ComponentEvidence, classify_tensor_table
from src.assets.gguf import GgufEvidence, inspect_gguf

CONTRACT = "asset_observation/1"
EXTENSIONS = frozenset({".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".bin"})
FORMAT_UNINSPECTED = (
    "FORMAT_UNINSPECTED"  # a pickle-based/unknown container is never deserialized to inventory it
)
_INDEX_SUFFIX = ".safetensors.index.json"
_CONFIG_NAMES = frozenset({"config.json", "generation_config.json", "model_index.json"})
_TOKENIZER_NAMES = frozenset(
    {
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.json",
        "merges.txt",
        "special_tokens_map.json",
    }
)
_CONFIG_KEYS = (
    "_class_name",
    "architectures",
    "model_type",
    "hidden_size",
    "num_hidden_layers",
    "in_channels",
    "joint_attention_dim",
    "num_layers",
    "num_single_layers",
    "num_attention_heads",
    "torch_dtype",
    "vocab_size",
)
_SAFE_SHARD = re.compile(r"^[A-Za-z0-9._\-+ ()]+\.safetensors$")


@dataclass(frozen=True)
class ScanLimits:
    max_files: int = 20_000
    max_dirs: int = 5_000
    max_depth: int = 12
    max_json_bytes: int = 8 * 1024 * 1024
    max_quant_metadata_bytes: int = 1024 * 1024
    max_dir_entries: int = 50_000


@dataclass(frozen=True)
class ObservationRoot:
    kind: str  # an AssetKind value, kept as text so this module stays import-light
    path: Path
    label: str


@dataclass(frozen=True)
class IdentityStatus:
    """``verified`` only when the existing registry cache holds a fingerprint-validated SHA-256; otherwise ``pending``."""

    status: str = "pending"
    sha256: str | None = None


@dataclass(frozen=True)
class HeaderObservation:
    format: str = "unknown"
    tensor_count: int | None = None
    component: ComponentEvidence | None = None
    checkpoint_architecture: str | None = None
    checkpoint_variant: str | None = None
    variant_basis: str | None = None
    claims: Mapping[str, str] = field(default_factory=dict)
    quantization_formats: tuple[str, ...] = ()
    lora: LoraEvidence | None = None
    embedding: EmbeddingEvidence | None = None
    gguf: GgufEvidence | None = None
    error: str | None = None


@dataclass(frozen=True)
class ObservedFile:
    root_label: str
    kind: str
    path: str  # canonical, case-normalized physical path (the dedup key's display form)
    relative: str  # posix path below the root
    size: int
    mtime_ns: int
    suffix: str
    header: HeaderObservation | None = None
    aliases: tuple[str, ...] = ()
    identity: IdentityStatus = field(default_factory=IdentityStatus)
    package_id: str | None = None
    errors: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.relative.rsplit("/", 1)[-1]


@dataclass(frozen=True)
class ObservedPackage:
    package_id: str
    directory: str  # relative to the root label
    root_label: str
    index_file: str | None
    status: str  # complete | incomplete | conflicting | invalid | single_file
    members: tuple[str, ...]  # canonical paths of the member files
    expected_shards: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    extra: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()
    declared_total_size: int | None = None
    observed_total_size: int | None = None
    component: ComponentEvidence | None = None
    config: Mapping[str, Any] = field(default_factory=dict)
    config_association: str = "none"  # validated | single_file_in_directory | none
    license: Mapping[str, str] = field(default_factory=dict)
    tokenizer_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class RootResult:
    label: str
    kind: str
    scanned: bool
    reason: str | None = None
    file_count: int = 0


@dataclass(frozen=True)
class ObservationScan:
    contract: str
    roots: tuple[RootResult, ...]
    files: tuple[ObservedFile, ...]
    packages: tuple[ObservedPackage, ...] = ()
    skipped: tuple[tuple[str, str], ...] = ()  # (relative display, reason)
    unassociated_configs: tuple[
        tuple[str, str, str], ...
    ] = ()  # (root label, relative dir, reason)
    truncated: str | None = None
    cancelled: bool = False
    errors: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        """False after a quota stop or a cancellation: absence in an incomplete scan is never evidence of absence."""

        return not self.cancelled and self.truncated is None


# --------------------------------------------------------------------------------------------------- helpers


def _key(path: str | Path) -> str:
    return os.path.normcase(os.path.realpath(path))


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:  # different drives
        return False


def _is_link(entry: os.DirEntry[str]) -> bool:
    try:
        if entry.is_symlink():
            return True
        junction = getattr(entry, "is_junction", None)
        if callable(junction) and junction():
            return True
        attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
        return bool(attributes & getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    except OSError:
        return True  # unreadable entries are skipped, never followed


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _read_json(path: Path, limit: int) -> tuple[Any, str | None]:
    try:
        if path.stat().st_size > limit:
            return None, "oversized json"
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
        return json.loads(data, object_pairs_hook=_unique_object), None
    except RecursionError:
        return None, "json nesting is too deep"
    except (OSError, ValueError, UnicodeDecodeError):
        return None, "malformed or unreadable json"


# --------------------------------------------------------------------------------------------------- per-file header


def _quantization_formats(metadata: Mapping[str, Any], limit: int) -> tuple[str, ...]:
    raw = metadata.get("_quantization_metadata")
    if not isinstance(raw, str) or len(raw) > limit:
        return ()
    try:
        parsed = json.loads(raw)
        layers = parsed.get("layers", {})
        return tuple(
            sorted(
                {
                    str(item.get("format"))
                    for item in layers.values()
                    if isinstance(item, dict) and item.get("format")
                }
            )
        )
    except (ValueError, AttributeError, RecursionError):
        return ()


def inspect_file(path: Path, kind: str, limits: ScanLimits) -> HeaderObservation:
    """Bounded header/container evidence for one file (never raises; never reads a tensor)."""

    suffix = path.suffix.lower()
    if suffix == ".gguf":
        evidence = inspect_gguf(path)
        return HeaderObservation("gguf", evidence.tensor_count, gguf=evidence, error=evidence.error)
    if suffix != ".safetensors":
        return HeaderObservation(FORMAT_UNINSPECTED)
    try:
        shapes, dtypes, metadata = read_tensor_table(path)
    except (OSError, ValueError, TypeError, UnicodeDecodeError):
        return HeaderObservation(
            "safetensors", error="malformed, truncated or unreadable safetensors header"
        )
    component = classify_tensor_table(shapes, dtypes)
    architecture, _error = classify_checkpoint_shapes(shapes)
    variant, basis = None, None
    if architecture == "sdxl_inpaint":
        variant, basis = "inpaint", "tensor_shape"
    elif architecture == "sdxl_refiner":
        variant, basis = "refiner", "tensor_shape"
    turbo = checkpoint_variant_from_metadata(dict(metadata))
    if turbo and architecture in ("sdxl_base", "unrecognized"):
        variant, basis = turbo, "embedded_metadata"
    claims = {
        key: str(metadata[key])[:80]
        for key in (*CLAIM_KEYS, "model_type", "format")
        if metadata.get(key) not in (None, "")
    }
    lora = embedding = None
    if kind == "lora":
        lora = classify_lora(shapes, dtypes, metadata)
    elif kind == "embedding":
        embedding = classify_embedding(shapes, dtypes)
    return HeaderObservation(
        "safetensors",
        len(shapes),
        component,
        architecture if architecture != "unrecognized" else None,
        variant,
        basis,
        claims,
        _quantization_formats(metadata, limits.max_quant_metadata_bytes),
        lora,
        embedding,
    )


# --------------------------------------------------------------------------------------------------- walking


@dataclass
class _Entry:
    root: ObservationRoot
    path: Path
    relative: str
    real: str
    size: int
    mtime_ns: int
    aliases: list[str] = field(default_factory=list)


def _walk(
    roots: Iterable[ObservationRoot],
    limits: ScanLimits,
    cancelled: Callable[[], bool],
) -> tuple[
    list[RootResult],
    list[_Entry],
    dict[tuple[str, str], dict[str, Path]],
    list[tuple[str, str]],
    str | None,
    bool,
]:
    results: list[RootResult] = []
    entries: dict[str, _Entry] = {}
    dir_files: dict[tuple[str, str], dict[str, Path]] = {}
    skipped: list[tuple[str, str]] = []
    truncated: str | None = None
    was_cancelled = False
    dirs_seen = 0
    for root in roots:
        if not root.path.is_dir():
            results.append(RootResult(root.label, root.kind, False, "root not present"))
            continue
        real_root = _key(root.path)
        count = 0
        stack: list[tuple[Path, int]] = [(root.path, 0)]
        while stack and truncated is None and not was_cancelled:
            current, depth = stack.pop()
            dirs_seen += 1
            if dirs_seen > limits.max_dirs:
                truncated = "max_dirs"
                break
            relative_dir = current.relative_to(root.path).as_posix() if current != root.path else ""
            try:
                with os.scandir(current) as listing:
                    scanned = list(itertools.islice(listing, limits.max_dir_entries + 1))
            except OSError:
                skipped.append((f"{root.label}/{relative_dir}".rstrip("/"), "directory unreadable"))
                continue
            if len(scanned) > limits.max_dir_entries:
                truncated = "max_dir_entries"
                break
            scanned.sort(key=lambda item: item.name.casefold())
            for entry in scanned:
                if cancelled():
                    was_cancelled = True
                    break
                shown = f"{root.label}/{(relative_dir + '/' if relative_dir else '')}{entry.name}"
                try:
                    linked = _is_link(entry)
                    # a symlinked directory is not a "real" directory to ``follow_symlinks=False``; ask again so it is recorded
                    is_dir = entry.is_dir(follow_symlinks=False) or (linked and entry.is_dir())
                    is_file = entry.is_file(follow_symlinks=True)
                except OSError:
                    skipped.append((shown, "entry unreadable"))
                    continue
                if linked and is_dir:
                    skipped.append((shown, "directory link not followed"))
                    continue
                if is_dir:
                    if depth + 1 > limits.max_depth:
                        skipped.append((shown, "max depth reached"))
                        continue
                    stack.append((Path(entry.path), depth + 1))
                    continue
                if not is_file:
                    continue
                lowered = entry.name.lower()
                if (
                    lowered.endswith(".json")
                    or lowered in _TOKENIZER_NAMES
                    or lowered.startswith(("readme", "license"))
                ):
                    dir_files.setdefault((root.label, relative_dir), {})[entry.name] = Path(
                        entry.path
                    )
                    continue
                if os.path.splitext(lowered)[1] not in EXTENSIONS:
                    continue
                real = _key(entry.path)
                if not _inside(real, real_root):
                    skipped.append((shown, "link resolves outside its root"))
                    continue
                try:
                    info = entry.stat()
                except OSError:
                    skipped.append((shown, "file unreadable"))
                    continue
                if real in entries:
                    entries[real].aliases.append(shown)  # one physical file, observed once
                    continue
                if len(entries) >= limits.max_files:
                    truncated = "max_files"
                    break
                count += 1
                entries[real] = _Entry(
                    root,
                    Path(entry.path),
                    f"{(relative_dir + '/' if relative_dir else '')}{entry.name}",
                    real,
                    info.st_size,
                    info.st_mtime_ns,
                )
            if truncated is not None or was_cancelled:
                break
        results.append(RootResult(root.label, root.kind, True, None, count))
    return results, list(entries.values()), dir_files, skipped, truncated, was_cancelled


# --------------------------------------------------------------------------------------------------- packages


def _package_for_index(
    root_label: str,
    directory: str,
    index_path: Path,
    siblings: Mapping[str, Path],
    safetensors_here: Mapping[str, _Entry],
    limits: ScanLimits,
) -> tuple[ObservedPackage, set[str]]:
    package_id = f"{root_label}:{directory}/{index_path.name}".replace(":/", ":")
    problems: list[str] = []
    data, error = _read_json(index_path, limits.max_json_bytes)
    if (
        error
        or not isinstance(data, dict)
        or not isinstance(data.get("weight_map"), dict)
        or not data["weight_map"]
    ):
        return ObservedPackage(
            package_id,
            directory,
            root_label,
            index_path.name,
            "invalid",
            (),
            problems=(error or "index has no weight_map",),
        ), set()
    weight_map: dict[str, Any] = data["weight_map"]
    declared = (
        data.get("metadata", {}).get("total_size")
        if isinstance(data.get("metadata"), dict)
        else None
    )
    expected: set[str] = set()
    for shard in weight_map.values():
        if not isinstance(shard, str) or not _SAFE_SHARD.match(shard) or shard.startswith("."):
            problems.append(
                "a shard reference is not a plain file name inside the package directory"
            )
            continue
        expected.add(shard)
    stem = index_path.name[: -len(".index.json")]
    prefix = stem[: -len(".safetensors")] if stem.endswith(".safetensors") else stem
    present = {name: entry for name, entry in safetensors_here.items() if name in expected}
    missing = sorted(expected - set(present))
    extra = sorted(
        name
        for name in safetensors_here
        if name not in expected
        and name.lower().startswith(prefix.lower())
        and re.search(r"-\d+-of-\d+\.safetensors$", name.lower())
    )
    conflicts: list[str] = []
    merged_shapes: dict[str, list[int]] = {}
    merged_dtypes: dict[str, str] = {}
    observed_total = 0
    tables_ok = True
    for name, entry in sorted(present.items()):
        try:
            shapes, dtypes, _metadata = read_tensor_table(entry.path)
        except (OSError, ValueError, TypeError, UnicodeDecodeError):
            problems.append("a shard header is malformed or unreadable")
            tables_ok = False
            continue
        mapped_here = {tensor for tensor, shard in weight_map.items() if shard == name}
        if mapped_here - set(shapes):
            conflicts.append("the index maps tensors that are absent from their shard")
        if set(shapes) - mapped_here:
            conflicts.append("a shard holds tensors the index does not map to it")
        for tensor, shape in shapes.items():
            if tensor in merged_shapes:
                conflicts.append("a tensor appears in more than one shard")
            merged_shapes[tensor] = shape
            merged_dtypes[tensor] = dtypes[tensor]
        with entry.path.open("rb") as stream:
            header_len = int.from_bytes(stream.read(8), "little")
        observed_total += entry.size - 8 - header_len
    if len(weight_map) != len(set(weight_map)):
        conflicts.append("duplicate tensor keys in the index")
    if extra:
        conflicts.append("extra shard files are present that the index does not reference")
    if (
        declared is not None
        and tables_ok
        and not missing
        and isinstance(declared, int)
        and declared != observed_total
    ):
        conflicts.append("the index's declared total size disagrees with the shard files")
    status = (
        "invalid"
        if problems and not present
        else "conflicting"
        if conflicts or problems
        else "incomplete"
        if missing
        else "complete"
    )
    component = (
        classify_tensor_table(merged_shapes, merged_dtypes) if status == "complete" else None
    )
    config: dict[str, Any] = {}
    association = "none"
    if status == "complete" and "config.json" in siblings and set(safetensors_here) <= expected:
        parsed, cfg_error = _read_json(siblings["config.json"], limits.max_json_bytes)
        if isinstance(parsed, dict) and not cfg_error:
            config = {key: parsed[key] for key in _CONFIG_KEYS if key in parsed}
            association = "validated"
    license_files = (
        {
            name: "present"
            for name in sorted(siblings)
            if name.lower().startswith(("readme", "license"))
        }
        if association == "validated"
        else {}
    )
    members = tuple(
        sorted(
            [entry.real for entry in present.values()]
            + [
                safetensors_here[name].real for name in extra
            ]  # shard-like strays belong to the package, flagged
        )
    )
    package = ObservedPackage(
        package_id,
        directory,
        root_label,
        index_path.name,
        status,
        members,
        tuple(sorted(expected)),
        tuple(missing),
        tuple(extra),
        tuple(dict.fromkeys([*problems, *conflicts])),
        declared if isinstance(declared, int) else None,
        observed_total if tables_ok and not missing else None,
        component,
        config,
        association,
        license_files,
        tokenizer_files=tuple(sorted(name for name in siblings if name in _TOKENIZER_NAMES))
        if association == "validated"
        else (),
    )
    return package, set(present) | set(extra)


# --------------------------------------------------------------------------------------------------- entry point


def observe_roots(
    roots: Iterable[ObservationRoot],
    *,
    limits: ScanLimits | None = None,
    cancelled: Callable[[], bool] | None = None,
    identity_lookup: Callable[[Path, int, int], str | None] | None = None,
) -> ObservationScan:
    """Observe every root once: bounded walk, header evidence, package grouping, provisional identity status."""

    limits = limits or ScanLimits()
    stop = cancelled or (lambda: False)
    root_list = list(roots)
    results, entries, dir_files, skipped, truncated, was_cancelled = _walk(root_list, limits, stop)
    errors: list[str] = []
    by_dir: dict[tuple[str, str], dict[str, _Entry]] = {}
    for entry in entries:
        directory = entry.relative.rsplit("/", 1)[0] if "/" in entry.relative else ""
        by_dir.setdefault((entry.root.label, directory), {})[entry.path.name] = entry

    packages: list[ObservedPackage] = []
    package_of: dict[str, str] = {}
    unassociated: list[tuple[str, str, str]] = []
    for (label, directory), siblings in sorted(dir_files.items()):
        here = by_dir.get((label, directory), {})
        indexes = sorted(name for name in siblings if name.lower().endswith(_INDEX_SUFFIX))
        covered: set[str] = set()
        for index_name in indexes:
            package, members = _package_for_index(
                label, directory, siblings[index_name], siblings, here, limits
            )
            packages.append(package)
            covered |= members
            for member in package.members:
                package_of[member] = package.package_id
        if "config.json" in siblings and not indexes:
            uncovered = list(here)
            if len(uncovered) == 1:
                parsed, cfg_error = _read_json(siblings["config.json"], limits.max_json_bytes)
                if isinstance(parsed, dict) and not cfg_error:
                    single = here[uncovered[0]]
                    packages.append(
                        ObservedPackage(
                            f"{label}:{directory}/{uncovered[0]}".replace(":/", ":"),
                            directory,
                            label,
                            None,
                            "single_file",
                            (single.real,),
                            config={k: parsed[k] for k in _CONFIG_KEYS if k in parsed},
                            config_association="single_file_in_directory",
                        )
                    )
                    package_of[single.real] = packages[-1].package_id
            elif uncovered:
                unassociated.append(
                    (
                        label,
                        directory,
                        "config.json is shared by several model files; no package boundary",
                    )
                )

    observed: list[ObservedFile] = []
    for entry in sorted(entries, key=lambda item: (item.root.label, item.relative.casefold())):
        if stop():
            was_cancelled = True
            break
        header: HeaderObservation | None
        try:
            before = entry.path.stat()
            header = inspect_file(entry.path, entry.root.kind, limits)
            after = entry.path.stat()
        except OSError:
            observed.append(
                ObservedFile(
                    entry.root.label,
                    entry.root.kind,
                    entry.real,
                    entry.relative,
                    entry.size,
                    entry.mtime_ns,
                    entry.path.suffix.lower(),
                    None,
                    tuple(entry.aliases),
                    errors=("file became unreadable during the scan",),
                )
            )
            continue
        errs: list[str] = []
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or (
            before.st_size,
            before.st_mtime_ns,
        ) != (entry.size, entry.mtime_ns):
            # a moving file yields an error, never evidence
            header = None
            errs.append("changed_during_scan")
        identity = IdentityStatus()
        if identity_lookup is not None:
            digest = identity_lookup(entry.path, entry.size, entry.mtime_ns)
            if digest:
                identity = IdentityStatus("verified", digest)
        observed.append(
            ObservedFile(
                entry.root.label,
                entry.root.kind,
                entry.real,
                entry.relative,
                entry.size,
                entry.mtime_ns,
                entry.path.suffix.lower(),
                header,
                tuple(entry.aliases),
                identity,
                package_of.get(entry.real),
                tuple(errs),
            )
        )
    return ObservationScan(
        CONTRACT,
        tuple(results),
        tuple(observed),
        tuple(packages),
        tuple(skipped),
        tuple(unassociated),
        truncated,
        was_cancelled,
        tuple(errors),
    )


__all__ = [
    "CONTRACT",
    "EXTENSIONS",
    "FORMAT_UNINSPECTED",
    "HeaderObservation",
    "IdentityStatus",
    "ObservationRoot",
    "ObservationScan",
    "ObservedFile",
    "ObservedPackage",
    "RootResult",
    "ScanLimits",
    "inspect_file",
    "observe_roots",
]
