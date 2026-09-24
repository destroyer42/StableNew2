"""Offline provenance-aware metadata enrichment over :mod:`src.assets.registry`.

This module is deliberately descriptive.  It neither selects assets nor alters
generation configuration; ``AssetRegistry`` remains the sole identity and file
discovery authority.
"""

from __future__ import annotations

import json
import re
import struct
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

from .registry import AssetKind, AssetRecord, AssetRegistry


class MetadataSource(str, Enum):
    EMBEDDED = "embedded_file_metadata"
    EXACT_HASH_SIDECAR = "exact_hash_sidecar_or_cache"
    LOCAL_DOCUMENTATION = "creator_local_documentation"
    TECHNICAL_INFERENCE = "deterministic_technical_inference"
    UNKNOWN = "unknown"


class EvidenceStrength(str, Enum):
    EXPLICIT = "explicit"
    STRONG_INFERENCE = "strong_inference"
    WEAK_INFERENCE = "weak_inference"
    UNKNOWN = "unknown"


class ModelFamily(str, Enum):
    SD1 = "sd1"
    SD2 = "sd2"
    SDXL = "sdxl"
    FLUX = "flux"
    OTHER = "other"
    UNKNOWN = "unknown"


class CompatibilityStatus(str, Enum):
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"
    ECOSYSTEM_SPECIFIC = "ecosystem_specific"


class ActivationRequirement(str, Enum):
    REQUIRED = "required"
    RECOMMENDED = "recommended"
    OPTIONAL = "optional"
    UNKNOWN = "unknown"


T = TypeVar("T")


@dataclass(frozen=True)
class MetadataProvenance:
    source: MetadataSource
    identifier: str | None
    extractor: str
    strength: EvidenceStrength


@dataclass(frozen=True)
class MetadataValue:
    value: T | None
    provenance: MetadataProvenance


@dataclass(frozen=True)
class MetadataConflict:
    field: str
    selected: MetadataValue[Any]
    alternatives: tuple[MetadataValue[Any], ...]


@dataclass(frozen=True)
class WeightGuidance:
    default: float | None = None
    minimum: float | None = None
    maximum: float | None = None


@dataclass(frozen=True)
class LegacyKeywordRecord:
    sha256: str
    cache_path: Path
    keywords: tuple[str, ...]
    cache_format: str
    error: str | None = None


@dataclass(frozen=True)
class CompatibilityProfile:
    sha256: str
    kind: AssetKind
    family: MetadataValue[ModelFamily]
    ecosystem_subfamily: MetadataValue[str]
    adapter_type: MetadataValue[str]
    embedding_dimension: MetadataValue[int]
    text_encoder_expectation: MetadataValue[str]
    known_incompatibilities: tuple[ModelFamily, ...]


@dataclass(frozen=True)
class AssetMetadata:
    sha256: str
    kind: AssetKind
    base_family: MetadataValue[ModelFamily]
    ecosystem_subfamily: MetadataValue[str]
    architecture: MetadataValue[str]
    adapter_type: MetadataValue[str]
    creator: MetadataValue[str]
    model_identifier: MetadataValue[str]
    version_identifier: MetadataValue[str]
    source_url: MetadataValue[str]
    activation_keywords: MetadataValue[tuple[str, ...]]
    activation_requirement: MetadataValue[ActivationRequirement]
    example_positive_prompts: MetadataValue[tuple[str, ...]]
    example_negative_prompts: MetadataValue[tuple[str, ...]]
    weight_guidance: MetadataValue[WeightGuidance]
    usage_notes: MetadataValue[str]
    raw_embedded_metadata: Mapping[str, Any]
    legacy_keyword_records: tuple[LegacyKeywordRecord, ...]
    conflicts: tuple[MetadataConflict, ...]
    source_errors: tuple[str, ...]


