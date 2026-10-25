"""Tk-free session service for generation-settings profiles (PR-IMG-PROFILE-630).

Owns the profile catalog (built-in Research profiles plus the app-owned store), the per-model selection, favorites, Save
as Custom, restore-selected and startup defaults. It works on plain dictionaries of Base Generation values, so the
controller adapter and the GUI strip stay thin and every rule is testable without Tk. It never queues, compiles or runs a
job, never scans or starts a runtime, and never writes PromptPacks.

Preferred profile for a model: the operator's favorite for it (when it still exists and still applies), else the built-in
Research profile for that exact model or verified family, else none. Learning profiles are offered in the selector but
only become preferred when the operator favorites one.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from typing import Any

from src.generation_profiles.application import (
    STATUS_NO_PROFILE,
    STATUS_PROFILE_MISSING,
    ApplicationPlan,
    plan_application,
    policy_blocks,
)
from src.generation_profiles.contract import (
    IDENTITY_FAMILY,
    KIND_CUSTOM,
    KIND_LEARNING,
    KIND_RESEARCH,
    SETTING_KEYS,
    GenerationProfile,
    ModelIdentity,
    ProfileError,
    ProfileRef,
)
from src.generation_profiles.identity import (
    IdentityMatch,
    ModelIdentityResolver,
    ResolvedModel,
    match_identity,
)
from src.generation_profiles.research import research_profiles
from src.generation_profiles.startup import (
    StartupDefaults,
    StartupRestorePlan,
    build_startup_defaults,
    plan_startup_restore,
)
from src.generation_profiles.store import GenerationProfileStore, ProfileStoreError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProfileOption:
    """One row of the selector for the current model."""

    profile: GenerationProfile
    match: IdentityMatch
    favorite: bool = False

    @property
    def ref(self) -> ProfileRef:
        return self.profile.ref

    @property
    def label(self) -> str:
        kind = {KIND_RESEARCH: "Research", KIND_LEARNING: "Learning", KIND_CUSTOM: "Custom"}[
            self.profile.kind
        ]
        star = " *" if self.favorite else ""
        return f"{kind}: {self.profile.name}{star}"


@dataclass(frozen=True)
class SelectionState:
    """What the strip shows for the current model."""

    model_name: str
    identity: ModelIdentity
    unverified_reason: str
    options: tuple[ProfileOption, ...]
    selected: ProfileRef | None
    #: Working values differ from the selected profile's recommendations.
    modified: bool = False


class GenerationProfileService:
    def __init__(
        self,
        store: GenerationProfileStore | None = None,
        resolver: ModelIdentityResolver | None = None,
        *,
        research: Callable[[], tuple[GenerationProfile, ...]] = research_profiles,
    ) -> None:
        self._store = store if store is not None else GenerationProfileStore()
        self._resolver = resolver if resolver is not None else ModelIdentityResolver()
        self._research = research
        self._selected: dict[str, ProfileRef] = {}
        self._last_family: str | None = None

    @property
    def store(self) -> GenerationProfileStore:
        return self._store

    # ------------------------------------------------------------------ catalog

    def resolve(self, model_name: str | None) -> ResolvedModel:
        return self._resolver.resolve(model_name)

    def _catalog(self) -> list[GenerationProfile]:
        return [
            *self._research(),
            *self._store.list_latest(KIND_LEARNING),
            *self._store.list_latest(KIND_CUSTOM),
        ]

    def options_for(self, identity: ModelIdentity) -> tuple[ProfileOption, ...]:
        favorite = self._store.favorite_for(identity.key)
        options = []
        for profile in self._catalog():
            match = match_identity(profile.model, identity)
            if match.applies:
                is_fav = bool(
                    favorite
                    and favorite.kind == profile.kind
                    and favorite.profile_id == profile.profile_id
                )
                options.append(ProfileOption(profile, match, is_fav))
        order = {KIND_RESEARCH: 0, KIND_LEARNING: 1, KIND_CUSTOM: 2}
        return tuple(sorted(options, key=lambda o: (order[o.profile.kind], o.profile.name.lower())))

    def get(self, ref: ProfileRef) -> GenerationProfile | None:
        if ref.kind == KIND_RESEARCH:
            return next((p for p in self._research() if p.profile_id == ref.profile_id), None)
        return self._store.load(ref)

    def preferred_ref(self, identity: ModelIdentity) -> tuple[ProfileRef | None, ProfileRef | None]:
        """``(preferred, missing)``: the profile to apply, and a favorite that points at a profile that is gone."""

        favorite = self._store.favorite_for(identity.key)
        missing: ProfileRef | None = None
        if favorite is not None:
            profile = self.get(favorite)
            if profile is not None and match_identity(profile.model, identity).applies:
                return profile.ref, None
            missing = favorite
        options = [o for o in self.options_for(identity) if o.profile.kind == KIND_RESEARCH]
        return (options[0].ref if options else None), missing

    # ------------------------------------------------------------------ selection and application

    def state_for(
        self, model_name: str, working: Mapping[str, Any] | None = None
    ) -> SelectionState:
        resolved = self.resolve(model_name)
        options = self.options_for(resolved.identity)
        selected = self._selected.get(resolved.identity.key)
        if selected is not None and not any(
            o.ref.profile_id == selected.profile_id and o.ref.kind == selected.kind for o in options
        ):
            selected = None
        modified = False
        if selected is not None and working is not None:
            profile = self.get(selected)
            modified = bool(
                profile
                and any(
                    _differs(working.get(k), v)
                    for k, v in profile.settings.items()
                    if not policy_blocks(resolved.policy, k, v)
                )
            )
        return SelectionState(
            model_name, resolved.identity, resolved.unverified_reason, options, selected, modified
        )

    def on_model_changed(
        self,
        model_name: str,
        working: Mapping[str, Any],
        *,
        catalogs: Mapping[str, Collection[str]] | None = None,
    ) -> tuple[ApplicationPlan, SelectionState]:
        """The operator picked a model: plan the preferred profile onto ``working`` (the caller applies the changes)."""

        resolved = self.resolve(model_name)
        preferred, missing = self.preferred_ref(resolved.identity)
        profile = self.get(preferred) if preferred else None
        previous_family = self._last_family
        self._last_family = resolved.identity.family
        if profile is None:
            plan = plan_application(
                profile=None,
                match=None,
                working=working,
                policy=resolved.policy,
                catalogs=catalogs,
                previous_family=previous_family,
                current_family=resolved.identity.family,
                missing_ref=missing,
            )
            self._selected.pop(resolved.identity.key, None)
        else:
            plan = plan_application(
                profile=profile,
                match=match_identity(profile.model, resolved.identity),
                working=working,
                policy=resolved.policy,
                catalogs=catalogs,
                previous_family=previous_family,
                current_family=resolved.identity.family,
            )
            self._selected[resolved.identity.key] = profile.ref
        merged = {**working, **plan.changes}
        return plan, self.state_for(model_name, merged)

    def select(
        self,
        model_name: str,
        ref: ProfileRef,
        working: Mapping[str, Any],
        *,
        catalogs: Mapping[str, Collection[str]] | None = None,
    ) -> tuple[ApplicationPlan, SelectionState]:
        """The operator chose a profile in the selector (or pressed Restore on the current one)."""

        resolved = self.resolve(model_name)
        profile = self.get(ref)
        plan = plan_application(
            profile=profile,
            match=match_identity(profile.model, resolved.identity) if profile else None,
            working=working,
            policy=resolved.policy,
            catalogs=catalogs,
            current_family=resolved.identity.family,
            previous_family=resolved.identity.family,
            missing_ref=ref if profile is None else None,
        )
        if (
            profile is not None
            and plan.status not in (STATUS_NO_PROFILE, STATUS_PROFILE_MISSING)
            and plan.profile == profile.ref
        ):
            if plan.status != "identity_conflict":
                self._selected[resolved.identity.key] = profile.ref
        return plan, self.state_for(model_name, {**working, **plan.changes})

    def clear_selection(self, model_name: str) -> None:
        """The operator chose "no profile": keep the working values, forget the selection for this model."""

        self._selected.pop(self.resolve(model_name).identity.key, None)

    def restore_selected(
        self,
        model_name: str,
        working: Mapping[str, Any],
        *,
        catalogs: Mapping[str, Collection[str]] | None = None,
    ) -> tuple[ApplicationPlan, SelectionState]:
        resolved = self.resolve(model_name)
        ref = self._selected.get(resolved.identity.key)
        if ref is None:
            plan = plan_application(
                profile=None, match=None, working=working, policy=resolved.policy, catalogs=catalogs
            )
            return plan, self.state_for(model_name, working)
        return self.select(model_name, ref, working, catalogs=catalogs)

    # ------------------------------------------------------------------ custom profiles and favorites

    def save_custom(
        self,
        name: str,
        model_name: str,
        working: Mapping[str, Any],
        *,
        update_ref: ProfileRef | None = None,
    ) -> GenerationProfile:
        """Save the working Base Generation values as a Custom profile (new, or the next revision of ``update_ref``).

        Values the executable policy owns are not recorded, so a Custom profile can never claim to override them.
        """

        resolved = self.resolve(model_name)
        if (
            resolved.identity.kind == IDENTITY_FAMILY
        ):  # pragma: no cover - resolver never returns a family
            raise ProfileError("A Custom profile belongs to one model.")
        values = {key: working[key] for key in SETTING_KEYS if working.get(key) not in (None,)}
        owned = {key for key in values if policy_blocks(resolved.policy, key, values[key])}
        values = {key: value for key, value in values.items() if key not in owned}
        profile_id = None
        if update_ref is not None:
            if update_ref.kind != KIND_CUSTOM:
                raise ProfileError(
                    "Only a Custom profile can be updated; use Save as Custom to keep a copy."
                )
            profile_id = update_ref.profile_id
        profile = self._store.save_custom(
            name.strip() or "Custom profile",
            resolved.identity,
            values,
            profile_id=profile_id,
            unavailable=dict.fromkeys(owned, "Owned by this model's executable profile."),
        )
        self._selected[resolved.identity.key] = profile.ref
        return profile

    def delete_custom(self, profile_id: str) -> bool:
        removed = self._store.delete_custom(profile_id)
        self._selected = {
            k: v
            for k, v in self._selected.items()
            if not (v.kind == KIND_CUSTOM and v.profile_id == profile_id)
        }
        return removed

    def set_favorite(self, model_name: str, ref: ProfileRef | None) -> None:
        identity = self.resolve(model_name).identity
        if ref is not None:
            profile = self.get(ref)
            if profile is None or not match_identity(profile.model, identity).applies:
                raise ProfileError("That profile does not apply to the selected model.")
            # A favorite follows the latest Custom/Learning revision; Research is pinned to its revision.
            ref = ProfileRef(
                ref.kind, ref.profile_id, ref.revision if ref.kind == KIND_RESEARCH else None
            )
        self._store.set_favorite(identity.key, ref)

    # ------------------------------------------------------------------ startup defaults

    def startup_defaults(self) -> StartupDefaults | None:
        document = self._store.load_startup_document()
        if document is None:
            return None
        try:
            return StartupDefaults.from_document(document)
        except ProfileError as exc:
            logger.warning("startup defaults ignored: %s", exc)
            self._store.diagnostics.append(f"startup defaults ignored: {exc}")
            return None

    def save_startup_defaults(
        self,
        model_name: str,
        working: Mapping[str, Any],
        stage_flags: Mapping[str, Any],
        stage_settings: Mapping[str, Any],
        saved_at: str = "",
    ) -> StartupDefaults:
        """Persist the current configuration as startup defaults. Raises with a plain message when nothing was written."""

        resolved = self.resolve(model_name)
        selected = self._selected.get(resolved.identity.key)
        record = build_startup_defaults(
            model_name=model_name,
            model=resolved.identity,
            profile=selected,
            generation=working,
            stage_flags=stage_flags,
            stage_settings=stage_settings,
            saved_at=saved_at or self._store.now(),
        )
        try:
            self._store.save_startup_document(record.to_document())
        except ProfileStoreError as exc:
            raise ProfileError(str(exc)) from exc
        return record

    def plan_startup(
        self,
        *,
        available_models: Collection[str] | None,
        catalogs: Mapping[str, Collection[str]] | None = None,
    ) -> tuple[StartupDefaults | None, StartupRestorePlan | None]:
        defaults = self.startup_defaults()
        if defaults is None:
            return None, None
        plan = plan_startup_restore(
            defaults,
            current_identity=self.resolve(defaults.model_name).identity,
            available_models=available_models,
            catalogs=catalogs,
        )
        if plan.model_name is not None and defaults.profile is not None:
            profile = self.get(defaults.profile)
            if profile is not None:
                self._selected[defaults.model.key] = profile.ref
                self._selected[self.resolve(defaults.model_name).identity.key] = profile.ref
            else:
                plan = StartupRestorePlan(
                    plan.model_name,
                    None,
                    plan.generation,
                    plan.stage_flags,
                    plan.stage_settings,
                    (
                        *plan.issues,
                        "The profile saved with the startup defaults is no longer available; its values were restored as saved.",
                    ),
                )
        if plan.model_name is not None:
            self._last_family = self.resolve(plan.model_name).identity.family
        return defaults, plan


def _differs(left: Any, right: Any) -> bool:
    try:
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return abs(float(left) - float(right)) > 1e-9
    except (TypeError, ValueError):
        pass
    return str(left if left is not None else "") != str(right if right is not None else "")


__all__ = ["GenerationProfileService", "ProfileOption", "SelectionState"]
