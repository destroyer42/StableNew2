"""Deterministic planning of how a profile lands on the working Base Generation settings (PR-IMG-PROFILE-630).

Pure functions over plain dicts: no Tk, no files, no network, no controller. A plan says which values would be written to
the editable working configuration, which were kept or refused and why. The executable model policy stays final: a value
the policy fixes, restricts or does not support is never written, and the plan says so. A profile cannot carry stage
enablement (``validate_settings`` refuses it), so applying one never switches ADetailer, upscale or any other stage.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import Any

from src.generation_profiles.contract import (
    IDENTITY_EXACT,
    KIND_LEARNING,
    SETTING_CFG,
    SETTING_HEIGHT,
    SETTING_SAMPLER,
    SETTING_SCHEDULER,
    SETTING_STEPS,
    SETTING_VAE,
    SETTING_WIDTH,
    GenerationProfile,
    ProfileRef,
)
from src.generation_profiles.identity import IdentityMatch
from src.image_backends.model_policy import (
    CONTROL_CFG,
    CONTROL_GEOMETRY,
    CONTROL_SAMPLER,
    CONTROL_SCHEDULER,
    CONTROL_STEPS,
    CONTROL_VAE,
    ControlMode,
    ModelPolicy,
)

STATUS_APPLIED = "applied"
STATUS_NO_CHANGE = "no_change"
STATUS_NO_PROFILE = "no_profile"
STATUS_PROFILE_MISSING = "profile_missing"
STATUS_IDENTITY_CONFLICT = "identity_conflict"

NOTE_APPLIED = "applied"
NOTE_UNCHANGED = "unchanged"
NOTE_UNAVAILABLE = "unavailable"
NOTE_POLICY = "policy_owned"
NOTE_NOT_OFFERED = "not_offered"
NOTE_RESET = "reset"
NOTE_KEPT = "kept"

_CONTROL_OF = {
    SETTING_SAMPLER: CONTROL_SAMPLER,
    SETTING_SCHEDULER: CONTROL_SCHEDULER,
    SETTING_STEPS: CONTROL_STEPS,
    SETTING_CFG: CONTROL_CFG,
    SETTING_VAE: CONTROL_VAE,
}
#: Settings whose meaning is tied to the family that produced them; they are not carried to another family.
_FAMILY_BOUND = (SETTING_VAE,)


@dataclass(frozen=True)
class SettingNote:
    key: str
    status: str
    message: str
    old: Any = None
    new: Any = None


@dataclass(frozen=True)
class ApplicationPlan:
    status: str
    profile: ProfileRef | None
    #: Values to write to the working configuration (only keys that actually change).
    changes: Mapping[str, Any] = field(default_factory=dict)
    notes: tuple[SettingNote, ...] = ()
    message: str = ""

    @property
    def conflicts(self) -> tuple[SettingNote, ...]:
        return tuple(
            n
            for n in self.notes
            if n.status in (NOTE_POLICY, NOTE_NOT_OFFERED, NOTE_RESET, NOTE_UNAVAILABLE)
        )

    def note_for(self, key: str) -> SettingNote | None:
        return next((n for n in self.notes if n.key == key), None)


def _same(left: Any, right: Any) -> bool:
    try:
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return abs(float(left) - float(right)) < 1e-9
    except (TypeError, ValueError):
        pass
    return str(left if left is not None else "") == str(right if right is not None else "")


def policy_blocks(policy: ModelPolicy | None, key: str, value: Any) -> str:
    """Why the executable policy refuses ``value`` for ``key`` ('' when it allows it)."""

    if policy is None:
        return ""
    if key in (SETTING_WIDTH, SETTING_HEIGHT):
        control = policy.control(CONTROL_GEOMETRY)
        if control.mode is not ControlMode.CONFIGURABLE:
            return "this model's geometry is fixed by its executable profile"
        return ""
    control = policy.control(_CONTROL_OF[key])
    if control.mode is not ControlMode.CONFIGURABLE:
        return "this model's executable profile owns this setting"
    return ""


def _allowed_geometry(policy: ModelPolicy | None) -> tuple[tuple[int, int], ...]:
    if policy is None:
        return ()
    allowed = policy.control(CONTROL_GEOMETRY).allowed
    pairs = []
    for item in allowed:
        try:
            pairs.append((int(item[0]), int(item[1])))
        except (TypeError, ValueError, IndexError, KeyError):
            continue
    return tuple(pairs)


def plan_application(
    *,
    profile: GenerationProfile | None,
    match: IdentityMatch | None,
    working: Mapping[str, Any],
    policy: ModelPolicy | None = None,
    catalogs: Mapping[str, Collection[str]] | None = None,
    previous_family: str | None = None,
    current_family: str | None = None,
    missing_ref: ProfileRef | None = None,
) -> ApplicationPlan:
    """Plan applying ``profile`` to ``working`` (keys are ``SETTING_KEYS`` names).

    ``catalogs`` optionally lists what the runtime currently offers (``samplers``, ``schedulers``, ``vaes``); a value that
    is not offered is reported and not written. ``previous_family``/``current_family`` let a family change drop a VAE that
    belonged to the previous model even when the new profile has no VAE recommendation.
    """

    notes: list[SettingNote] = []
    changes: dict[str, Any] = {}
    family_changed = bool(previous_family and current_family and previous_family != current_family)

    if profile is None:
        status = STATUS_PROFILE_MISSING if missing_ref is not None else STATUS_NO_PROFILE
        message = (
            "The selected profile is no longer available; the current settings were kept."
            if missing_ref is not None
            else "No profile is available for this model; the current settings were kept."
        )
        plan_notes = _carry_over(
            notes, changes, working, policy, catalogs, family_changed, set(), set()
        )
        return ApplicationPlan(status, missing_ref, changes, tuple(plan_notes), message)

    if match is not None and not match.applies:
        message = match.reason or "This profile belongs to a different model; nothing was applied."
        return ApplicationPlan(STATUS_IDENTITY_CONFLICT, profile.ref, {}, (), message)

    if (
        profile.kind == KIND_LEARNING
        and profile.model.kind == IDENTITY_EXACT
        and (
            not policy
            or not (profile.model.exact_profile or {}).get("version")
            or dict(profile.model.exact_profile or {}) != dict(policy.profile_ref or {})
            or dict(profile.executable_profile or {}) != dict(policy.profile_ref or {})
        )
    ):
        return ApplicationPlan(
            STATUS_IDENTITY_CONFLICT,
            profile.ref,
            {},
            (),
            "Learning profile executable version differs; nothing was applied.",
        )

    geometry_pairs = _allowed_geometry(policy)
    covered: set[str] = set()
    for key, value in profile.settings.items():
        covered.add(key)
        old = working.get(key)
        blocked = policy_blocks(policy, key, value)
        if blocked:
            notes.append(
                SettingNote(key, NOTE_POLICY, f"{_label(key)} not applied: {blocked}.", old, value)
            )
            continue
        catalog_key = {
            SETTING_SAMPLER: "samplers",
            SETTING_SCHEDULER: "schedulers",
            SETTING_VAE: "vaes",
        }.get(key)
        if (
            catalog_key
            and catalogs
            and catalogs.get(catalog_key)
            and value not in catalogs[catalog_key]
            and value != ""
        ):
            notes.append(
                SettingNote(
                    key,
                    NOTE_NOT_OFFERED,
                    f"{_label(key)} '{value}' is not offered by the runtime; kept '{old}'.",
                    old,
                    value,
                )
            )
            continue
        if key in (SETTING_WIDTH, SETTING_HEIGHT) and geometry_pairs:
            width = profile.settings.get(SETTING_WIDTH)
            height = profile.settings.get(SETTING_HEIGHT)
            if (width, height) not in geometry_pairs:
                notes.append(
                    SettingNote(
                        key,
                        NOTE_POLICY,
                        "Size not applied: it is not one of this model's qualified sizes.",
                        old,
                        value,
                    )
                )
                continue
        if _same(old, value):
            notes.append(
                SettingNote(key, NOTE_UNCHANGED, f"{_label(key)} already matches.", old, value)
            )
        else:
            changes[key] = value
            notes.append(
                SettingNote(
                    key, NOTE_APPLIED, f"{_label(key)}: {_show(old)} -> {_show(value)}.", old, value
                )
            )
    for key, reason in profile.unavailable.items():
        covered.add(key)
        notes.append(
            SettingNote(
                key,
                NOTE_UNAVAILABLE,
                f"No recommended {_label(key).lower()}: {reason}",
                working.get(key),
                None,
            )
        )
    _carry_over(
        notes, changes, working, policy, catalogs, family_changed, covered, set(profile.settings)
    )
    status = STATUS_APPLIED if changes else STATUS_NO_CHANGE
    message = (
        f"Applied {profile.name}."
        if changes
        else f"{profile.name} already matches the current settings."
    )
    return ApplicationPlan(status, profile.ref, changes, tuple(notes), message)


def _carry_over(
    notes: list[SettingNote],
    changes: dict[str, Any],
    working: Mapping[str, Any],
    policy: ModelPolicy | None,
    catalogs: Mapping[str, Collection[str]] | None,
    family_changed: bool,
    covered: set[str],
    recommended: set[str],
) -> list[SettingNote]:
    """Settings the profile did not set: keep legal values, drop ones that cannot belong to the new model."""

    for key in _FAMILY_BOUND:
        # "No recommendation" for a VAE is not permission to keep one that belonged to another family.
        if key in recommended or key in changes:
            continue
        current = working.get(key)
        if family_changed and current:
            changes[key] = ""
            notes.append(
                SettingNote(
                    key,
                    NOTE_RESET,
                    "VAE reset to the model's own: a VAE does not carry across model families.",
                    current,
                    "",
                )
            )
    for key in (SETTING_SAMPLER, SETTING_SCHEDULER):
        if key in covered:
            continue
        current = working.get(key)
        catalog = (catalogs or {}).get("samplers" if key == SETTING_SAMPLER else "schedulers")
        if current and catalog and current not in catalog:
            notes.append(
                SettingNote(
                    key,
                    NOTE_NOT_OFFERED,
                    f"{_label(key)} '{current}' is not offered by the runtime.",
                    current,
                    None,
                )
            )
        elif current:
            notes.append(
                SettingNote(
                    key,
                    NOTE_KEPT,
                    f"{_label(key)} kept: this profile has no recommendation.",
                    current,
                    None,
                )
            )
    return notes


_LABELS = {
    SETTING_SAMPLER: "Sampler",
    SETTING_SCHEDULER: "Scheduler",
    SETTING_STEPS: "Steps",
    SETTING_CFG: "CFG",
    SETTING_WIDTH: "Width",
    SETTING_HEIGHT: "Height",
    SETTING_VAE: "VAE",
}


def _label(key: str) -> str:
    return _LABELS.get(key, key)


def _show(value: Any) -> str:
    return "model default" if value in ("", None) else str(value)


__all__ = [
    "NOTE_APPLIED",
    "NOTE_KEPT",
    "NOTE_NOT_OFFERED",
    "NOTE_POLICY",
    "NOTE_RESET",
    "NOTE_UNAVAILABLE",
    "NOTE_UNCHANGED",
    "STATUS_APPLIED",
    "STATUS_IDENTITY_CONFLICT",
    "STATUS_NO_CHANGE",
    "STATUS_NO_PROFILE",
    "STATUS_PROFILE_MISSING",
    "ApplicationPlan",
    "SettingNote",
    "plan_application",
    "policy_blocks",
]