@dataclass(frozen=True)
class AssetEnrichmentSnapshot:
    metadata: tuple[AssetMetadata, ...]
    profiles: tuple[CompatibilityProfile, ...]


_HEADER_LIMIT = 64 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FIELD_PRECEDENCE = {
    MetadataSource.EMBEDDED: 0,
    MetadataSource.EXACT_HASH_SIDECAR: 1,
    MetadataSource.LOCAL_DOCUMENTATION: 2,
    MetadataSource.TECHNICAL_INFERENCE: 3,
    MetadataSource.UNKNOWN: 4,
}


def _unknown() -> MetadataProvenance:
    return MetadataProvenance(
        MetadataSource.UNKNOWN, None, "asset-metadata-v1", EvidenceStrength.UNKNOWN
    )


def _empty_value() -> MetadataValue[Any]:
    return MetadataValue(None, _unknown())


def _string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _strings(value: Any) -> tuple[str, ...]:
    values = value if isinstance(value, list) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _string(item)
        if text and text.casefold() not in seen:
            result.append(text)
            seen.add(text.casefold())
    return tuple(result)


def _family_from_explicit(value: Any) -> tuple[ModelFamily, str | None] | None:
    text = _string(value)
    if not text:
        return None
    lowered = text.casefold().replace("_", " ")
    if "pony" in lowered and "xl" in lowered:
        return ModelFamily.SDXL, "pony"
    if "sdxl" in lowered or "stable diffusion xl" in lowered:
        return ModelFamily.SDXL, None
    if "sd 2" in lowered or "sd2" in lowered or "stable diffusion 2" in lowered:
        return ModelFamily.SD2, None
    if "sd 1" in lowered or "sd1" in lowered or "1.5" in lowered:
        return ModelFamily.SD1, None
    if "flux" in lowered:
        return ModelFamily.FLUX, None
    return None


def _read_json(path: Path) -> tuple[dict[str, Any], str | None]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return {}, f"{path}: {type(exc).__name__}: {exc}"
    if not isinstance(parsed, dict):
        return {}, f"{path}: expected JSON object"
    return parsed, None


def _safetensors_header(path: Path) -> tuple[dict[str, Any], str | None]:
    try:
        with path.open("rb") as stream:
            prefix = stream.read(8)
            if len(prefix) != 8:
                return {}, "truncated safetensors header length"
            length = struct.unpack("<Q", prefix)[0]
            if length > _HEADER_LIMIT:
                return {}, "safetensors header too large"
            encoded = stream.read(length)
        if len(encoded) != length:
            return {}, "truncated safetensors header"
        parsed = json.loads(encoded.decode("utf-8"))
        return (parsed if isinstance(parsed, dict) else {}), None
    except (OSError, UnicodeDecodeError, ValueError, struct.error) as exc:
        return {}, f"{type(exc).__name__}: {exc}"


def _sidecars(path: Path) -> tuple[Path, ...]:
    return tuple(
        candidate
        for candidate in (
            path.with_suffix(path.suffix + ".civitai.info"),
            path.with_name(f"{path.stem}.civitai.info"),
        )
        if candidate.is_file()
    )


def _documentation(path: Path) -> tuple[Path, ...]:
    candidates = (path.with_suffix(".txt"), path.parent / "README.md", path.parent / "README.txt")
    return tuple(candidate for candidate in candidates if candidate.is_file())


def _source_fingerprint(paths: Iterable[Path]) -> tuple[tuple[str, int, int], ...]:
    result: list[tuple[str, int, int]] = []
    for path in sorted(set(paths), key=lambda item: str(item).casefold()):
        try:
            stat = path.stat()
        except OSError:
            continue
        result.append((str(path.resolve()), stat.st_mtime_ns, stat.st_size))
    return tuple(result)


