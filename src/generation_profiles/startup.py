"""Startup defaults: the operator's saved starting configuration, and how it is restored (PR-IMG-PROFILE-630).

Saved: the selected model with its profile identity, the selected profile reference, the Base Generation values, the stage
flags and the stage settings. Never saved: input or source image paths, masks and anchors, experiment or Learning
working state, active jobs, historical jobs, result paths, model files. The document is built from plain values, so
building and restoring it is deterministic and needs no Tk, no runtime and no scan.

Restore is a plan, not an action: it reports every saved value that is missing or no longer legal and never substitutes
a different model or value silently.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import Any

from src.generation_profiles.contract import (
    SETTING_KEYS,
    ModelIdentity,
    ProfileError,
    ProfileRef,
    validate_settings,
)
from src.generation_profiles.identity import MATCH_CONFLICT, MATCH_OTHER_MODEL, match_identity

STARTUP_SCHEMA = 1
STAGE_NAMES = ("txt2img", "img2img", "adetailer", "upscale")

#: Key fragments that mark per-job inputs, results or machine paths. Anything matching is dropped from stage settings.
_EXCLUDED_KEY = re.compile(
    r"(path|mask|anchor|init_image|input_image|source_image|image_file|images|experiment|learning|job_id|njr|history|result|output_dir|checkpoint_file|weights)",
    re.IGNORECASE,
)
_IMAGE_VALUE = re.compile(
    r"\.(png|jpe?g|webp|bmp|gif|tiff?|mp4|webm|safetensors|ckpt|gguf)$", re.IGNORECASE
)
_MAX_DEPTH = 6


def sanitize_stage_settings(value: Any, *, _depth: int = 0) -> Any:
    """A deep copy of ``value`` without excluded keys, image or weight file references and non-JSON values."""

    if _depth > _MAX_DEPTH:
        return None
    if isinstance(value, Mapping):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or _EXCLUDED_KEY.search(key):
                continue
            cleaned = sanitize_stage_settings(item, _depth=_depth + 1)
            if cleaned is not _DROP:
                clean[key] = cleaned
        return clean
    if isinstance(value, (list, tuple)):
        items = [sanitize_stage_settings(item, _depth=_depth + 1) for item in value]
        return [item for item in items if item is not _DROP]
    if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return _DROP if _IMAGE_VALUE.search(value.strip()) else value
    return _DROP


class _Drop:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<dropped>"


_DROP: Any = _Drop()


@dataclass(frozen=True)
class StartupDefaults:
    model_name: str
    model: ModelIdentity
    profile: ProfileRef | None
    generation: Mapping[str, Any]
    stage_flags: Mapping[str, bool]
    stage_settings: Mapping[str, Any]
    saved_at: str = ""

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_version": STARTUP_SCHEMA,
            "saved_at": self.saved_at,
            "model_name": self.model_name,
            "model": self.model.to_dict(),
            "profile": self.profile.to_dict() if self.profile else None,
            "generation": dict(self.generation),
            "stage_flags": dict(self.stage_flags),
            "stage_settings": copy.deepcopy(dict(self.stage_settings)),
        }

    @classmethod
    def from_document(cls, document: Any) -> StartupDefaults:
        """Parse a stored document. Raises :class:`ProfileError` for anything malformed or from a newer schema."""

        if not isinstance(document, Mapping):
            raise ProfileError("startup defaults must be an object")
        if document.get("schema_version") != STARTUP_SCHEMA:
            raise ProfileError(
                f"unsupported startup defaults schema {document.get('schema_version')!r}"
            )
        model_name = document.get("model_name")
        if not isinstance(model_name, str) or not model_name.strip():
            raise ProfileError("startup defaults need a model name")
        generation = document.get("generation")
        flags = document.get("stage_flags", {})
        settings = document.get("stage_settings", {})
        if (
            not isinstance(generation, Mapping)
            or not isinstance(flags, Mapping)
            or not isinstance(settings, Mapping)
        ):
            raise ProfileError("generation, stage_flags and stage_settings must be objects")
        profile = document.get("profile")
        saved_at = document.get("saved_at", "")
        return cls(
            model_name=model_name.strip(),
            model=ModelIdentity.from_dict(document.get("model") or {}),
            profile=ProfileRef.from_dict(profile) if profile else None,
            generation=validate_settings(generation),
            stage_flags={
                str(k): bool(v)
                for k, v in flags.items()
                if k in STAGE_NAMES and isinstance(v, bool)
            },
            stage_settings=sanitize_stage_settings(dict(settings)),
            saved_at=saved_at if isinstance(saved_at, str) else "",
        )


def build_startup_defaults(
    *,
    model_name: str,
    model: ModelIdentity,
    profile: ProfileRef | None,
    generation: Mapping[str, Any],
    stage_flags: Mapping[str, Any],
    stage_settings: Mapping[str, Any],
    saved_at: str = "",
) -> StartupDefaults:
    """Build a defaults record from the live working state, keeping only the allowed parts."""

    if not str(model_name or "").strip():
        raise ProfileError("Select a model before saving startup defaults.")
    return StartupDefaults(
        model_name=str(model_name).strip(),
        model=model,
        profile=profile,
        generation=validate_settings({k: v for k, v in generation.items() if k in SETTING_KEYS}),
        stage_flags={name: bool(stage_flags[name]) for name in STAGE_NAMES if name in stage_flags},
        stage_settings=sanitize_stage_settings(dict(stage_settings)),
        saved_at=saved_at,
    )


@dataclass(frozen=True)
class StartupRestorePlan:
    #: Model to select, or ``None`` when the saved model cannot be restored (nothing else is applied then).
    model_name: str | None
    profile: ProfileRef | None = None
    generation: Mapping[str, Any] = field(default_factory=dict)
    stage_flags: Mapping[str, bool] = field(default_factory=dict)
    stage_settings: Mapping[str, Any] = field(default_factory=dict)
    issues: tuple[str, ...] = ()

    @property
    def restores_anything(self) -> bool:
        return self.model_name is not None


def restored_generation_values(
    plan: StartupRestorePlan, working: Mapping[str, Any]
) -> dict[str, Any]:
    """Final shared Base Generation overlay after stage restoration.

    Rejected saved values retain the pre-restore working value, never the unchecked
    duplicate in stage settings or the stage loader's default.
    """
    return {
        **{key: value for key, value in working.items() if key in SETTING_KEYS},
        **plan.generation,
        "model": plan.model_name,
    }


def available_model_names(resources: Mapping[str, Any] | None) -> set[str] | None:
    """Names from this resource snapshot; None until a usable model list arrives."""
    entries = resources.get("models") if isinstance(resources, Mapping) else None
    if not isinstance(entries, (list, tuple)) or not entries:
        return None
    names: set[str] = set()
    for entry in entries:
        for attr in ("name", "display_name"):
            value = getattr(entry, attr, None)
            if value:
                names.add(str(value))
        if isinstance(entry, str) and entry:
            names.add(entry)
    return names or None


def plan_startup_restore(
    defaults: StartupDefaults,
    *,
    current_identity: ModelIdentity | None,
    available_models: Collection[str] | None,
    catalogs: Mapping[str, Collection[str]] | None = None,
) -> StartupRestorePlan:
    """What to restore at startup, and what to report instead. Never launches, scans or substitutes."""

    issues: list[str] = []
    if available_models is not None and defaults.model_name not in available_models:
        return StartupRestorePlan(
            None,
            issues=(
                f"Saved startup model '{defaults.model_name}' is not available; startup defaults were not applied "
                "and the current configuration was kept.",
            ),
        )
    if current_identity is not None:
        match = match_identity(defaults.model, current_identity)
        if match.status in (MATCH_CONFLICT, MATCH_OTHER_MODEL):
            return StartupRestorePlan(
                None,
                issues=(
                    "The saved startup model no longer matches the checkpoint of that name"
                    + (f" ({match.reason})" if match.reason else "")
                    + "; startup defaults were not applied.",
                ),
            )
    generation = dict(defaults.generation)
    for key, catalog_key in (
        ("sampler_name", "samplers"),
        ("scheduler", "schedulers"),
        ("vae", "vaes"),
    ):
        offered = (catalogs or {}).get(catalog_key)
        value = generation.get(key)
        if value and offered and value not in offered:
            issues.append(
                f"Saved {key.replace('_name', '')} '{value}' is not offered by the runtime and was not restored."
            )
            generation.pop(key)
    return StartupRestorePlan(
        defaults.model_name,
        defaults.profile,
        generation,
        dict(defaults.stage_flags),
        copy.deepcopy(dict(defaults.stage_settings)),
        tuple(issues),
    )


__all__ = [
    "STAGE_NAMES",
    "STARTUP_SCHEMA",
    "StartupDefaults",
    "StartupRestorePlan",
    "available_model_names",
    "build_startup_defaults",
    "plan_startup_restore",
    "restored_generation_values",
    "sanitize_stage_settings",
]
