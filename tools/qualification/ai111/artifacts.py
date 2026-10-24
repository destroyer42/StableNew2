"""The five authorized PR-AI-111 artifacts: identity checks, verified download, quarantine and staging.

Download-only. Nothing here executes, unpacks, imports, loads or activates an artifact: a staged file is verified by size and
SHA-256, a GGUF is confirmed by reading only its leading metadata (magic, version and three ``general.*`` keys, never a tensor),
and the runtime archive is inspected through its central directory without extracting a byte. Identities come only from the
frozen plan (and are cross-checked against the freeze evidence); the command line cannot name a URL, so an unapproved
substitution is not expressible.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import struct
import zipfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlparse

from tools.qualification.ai111 import plan as plan_module

ALLOWED_HOSTS = frozenset({"huggingface.co", "github.com"})
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MUTABLE = ("/main/", "/master/", "/latest/", "/HEAD/", "refs/heads")
#: ``general.file_type`` values for the quantisations this plan covers (llama.cpp's LLAMA_FTYPE enumeration).
FILE_TYPE = {"Q8_0": 7, "Q4_K_M": 15, "Q5_K_M": 17}
FREE_SPACE_MARGIN = 2 * 1024**3
_CHUNK = 1024 * 1024


class SubstitutionRefused(Exception):
    """The artifact is not exactly the one the plan authorizes; nothing was downloaded."""


@dataclass(frozen=True)
class Artifact:
    key: str
    kind: str  # "runtime" | "model"
    filename: str
    url: str
    bytes: int
    sha256: str
    revision: str  # pinned commit (models) or release tag (runtime)
    publisher: str
    packager: str
    quantization: str | None = None


def authorized_artifacts(plan: dict[str, Any] | None = None) -> list[Artifact]:
    """The exact five artifacts the frozen plan names (runtime first), built from the plan and the committed registry."""

    plan = plan or plan_module.frozen_plan()
    from src.ai_assist.manifests import load_model_registry

    registry = {e.model_id: e for e in load_model_registry(plan_module.REGISTRY_PATH).entries}
    intent = plan["runtime_intent"]
    artifacts = [
        Artifact(
            key="llama.cpp-" + intent["tag"] + "-win-cpu-x64",
            kind="runtime",
            filename=intent["asset"],
            url=intent["source_url"],
            bytes=intent["bytes"],
            sha256=intent["sha256"],
            revision=intent["tag"],
            publisher=intent["repository"],
            packager=intent["repository"],
        )
    ]
    for model in plan["models"]:
        entry = registry[model["model_id"]]
        artifacts.append(
            Artifact(
                key=model["model_id"],
                kind="model",
                filename=model["filename"],
                url=model["source_url"],
                bytes=model["bytes"],
                sha256=model["sha256"],
                revision=entry.provenance.packager_revision,
                publisher=entry.provenance.publisher_repo,
                packager=entry.provenance.packager_repo,
                quantization=model["quantization"],
            )
        )
    return artifacts


def verify_identity(artifact: Artifact) -> None:
    """Raise :class:`SubstitutionRefused` unless this is a pinned, immutable, correctly named artifact."""

    parsed = urlparse(artifact.url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise SubstitutionRefused(f"{artifact.key}: host is not an allowed source")
    if any(token in parsed.path for token in _MUTABLE) or parsed.query:
        raise SubstitutionRefused(f"{artifact.key}: URL names a mutable reference")
    if not _SHA256.match(artifact.sha256) or artifact.bytes <= 0:
        raise SubstitutionRefused(f"{artifact.key}: size or SHA-256 is not pinned")
    if Path(parsed.path).name != artifact.filename:
        raise SubstitutionRefused(
            f"{artifact.key}: URL file name differs from the pinned file name"
        )
    if artifact.kind == "model":
        if (
            not _REVISION.match(artifact.revision)
            or f"/resolve/{artifact.revision}/" not in parsed.path
        ):
            raise SubstitutionRefused(f"{artifact.key}: URL is not pinned to the recorded commit")
        if f"/{artifact.packager}/" not in parsed.path:
            raise SubstitutionRefused(
                f"{artifact.key}: URL is not the recorded packager repository"
            )
        if (
            artifact.quantization not in FILE_TYPE
            or f"-{artifact.quantization}." not in artifact.filename
        ):
            raise SubstitutionRefused(f"{artifact.key}: quantisation does not match the file name")
        if not artifact.filename.endswith(".gguf"):
            raise SubstitutionRefused(f"{artifact.key}: not a GGUF file")
    else:
        expected = f"/ggml-org/llama.cpp/releases/download/{artifact.revision}/{artifact.filename}"
        if parsed.path != expected or "win-cpu-x64" not in artifact.filename:
            raise SubstitutionRefused(
                f"{artifact.key}: not the pinned CPU-only Windows release asset"
            )


def crosscheck_freeze_evidence(artifacts: list[Artifact], freeze_dir: Path) -> None:
    """The five identities must equal what the owner was shown in the freeze evidence (``authorization-request.json``)."""

    request = json.loads((freeze_dir / "authorization-request.json").read_text(encoding="utf-8"))
    listed = {d["url"]: d for d in request["downloads"]}
    if len(listed) != len(artifacts):
        raise SubstitutionRefused("freeze evidence lists a different number of artifacts")
    for artifact in artifacts:
        row = listed.get(artifact.url)
        if row is None or row["bytes"] != artifact.bytes or row["sha256"] != artifact.sha256:
            raise SubstitutionRefused(f"{artifact.key}: differs from the freeze evidence")


# -- GGUF metadata (header only) --------------------------------------------------------------------------------------------

_SCALAR = {
    0: "B",
    1: "b",
    2: "H",
    3: "h",
    4: "I",
    5: "i",
    6: "f",
    7: "?",
    10: "Q",
    11: "q",
    12: "d",
}


def _read(handle: BinaryIO, size: int) -> bytes:
    data = handle.read(size)
    if len(data) != size:
        raise ValueError("truncated GGUF header")
    return data


def _string(handle: BinaryIO) -> str:
    (length,) = struct.unpack("<Q", _read(handle, 8))
    if length > 1 << 20:
        raise ValueError("implausible GGUF string length")
    return _read(handle, length).decode("utf-8", errors="replace")


def _value(handle: BinaryIO, kind: int) -> Any:
    if kind in _SCALAR:
        fmt = "<" + _SCALAR[kind]
        return struct.unpack(fmt, _read(handle, struct.calcsize(fmt)))[0]
    if kind == 8:
        return _string(handle)
    if kind == 9:
        (element,) = struct.unpack("<I", _read(handle, 4))
        (count,) = struct.unpack("<Q", _read(handle, 8))
        if count > 1 << 24:
            raise ValueError("implausible GGUF array length")
        if element in _SCALAR:
            _read(handle, struct.calcsize("<" + _SCALAR[element]) * count)
            return None
        for _ in range(count):
            _value(handle, element)
        return None
    raise ValueError(f"unknown GGUF value type {kind}")


def read_gguf_metadata(path: Path, *, byte_limit: int = 256 * 1024 * 1024) -> dict[str, Any]:
    """``general.architecture``, ``general.name`` and ``general.file_type`` from the leading metadata. No tensor is read."""

    wanted = {"general.architecture", "general.name", "general.file_type"}
    found: dict[str, Any] = {}
    with path.open("rb") as handle:
        if _read(handle, 4) != b"GGUF":
            raise ValueError("not a GGUF file (bad magic)")
        (version,) = struct.unpack("<I", _read(handle, 4))
        if version not in (2, 3):
            raise ValueError(f"unsupported GGUF version {version}")
        tensor_count, kv_count = struct.unpack("<QQ", _read(handle, 16))
        found.update(gguf_version=version, tensor_count=tensor_count, kv_count=kv_count)
        for _ in range(kv_count):
            if handle.tell() > byte_limit:
                raise ValueError("GGUF metadata larger than the inspection limit")
            key = _string(handle)
            (kind,) = struct.unpack("<I", _read(handle, 4))
            value = _value(handle, kind)
            if key in wanted:
                found[key] = value
                if wanted <= found.keys():
                    break
    missing = wanted - found.keys()
    if missing:
        raise ValueError("GGUF metadata lacks " + ", ".join(sorted(missing)))
    return found


def inspect_zip(path: Path) -> dict[str, Any]:
    """Central-directory listing only: nothing is extracted or executed."""

    with zipfile.ZipFile(path) as bundle:
        names = [i.filename for i in bundle.infolist() if not i.is_dir()]
        unsafe = [
            n
            for n in names
            if n.startswith(("/", "\\")) or ".." in Path(n).parts or re.match(r"^[A-Za-z]:", n)
        ]
        suffix = {
            n
            for n in names
            if Path(n).suffix.lower() in {".exe", ".dll", ".bat", ".cmd", ".ps1", ".py"}
        }
        return {
            "members": len(names),
            "unsafe_member_paths": unsafe,
            "loadable_or_script_members": sorted(suffix),
        }


# -- download, verify, quarantine, stage -----------------------------------------------------------------------------------


def sha256_of(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


Fetcher = Callable[[str, Path, int, int], dict[str, Any]]


def http_fetch(url: str, partial: Path, resume_from: int, max_bytes: int) -> dict[str, Any]:
    """Stream ``url`` into ``partial`` (resuming), refusing to write past ``max_bytes``. Returns the final host and status."""

    import requests

    headers = {"Range": f"bytes={resume_from}-"} if resume_from else {}
    with requests.get(
        url, headers=headers, stream=True, timeout=(30, 120), allow_redirects=True
    ) as response:
        if resume_from and response.status_code == 200:
            resume_from = 0  # the server ignored Range: start over rather than append a second copy
        response.raise_for_status()
        mode = "ab" if resume_from else "wb"
        written = resume_from
        with partial.open(mode) as handle:
            for chunk in response.iter_content(_CHUNK):
                written += len(chunk)
                if written > max_bytes:
                    raise ValueError("download exceeded the pinned size")
                handle.write(chunk)
        return {"final_host": urlparse(response.url).hostname, "status": response.status_code}


def _quarantine(path: Path, observed_sha: str) -> Path:
    target = path.with_name(f"{path.name}.quarantined-{observed_sha[:12]}")
    os.replace(path, target)
    return target


def stage(
    artifact: Artifact,
    dest_dir: Path,
    fetch: Fetcher = http_fetch,
    *,
    free_bytes: Callable[[Path], int] | None = None,
) -> dict[str, Any]:
    """Download, verify and stage one artifact. Never raises for a failed download; the record says what happened."""

    record: dict[str, Any] = {
        **{k: v for k, v in asdict(artifact).items() if k != "quantization"},
        "quantization": artifact.quantization,
        "started_utc": datetime.now(UTC).isoformat(),
        "verified": False,
    }
    try:
        verify_identity(artifact)
    except SubstitutionRefused as exc:
        return {**record, "result": "refused", "reason": str(exc)}
    dest_dir.mkdir(parents=True, exist_ok=True)
    final, partial = dest_dir / artifact.filename, dest_dir / (artifact.filename + ".partial")
    for entry in (final, partial):
        if entry.is_symlink() or entry.is_junction():
            return {**record, "result": "refused", "reason": "redirected staging entry"}
        if entry.exists():
            info = entry.lstat()
            if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                return {**record, "result": "refused", "reason": "nonregular staging entry"}
    free_of = free_bytes or (lambda p: shutil.disk_usage(p).free)
    record["free_bytes_before"] = free_of(dest_dir)
    if final.exists():
        sha, size = sha256_of(final)
        if sha == artifact.sha256 and size == artifact.bytes:
            return _finish(record, artifact, final, sha, size, free_of(dest_dir), already=True)
        return {
            **record,
            "result": "refused",
            "reason": "a different file already occupies the staging name; left untouched",
            "path": str(final),
        }
    resume = partial.stat().st_size if partial.exists() else 0
    if free_of(dest_dir) < (artifact.bytes - resume) + FREE_SPACE_MARGIN:
        return {**record, "result": "refused", "reason": "not enough free disk space"}
    try:
        record["transfer"] = fetch(artifact.url, partial, resume, artifact.bytes)
    except Exception as exc:  # noqa: BLE001 - recorded; the partial file is kept for a resume, never staged
        return {
            **record,
            "result": "failed",
            "reason": f"{type(exc).__name__}: {exc}"[:300],
            "partial_bytes": partial.stat().st_size if partial.exists() else 0,
        }
    sha, size = sha256_of(partial)
    if size != artifact.bytes or sha != artifact.sha256:
        quarantined = _quarantine(partial, sha)
        return {
            **record,
            "result": "quarantined",
            "reason": "size or SHA-256 mismatch",
            "observed_sha256": sha,
            "observed_bytes": size,
            "quarantine_path": str(quarantined),
        }
    try:
        record["metadata"] = _inspect(artifact, partial)
    except ValueError as exc:
        quarantined = _quarantine(partial, sha)
        return {
            **record,
            "result": "quarantined",
            "reason": f"content check failed: {exc}",
            "observed_sha256": sha,
            "quarantine_path": str(quarantined),
        }
    os.replace(partial, final)
    return _finish(record, artifact, final, sha, size, free_of(dest_dir), already=False)


def _inspect(artifact: Artifact, path: Path) -> dict[str, Any]:
    if artifact.kind == "runtime":
        info = inspect_zip(path)
        if info["unsafe_member_paths"]:
            raise ValueError("archive contains member paths that escape their directory")
        return info
    meta = read_gguf_metadata(path)
    if not str(meta["general.architecture"]).startswith("qwen"):
        raise ValueError(f"unexpected architecture {meta['general.architecture']!r}")
    if meta["general.file_type"] != FILE_TYPE[artifact.quantization or ""]:
        raise ValueError(
            f"file type {meta['general.file_type']} does not match {artifact.quantization}"
        )
    return meta


def _finish(
    record: dict[str, Any],
    artifact: Artifact,
    path: Path,
    sha: str,
    size: int,
    free_after: int,
    *,
    already: bool,
) -> dict[str, Any]:
    if "metadata" not in record:
        try:
            record["metadata"] = _inspect(artifact, path)
        except ValueError as exc:
            return {
                **record,
                "result": "failed",
                "reason": f"content check failed: {exc}",
                "path": str(path),
            }
    return {
        **record,
        "result": "already_staged" if already else "staged",
        "verified": True,
        "observed_sha256": sha,
        "observed_bytes": size,
        "path": str(path),
        "free_bytes_after": free_after,
        "finished_utc": datetime.now(UTC).isoformat(),
    }


__all__ = [
    "ALLOWED_HOSTS",
    "Artifact",
    "SubstitutionRefused",
    "authorized_artifacts",
    "crosscheck_freeze_evidence",
    "http_fetch",
    "inspect_zip",
    "read_gguf_metadata",
    "sha256_of",
    "stage",
    "verify_identity",
]