def _structured_documentation(path: Path) -> tuple[dict[str, Any], str | None]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {}, f"{path}: {type(exc).__name__}: {exc}"
    values: dict[str, Any] = {"usage_notes": text[:4000].strip()} if text.strip() else {}
    labels = {
        "activation_keywords": r"(?:trigger|activation)\s*(?:words?|tokens?)?\s*[:=-]\s*([^\n]+)",
        "activation_requirement": r"activation\s+requirement\s*[:=-]\s*([^\n]+)",
        "positive_prompt": r"(?:example\s+)?positive\s+prompt\s*[:=-]\s*([^\n]+)",
        "negative_prompt": r"(?:example\s+)?negative\s+prompt\s*[:=-]\s*([^\n]+)",
        "weight": r"(?:recommended\s+)?(?:weight|strength)(?:\s+range)?\s*[:=-]\s*([^\n]+)",
    }
    for field, pattern in labels.items():
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        if matches:
            values[field] = matches
    return values, None


def _weight_guidance(value: Any) -> WeightGuidance | None:
    text = " ".join(_strings(value))
    numbers = [float(number) for number in re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)", text)]
    if not numbers:
        return None
    if len(numbers) >= 2 and ("-" in text or "to" in text.casefold()):
        return WeightGuidance(minimum=numbers[0], maximum=numbers[1])
    return WeightGuidance(default=numbers[0])


def _activation_requirement(value: Any) -> ActivationRequirement | None:
    values = _strings(value)
    if not values:
        return None
    text = values[0]
    return next(
        (
            requirement
            for requirement in ActivationRequirement
            if requirement.value == text.casefold()
        ),
        None,
    )


def _legacy_keyword_records(
    cache_roots: Iterable[Path],
) -> dict[str, tuple[LegacyKeywordRecord, ...]]:
    grouped: dict[str, list[LegacyKeywordRecord]] = defaultdict(list)
    for supplied in sorted(
        (Path(path) for path in cache_roots), key=lambda item: str(item).casefold()
    ):
        directories = (
            [supplied]
            if supplied.name in {"known", "metadata_cache"}
            else [
                supplied / "known",
                supplied / "metadata_cache",
            ]
        )
        for directory in directories:
            if not directory.is_dir():
                continue
            for path in sorted(directory.rglob("*.json"), key=lambda item: str(item).casefold()):
                digest = path.stem.casefold()
                if not _SHA256_RE.fullmatch(digest):
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    keywords = _strings(
                        data
                        if isinstance(data, list)
                        else data.get("trainedWords", data.get("keywords", []))
                        if isinstance(data, dict)
                        else []
                    )
                    cache_format = (
                        "legacy_keyword_list"
                        if isinstance(data, list)
                        else "rich_object"
                        if isinstance(data, dict)
                        else "unrecognized"
                    )
                    error = None
                except (OSError, UnicodeDecodeError, ValueError) as exc:
                    keywords, cache_format, error = (
                        (),
                        "unrecognized",
                        f"{type(exc).__name__}: {exc}",
                    )
                grouped[digest].append(
                    LegacyKeywordRecord(digest, path, keywords, cache_format, error)
                )
    return {digest: tuple(records) for digest, records in sorted(grouped.items())}


def _candidate(
    value: T, source: MetadataSource, identifier: str | None, strength: EvidenceStrength
) -> MetadataValue[T]:
    return MetadataValue(
        value, MetadataProvenance(source, identifier, "asset-metadata-v1", strength)
    )


def _select(
    field: str, candidates: Iterable[MetadataValue[T]]
) -> tuple[MetadataValue[T], MetadataConflict | None]:
    ordered = sorted(
        (candidate for candidate in candidates if candidate.value is not None),
        key=lambda candidate: (
            _FIELD_PRECEDENCE[candidate.provenance.source],
            candidate.provenance.identifier or "",
        ),
    )
    if not ordered:
        return MetadataValue(None, _unknown()), None
    selected = ordered[0]
    alternatives = tuple(
        candidate for candidate in ordered[1:] if candidate.value != selected.value
    )
    return selected, MetadataConflict(field, selected, alternatives) if alternatives else None


