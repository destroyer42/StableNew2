"""Pinned runtime manifest, provenance-gated model registry, local import and integrity verification.

Everything here works on files the operator already has: nothing is downloaded, no dependency is resolved, and no model
or binary is run. A runtime build or a model is usable only if it appears in the committed manifest with complete
provenance and its bytes hash to the pinned SHA-256 (owner decisions D4 and D6). An unknown or mismatched hash is refused;
there is no operator-pinned "unqualified" override.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from src.ai_assist.contracts import OutcomeCode
from src.ai_assist.paths import active_pointer_path, model_dir, runtime_dir
from src.utils.atomic_io import atomic_write_json

MANIFEST_SCHEMA_VERSION = 1
POINTER_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,199}$")
_ACTIVE_CONTENT_SUFFIXES = frozenset(
    {".exe", ".dll", ".bat", ".cmd", ".ps1", ".py", ".sh", ".so", ".dylib"}
)
#: Upper bounds that keep a hostile or damaged archive from filling the disk.
_MAX_ARCHIVE_MEMBERS = 2000
_MAX_EXTRACTED_BYTES = 6 * 1024**3
_CHUNK = 1024 * 1024


class ImportRefused(Exception):
    """A local import was refused. ``code`` is a stable string; nothing was installed."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class RuntimeBuild:
    build_id: str
    upstream_repository: str
    upstream_tag: str
    asset_name: str
    asset_sha256: str
    asset_bytes: int
    license_spdx: str
    executable: str
    #: Every loadable file of the build (relative POSIX path -> SHA-256). The archive may hold nothing executable beyond it.
    files: Mapping[str, str]
    qualified: bool = False


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where the bytes came from. Recorded for the operator; the application never contacts any of it."""

    publisher_repo: str
    publisher_revision: str
    packager_repo: str
    packager_revision: str
    converter: str
    source_url: str


@dataclass(frozen=True, slots=True)
class ModelEntry:
    model_id: str
    display_name: str
    license_spdx: str
    architecture: str
    quantization: str
    filename: str
    bytes: int
    sha256: str
    provenance: Provenance
    max_context: int = 8192
    capabilities: tuple[str, ...] = ()
    #: ``False`` = a registered candidate that may only be used by the qualification harness; ``True`` = qualified.
    qualified: bool = False


@dataclass(frozen=True, slots=True)
class RuntimeManifest:
    builds: tuple[RuntimeBuild, ...] = ()
    problems: tuple[str, ...] = ()

    def find(self, build_id: str) -> RuntimeBuild | None:
        return next((b for b in self.builds if b.build_id == build_id), None)


@dataclass(frozen=True, slots=True)
class ModelRegistry:
    entries: tuple[ModelEntry, ...] = ()
    problems: tuple[str, ...] = ()

    def find_by_sha(self, sha256: str) -> ModelEntry | None:
        return next((e for e in self.entries if e.sha256 == sha256), None)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _safe_relative(path: str) -> bool:
    if not path or "\\" in path or path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        return False
    parts = PurePosixPath(path).parts
    return bool(parts) and all(part not in ("", ".", "..") for part in parts)


def _parse_build(raw: Any) -> RuntimeBuild:
    if not isinstance(raw, dict):
        raise ValueError("build is not an object")
    build_id = _text(raw.get("build_id"))
    if not _SAFE_ID.match(build_id):
        raise ValueError("build_id is missing or unsafe")
    sha = _text(raw.get("asset_sha256"))
    if not _SHA256.match(sha):
        raise ValueError(f"{build_id}: asset_sha256 is not a lowercase SHA-256")
    size = raw.get("asset_bytes")
    if type(size) is not int or size <= 0:
        raise ValueError(f"{build_id}: asset_bytes must be a positive integer")
    for key in ("upstream_repository", "upstream_tag", "asset_name", "license_spdx", "executable"):
        if not _text(raw.get(key)):
            raise ValueError(f"{build_id}: {key} is required")
    files_raw = raw.get("files")
    if not isinstance(files_raw, dict) or not files_raw:
        raise ValueError(f"{build_id}: files must list every loadable file")
    files: dict[str, str] = {}
    for rel, digest in files_raw.items():
        if not _safe_relative(rel) or not isinstance(digest, str) or not _SHA256.match(digest):
            raise ValueError(f"{build_id}: invalid file entry {rel!r}")
        files[rel] = digest
    executable = _text(raw["executable"])
    if executable not in files:
        raise ValueError(f"{build_id}: executable is not among the pinned files")
    return RuntimeBuild(
        build_id=build_id,
        upstream_repository=_text(raw["upstream_repository"]),
        upstream_tag=_text(raw["upstream_tag"]),
        asset_name=_text(raw["asset_name"]),
        asset_sha256=sha,
        asset_bytes=size,
        license_spdx=_text(raw["license_spdx"]),
        executable=executable,
        files=files,
        qualified=raw.get("qualified") is True,
    )


def _parse_provenance(raw: Any, label: str) -> Provenance:
    if not isinstance(raw, dict):
        raise ValueError(f"{label}: provenance is required")
    values = {
        key: _text(raw.get(key))
        for key in (
            "publisher_repo",
            "publisher_revision",
            "packager_repo",
            "packager_revision",
            "converter",
            "source_url",
        )
    }
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise ValueError(f"{label}: provenance is incomplete ({', '.join(missing)})")
    if not values["source_url"].startswith("https://"):
        raise ValueError(f"{label}: provenance source_url must be an https URL")
    return Provenance(**values)


def _parse_model(raw: Any) -> ModelEntry:
    if not isinstance(raw, dict):
        raise ValueError("model entry is not an object")
    model_id = _text(raw.get("model_id"))
    if not _SAFE_ID.match(model_id):
        raise ValueError("model_id is missing or unsafe")
    sha = _text(raw.get("sha256"))
    if not _SHA256.match(sha):
        raise ValueError(f"{model_id}: sha256 is not a lowercase SHA-256")
    size = raw.get("bytes")
    if type(size) is not int or size <= 0:
        raise ValueError(f"{model_id}: bytes must be a positive integer")
    filename = _text(raw.get("filename"))
    if not _SAFE_FILENAME.match(filename) or not filename.lower().endswith(".gguf"):
        raise ValueError(f"{model_id}: filename must be a plain .gguf name")
    for key in ("display_name", "license_spdx", "architecture", "quantization"):
        if not _text(raw.get(key)):
            raise ValueError(f"{model_id}: {key} is required")
    context = raw.get("max_context", 8192)
    if type(context) is not int or not 512 <= context <= 262144:
        raise ValueError(f"{model_id}: max_context is out of range")
    capabilities = raw.get("capabilities", [])
    if not isinstance(capabilities, list) or not all(isinstance(c, str) for c in capabilities):
        raise ValueError(f"{model_id}: capabilities must be a list of names")
    return ModelEntry(
        model_id=model_id,
        display_name=_text(raw["display_name"]),
        license_spdx=_text(raw["license_spdx"]),
        architecture=_text(raw["architecture"]),
        quantization=_text(raw["quantization"]),
        filename=filename,
        bytes=size,
        sha256=sha,
        provenance=_parse_provenance(raw.get("provenance"), model_id),
        max_context=context,
        capabilities=tuple(capabilities),
        qualified=raw.get("qualified") is True,
    )


def _load_document(source: str | Path) -> Any:
    text = Path(source).read_text(encoding="utf-8") if isinstance(source, Path) else source
    return json.loads(text)


def load_runtime_manifest(source: str | Path) -> RuntimeManifest:
    """Parse the pinned-runtime manifest. An invalid build is dropped and reported, never half-used."""

    try:
        document = _load_document(source)
    except (OSError, ValueError) as exc:
        return RuntimeManifest(problems=(f"manifest unreadable: {type(exc).__name__}",))
    if not isinstance(document, dict) or document.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        return RuntimeManifest(problems=("manifest schema_version is unsupported",))
    builds: list[RuntimeBuild] = []
    problems: list[str] = []
    for raw in document.get("builds", []):
        try:
            builds.append(_parse_build(raw))
        except ValueError as exc:
            problems.append(str(exc))
    return RuntimeManifest(tuple(builds), tuple(problems))


def load_model_registry(source: str | Path) -> ModelRegistry:
    """Parse the model registry. An entry without complete provenance is dropped and reported, never used."""

    try:
        document = _load_document(source)
    except (OSError, ValueError) as exc:
        return ModelRegistry(problems=(f"registry unreadable: {type(exc).__name__}",))
    if not isinstance(document, dict) or document.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        return ModelRegistry(problems=("registry schema_version is unsupported",))
    entries: list[ModelEntry] = []
    problems: list[str] = []
    for raw in document.get("models", []):
        try:
            entries.append(_parse_model(raw))
        except ValueError as exc:
            problems.append(str(exc))
    return ModelRegistry(tuple(entries), tuple(problems))


def hash_file(path: Path) -> tuple[str, int]:
    """Stream the file once: ``(sha256, size)``."""

    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _stat_snapshot(path: Path) -> dict[str, int]:
    info = path.stat()
    return {"size": info.st_size, "mtime_ns": info.st_mtime_ns}


def import_model(source: Path, entry: ModelEntry, root: Path) -> Path:
    """Copy an operator-chosen local file into the content-addressed model directory after proving it is ``entry``."""

    if not source.is_file():
        raise ImportRefused("source_missing")
    sha, size = hash_file(source)
    if size != entry.bytes:
        raise ImportRefused("size_mismatch")
    if sha != entry.sha256:
        raise ImportRefused("hash_mismatch")
    target_dir = model_dir(root, entry.sha256)
    target = target_dir / entry.filename
    if target.exists():
        raise ImportRefused("already_installed")
    target_dir.mkdir(parents=True, exist_ok=True)
    partial = target_dir / f".{entry.filename}.{uuid.uuid4().hex}.partial"
    try:
        shutil.copyfile(source, partial)
        copied_sha, copied_size = hash_file(partial)
        if copied_sha != entry.sha256 or copied_size != entry.bytes:
            raise ImportRefused("copy_verification_failed")
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def _check_member(info: zipfile.ZipInfo, total: int) -> str:
    name = info.filename
    if info.is_dir():
        return ""
    if not _safe_relative(name):
        raise ImportRefused("unsafe_archive_path")
    if (info.external_attr >> 16) & 0o170000 == 0o120000:
        raise ImportRefused("archive_symlink")
    if total + info.file_size > _MAX_EXTRACTED_BYTES:
        raise ImportRefused("archive_too_large")
    return name


def import_runtime(archive: Path, build: RuntimeBuild, root: Path) -> Path:
    """Verify an operator-chosen local zip against ``build`` and unpack it into the content-addressed runtime directory.

    The archive hash is checked before anything is read from it, every member path is confined to the target, and the
    unpacked tree may hold no loadable or scriptable file that the manifest does not list and hash.
    """

    if not archive.is_file():
        raise ImportRefused("source_missing")
    sha, size = hash_file(archive)
    if size != build.asset_bytes:
        raise ImportRefused("size_mismatch")
    if sha != build.asset_sha256:
        raise ImportRefused("hash_mismatch")
    final = runtime_dir(root, build.build_id)
    if final.exists():
        raise ImportRefused("already_installed")
    staging = final.parent / f".{build.build_id}.{uuid.uuid4().hex}.staging"
    try:
        staging.mkdir(parents=True)
        try:
            with zipfile.ZipFile(archive) as bundle:
                members = bundle.infolist()
                if len(members) > _MAX_ARCHIVE_MEMBERS:
                    raise ImportRefused("archive_too_many_members")
                total = 0
                for info in members:
                    name = _check_member(info, total)
                    if not name:
                        continue
                    total += info.file_size
                    target = (staging / name).resolve()
                    if not target.is_relative_to(staging.resolve()):
                        raise ImportRefused("unsafe_archive_path")
                    if (
                        PurePosixPath(name).suffix.lower() in _ACTIVE_CONTENT_SUFFIXES
                        and name not in build.files
                    ):
                        raise ImportRefused("unlisted_executable_content", name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(info) as source, target.open("wb") as sink:
                        shutil.copyfileobj(source, sink, _CHUNK)
        except zipfile.BadZipFile as exc:
            raise ImportRefused("archive_unreadable") from exc
        for rel, expected in build.files.items():
            candidate = staging / rel
            if not candidate.is_file():
                raise ImportRefused("pinned_file_missing", rel)
            if hash_file(candidate)[0] != expected:
                raise ImportRefused("pinned_file_hash_mismatch", rel)
        os.replace(staging, final)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return final


def record_active(root: Path, build: RuntimeBuild, entry: ModelEntry) -> Path:
    """Atomically point the installation at one runtime build and one model, with a stat snapshot for fast re-checks."""

    runtime_root = runtime_dir(root, build.build_id)
    model_path = model_dir(root, entry.sha256) / entry.filename
    payload = {
        "schema_version": POINTER_SCHEMA_VERSION,
        "runtime_build_id": build.build_id,
        "model_sha256": entry.sha256,
        "recorded_utc": datetime.now(UTC).isoformat(),
        "runtime_files": {rel: _stat_snapshot(runtime_root / rel) for rel in sorted(build.files)},
        "model": _stat_snapshot(model_path),
    }
    return atomic_write_json(active_pointer_path(root), payload, indent=2, sort_keys=True)


@dataclass(frozen=True, slots=True)
class Verification:
    """Result of verifying the active installation. Spawning anything requires ``ok``."""

    code: OutcomeCode | None
    reason: str = ""
    build: RuntimeBuild | None = None
    entry: ModelEntry | None = None
    executable: Path | None = None
    model_path: Path | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.code is None


def _refused(code: OutcomeCode, reason: str) -> Verification:
    return Verification(code=code, reason=reason)


def read_pointer(root: Path) -> dict[str, Any] | None:
    path = active_pointer_path(root)
    if not path.is_file():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema_version") != POINTER_SCHEMA_VERSION:
        raise ValueError("unsupported pointer")
    return document


def verify_installation(
    root: Path,
    runtime: RuntimeManifest,
    registry: ModelRegistry,
    *,
    deep: bool = False,
    allow_candidate: bool = False,
) -> Verification:
    """Fail-closed identity check of the active runtime and model.

    The default check compares sizes and modification times with the snapshot taken at import. ``deep`` re-hashes every
    pinned file. A model that is registered but not yet qualified is accepted only with ``allow_candidate`` (the
    qualification harness); production use needs a qualified entry.
    """

    try:
        pointer = read_pointer(root)
    except (OSError, ValueError):
        return _refused(OutcomeCode.INTEGRITY_FAILED, "pointer_invalid")
    if pointer is None:
        return _refused(OutcomeCode.NOT_INSTALLED, "no_active_pointer")
    build = runtime.find(str(pointer.get("runtime_build_id", "")))
    if build is None:
        return _refused(OutcomeCode.INTEGRITY_FAILED, "unknown_runtime_build")
    entry = registry.find_by_sha(str(pointer.get("model_sha256", "")))
    if entry is None:
        return _refused(OutcomeCode.INTEGRITY_FAILED, "unknown_model_hash")
    if not entry.qualified and not allow_candidate:
        return _refused(OutcomeCode.NOT_INSTALLED, "model_not_qualified")
    if not build.qualified and not allow_candidate:
        return _refused(OutcomeCode.NOT_INSTALLED, "runtime_not_qualified")

    runtime_root = runtime_dir(root, build.build_id)
    snapshot = pointer.get("runtime_files")
    if not isinstance(snapshot, dict):
        return _refused(OutcomeCode.INTEGRITY_FAILED, "pointer_invalid")
    for rel, expected in sorted(build.files.items()):
        path = runtime_root / rel
        recorded = snapshot.get(rel)
        try:
            current = _stat_snapshot(path)
        except OSError:
            return _refused(OutcomeCode.INTEGRITY_FAILED, f"runtime_file_missing:{rel}")
        if recorded != current:
            return _refused(OutcomeCode.INTEGRITY_FAILED, f"runtime_file_changed:{rel}")
        if deep and hash_file(path)[0] != expected:
            return _refused(OutcomeCode.INTEGRITY_FAILED, f"runtime_file_hash:{rel}")

    model_path = model_dir(root, entry.sha256) / entry.filename
    try:
        current = _stat_snapshot(model_path)
    except OSError:
        return _refused(OutcomeCode.INTEGRITY_FAILED, "model_file_missing")
    if current["size"] != entry.bytes or pointer.get("model") != current:
        return _refused(OutcomeCode.INTEGRITY_FAILED, "model_file_changed")
    if deep and hash_file(model_path)[0] != entry.sha256:
        return _refused(OutcomeCode.INTEGRITY_FAILED, "model_hash")

    return Verification(
        code=None,
        build=build,
        entry=entry,
        executable=runtime_root / build.executable,
        model_path=model_path,
    )


__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "ImportRefused",
    "ModelEntry",
    "ModelRegistry",
    "Provenance",
    "RuntimeBuild",
    "RuntimeManifest",
    "Verification",
    "hash_file",
    "import_model",
    "import_runtime",
    "load_model_registry",
    "load_runtime_manifest",
    "read_pointer",
    "record_active",
    "verify_installation",
]
