"""Application-owned, versioned store for generation-settings profiles, favorites and startup defaults (PR-IMG-PROFILE-630).

Separate from the retired Generation Presets, from saved PromptPacks and from the engine settings. Layout under the
per-user directory::

    profiles/custom/<profile id>/r0001.json   one immutable file per revision
    profiles/learning/<profile id>/r0001.json
    favorites.json                            model identity key -> profile reference
    startup_defaults.json                     the operator's saved startup configuration

Mutable files use :func:`atomic_write_json`; Learning revisions use atomic no-replace publication.
A revision is never rewritten: a change is the next revision, and a malformed or incompatible revision file is skipped
(and reported) so the last valid revision keeps being used. Names live only inside the JSON, never in a path, so spaces
and Unicode names are safe. Nothing here touches PromptPack files or the executable model policy.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.generation_profiles.contract import (
    IDENTITY_FAMILY,
    KIND_CUSTOM,
    KIND_LEARNING,
    SOURCE_OPERATOR,
    EvidenceNote,
    GenerationProfile,
    ModelIdentity,
    ProfileError,
    ProfileRef,
    validate_settings,
)
from src.utils.atomic_io import atomic_publish_json, atomic_write_json

logger = logging.getLogger(__name__)

GENERATION_PROFILE_DIR_ENV = "STABLENEW_GENERATION_PROFILE_DIR"
_FAVORITES_FILE = "favorites.json"
_STARTUP_FILE = "startup_defaults.json"
_REVISION_RE = re.compile(r"^r(\d{4,})\.json$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")
_FILE_SCHEMA = 1


class ProfileStoreError(RuntimeError):
    """A write could not be completed; the previous stored content is unchanged."""


def resolve_generation_profile_dir(
    explicit: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    system_name: str | None = None,
    home_dir: str | Path | None = None,
) -> Path:
    """The per-user profile directory, without creating it (explicit, then ``STABLENEW_GENERATION_PROFILE_DIR``, then the platform default)."""

    if explicit is not None:
        return Path(explicit)
    environment = os.environ if environ is None else environ
    configured = environment.get(GENERATION_PROFILE_DIR_ENV)
    if configured:
        return Path(configured)
    home = Path(home_dir) if home_dir is not None else Path.home()
    if (system_name or platform.system()) == "Windows":
        local = environment.get("LOCALAPPDATA")
        base = Path(local) if local else home / "AppData" / "Local"
        return base / "StableNew" / "GenerationProfiles"
    data_home = environment.get("XDG_DATA_HOME")
    return (
        (Path(data_home) if data_home else home / ".local" / "share")
        / "StableNew"
        / "GenerationProfiles"
    )


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class GenerationProfileStore:
    def __init__(self, root: str | Path | None = None, *, clock: Callable[[], str] = _now) -> None:
        self._root = resolve_generation_profile_dir(root)
        self._clock = clock
        #: Human-readable reasons stored records were skipped during the latest reads (bounded).
        self.diagnostics: list[str] = []

    @property
    def root(self) -> Path:
        return self._root

    def now(self) -> str:
        return self._clock()

    # ------------------------------------------------------------------ paths and files

    def _profile_dir(self, kind: str, profile_id: str) -> Path:
        if kind not in (KIND_CUSTOM, KIND_LEARNING) or not _ID_RE.match(profile_id):
            raise ProfileError(f"'{profile_id}' is not a storable {kind} profile id")
        return self._root / "profiles" / kind / profile_id

    @staticmethod
    def _revision_file(directory: Path, revision: int) -> Path:
        return directory / f"r{revision:04d}.json"

    def _note(self, message: str) -> None:
        logger.warning("generation profiles: %s", message)
        if len(self.diagnostics) < 50:
            self.diagnostics.append(message)

    def _read_json(self, path: Path) -> Any:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def _write(self, path: Path, payload: Any) -> None:
        try:
            atomic_write_json(path, payload, indent=2, ensure_ascii=False)
        except (OSError, TypeError, ValueError) as exc:
            raise ProfileStoreError(f"Could not write {path.name}: {exc}") from exc

    # ------------------------------------------------------------------ revisions

    def revisions(self, kind: str, profile_id: str) -> list[GenerationProfile]:
        """Valid revisions of one profile, oldest first. Malformed or incompatible files are skipped and reported."""

        try:
            directory = self._profile_dir(kind, profile_id)
        except ProfileError:
            return []
        found: dict[int, GenerationProfile] = {}
        if not directory.is_dir():
            return []
        for path in sorted(directory.iterdir()):
            match = _REVISION_RE.match(path.name)
            if not match:
                continue
            try:
                profile = GenerationProfile.from_dict(self._read_json(path))
                if (
                    profile.profile_id != profile_id
                    or profile.kind != kind
                    or profile.revision != int(match.group(1))
                ):
                    raise ProfileError("file name and content disagree")
                found[profile.revision] = profile
            except (OSError, ValueError, ProfileError) as exc:  # json errors are ValueError
                self._note(f"skipped {kind}/{profile_id}/{path.name}: {exc}")
        return [found[number] for number in sorted(found)]

    def load(self, ref: ProfileRef) -> GenerationProfile | None:
        """The referenced revision, or the latest valid one when the reference does not pin a revision."""

        history = self.revisions(ref.kind, ref.profile_id)
        if not history:
            return None
        if ref.revision is None:
            return history[-1]
        return next((item for item in history if item.revision == ref.revision), None)

    def list_latest(self, kind: str) -> list[GenerationProfile]:
        """The latest valid revision of every stored profile of ``kind``."""

        base = self._root / "profiles" / kind
        if not base.is_dir():
            return []
        latest = []
        for directory in sorted(base.iterdir()):
            if directory.is_dir():
                history = self.revisions(kind, directory.name)
                if history:
                    latest.append(history[-1])
        return latest

    def _next_revision(self, kind: str, profile_id: str) -> int:
        directory = self._profile_dir(kind, profile_id)
        numbers = (
            [int(m.group(1)) for p in directory.iterdir() if (m := _REVISION_RE.match(p.name))]
            if directory.is_dir()
            else []
        )
        return max(numbers, default=0) + 1

    def _publish(self, profile: GenerationProfile) -> GenerationProfile:
        directory = self._profile_dir(profile.kind, profile.profile_id)
        path = self._revision_file(directory, profile.revision)
        if path.exists():
            raise ProfileStoreError(
                f"Revision {profile.revision} of {profile.profile_id} already exists; revisions are immutable."
            )
        self._write(path, profile.to_dict())
        return profile

    # ------------------------------------------------------------------ custom profiles (operator-owned)

    def save_custom(
        self,
        name: str,
        model: ModelIdentity,
        settings: Mapping[str, Any],
        *,
        profile_id: str | None = None,
        unavailable: Mapping[str, str] | None = None,
    ) -> GenerationProfile:
        """Save ``settings`` as a new Custom profile, or as the next revision of ``profile_id``.

        A Custom profile belongs to the model it was created for; it cannot be re-pointed at another checkpoint.
        """

        if model.kind == IDENTITY_FAMILY:
            raise ProfileError("A Custom profile belongs to one model, not a whole family.")
        clean = validate_settings(settings)
        new_id = profile_id or f"custom-{uuid.uuid4().hex[:12]}"
        revision = 1
        if profile_id is not None:
            history = self.revisions(KIND_CUSTOM, profile_id)
            if not history and self._profile_dir(KIND_CUSTOM, profile_id).is_dir():
                raise ProfileStoreError(
                    f"{profile_id} has stored files but no valid revision; it was not overwritten."
                )
            if history:
                if history[-1].model.key != model.key:
                    raise ProfileError(
                        "A Custom profile cannot be moved to another model; save a new one."
                    )
                name = name or history[-1].name
            revision = self._next_revision(KIND_CUSTOM, profile_id)
        profile = GenerationProfile(
            profile_id=new_id,
            revision=revision,
            kind=KIND_CUSTOM,
            name=name,
            model=model,
            settings=clean,
            unavailable={k: v for k, v in dict(unavailable or {}).items() if k not in clean},
            evidence=(
                EvidenceNote(
                    fields=tuple(clean) or ("steps",),
                    source_class=SOURCE_OPERATOR,
                    rationale="Values the operator saved from their working configuration.",
                ),
            )
            if clean
            else (),
            provenance={"owner": "operator"},
            created_at=self._clock(),
        )
        return self._publish(profile)

    def delete_custom(self, profile_id: str) -> bool:
        """Remove one Custom profile's files. Jobs already frozen keep their own settings; nothing else is touched."""

        directory = self._profile_dir(KIND_CUSTOM, profile_id)
        if not directory.is_dir():
            return False
        try:
            shutil.rmtree(directory)
        except OSError as exc:
            raise ProfileStoreError(f"Could not delete {profile_id}: {exc}") from exc
        return True

    # ------------------------------------------------------------------ learning seam

    def publish_learning_profile(self, profile: GenerationProfile) -> GenerationProfile:
        """Publish one new immutable Learning revision (the seam LEARN-PROFILE-660 will call).

        Only a Learning profile whose revision is exactly the next one is accepted, and it is validated before any
        byte is written. Custom and Research data are never touched by this call.
        """

        if profile.kind != KIND_LEARNING:
            raise ProfileError("Only a learning profile can be published here.")
        expected = self._next_revision(KIND_LEARNING, profile.profile_id)
        if profile.revision != expected:
            raise ProfileError(f"Learning revision must be {expected}, not {profile.revision}.")
        previous = self.revisions(KIND_LEARNING, profile.profile_id)
        if previous and previous[-1].model != profile.model:
            raise ProfileError("A Learning profile lineage cannot change its model.")
        validated = GenerationProfile.from_dict(profile.to_dict())
        directory = self._profile_dir(KIND_LEARNING, validated.profile_id)
        path = self._revision_file(directory, validated.revision)
        try:
            atomic_publish_json(path, validated.to_dict(), indent=2, ensure_ascii=False)
        except (OSError, TypeError, ValueError) as exc:
            raise ProfileStoreError(
                f"Could not publish immutable Learning revision: {exc}"
            ) from exc
        return validated

    # ------------------------------------------------------------------ favorites

    def favorites(self) -> dict[str, ProfileRef]:
        path = self._root / _FAVORITES_FILE
        if not path.exists():
            return {}
        try:
            data = self._read_json(path)
            entries = data["favorites"]
            return {str(key): ProfileRef.from_dict(value) for key, value in entries.items()}
        except (OSError, ValueError, KeyError, TypeError, AttributeError, ProfileError) as exc:
            self._note(f"favorites file ignored: {exc}")
            return {}

    def favorite_for(self, identity_key: str) -> ProfileRef | None:
        return self.favorites().get(identity_key)

    def set_favorite(self, identity_key: str, ref: ProfileRef | None) -> None:
        """Point (or, with ``None``, un-point) one model's favorite. Other models' favorites are preserved."""

        path = self._root / _FAVORITES_FILE
        current = self.favorites()
        if path.exists() and not current:
            try:  # keep an unreadable file for inspection instead of silently replacing it
                self._read_json(path)
            except (OSError, ValueError):
                shutil.copy2(path, path.with_name(_FAVORITES_FILE + ".corrupt"))
        if ref is None:
            current.pop(identity_key, None)
        else:
            current[identity_key] = ref
        self._write(
            path,
            {
                "schema_version": _FILE_SCHEMA,
                "favorites": {key: value.to_dict() for key, value in sorted(current.items())},
            },
        )

    # ------------------------------------------------------------------ startup defaults

    def load_startup_document(self) -> dict[str, Any] | None:
        path = self._root / _STARTUP_FILE
        if not path.exists():
            return None
        try:
            data = self._read_json(path)
        except (OSError, ValueError) as exc:
            self._note(f"startup defaults ignored: {exc}")
            return None
        return data if isinstance(data, dict) else None

    def save_startup_document(self, document: Mapping[str, Any]) -> Path:
        path = self._root / _STARTUP_FILE
        self._write(path, dict(document))
        return path


__all__ = [
    "GENERATION_PROFILE_DIR_ENV",
    "GenerationProfileStore",
    "ProfileStoreError",
    "resolve_generation_profile_dir",
]