def _embedding_inference(
    path: Path,
) -> tuple[ModelFamily | None, int | None, str | None, str | None]:
    if path.suffix.casefold() != ".safetensors":
        return None, None, None, None
    header, error = _safetensors_header(path)
    tensors = {
        key: value
        for key, value in header.items()
        if key != "__metadata__" and isinstance(value, dict)
    }
    dimensions: list[int] = []
    for tensor in tensors.values():
        shape = tensor.get("shape")
        if isinstance(shape, list) and shape and isinstance(shape[-1], int):
            dimensions.append(shape[-1])
    names = {name.casefold() for name in tensors}
    if any("clip_g" in name for name in names) and any("clip_l" in name for name in names):
        return ModelFamily.SDXL, 1280, "dual_encoder_sdxl", error
    if 768 in dimensions and len(dimensions) == 1:
        return ModelFamily.SD1, 768, "clip_l_768", error
    return None, dimensions[0] if len(dimensions) == 1 else None, None, error


class AssetMetadataService:
    """Read-only metadata and compatibility projection keyed by registry SHA-256."""

    def __init__(
        self, registry: AssetRegistry, *, legacy_keyword_cache_roots: Iterable[Path] = ()
    ) -> None:
        self.registry = registry
        self.legacy_keyword_cache_roots = tuple(Path(path) for path in legacy_keyword_cache_roots)
        self._cache: dict[
            str, tuple[tuple[tuple[str, int, int], ...], AssetMetadata, CompatibilityProfile]
        ] = {}
        self._snapshot = AssetEnrichmentSnapshot((), ())

    @property
    def snapshot(self) -> AssetEnrichmentSnapshot:
        return self._snapshot

    def refresh(self) -> AssetEnrichmentSnapshot:
        registry_snapshot = self.registry.refresh().snapshot
        legacy = _legacy_keyword_records(self.legacy_keyword_cache_roots)
        metadata: list[AssetMetadata] = []
        profiles: list[CompatibilityProfile] = []
        next_cache: dict[
            str, tuple[tuple[tuple[str, int, int], ...], AssetMetadata, CompatibilityProfile]
        ] = {}
        for record in registry_snapshot.records:
            paths = [location.path for location in record.locations]
            sources = [
                candidate
                for path in paths
                for candidate in (*_sidecars(path), *_documentation(path))
            ]
            sources.extend(item.cache_path for item in legacy.get(record.sha256, ()))
            fingerprint = _source_fingerprint(sources)
            cached = self._cache.get(record.sha256)
            if cached and cached[0] == fingerprint:
                asset_metadata, profile = cached[1], cached[2]
            else:
                asset_metadata, profile = self._enrich(record, legacy.get(record.sha256, ()))
            metadata.append(asset_metadata)
            profiles.append(profile)
            next_cache[record.sha256] = (fingerprint, asset_metadata, profile)
        self._cache = next_cache
        self._snapshot = AssetEnrichmentSnapshot(tuple(metadata), tuple(profiles))
        return self._snapshot

    def metadata_for(self, sha256: str) -> AssetMetadata | None:
        return next((item for item in self._snapshot.metadata if item.sha256 == sha256), None)

    def profile_for(self, sha256: str) -> CompatibilityProfile | None:
        return next((item for item in self._snapshot.profiles if item.sha256 == sha256), None)

    def provenance_for(self, sha256: str, field: str) -> MetadataProvenance | None:
        metadata = self.metadata_for(sha256)
        value = getattr(metadata, field, None) if metadata else None
        return value.provenance if isinstance(value, MetadataValue) else None

    def activation_for(
        self, sha256: str
    ) -> tuple[MetadataValue[tuple[str, ...]], MetadataValue[ActivationRequirement]] | None:
        metadata = self.metadata_for(sha256)
        return (metadata.activation_keywords, metadata.activation_requirement) if metadata else None

    def assets_with_conflicts(self) -> tuple[AssetMetadata, ...]:
        return tuple(item for item in self._snapshot.metadata if item.conflicts)

    def assets_with_unknown_family(self) -> tuple[CompatibilityProfile, ...]:
        return tuple(
            item for item in self._snapshot.profiles if item.family.value is ModelFamily.UNKNOWN
        )

    def compatibility_with_family(self, sha256: str, family: ModelFamily) -> CompatibilityStatus:
        profile = self.profile_for(sha256)
        if (
            profile is None
            or profile.family.value is None
            or profile.family.value is ModelFamily.UNKNOWN
        ):
            return CompatibilityStatus.UNKNOWN
        return (
            CompatibilityStatus.COMPATIBLE
            if profile.family.value is family
            else CompatibilityStatus.INCOMPATIBLE
        )

    def compatibility_between(self, left_sha256: str, right_sha256: str) -> CompatibilityStatus:
        left, right = self.profile_for(left_sha256), self.profile_for(right_sha256)
        if left is None or right is None or left.family.value is None or right.family.value is None:
            return CompatibilityStatus.UNKNOWN
        if ModelFamily.UNKNOWN in {left.family.value, right.family.value}:
            return CompatibilityStatus.UNKNOWN
        return (
            CompatibilityStatus.COMPATIBLE
            if left.family.value is right.family.value
            else CompatibilityStatus.INCOMPATIBLE
        )

    def _enrich(
        self, record: AssetRecord, legacy_records: tuple[LegacyKeywordRecord, ...]
    ) -> tuple[AssetMetadata, CompatibilityProfile]:
        kind = record.locations[0].kind
        embedded = record.embedded_metadata
        field_candidates: dict[str, list[MetadataValue[Any]]] = defaultdict(list)
        errors: list[str] = []

        def add(
            field: str,
            value: Any,
            source: MetadataSource,
            identifier: str | None,
            strength: EvidenceStrength,
        ) -> None:
            if value is not None:
                field_candidates[field].append(_candidate(value, source, identifier, strength))

        for key in (
            "ss_base_model_version",
            "modelspec.architecture",
            "modelspec.sai_model_spec",
            "base_model",
        ):
            inferred = _family_from_explicit(embedded.get(key))
            if inferred:
                family, ecosystem = inferred
                add("base_family", family, MetadataSource.EMBEDDED, key, EvidenceStrength.EXPLICIT)
                if ecosystem:
                    add(
                        "ecosystem_subfamily",
                        ecosystem,
                        MetadataSource.EMBEDDED,
                        key,
                        EvidenceStrength.EXPLICIT,
                    )
        for field, keys in {
            "architecture": ("modelspec.architecture", "ss_base_model_version"),
            "adapter_type": ("ss_network_module", "network_module"),
            "creator": ("ss_creator", "creator"),
            "model_identifier": ("modelspec.name", "ss_sd_model_name"),
            "version_identifier": ("modelspec.version", "ss_version"),
        }.items():
            for key in keys:
                text = _string(embedded.get(key))
                if text:
                    add(field, text, MetadataSource.EMBEDDED, key, EvidenceStrength.EXPLICIT)
                    break

        for location in record.locations:
            for sidecar in _sidecars(location.path):
                payload, error = _read_json(sidecar)
                if error:
                    errors.append(error)
                    continue
                identifier = str(sidecar)
                for key in ("baseModel", "base_model", "modelType"):
                    inferred = _family_from_explicit(payload.get(key))
                    if inferred:
                        family, ecosystem = inferred
                        add(
                            "base_family",
                            family,
                            MetadataSource.EXACT_HASH_SIDECAR,
                            identifier,
                            EvidenceStrength.EXPLICIT,
                        )
                        if ecosystem:
                            add(
                                "ecosystem_subfamily",
                                ecosystem,
                                MetadataSource.EXACT_HASH_SIDECAR,
                                identifier,
                                EvidenceStrength.EXPLICIT,
                            )
                for field, keys in {
                    "creator": ("creator", "username"),
                    "model_identifier": ("modelId", "model_id", "modelName", "model_name"),
                    "version_identifier": ("id", "version_id", "versionId"),
                    "source_url": ("modelUrl", "url"),
                    "adapter_type": ("networkType", "network_type"),
                }.items():
                    for key in keys:
                        text = _string(payload.get(key))
                        if text:
                            add(
                                field,
                                text,
                                MetadataSource.EXACT_HASH_SIDECAR,
                                identifier,
                                EvidenceStrength.EXPLICIT,
                            )
                            break
                words = _strings(payload.get("trainedWords", payload.get("trained_words", [])))
                if words:
                    add(
                        "activation_keywords",
                        words,
                        MetadataSource.EXACT_HASH_SIDECAR,
                        identifier,
                        EvidenceStrength.EXPLICIT,
                    )
                requirement = _activation_requirement(
                    payload.get("activationRequirement", payload.get("triggerRequirement"))
                )
                if requirement:
                    add(
                        "activation_requirement",
                        requirement,
                        MetadataSource.EXACT_HASH_SIDECAR,
                        identifier,
                        EvidenceStrength.EXPLICIT,
                    )
                positive = _strings(
                    payload.get("examplePositivePrompt", payload.get("positivePrompt", []))
                )
                negative = _strings(
                    payload.get("exampleNegativePrompt", payload.get("negativePrompt", []))
                )
                if positive:
                    add(
                        "example_positive_prompts",
                        positive,
                        MetadataSource.EXACT_HASH_SIDECAR,
                        identifier,
                        EvidenceStrength.EXPLICIT,
                    )
                if negative:
                    add(
                        "example_negative_prompts",
                        negative,
                        MetadataSource.EXACT_HASH_SIDECAR,
                        identifier,
                        EvidenceStrength.EXPLICIT,
                    )
                guidance = _weight_guidance(payload.get("recommendedWeight", payload.get("weight")))
                if guidance:
                    add(
                        "weight_guidance",
                        guidance,
                        MetadataSource.EXACT_HASH_SIDECAR,
                        identifier,
                        EvidenceStrength.EXPLICIT,
                    )

            for document in _documentation(location.path):
                payload, error = _structured_documentation(document)
                if error:
                    errors.append(error)
                    continue
                identifier = str(document)
                if payload.get("usage_notes"):
                    add(
                        "usage_notes",
                        payload["usage_notes"],
                        MetadataSource.LOCAL_DOCUMENTATION,
                        identifier,
                        EvidenceStrength.WEAK_INFERENCE,
                    )
                words = _strings(payload.get("activation_keywords", []))
                if words:
                    add(
                        "activation_keywords",
                        words,
                        MetadataSource.LOCAL_DOCUMENTATION,
                        identifier,
                        EvidenceStrength.EXPLICIT,
                    )
                requirement = _activation_requirement(payload.get("activation_requirement"))
                if requirement:
                    add(
                        "activation_requirement",
                        requirement,
                        MetadataSource.LOCAL_DOCUMENTATION,
                        identifier,
                        EvidenceStrength.EXPLICIT,
                    )
                for field in ("positive_prompt", "negative_prompt"):
                    prompts = _strings(payload.get(field, []))
                    if prompts:
                        add(
                            "example_positive_prompts"
                            if field == "positive_prompt"
                            else "example_negative_prompts",
                            prompts,
                            MetadataSource.LOCAL_DOCUMENTATION,
                            identifier,
                            EvidenceStrength.EXPLICIT,
                        )
                guidance = _weight_guidance(payload.get("weight"))
                if guidance:
                    add(
                        "weight_guidance",
                        guidance,
                        MetadataSource.LOCAL_DOCUMENTATION,
                        identifier,
                        EvidenceStrength.EXPLICIT,
                    )

        cached_words = tuple(word for item in legacy_records for word in item.keywords)
        if cached_words:
            add(
                "activation_keywords",
                tuple(dict.fromkeys(cached_words)),
                MetadataSource.EXACT_HASH_SIDECAR,
                "legacy-keyword-cache",
                EvidenceStrength.EXPLICIT,
            )
            add(
                "activation_requirement",
                ActivationRequirement.UNKNOWN,
                MetadataSource.EXACT_HASH_SIDECAR,
                "legacy-keyword-cache",
                EvidenceStrength.UNKNOWN,
            )

        dimension: int | None = None
        encoder: str | None = None
        if kind is AssetKind.EMBEDDING:
            family, dimension, encoder, error = _embedding_inference(record.locations[0].path)
            if error:
                errors.append(f"{record.locations[0].path}: {error}")
            if family:
                add(
                    "base_family",
                    family,
                    MetadataSource.TECHNICAL_INFERENCE,
                    str(record.locations[0].path),
                    EvidenceStrength.STRONG_INFERENCE,
                )
            if dimension:
                add(
                    "embedding_dimension",
                    dimension,
                    MetadataSource.TECHNICAL_INFERENCE,
                    str(record.locations[0].path),
                    EvidenceStrength.STRONG_INFERENCE,
                )
            if encoder:
                add(
                    "text_encoder_expectation",
                    encoder,
                    MetadataSource.TECHNICAL_INFERENCE,
                    str(record.locations[0].path),
                    EvidenceStrength.STRONG_INFERENCE,
                )

        selected: dict[str, MetadataValue[Any]] = {}
        conflicts: list[MetadataConflict] = []
        fields = (
            "base_family",
            "ecosystem_subfamily",
            "architecture",
            "adapter_type",
            "creator",
            "model_identifier",
            "version_identifier",
            "source_url",
            "activation_keywords",
            "activation_requirement",
            "example_positive_prompts",
            "example_negative_prompts",
            "weight_guidance",
            "usage_notes",
            "embedding_dimension",
            "text_encoder_expectation",
        )
        for field in fields:
            value, conflict = _select(field, field_candidates[field])
            selected[field] = value
            if conflict:
                conflicts.append(conflict)
        if selected["base_family"].value is None:
            selected["base_family"] = MetadataValue(ModelFamily.UNKNOWN, _unknown())
        if selected["activation_requirement"].value is None:
            selected["activation_requirement"] = MetadataValue(
                ActivationRequirement.UNKNOWN, _unknown()
            )
        metadata = AssetMetadata(
            record.sha256,
            kind,
            selected["base_family"],
            selected["ecosystem_subfamily"],
            selected["architecture"],
            selected["adapter_type"],
            selected["creator"],
            selected["model_identifier"],
            selected["version_identifier"],
            selected["source_url"],
            selected["activation_keywords"],
            selected["activation_requirement"],
            selected["example_positive_prompts"],
            selected["example_negative_prompts"],
            selected["weight_guidance"],
            selected["usage_notes"],
            embedded,
            legacy_records,
            tuple(conflicts),
            tuple(sorted(errors)),
        )
        family = selected["base_family"]
        incompatibilities = (
            tuple(
                item
                for item in ModelFamily
                if item not in {family.value, ModelFamily.UNKNOWN, ModelFamily.OTHER}
            )
            if family.value not in {None, ModelFamily.UNKNOWN, ModelFamily.OTHER}
            else ()
        )
        profile = CompatibilityProfile(
            record.sha256,
            kind,
            family,
            selected["ecosystem_subfamily"],
            selected["adapter_type"],
            selected["embedding_dimension"],
            selected["text_encoder_expectation"],
            incompatibilities,
        )
        return metadata, profile
