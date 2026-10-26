"""Controller adapter for model-aware generation profiles and startup defaults (PR-IMG-PROFILE-630).

Thin orchestration between the Tk-free :class:`GenerationProfileService` and the Pipeline tab. It reads and writes only
the editable *working* Base Generation settings through the Base Generation panel's small override seam; it never builds a
job, never touches a PromptPack, a queued job or a Preview record, never scans or starts a runtime, and never enables a
stage because of a profile. The canonical execution path (Intent -> Compiler -> NJR -> JobService -> ...) is unchanged.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping, Sequence
from typing import Any

from src.generation_profiles.application import ApplicationPlan
from src.generation_profiles.contract import ProfileError, ProfileRef
from src.generation_profiles.service import GenerationProfileService, SelectionState
from src.generation_profiles.startup import (
    STAGE_NAMES,
    StartupRestorePlan,
    available_model_names,
    restored_generation_values,
)
from src.generation_profiles.store import GenerationProfileStore
from src.gui_v2.generation_profile_projection import (
    StripView,
    build_strip_view,
    effective_profile_lines,
)

logger = logging.getLogger(__name__)

#: Panel override key -> profile setting key.
_PANEL_TO_SETTING = {
    "sampler": "sampler_name",
    "scheduler": "scheduler",
    "steps": "steps",
    "cfg_scale": "cfg_scale",
    "width": "width",
    "height": "height",
    "vae_name": "vae",
}


def draft_staleness_notices(
    entries: Sequence[Any],
    *,
    current_flags: Mapping[str, bool],
    built_with: Mapping[str, Any] | None,
    override_enabled: bool | None,
    current_profile: str,
) -> tuple[str, ...]:
    """Why the compiled Preview may not match what the working settings say now (empty when it does)."""

    if not entries:
        return ()
    notices: list[str] = []
    changed = []
    for stage in STAGE_NAMES:
        frozen = {bool(getattr(entry, "stage_flags", {}).get(stage, False)) for entry in entries}
        if frozen != {bool(current_flags.get(stage, False))}:
            changed.append(f"{stage} is {'on' if current_flags.get(stage) else 'off'} now")
    if changed:
        notices.append(
            "The draft was built with different stages than are selected now ("
            + "; ".join(changed)
            + "). Add the packs to the job again to apply the change."
        )
    if built_with is not None:
        if (
            override_enabled is not None
            and built_with.get("override") is not None
            and built_with["override"] != override_enabled
        ):
            notices.append(
                "The pack-settings override was switched "
                + ("on" if override_enabled else "off")
                + " after these packs were added. Add them again to apply it."
            )
        if built_with.get("profile") is not None and built_with["profile"] != current_profile:
            notices.append(
                "The model or generation profile changed after these packs were added; the draft keeps the earlier values. "
                "Add the packs again to use the current ones."
            )
    return tuple(notices)


class GenerationProfileController:
    def __init__(self, host: Any, service: GenerationProfileService | None = None) -> None:
        self._host = host
        self._service = service
        self._last_model: str | None = None
        self._last_plan: ApplicationPlan | None = None
        self._built_with: dict[str, Any] | None = None
        self._startup_issues: tuple[str, ...] = ()
        self._startup_model: str | None = None
        self._listeners: list[Callable[[], None]] = []

    # ------------------------------------------------------------------ plumbing

    @property
    def service(self) -> GenerationProfileService:
        if self._service is None:
            self._service = GenerationProfileService(GenerationProfileStore())
        return self._service

    def add_listener(self, listener: Callable[[], None]) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def notify_changed(self) -> None:
        """A stage flag, the override or a working value changed: let listeners (the Preview) re-read."""
        self._changed()

    def _changed(self) -> None:
        for listener in tuple(self._listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001 - a view refresh must never break a settings change
                logger.debug("generation profile listener failed", exc_info=True)

    def _log(self, message: str) -> None:
        append = getattr(self._host, "_append_log", None)
        if callable(append):
            append(f"[profiles] {message}")

    def _panel(self) -> Any:
        sidebar = self._host._get_sidebar_panel()
        getter = getattr(sidebar, "get_base_generation_panel", None)
        return getter() if callable(getter) else None

    def working_values(self) -> dict[str, Any]:
        """The editable Base Generation values, keyed by profile setting name (plus ``model``)."""

        panel = self._panel()
        if panel is None or not hasattr(panel, "get_overrides"):
            return {}
        overrides = panel.get_overrides()
        values = {_PANEL_TO_SETTING[k]: overrides[k] for k in _PANEL_TO_SETTING if k in overrides}
        values["model"] = str(overrides.get("model") or "")
        return values

    def current_model(self) -> str:
        return str(self.working_values().get("model") or "")

    def catalogs(self) -> dict[str, Collection[str]]:
        resources = getattr(getattr(self._host, "app_state", None), "resources", None)
        if not isinstance(resources, Mapping):
            return {}
        catalogs: dict[str, Collection[str]] = {}
        for key in ("samplers", "schedulers", "vaes"):
            entries = resources.get(key)
            if isinstance(entries, (list, tuple)) and entries:
                catalogs[key] = [str(getattr(item, "name", item)) for item in entries]
        return catalogs

    def _available_models(self) -> set[str] | None:
        resources = getattr(getattr(self._host, "app_state", None), "resources", None)
        return available_model_names(resources)

    def _apply_to_panel(self, changes: Mapping[str, Any]) -> None:
        panel = self._panel()
        if panel is not None and changes and hasattr(panel, "apply_profile_values"):
            panel.apply_profile_values(dict(changes))

    # ------------------------------------------------------------------ view

    def state(self) -> SelectionState | None:
        values = self.working_values()
        model = str(values.get("model") or "")
        return self.service.state_for(model, values) if model else None

    def strip_view(self) -> StripView:
        return build_strip_view(self.state(), self._last_plan)

    def profile_label(self) -> str:
        state = self.state()
        if state is None or state.selected is None:
            return ""
        return f"{state.selected.kind}:{state.selected.profile_id}:{state.selected.revision}"

    # ------------------------------------------------------------------ events from the Base Generation panel

    def on_model_chosen(self, model_name: str) -> ApplicationPlan | None:
        """The operator picked a checkpoint: apply its preferred profile to the working settings immediately."""

        name = str(model_name or "").strip()
        if not name or name == self._last_model:
            return None
        self._last_model = name
        values = self.working_values()
        values["model"] = name
        plan, _state = self.service.on_model_changed(name, values, catalogs=self.catalogs())
        self._apply_to_panel(plan.changes)
        self._last_plan = plan
        self._log(plan.message)
        self._changed()
        return plan

    def note_model(self, model_name: str) -> None:
        """Record the current model without applying anything (startup restore, programmatic loads)."""

        self._last_model = str(model_name or "").strip() or None

    def on_profile_selected(self, ref: ProfileRef | None) -> ApplicationPlan | None:
        if ref is None:
            self._last_plan = None
            self.service.clear_selection(self.current_model())
            self._changed()
            return None
        model = self.current_model()
        plan, _state = self.service.select(
            model, ref, self.working_values(), catalogs=self.catalogs()
        )
        self._apply_to_panel(plan.changes)
        self._last_plan = plan
        self._log(plan.message)
        self._changed()
        return plan

    def on_restore_selected(self) -> ApplicationPlan:
        model = self.current_model()
        plan, _state = self.service.restore_selected(
            model, self.working_values(), catalogs=self.catalogs()
        )
        self._apply_to_panel(plan.changes)
        self._last_plan = plan
        self._log(plan.message)
        self._changed()
        return plan

    def on_save_custom(self, name: str, *, update: bool = False) -> tuple[bool, str]:
        model = self.current_model()
        if not model:
            return False, "Select a model before saving a profile."
        state = self.state()
        update_ref = state.selected if update and state is not None else None
        if state is not None and update_ref is not None and not name:
            name = next(
                (
                    o.profile.name
                    for o in state.options
                    if o.ref.profile_id == update_ref.profile_id
                ),
                "",
            )
        try:
            profile = self.service.save_custom(
                name, model, self.working_values(), update_ref=update_ref
            )
        except (ProfileError, RuntimeError) as exc:
            self._log(f"Custom profile not saved: {exc}")
            return False, f"The profile was not saved. {exc}"
        self._last_plan = None
        self._changed()
        verb = "Saved a new revision of" if update_ref is not None else "Saved"
        return (
            True,
            f"{verb} Custom profile '{profile.name}' (revision {profile.revision}) for this model.",
        )

    def on_toggle_favorite(self) -> tuple[bool, str]:
        state = self.state()
        if state is None or state.selected is None:
            return False, "Select a profile first."
        option = next(
            (o for o in state.options if o.ref.profile_id == state.selected.profile_id), None
        )
        try:
            self.service.set_favorite(
                state.model_name, None if option is not None and option.favorite else state.selected
            )
        except (ProfileError, RuntimeError) as exc:
            return False, f"The favorite was not changed. {exc}"
        self._changed()
        return (
            True,
            "Removed the favorite for this model."
            if option is not None and option.favorite
            else "This profile is now the favorite for this model.",
        )

    # ------------------------------------------------------------------ Preview / draft truth

    def note_draft_built(self) -> None:
        """Remember what the working settings were when packs were added to the job draft."""

        self._built_with = {
            "override": getattr(self._host, "override_pack_config_enabled", None),
            "profile": self.profile_label() + "|" + self.current_model(),
        }

    def clear_draft_record(self) -> None:
        self._built_with = None

    def draft_notices(self) -> tuple[str, ...]:
        draft = getattr(getattr(self._host, "app_state", None), "job_draft", None)
        entries = list(getattr(draft, "packs", None) or [])
        try:
            flags = self._host._build_stage_flags()
        except Exception:  # noqa: BLE001 - unreadable stage state: say nothing rather than guess
            return ()
        override = getattr(self._host, "override_pack_config_enabled", None)
        return draft_staleness_notices(
            entries,
            current_flags=flags,
            built_with=self._built_with,
            override_enabled=override if isinstance(override, bool) else None,
            current_profile=self.profile_label() + "|" + self.current_model(),
        )

    def effective_lines(self) -> tuple[str, ...]:
        override = getattr(self._host, "override_pack_config_enabled", None)
        return effective_profile_lines(
            self.state(), override_enabled=override if isinstance(override, bool) else None
        )

    # ------------------------------------------------------------------ startup defaults

    def save_startup_defaults(self) -> tuple[bool, str]:
        """Persist the current configuration as startup defaults. Returns what actually happened."""

        values = self.working_values()
        model = str(values.pop("model", "") or "")
        if not model:
            return False, "Select a model first."
        try:
            flags = {
                k: bool(v) for k, v in self._host._build_stage_flags().items() if k in STAGE_NAMES
            }
            stage_settings = self._host._collect_current_stage_configs()
            record = self.service.save_startup_defaults(model, values, flags, stage_settings)
        except (ProfileError, RuntimeError, OSError) as exc:
            self._log(f"Startup defaults not saved: {exc}")
            return False, str(exc)
        profile = f" with profile '{record.profile.profile_id}'" if record.profile else ""
        return (
            True,
            f"Saved startup defaults for {record.model_name}{profile}. They are used the next time StableNew starts.",
        )

    def restore_startup_defaults(self) -> StartupRestorePlan | None:
        """Apply saved startup defaults to the working settings. Reports what could not be restored; launches nothing."""

        try:
            defaults, plan = self.service.plan_startup(
                available_models=self._available_models(), catalogs=self.catalogs()
            )
        except Exception as exc:  # noqa: BLE001 - startup must never fail because of a profile file
            logger.warning("startup defaults not restored: %s", exc)
            return None
        if plan is None:
            return None
        self._startup_issues = plan.issues
        for issue in plan.issues:
            self._log(issue)
        if not plan.restores_anything or defaults is None:
            self._changed()
            return plan
        values = restored_generation_values(plan, self.working_values())
        stage_config = dict(plan.stage_settings)
        pipeline = dict(stage_config.get("pipeline") or {})
        for stage, enabled in plan.stage_flags.items():
            pipeline[f"{stage}_enabled"] = bool(enabled)
        stage_config["pipeline"] = pipeline
        if stage_config:
            apply = getattr(self._host, "_apply_last_run_payload", None)
            if callable(apply):
                apply(stage_config, None)
        self._apply_to_panel(values)
        self.note_model(plan.model_name or "")
        sidebar = self._host._get_sidebar_panel()
        marker = getattr(sidebar, "set_settings_source", None)
        if callable(marker):
            marker("startup")
        self._log(f"Restored startup defaults for {plan.model_name}.")
        self._startup_model = plan.model_name
        self._changed()
        return plan

    def on_resources_updated(self, resources: Mapping[str, Any] | None) -> None:
        """Once the runtime publishes its model list, report a saved startup model it does not offer (no substitution)."""

        if self._startup_model is None or not isinstance(resources, Mapping):
            return
        models = available_model_names(resources)
        if models is None:
            return
        startup_model = self._startup_model

        def validate() -> None:
            if self._startup_model != startup_model:
                return
            if startup_model not in models:
                message = (
                    f"Saved startup model '{startup_model}' is not offered by the runtime; "
                    "your current selection was kept."
                )
                self._startup_issues = (*self._startup_issues, message)
                self._log(message)
            self._startup_model = None
            self._changed()

        dispatch = getattr(self._host, "_run_in_gui_thread", None)
        if callable(dispatch):
            dispatch(validate)
        else:
            validate()

    @property
    def startup_issues(self) -> tuple[str, ...]:
        return self._startup_issues


__all__ = ["GenerationProfileController", "draft_staleness_notices"]
