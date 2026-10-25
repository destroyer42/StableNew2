"""Typed, versioned generation-settings profile contract (PR-IMG-PROFILE-630).

A *generation-settings profile* is a **recommendation**: starting values for the Base Generation controls of one model
(or one verified model family) together with where each value came from. It is a different concept from the executable
exact-model profiles and ``ModelPolicy`` in ``src/image_backends`` (which decide what is *legal*) and from the Learning
style priors in ``src/learning/model_profiles.py``. A profile can never widen what the executable policy allows, never
enables an optional stage, and never invents a value: a setting the evidence does not cover is absent and listed in
``unavailable`` with the reason.

Kinds: ``research`` (built-in, read-only, sourced), ``custom`` (operator-owned, versioned) and ``learning`` (published
by the later LEARN-PROFILE-660 promotion engine through ``GenerationProfileStore.publish_learning_profile``). Every
revision is immutable once written; a change is a new revision.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = 1

KIND_RESEARCH = "research"
KIND_CUSTOM = "custom"
KIND_LEARNING = "learning"
PROFILE_KINDS = (KIND_RESEARCH, KIND_CUSTOM, KIND_LEARNING)

#: Identity kinds a profile may be bound to.
IDENTITY_EXACT = "exact_profile"  # an immutable executable profile (Klein, Z-Image)
IDENTITY_FAMILY = "family"  # every checkpoint the registry verifies as one family (research only)
IDENTITY_MODEL = (
    "model"  # one checkpoint: registry family plus a whole-name key and, when known, SHA-256
)
IDENTITY_KINDS = (IDENTITY_EXACT, IDENTITY_FAMILY, IDENTITY_MODEL)

#: How trustworthy a recommendation's source is. The classes are not interchangeable.
SOURCE_OFFICIAL = "official_model_recommendation"
SOURCE_STABLENEW_TESTED = "stablenew_tested"
SOURCE_INFERRED = "inferred_or_community"
SOURCE_UNVERIFIED = "unverified"
SOURCE_OPERATOR = "operator_saved"
SOURCE_LEARNING = "learning_evidence"
SOURCE_CLASSES = (
    SOURCE_OFFICIAL,
    SOURCE_STABLENEW_TESTED,
    SOURCE_INFERRED,
    SOURCE_UNVERIFIED,
    SOURCE_OPERATOR,
    SOURCE_LEARNING,
)

#: Base Generation controls a profile may recommend. Stage *enablement* is deliberately not representable.
SETTING_SAMPLER = "sampler_name"
SETTING_SCHEDULER = "scheduler"
SETTING_STEPS = "steps"
SETTING_CFG = "cfg_scale"
SETTING_WIDTH = "width"
SETTING_HEIGHT = "height"
SETTING_VAE = "vae"
SETTING_KEYS = (
    SETTING_SAMPLER,
    SETTING_SCHEDULER,
    SETTING_STEPS,
    SETTING_CFG,
    SETTING_WIDTH,
    SETTING_HEIGHT,
    SETTING_VAE,
)

_MAX_TEXT = 400


class ProfileError(ValueError):
    """A profile, revision or stored record is malformed or breaks an invariant."""


def _text(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ProfileError(f"{label} must be text")
    stripped = value.strip()
    if not stripped and not allow_empty:
        raise ProfileError(f"{label} must not be empty")
    if len(stripped) > _MAX_TEXT * 4:
        raise ProfileError(f"{label} is too long")
    return stripped


def _optional_text(value: Any, label: str) -> str | None:
    return None if value is None else _text(value, label, allow_empty=True) or None


def validate_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
    """Return a clean copy of recommended values, or raise. Unknown keys (for example ``adetailer_enabled``) are refused."""

    clean: dict[str, Any] = {}
    for key, value in settings.items():
        if key not in SETTING_KEYS:
            raise ProfileError(f"'{key}' is not a recommendable setting")
        if key in (SETTING_SAMPLER, SETTING_SCHEDULER):
            clean[key] = _text(value, key)
        elif key == SETTING_VAE:
            clean[key] = _text(value, key, allow_empty=True)  # '' = the model's own VAE
        elif key == SETTING_STEPS:
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 200:
                raise ProfileError("steps must be a whole number from 1 to 200")
            clean[key] = value
        elif key == SETTING_CFG:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ProfileError("cfg_scale must be a finite number")
            if not 0.0 <= float(value) <= 30.0:
                raise ProfileError("cfg_scale must be from 0 to 30")
            clean[key] = float(value)
        else:  # width / height
            if isinstance(value, bool) or not isinstance(value, int) or not 64 <= value <= 4096:
                raise ProfileError(f"{key} must be a whole number from 64 to 4096")
            clean[key] = value
    return clean


@dataclass(frozen=True)
class ModelIdentity:
    """Which model a profile belongs to. Never a display label and never a filename substring."""

    kind: str
    #: Stable machine key: ``exact:<profile id>``, ``family:<family>`` or ``model:<family>:<whole-name key>``.
    key: str
    family: str
    display_name: str = ""
    #: ``{"id", "version"}`` of the executable profile this was written against (exact identities only).
    exact_profile: Mapping[str, Any] | None = None
    #: Whole-name key (directory, weights extension and ``[hash]`` suffix removed, lower-cased) for ``model`` identities.
    model_key: str = ""
    #: SHA-256 from the registry snapshot when it was already known; never computed on the UI thread.
    sha256: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in IDENTITY_KINDS:
            raise ProfileError(f"unknown identity kind '{self.kind}'")
        if not self.key or not self.family:
            raise ProfileError("a model identity needs a key and a family")
        if self.kind == IDENTITY_EXACT and not (
            self.exact_profile and self.exact_profile.get("id")
        ):
            raise ProfileError("an exact identity needs its executable profile reference")
        if self.kind == IDENTITY_MODEL and not self.model_key:
            raise ProfileError("a model identity needs a whole-name key")
        if self.sha256 is not None and (
            len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256)
        ):
            raise ProfileError("sha256 must be 64 lowercase hex characters")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "key": self.key,
            "family": self.family,
            "display_name": self.display_name,
            "exact_profile": dict(self.exact_profile) if self.exact_profile else None,
            "model_key": self.model_key,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ModelIdentity:
        if not isinstance(data, Mapping):
            raise ProfileError("model identity must be an object")
        exact = data.get("exact_profile")
        if exact is not None and not isinstance(exact, Mapping):
            raise ProfileError("exact_profile must be an object")
        return cls(
            kind=_text(data.get("kind"), "identity kind"),
            key=_text(data.get("key"), "identity key"),
            family=_text(data.get("family"), "identity family"),
            display_name=_text(data.get("display_name", ""), "display name", allow_empty=True),
            exact_profile=dict(exact) if exact else None,
            model_key=_text(data.get("model_key", ""), "model key", allow_empty=True),
            sha256=_optional_text(data.get("sha256"), "sha256"),
        )


@dataclass(frozen=True)
class EvidenceNote:
    """Why a group of values is recommended, and how far to trust that."""

    fields: tuple[str, ...]
    source_class: str
    rationale: str
    citation: str = ""
    reference: str = ""
    reviewed_on: str = ""
    source_revision: str | None = None

    def __post_init__(self) -> None:
        if self.source_class not in SOURCE_CLASSES:
            raise ProfileError(f"unknown source class '{self.source_class}'")
        if not self.fields or any(name not in SETTING_KEYS for name in self.fields):
            raise ProfileError("an evidence note must name recommendable settings")
        if not self.rationale.strip():
            raise ProfileError("an evidence note needs a rationale")

    def to_dict(self) -> dict[str, Any]:
        return {
            "fields": list(self.fields),
            "source_class": self.source_class,
            "rationale": self.rationale,
            "citation": self.citation,
            "reference": self.reference,
            "reviewed_on": self.reviewed_on,
            "source_revision": self.source_revision,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> EvidenceNote:
        if not isinstance(data, Mapping):
            raise ProfileError("evidence note must be an object")
        fields_value = data.get("fields")
        if not isinstance(fields_value, list):
            raise ProfileError("evidence note fields must be a list")
        return cls(
            fields=tuple(_text(item, "evidence field") for item in fields_value),
            source_class=_text(data.get("source_class"), "source class"),
            rationale=_text(data.get("rationale"), "rationale"),
            citation=_text(data.get("citation", ""), "citation", allow_empty=True),
            reference=_text(data.get("reference", ""), "reference", allow_empty=True),
            reviewed_on=_text(data.get("reviewed_on", ""), "reviewed_on", allow_empty=True),
            source_revision=_optional_text(data.get("source_revision"), "source revision"),
        )


@dataclass(frozen=True)
class GenerationProfile:
    """One immutable revision of a generation-settings recommendation."""

    profile_id: str
    revision: int
    kind: str
    name: str
    model: ModelIdentity
    settings: Mapping[str, Any]
    #: Setting -> why there is no recommendation for it. Disjoint from ``settings``.
    unavailable: Mapping[str, str] = field(default_factory=dict)
    evidence: tuple[EvidenceNote, ...] = ()
    #: Operations the values were written for (Base Generation txt2img today).
    operations: tuple[str, ...] = ("txt2img",)
    #: Executable profile version a research profile was written against; a moved version makes it stale, not silently wrong.
    executable_profile: Mapping[str, Any] | None = None
    #: Learning: opaque, scalar-only evidence summary written by the promotion engine. Custom: ``{"owner": "operator"}``.
    provenance: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = ""
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ProfileError(f"unsupported profile schema {self.schema_version}")
        if self.kind not in PROFILE_KINDS:
            raise ProfileError(f"unknown profile kind '{self.kind}'")
        if not self.profile_id.strip() or any(sep in self.profile_id for sep in "/\\:"):
            raise ProfileError("profile id must be a plain token")
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 1
        ):
            raise ProfileError("revision must be a positive whole number")
        if not self.name.strip():
            raise ProfileError("a profile needs a name")
        clean = validate_settings(self.settings)
        object.__setattr__(self, "settings", clean)
        object.__setattr__(
            self, "unavailable", {str(k): str(v) for k, v in dict(self.unavailable).items()}
        )
        overlap = set(clean) & set(self.unavailable)
        if overlap or any(key not in SETTING_KEYS for key in self.unavailable):
            raise ProfileError("unavailable must name recommendable settings that have no value")
        if self.kind == KIND_RESEARCH:
            if self.model.kind == IDENTITY_MODEL:
                raise ProfileError(
                    "a research profile binds to an exact profile or a verified family, not one file"
                )
            covered = {name for note in self.evidence for name in note.fields}
            missing = set(clean) - covered
            if missing:
                raise ProfileError(
                    f"research settings without evidence: {', '.join(sorted(missing))}"
                )
            if any(
                note.source_class in (SOURCE_OPERATOR, SOURCE_LEARNING) for note in self.evidence
            ):
                raise ProfileError("a research profile cannot cite operator or learning evidence")
        if self.kind == KIND_LEARNING and not self.provenance:
            raise ProfileError("a learning profile must carry its evidence provenance")
        if self.kind != KIND_RESEARCH and self.model.kind == IDENTITY_FAMILY:
            raise ProfileError("only research profiles may bind to a whole family")

    @property
    def ref(self) -> ProfileRef:
        return ProfileRef(self.kind, self.profile_id, self.revision)

    def evidence_for(self, setting: str) -> EvidenceNote | None:
        return next((note for note in self.evidence if setting in note.fields), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "revision": self.revision,
            "kind": self.kind,
            "name": self.name,
            "model": self.model.to_dict(),
            "settings": dict(self.settings),
            "unavailable": dict(self.unavailable),
            "evidence": [note.to_dict() for note in self.evidence],
            "operations": list(self.operations),
            "executable_profile": dict(self.executable_profile)
            if self.executable_profile
            else None,
            "provenance": copy.deepcopy(dict(self.provenance)),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GenerationProfile:
        if not isinstance(data, Mapping):
            raise ProfileError("profile must be an object")
        evidence = data.get("evidence", [])
        operations = data.get("operations", ["txt2img"])
        if not isinstance(evidence, list) or not isinstance(operations, list):
            raise ProfileError("evidence and operations must be lists")
        settings = data.get("settings")
        unavailable = data.get("unavailable", {})
        provenance = data.get("provenance", {})
        if (
            not isinstance(settings, Mapping)
            or not isinstance(unavailable, Mapping)
            or not isinstance(provenance, Mapping)
        ):
            raise ProfileError("settings, unavailable and provenance must be objects")
        executable = data.get("executable_profile")
        if executable is not None and not isinstance(executable, Mapping):
            raise ProfileError("executable_profile must be an object")
        revision = data.get("revision")
        schema = data.get("schema_version")
        if isinstance(schema, bool) or not isinstance(schema, int):
            raise ProfileError("schema_version must be a whole number")
        if isinstance(revision, bool) or not isinstance(revision, int):
            raise ProfileError("revision must be a whole number")
        return cls(
            profile_id=_text(data.get("profile_id"), "profile id"),
            revision=revision,
            kind=_text(data.get("kind"), "kind"),
            name=_text(data.get("name"), "name"),
            model=ModelIdentity.from_dict(data.get("model") or {}),
            settings=dict(settings),
            unavailable=dict(unavailable),
            evidence=tuple(EvidenceNote.from_dict(item) for item in evidence),
            operations=tuple(_text(item, "operation") for item in operations),
            executable_profile=dict(executable) if executable else None,
            provenance=copy.deepcopy(dict(provenance)),
            created_at=_text(data.get("created_at", ""), "created_at", allow_empty=True),
            schema_version=schema,
        )


@dataclass(frozen=True)
class ProfileRef:
    """A pointer to one profile. ``revision`` ``None`` means "the latest valid revision" (custom/learning only)."""

    kind: str
    profile_id: str
    revision: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "profile_id": self.profile_id, "revision": self.revision}

    @classmethod
    def from_dict(cls, data: Any) -> ProfileRef:
        if not isinstance(data, Mapping):
            raise ProfileError("profile reference must be an object")
        revision = data.get("revision")
        if revision is not None and (
            isinstance(revision, bool) or not isinstance(revision, int) or revision < 1
        ):
            raise ProfileError("profile reference revision must be a positive whole number or null")
        kind = _text(data.get("kind"), "kind")
        if kind not in PROFILE_KINDS:
            raise ProfileError(f"unknown profile kind '{kind}'")
        return cls(kind, _text(data.get("profile_id"), "profile id"), revision)


__all__ = [
    "IDENTITY_EXACT",
    "IDENTITY_FAMILY",
    "IDENTITY_MODEL",
    "KIND_CUSTOM",
    "KIND_LEARNING",
    "KIND_RESEARCH",
    "SCHEMA_VERSION",
    "SETTING_KEYS",
    "SOURCE_CLASSES",
    "SOURCE_INFERRED",
    "SOURCE_LEARNING",
    "SOURCE_OFFICIAL",
    "SOURCE_OPERATOR",
    "SOURCE_STABLENEW_TESTED",
    "SOURCE_UNVERIFIED",
    "EvidenceNote",
    "GenerationProfile",
    "ModelIdentity",
    "ProfileError",
    "ProfileRef",
    "validate_settings",
]
