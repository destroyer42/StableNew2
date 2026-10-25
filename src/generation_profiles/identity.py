"""Resolve which model a selected checkpoint is, and whether a saved profile belongs to it (PR-IMG-PROFILE-630).

Identity comes from the executable-policy authority first (``resolve_model_policy``: exact profile by whole-name match,
else ``AssetRegistry`` family evidence), then from a whole-name key and, when the registry snapshot already knows it,
the file's SHA-256. Nothing here scans, hashes a model file, or touches the network, so it is safe on the Tk thread. A
profile never attaches to a checkpoint by a filename substring, and a same-named file whose bytes differ is a conflict.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.generation_profiles.contract import (
    IDENTITY_EXACT,
    IDENTITY_FAMILY,
    IDENTITY_MODEL,
    ModelIdentity,
)
from src.image_backends.model_policy import (
    EVIDENCE_REGISTRY,
    FAMILY_UNKNOWN,
    FamilyLookup,
    ModelPolicy,
    RegistryFamilyLookup,
    resolve_model_policy,
)
from src.image_backends.model_readiness_probe import checkpoint_key

#: model name -> SHA-256 already recorded by the registry snapshot, or ``None`` (unknown or ambiguous).
ShaLookup = Callable[[str], str | None]

MATCH_EXACT = "matched"
MATCH_RENAMED = "matched_renamed"
MATCH_UNVERIFIED_BYTES = "matched_name_only"
MATCH_CONFLICT = "conflict"
MATCH_OTHER_MODEL = "other_model"


class RegistryShaLookup:
    """SHA-256 of a checkpoint from the persisted registry snapshot only (never computed here)."""

    def __init__(self, registry: Any | None = None) -> None:
        self._registry = registry

    def __call__(self, model_name: str) -> str | None:
        try:
            from src.assets import AssetKind, AssetRegistry

            registry = self._registry if self._registry is not None else AssetRegistry()
            if getattr(registry, "webui_root", None) is None:
                return None
            key = checkpoint_key(model_name)
            digests = set()
            for record in registry.cached_snapshot().records_for(AssetKind.CHECKPOINT):
                for location in record.locations:
                    if (
                        location.kind is AssetKind.CHECKPOINT
                        and checkpoint_key(Path(location.path).name) == key
                    ):
                        verified = registry.verified_sha256(Path(location.path))
                        digests.add(verified if verified == record.sha256 else None)
        except Exception:  # noqa: BLE001 - absent evidence, never a guess
            return None
        return next(iter(digests)) if len(digests) == 1 else None


@dataclass(frozen=True)
class ResolvedModel:
    """The identity of the selected checkpoint plus the executable policy that governs it."""

    identity: ModelIdentity
    policy: ModelPolicy
    #: Why no profile identity can be established ("" when the family is verified or the profile exact).
    unverified_reason: str = ""

    @property
    def verified_family(self) -> bool:
        return (
            self.policy.evidence in ("exact_profile", EVIDENCE_REGISTRY)
            and self.policy.family != FAMILY_UNKNOWN
        )


class ModelIdentityResolver:
    def __init__(
        self,
        *,
        family_lookup: FamilyLookup | None = None,
        sha_lookup: ShaLookup | None = None,
        policy_resolver: Callable[[str | None], ModelPolicy] | None = None,
    ) -> None:
        self._family_lookup: FamilyLookup = (
            family_lookup if family_lookup is not None else RegistryFamilyLookup()
        )
        self._sha_lookup: ShaLookup = sha_lookup if sha_lookup is not None else RegistryShaLookup()
        self._policy_resolver = policy_resolver

    def resolve(self, model_name: str | None) -> ResolvedModel:
        name = str(model_name or "").strip()
        policy = (
            self._policy_resolver(name)
            if self._policy_resolver is not None
            else resolve_model_policy(name, family_lookup=self._family_lookup)
        )
        key = checkpoint_key(name)
        if policy.exact_identity_authority and policy.profile_ref:
            return ResolvedModel(
                ModelIdentity(
                    kind=IDENTITY_EXACT,
                    key=f"exact:{policy.profile_ref['id']}",
                    family=policy.family,
                    display_name=policy.display_name,
                    exact_profile=dict(policy.profile_ref),
                    model_key=key,
                ),
                policy,
            )
        if not key:
            return ResolvedModel(_unverified(key, "unknown"), policy, "No checkpoint is selected.")
        sha = self._safe_sha(name)
        if policy.evidence == EVIDENCE_REGISTRY and policy.family != FAMILY_UNKNOWN:
            reason = (
                ""
                if policy.qualified or policy.family == "sdxl"
                else (
                    f"The registry labels this checkpoint {policy.family}, but StableNew has not qualified that family."
                )
            )
            return ResolvedModel(
                ModelIdentity(
                    kind=IDENTITY_MODEL,
                    key=f"model:{policy.family}:{key}",
                    family=policy.family,
                    display_name=name,
                    model_key=key,
                    sha256=sha,
                ),
                policy,
                reason,
            )
        reason = {
            "conflicting_evidence": "The registry has conflicting evidence for this checkpoint.",
            "unknown_evidence": "The registry could not classify this checkpoint.",
        }.get(
            policy.evidence,
            "No registry evidence for this checkpoint yet; refresh resources to classify it.",
        )
        return ResolvedModel(_unverified(key, name, sha), policy, reason)

    def _safe_sha(self, name: str) -> str | None:
        try:
            value = self._sha_lookup(name)
        except Exception:  # noqa: BLE001
            return None
        return value if isinstance(value, str) and len(value) == 64 else None


def _unverified(key: str, name: str, sha: str | None = None) -> ModelIdentity:
    return ModelIdentity(
        kind=IDENTITY_MODEL,
        key=f"model:{FAMILY_UNKNOWN}:{key or 'none'}",
        family=FAMILY_UNKNOWN,
        display_name=name,
        model_key=key or "none",
        sha256=sha,
    )


@dataclass(frozen=True)
class IdentityMatch:
    status: str
    reason: str = ""

    @property
    def applies(self) -> bool:
        return self.status in (MATCH_EXACT, MATCH_RENAMED, MATCH_UNVERIFIED_BYTES)


def match_identity(saved: ModelIdentity, current: ModelIdentity) -> IdentityMatch:
    """Whether a profile written for ``saved`` may be offered for ``current``. Conflicts are never resolved by picking."""

    if saved.kind == IDENTITY_FAMILY:
        if (
            current.kind == IDENTITY_MODEL
            and current.family == saved.family
            and current.family != FAMILY_UNKNOWN
        ):
            return IdentityMatch(MATCH_EXACT)
        return IdentityMatch(MATCH_OTHER_MODEL)
    if saved.kind == IDENTITY_EXACT:
        same = current.kind == IDENTITY_EXACT and (current.exact_profile or {}).get("id") == (
            saved.exact_profile or {}
        ).get("id")
        return IdentityMatch(MATCH_EXACT) if same else IdentityMatch(MATCH_OTHER_MODEL)
    if current.kind != IDENTITY_MODEL or saved.family != current.family:
        return IdentityMatch(MATCH_OTHER_MODEL)
    if saved.sha256 and current.sha256:
        if saved.sha256 != current.sha256:
            reason = (
                "A checkpoint with this name has different bytes than the one the profile was saved for."
                if saved.model_key == current.model_key
                else "This is a different checkpoint."
            )
            return IdentityMatch(
                MATCH_CONFLICT if saved.model_key == current.model_key else MATCH_OTHER_MODEL,
                reason,
            )
        return IdentityMatch(
            MATCH_EXACT if saved.model_key == current.model_key else MATCH_RENAMED,
            "" if saved.model_key == current.model_key else "Same file contents under a new name.",
        )
    if saved.model_key == current.model_key:
        return IdentityMatch(
            MATCH_UNVERIFIED_BYTES, "Matched by file name; the file contents are not verified."
        )
    return IdentityMatch(MATCH_OTHER_MODEL)


def match_learning_identity(saved: ModelIdentity, current: ModelIdentity) -> IdentityMatch:
    """Learning findings require frozen bytes or an identical executable profile version.

    Kept separate from Research/Custom matching so their historical semantics are unchanged.
    """
    if saved.kind == IDENTITY_EXACT:
        if (saved.exact_profile or {}).get("version") is None or dict(
            saved.exact_profile or {}
        ) != dict(current.exact_profile or {}):
            return IdentityMatch(
                MATCH_CONFLICT, "Learning profile executable version differs; nothing was applied."
            )
    elif not saved.sha256 or not current.sha256:
        return IdentityMatch(
            MATCH_CONFLICT, "Learning profile checkpoint bytes are unverified; nothing was applied."
        )
    return match_identity(saved, current)


__all__ = [
    "MATCH_CONFLICT",
    "MATCH_EXACT",
    "MATCH_OTHER_MODEL",
    "MATCH_RENAMED",
    "MATCH_UNVERIFIED_BYTES",
    "IdentityMatch",
    "ModelIdentityResolver",
    "RegistryShaLookup",
    "ResolvedModel",
    "ShaLookup",
    "match_identity",
]
