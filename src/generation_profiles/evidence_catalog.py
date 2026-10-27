"""Versioned, source-cited advisory evidence. No discovery, execution or network authority."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from src.generation_profiles.contract import (
    IDENTITY_MODEL,
    KIND_RESEARCH,
    SETTING_KEYS,
    SOURCE_OFFICIAL,
    SOURCE_STABLENEW_TESTED,
    EvidenceNote,
    GenerationProfile,
    ModelIdentity,
    validate_settings,
)
from src.utils.atomic_io import atomic_write_text

CONTRACT = "model_evidence_catalog/1"
MAX_BYTES = 2 * 1024 * 1024
CLASSES = (
    "exact_publisher",
    "exact_stablenew",
    "publisher_family",
    "implementation",
    "community",
    "unverified",
)
CONFIDENCES = ("high", "medium", "low", "unknown")
TECHNICAL_FIELDS = (
    "native_scheduler",
    "training_geometry",
    "text_encoders",
    "context_length",
    "clip_skip",
    "subtype",
    "quantization",
    "variant",
    "dependencies",
    "compatible_families",
    "restrictions",
)


def text(value: Any, label: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 1600 or (not empty and not value.strip()):
        raise ValueError(f"Invalid {label}")
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ValueError(f"Invalid control character in {label}")
    return value


def source_url(raw: Any) -> str:
    value = text(raw, "source")
    if value.startswith("local:"):
        if not re.fullmatch(r"local:[A-Za-z0-9_./:#-]+", value) or ".." in value:
            raise ValueError("Invalid local authority")
        return value
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Source must be a public HTTPS citation without credentials or query")
    return value


@dataclass(frozen=True)
class Claim:
    field: str
    value: Any
    classification: str
    source: str
    reviewed_on: str
    rationale: str
    confidence: str
    caveat: str = ""
    source_revision: str = ""

    def __post_init__(self) -> None:
        if self.field not in (*SETTING_KEYS, *TECHNICAL_FIELDS):
            raise ValueError("Unknown evidence field")
        if self.classification not in CLASSES or self.confidence not in CONFIDENCES:
            raise ValueError("Invalid evidence classification")
        source_url(self.source)
        date.fromisoformat(self.reviewed_on)
        text(self.rationale, "rationale")
        text(self.caveat, "caveat", empty=True)
        text(self.source_revision, "source revision", empty=True)
        if self.field in SETTING_KEYS:
            validate_settings({self.field: self.value})
        elif not isinstance(self.value, (str, int, float, bool, list, type(None))):
            raise ValueError("Technical metadata must be scalar or a bounded list of text")
        if isinstance(self.value, list) and (
            len(self.value) > 32 or any(not isinstance(v, str) or len(v) > 400 for v in self.value)
        ):
            raise ValueError("Invalid technical metadata list")
        if len(json.dumps(self.value, allow_nan=False)) > 4096:
            raise ValueError("Evidence value too large")

    @property
    def recommendable(self) -> bool:
        return (
            self.field in SETTING_KEYS
            and self.classification in CLASSES[:3]
            and self.confidence == "high"
            and not self.caveat
        )


@dataclass(frozen=True)
class EvidenceRecord:
    record_id: str
    asset_kind: str
    family: str
    scope: str  # family | variant | exact
    claims: tuple[Claim, ...]
    sha256: str = ""
    variant: str = ""

    def __post_init__(self) -> None:
        for label, value in (
            ("record id", self.record_id),
            ("family", self.family),
            ("asset kind", self.asset_kind),
        ):
            text(value, label)
        if self.scope not in ("family", "variant", "exact"):
            raise ValueError("Invalid evidence scope")
        if self.scope == "exact" and not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("Exact evidence requires SHA-256")
        if self.scope != "exact" and self.sha256:
            raise ValueError("Hash belongs only to exact evidence")
        if self.scope == "variant" and not self.variant:
            raise ValueError("Variant evidence requires a variant")
        text(self.variant, "variant", empty=True)
        if len(self.claims) > 128 or any(not isinstance(c, Claim) for c in self.claims):
            raise ValueError("Invalid claims")
        if self.asset_kind != "checkpoint" and any(c.field in SETTING_KEYS for c in self.claims):
            raise ValueError("Accessories carry usage metadata, not checkpoint defaults")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> EvidenceRecord:
        data = dict(raw)
        claims = data.pop("claims")
        if not isinstance(claims, list) or len(claims) > 128:
            raise ValueError("Invalid claims array")
        return cls(**data, claims=tuple(Claim(**c) for c in claims))


@dataclass(frozen=True)
class Coverage:
    field: str
    status: str
    claims: tuple[Claim, ...]
    reason: str


class EvidenceCatalog:
    def __init__(self, records: tuple[EvidenceRecord, ...] = ()) -> None:
        if len(records) > 4096 or len({r.record_id for r in records}) != len(records):
            raise ValueError("Duplicate or excessive catalog records")
        self.records = records

    def to_document(self) -> dict[str, Any]:
        return {"contract": CONTRACT, "records": [r.to_dict() for r in self.records]}

    @property
    def revision(self) -> str:
        return hashlib.sha256(json.dumps(self.to_document(), sort_keys=True).encode()).hexdigest()

    @classmethod
    def from_document(cls, raw: Mapping[str, Any]) -> EvidenceCatalog:
        if (
            set(raw) != {"contract", "records"}
            or raw["contract"] != CONTRACT
            or not isinstance(raw["records"], list)
        ):
            raise ValueError("Unsupported evidence catalog")
        if len(json.dumps(raw, allow_nan=False)) > MAX_BYTES:
            raise ValueError("Catalog exceeds limit")
        return cls(tuple(EvidenceRecord.from_dict(r) for r in raw["records"]))

    @classmethod
    def load(cls, path: Path) -> EvidenceCatalog:
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Catalog exceeds limit")
        return cls.from_document(json.loads(raw))

    def save_revision(self, root: Path) -> Path:
        # Content-addressed, operator-only catalog snapshots; no mutable profile writes.
        from src.utils.atomic_io import atomic_publish_json

        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{self.revision}.json"
        if not path.exists():
            try:
                atomic_publish_json(path, self.to_document())
            except FileExistsError:
                if EvidenceCatalog.load(path).revision != self.revision:
                    raise ValueError("Evidence revision content mismatch") from None
        return path

    def coverage(
        self, identity: ModelIdentity, *, variant: str = "", asset_kind: str = "checkpoint"
    ) -> tuple[Coverage, ...]:
        matches = [
            r
            for r in self.records
            if r.asset_kind == asset_kind
            and r.family == identity.family
            and (
                (r.scope == "exact" and identity.sha256 and r.sha256 == identity.sha256)
                or (r.scope == "family" and identity.family != "unknown")
                or (r.scope == "variant" and variant and r.variant == variant)
            )
        ]
        result = []
        for key in (*SETTING_KEYS, *TECHNICAL_FIELDS):
            # Exact recommendations supersede family starting points for each field;
            # contradictions at the same specificity remain visible and unapplied.
            records = [r for r in matches if any(c.field == key for c in r.claims)]
            rank = {"family": 0, "variant": 1, "exact": 2}
            best = max((rank[r.scope] for r in records), default=-1)
            claims = tuple(
                c for r in records if rank[r.scope] == best for c in r.claims if c.field == key
            )
            values = {json.dumps(c.value, sort_keys=True) for c in claims}
            status = (
                "unavailable"
                if not claims
                else "conflicting"
                if len(values) > 1
                else "recommended"
                if any(c.recommendable for c in claims)
                else "hypothesis"
            )
            result.append(
                Coverage(
                    key,
                    status,
                    claims,
                    {
                        "unavailable": "No verified source recommendation for this field.",
                        "conflicting": "Sources disagree at the same identity scope; no automatic resolution.",
                        "recommended": "Source-backed recommendation; executable policy remains final.",
                        "hypothesis": "Candidate or technical evidence; no automatic executable default.",
                    }[status],
                )
            )
        return tuple(result)

    def exact_profile(self, identity: ModelIdentity) -> GenerationProfile | None:
        if identity.kind != IDENTITY_MODEL or not identity.sha256 or identity.family == "unknown":
            return None
        if not any(
            r.scope == "exact"
            and r.sha256 == identity.sha256
            and r.family == identity.family
            and r.asset_kind == "checkpoint"
            for r in self.records
        ):
            return None
        settings, unavailable, notes = {}, {}, []
        for row in self.coverage(identity):
            if row.field not in SETTING_KEYS:
                continue
            if row.status != "recommended":
                unavailable[row.field] = row.reason
                continue
            claim = next(c for c in row.claims if c.recommendable)
            settings[row.field] = claim.value
            notes.append(
                EvidenceNote(
                    (row.field,),
                    SOURCE_STABLENEW_TESTED
                    if claim.classification == "exact_stablenew"
                    else SOURCE_OFFICIAL,
                    claim.rationale,
                    reference=claim.source,
                    reviewed_on=claim.reviewed_on,
                    source_revision=claim.source_revision or None,
                )
            )
        if not settings:
            return None
        return GenerationProfile(
            profile_id=f"research-bytes-{identity.sha256}-{self.revision[:12]}",
            revision=1,
            kind=KIND_RESEARCH,
            name=f"Exact research: {identity.display_name}",
            model=identity,
            settings=settings,
            unavailable=unavailable,
            evidence=tuple(notes),
            provenance={"catalog_revision": self.revision},
        )


def operator_catalog_root() -> Path:
    from src.generation_profiles.store import GenerationProfileStore

    return GenerationProfileStore().root / "evidence"


def load_operator_catalog() -> EvidenceCatalog:
    from src.generation_profiles.evidence_baseline import baseline_catalog

    root = operator_catalog_root()
    pointer = root / "selected.json"
    if not pointer.exists():
        return baseline_catalog()
    with pointer.open("rb") as stream:
        raw = stream.read(256)
    revision = json.loads(raw).get("revision")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{64}", revision):
        raise ValueError("Invalid evidence revision pointer")
    catalog = EvidenceCatalog.load(root / f"{revision}.json")
    if catalog.revision != revision:
        raise ValueError("Selected evidence revision content mismatch")
    return catalog


def select_operator_catalog(catalog: EvidenceCatalog, root: Path) -> None:
    catalog.save_revision(root)
    atomic_write_text(root / "selected.json", json.dumps({"revision": catalog.revision}))


def catalog_profiles() -> tuple[GenerationProfile, ...]:
    """Read operator-reviewed exact evidence; no lookup, scan or profile application."""
    try:
        catalog = load_operator_catalog()
        identities = {
            (r.sha256, r.family)
            for r in catalog.records
            if r.scope == "exact" and r.asset_kind == "checkpoint"
        }
        profiles = [
            catalog.exact_profile(
                ModelIdentity(
                    IDENTITY_MODEL,
                    f"model:{family}:{sha}",
                    family,
                    display_name=sha[:8],
                    model_key=sha,
                    sha256=sha,
                )
            )
            for sha, family in sorted(identities)
        ]
        return tuple(p for p in profiles if p is not None)
    except (OSError, ValueError, TypeError, KeyError):
        return ()  # malformed optional research never changes Custom/Learning/defaults
