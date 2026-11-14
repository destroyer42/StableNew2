"""The visual candidate record and its fail-closed admission check (PR-AI-VL-220, decision D22).

``config/ai_visual_candidates.json`` is read only here (and by the harness CLI and tests beside it). It is not the text model
registry: nothing in ``src/`` reads it, so a visual candidate can never be selected, activated, enabled for Preview or
imported by the production AI Assist path.

:func:`load_candidates` is strict (any unknown key, floating revision, non-https or non-pinned URL, malformed digest or a flag
that claims qualification, production use, text use or an approved image invocation refuses the whole document).
:func:`check_admission` answers one question for the evaluation harness: may these staged bytes and this runtime build be used
for the offline evaluation, and if not, why. It is fail-closed: any problem, including an unexpected exception, is a refusal
with a stable reason code. Nothing here executes a binary, loads a model or opens a network connection.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.ai_assist.manifests import RuntimeManifest, load_runtime_manifest
from tools.qualification.vl220.gguf_header import GgufHeader, GgufHeaderError, read_header

REPO_ROOT = Path(__file__).resolve().parents[3]
CANDIDATES_PATH = REPO_ROOT / "config" / "ai_visual_candidates.json"
RUNTIME_MANIFEST_PATH = REPO_ROOT / "config" / "managed_ai_runtime.json"

#: The owner-set ceiling for what the operator may download for one candidate (model and projector together).
MAX_DOWNLOAD_BYTES = 6 * 1024**3

REASON_CANCELLED = "cancelled"
REASON_MODEL_MISSING = "model_missing"
REASON_MODEL_SIZE = "model_size_mismatch"
REASON_MODEL_HASH = "model_hash_mismatch"
REASON_MODEL_HEADER = "model_header_mismatch"
REASON_PROJECTOR_MISSING = "projector_missing"
REASON_PROJECTOR_SIZE = "projector_size_mismatch"
REASON_PROJECTOR_HASH = "projector_hash_mismatch"
REASON_PROJECTOR_HEADER = "projector_header_mismatch"
REASON_PAIR_MISMATCH = "projector_does_not_match_model"
REASON_RUNTIME_UNSUPPORTED = "runtime_unsupported"
REASON_RUNTIME_UNKNOWN = "runtime_build_not_pinned"
REASON_LICENSE_MISSING = "license_acknowledgement_missing"
REASON_LICENSE_MISMATCH = "license_acknowledgement_mismatch"
REASON_CANDIDATE_INVALID = "candidate_invalid"
REASON_INTERNAL = "admission_error"

_HEX40 = re.compile(r"[0-9a-f]{40}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[a-z0-9][a-z0-9._-]{2,63}")
_REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.gguf")
_FORBIDDEN_TRUE_FLAGS = (
    "qualified",
    "production_eligible",
    "text_registry_eligible",
    "image_invocation_approved",
)
#: Keys that would make the text registry or selector treat a record as a text model; never allowed here.
_TEXT_REGISTRY_KEYS = (
    "capabilities",
    "compatible_builds",
    "max_context",
    "model_id",
    "license_spdx",
)

CancelCheck = Callable[[], bool]


class CandidateInvalid(ValueError):
    """The candidate document is not acceptable as written."""


@dataclass(frozen=True, slots=True)
class StagedFile:
    repository: str
    revision: str
    filename: str
    bytes: int
    sha256: str
    source_url: str
    architecture: str
    gguf_file_type: int


@dataclass(frozen=True, slots=True)
class ModelFile(StagedFile):
    quantization: str
    embedding_length: int
    native_context_tokens: int


@dataclass(frozen=True, slots=True)
class ProjectorFile(StagedFile):
    projector_type: str
    precision: str
    projection_dim: int


@dataclass(frozen=True, slots=True)
class LicenseRecord:
    spdx: str
    name: str
    text_bytes: int
    text_sha256: str
    text_source_url: str


@dataclass(frozen=True, slots=True)
class RuntimeRequirement:
    required_build_id: str
    unsupported_build_ids: tuple[str, ...]
    tool: str


@dataclass(frozen=True, slots=True)
class VisualCandidate:
    candidate_id: str
    display_name: str
    modality: str
    license: LicenseRecord
    publisher_repository: str
    publisher_revision: str
    model: ModelFile
    projector: ProjectorFile
    runtime: RuntimeRequirement

    @property
    def download_bytes(self) -> int:
        return self.model.bytes + self.projector.bytes


@dataclass(frozen=True, slots=True)
class Admission:
    ok: bool
    reasons: tuple[str, ...]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CandidateInvalid(message)


def _mapping(value: Any, label: str, allowed: frozenset[str]) -> Mapping[str, Any]:
    _require(isinstance(value, dict), f"{label} must be an object")
    unknown = set(value) - allowed
    _require(not unknown, f"{label} has unknown keys: {sorted(unknown)}")
    return value  # type: ignore[no-any-return]


def _text(value: Any, label: str, pattern: re.Pattern[str] | None = None) -> str:
    _require(isinstance(value, str) and bool(value.strip()), f"{label} must be a non-empty string")
    if pattern is not None:
        _require(pattern.fullmatch(value) is not None, f"{label} is malformed")
    return str(value)


def _count(value: Any, label: str) -> int:
    _require(
        isinstance(value, int) and not isinstance(value, bool) and value > 0,
        f"{label} must be a positive integer",
    )
    return int(value)


def _pinned_url(repository: str, revision: str, filename: str, url: str, label: str) -> None:
    expected = f"https://huggingface.co/{repository}/resolve/{revision}/{filename}"
    _require(url == expected, f"{label} source_url must be the revision-pinned resolve URL")


def _staged_common(raw: Mapping[str, Any], label: str) -> tuple[str, str, str, int, str, str]:
    repository = _text(raw.get("repository"), f"{label}.repository", _REPOSITORY)
    revision = _text(raw.get("revision"), f"{label}.revision", _HEX40)
    filename = _text(raw.get("filename"), f"{label}.filename", _FILENAME)
    size = _count(raw.get("bytes"), f"{label}.bytes")
    digest = _text(raw.get("sha256"), f"{label}.sha256", _HEX64)
    url = _text(raw.get("source_url"), f"{label}.source_url")
    _pinned_url(repository, revision, filename, url, label)
    return repository, revision, filename, size, digest, url


_MODEL_KEYS = frozenset(
    {
        "repository", "revision", "filename", "bytes", "sha256", "source_url", "architecture", "quantization",
        "gguf_file_type", "embedding_length", "native_context_tokens",
    }
)  # fmt: skip
_PROJECTOR_KEYS = frozenset(
    {
        "repository", "revision", "filename", "bytes", "sha256", "source_url", "architecture", "projector_type",
        "precision", "gguf_file_type", "projection_dim", "selection_basis",
    }
)  # fmt: skip


def _parse_model(raw: Any) -> ModelFile:
    data = _mapping(raw, "model", _MODEL_KEYS)
    repository, revision, filename, size, digest, url = _staged_common(data, "model")
    _require(not filename.lower().startswith("mmproj"), "model.filename must not be a projector")
    return ModelFile(
        repository, revision, filename, size, digest, url,
        _text(data.get("architecture"), "model.architecture"),
        _count(data.get("gguf_file_type"), "model.gguf_file_type"),
        _text(data.get("quantization"), "model.quantization"),
        _count(data.get("embedding_length"), "model.embedding_length"),
        _count(data.get("native_context_tokens"), "model.native_context_tokens"),
    )  # fmt: skip


def _parse_projector(raw: Any) -> ProjectorFile:
    data = _mapping(raw, "projector", _PROJECTOR_KEYS)
    repository, revision, filename, size, digest, url = _staged_common(data, "projector")
    _require(filename.startswith("mmproj"), "projector.filename must be an mmproj file")
    return ProjectorFile(
        repository, revision, filename, size, digest, url,
        _text(data.get("architecture"), "projector.architecture"),
        _count(data.get("gguf_file_type"), "projector.gguf_file_type"),
        _text(data.get("projector_type"), "projector.projector_type"),
        _text(data.get("precision"), "projector.precision"),
        _count(data.get("projection_dim"), "projector.projection_dim"),
    )  # fmt: skip


def _parse_license(raw: Any) -> LicenseRecord:
    data = _mapping(
        raw,
        "license",
        frozenset(
            {
                "spdx",
                "name",
                "text_bytes",
                "text_sha256",
                "text_source_url",
                "acknowledgement_required",
            }
        ),
    )
    _require(
        data.get("acknowledgement_required") is True,
        "license.acknowledgement_required must be true",
    )
    url = _text(data.get("text_source_url"), "license.text_source_url")
    _require(
        re.fullmatch(r"https://huggingface\.co/[^/]+/[^/]+/resolve/[0-9a-f]{40}/LICENSE", url)
        is not None,
        "license.text_source_url must be a revision-pinned LICENSE URL",
    )
    return LicenseRecord(
        _text(data.get("spdx"), "license.spdx"),
        _text(data.get("name"), "license.name"),
        _count(data.get("text_bytes"), "license.text_bytes"),
        _text(data.get("text_sha256"), "license.text_sha256", _HEX64),
        url,
    )


def _parse_runtime(raw: Any) -> RuntimeRequirement:
    data = _mapping(
        raw, "runtime", frozenset({"required_build_id", "unsupported_build_ids", "tool", "basis"})
    )
    unsupported: Any = data.get("unsupported_build_ids")
    if not isinstance(unsupported, list):
        raise CandidateInvalid("runtime.unsupported_build_ids must be a list")
    builds = tuple(_text(item, "runtime.unsupported_build_ids[]") for item in unsupported)
    required = _text(data.get("required_build_id"), "runtime.required_build_id")
    _require(required not in builds, "the required build cannot also be unsupported")
    return RuntimeRequirement(required, builds, _text(data.get("tool"), "runtime.tool"))


_CANDIDATE_KEYS = frozenset(
    {
        "candidate_id", "display_name", "modality", "license", "publisher", "converter", "model", "projector",
        "alternate_projectors", "runtime", "known_limits", *_FORBIDDEN_TRUE_FLAGS,
    }
)  # fmt: skip


def _parse_candidate(raw: Any) -> VisualCandidate:
    for key in _TEXT_REGISTRY_KEYS:
        _require(
            not (isinstance(raw, dict) and key in raw),
            f"{key} would make this a text registry entry",
        )
    data = _mapping(raw, "candidate", _CANDIDATE_KEYS)
    for flag in _FORBIDDEN_TRUE_FLAGS:
        _require(data.get(flag) is False, f"{flag} must be present and false for a candidate")
    _require(data.get("modality") == "vision_language", "modality must be vision_language")
    publisher = _mapping(data.get("publisher"), "publisher", frozenset({"repository", "revision"}))
    model = _parse_model(data.get("model"))
    projector = _parse_projector(data.get("projector"))
    _require(
        model.repository == projector.repository and model.revision == projector.revision,
        "model and projector must come from the same repository revision",
    )
    _require(
        model.bytes + projector.bytes <= MAX_DOWNLOAD_BYTES, "the pair exceeds the download ceiling"
    )
    alternates = data.get("alternate_projectors", [])
    _require(isinstance(alternates, list), "alternate_projectors must be a list")
    for index, alternate in enumerate(alternates):
        item = _mapping(
            alternate,
            f"alternate_projectors[{index}]",
            frozenset({"filename", "bytes", "sha256", "precision", "status"}),
        )
        _text(item.get("sha256"), "alternate sha256", _HEX64)
        _require(
            item.get("status") == "listed_not_downloaded_not_approved", "alternates are listed only"
        )
    return VisualCandidate(
        _text(data.get("candidate_id"), "candidate_id", _ID),
        _text(data.get("display_name"), "display_name"),
        "vision_language",
        _parse_license(data.get("license")),
        _text(publisher.get("repository"), "publisher.repository", _REPOSITORY),
        _text(publisher.get("revision"), "publisher.revision", _HEX40),
        model,
        projector,
        _parse_runtime(data.get("runtime")),
    )


def parse_candidates(document: Any) -> tuple[VisualCandidate, ...]:
    """Parse a candidate document. Raises :class:`CandidateInvalid` for the whole document on any problem."""

    data = _mapping(
        document, "document", frozenset({"schema_version", "description", "candidates"})
    )
    _require(data.get("schema_version") == 1, "unsupported schema_version")
    raw: Any = data.get("candidates")
    if not isinstance(raw, list) or not raw:
        raise CandidateInvalid("candidates must be a non-empty list")
    parsed = tuple(_parse_candidate(item) for item in raw)
    _require(len({item.candidate_id for item in parsed}) == len(parsed), "duplicate candidate_id")
    return parsed


def load_candidates(source: str | Path | None = None) -> tuple[VisualCandidate, ...]:
    path = Path(source) if source is not None else CANDIDATES_PATH
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CandidateInvalid(f"cannot read candidate document: {exc.__class__.__name__}") from exc
    return parse_candidates(document)


def find_candidate(candidate_id: str, source: str | Path | None = None) -> VisualCandidate:
    for candidate in load_candidates(source):
        if candidate.candidate_id == candidate_id:
            return candidate
    raise CandidateInvalid(f"unknown candidate: {candidate_id}")


def hash_file(path: Path, cancel: CancelCheck | None = None) -> tuple[str, int] | None:
    """SHA-256 and size of ``path``; ``None`` when ``cancel`` asked to stop (checked between 4 MiB chunks)."""

    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            if cancel is not None and cancel():
                return None
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _check_file(
    path: Path,
    pinned: StagedFile,
    reasons: list[str],
    missing: str,
    size_reason: str,
    hash_reason: str,
    cancel: CancelCheck | None,
) -> bool:
    """Append reasons for a staged file; return False when the run was cancelled."""

    if not path.is_file():
        reasons.append(missing)
        return True
    if path.stat().st_size != pinned.bytes:
        reasons.append(size_reason)
        return True
    measured = hash_file(path, cancel)
    if measured is None:
        return False
    if measured[0] != pinned.sha256:
        reasons.append(hash_reason)
    return True


def _header(path: Path) -> GgufHeader | None:
    try:
        return read_header(path)
    except GgufHeaderError:
        return None


def _check_headers(candidate: VisualCandidate, staging: Path, reasons: list[str]) -> None:
    model_header = _header(staging / candidate.model.filename)
    projector_header = _header(staging / candidate.projector.filename)
    if model_header is None or not (
        model_header.architecture == candidate.model.architecture
        and model_header.metadata.get("general.type") == "model"
        and model_header.metadata.get("general.file_type") == candidate.model.gguf_file_type
        and model_header.metadata.get("lfm3.embedding_length") == candidate.model.embedding_length
    ):
        reasons.append(REASON_MODEL_HEADER)
    if projector_header is None or not (
        projector_header.architecture == candidate.projector.architecture
        and projector_header.metadata.get("general.type") == "mmproj"
        and projector_header.projector_type == candidate.projector.projector_type
        and projector_header.metadata.get("general.file_type") == candidate.projector.gguf_file_type
    ):
        reasons.append(REASON_PROJECTOR_HEADER)
    if model_header is not None and projector_header is not None:
        paired = (
            projector_header.metadata.get("clip.vision.projection_dim")
            == model_header.metadata.get("lfm3.embedding_length")
            and projector_header.metadata.get("general.base_model.0.name")
            == model_header.metadata.get("general.base_model.0.name")
            and projector_header.metadata.get("general.name")
            == model_header.metadata.get("general.name")
        )
        if not paired:
            reasons.append(REASON_PAIR_MISMATCH)


def runtime_reasons(
    candidate: VisualCandidate, build_id: str, manifest: RuntimeManifest
) -> list[str]:
    """Why ``build_id`` cannot run the candidate. Empty only for the one build the record requires."""

    build = manifest.find(build_id)
    if build is None:
        return [REASON_RUNTIME_UNKNOWN]
    runtime = candidate.runtime
    if (
        build_id != runtime.required_build_id
        or build_id in runtime.unsupported_build_ids
        or runtime.tool not in build.files
        or build.qualified is not False
    ):
        return [REASON_RUNTIME_UNSUPPORTED]
    return []


def license_reasons(
    candidate: VisualCandidate, acknowledgement: Mapping[str, Any] | None
) -> list[str]:
    """The owner's acknowledgement is a record kept outside Git; it must name this exact license text."""

    if not acknowledgement or acknowledgement.get("owner_acknowledged") is not True:
        return [REASON_LICENSE_MISSING]
    if acknowledgement.get("license_text_sha256") != candidate.license.text_sha256:
        return [REASON_LICENSE_MISMATCH]
    if acknowledgement.get("candidate_id") != candidate.candidate_id:
        return [REASON_LICENSE_MISMATCH]
    return []


def check_admission(
    candidate: VisualCandidate,
    staging_dir: Path,
    *,
    build_id: str,
    runtime_manifest: RuntimeManifest | None = None,
    acknowledgement: Mapping[str, Any] | None = None,
    cancel: CancelCheck | None = None,
) -> Admission:
    """May the evaluation harness use these staged bytes on ``build_id``? Fail-closed; never raises."""

    try:
        reasons: list[str] = []
        manifest = (
            runtime_manifest
            if runtime_manifest is not None
            else load_runtime_manifest(RUNTIME_MANIFEST_PATH)
        )
        reasons.extend(runtime_reasons(candidate, build_id, manifest))
        reasons.extend(license_reasons(candidate, acknowledgement))
        staging = Path(staging_dir)
        if not _check_file(
            staging / candidate.model.filename, candidate.model, reasons,
            REASON_MODEL_MISSING, REASON_MODEL_SIZE, REASON_MODEL_HASH, cancel,
        ):  # fmt: skip
            return Admission(False, (REASON_CANCELLED,))
        if not _check_file(
            staging / candidate.projector.filename, candidate.projector, reasons,
            REASON_PROJECTOR_MISSING, REASON_PROJECTOR_SIZE, REASON_PROJECTOR_HASH, cancel,
        ):  # fmt: skip
            return Admission(False, (REASON_CANCELLED,))
        if not any(
            reason.endswith(("_missing", "_size_mismatch", "_hash_mismatch")) for reason in reasons
        ):
            _check_headers(candidate, staging, reasons)
        return Admission(not reasons, tuple(dict.fromkeys(reasons)))
    except Exception:  # noqa: BLE001 - admission is fail-closed: an unexpected problem is a refusal, never a pass
        return Admission(False, (REASON_INTERNAL,))


__all__ = [
    "CANDIDATES_PATH",
    "MAX_DOWNLOAD_BYTES",
    "Admission",
    "CandidateInvalid",
    "VisualCandidate",
    "check_admission",
    "find_candidate",
    "hash_file",
    "license_reasons",
    "load_candidates",
    "parse_candidates",
    "runtime_reasons",
]
