"""Toolkit-neutral projection of the model's generation profiles for the Base Generation panel (PR-IMG-PROFILE-630).

Pure: takes the service's :class:`SelectionState` and the latest :class:`ApplicationPlan` and returns plain text and flags
the Tk strip renders, so every sentence the operator reads here is testable without a window. It never reads files,
runtimes or widgets, and never decides what a model may run (the executable policy does).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from src.generation_profiles.application import (
    NOTE_APPLIED,
    NOTE_KEPT,
    NOTE_NOT_OFFERED,
    NOTE_POLICY,
    NOTE_RESET,
    NOTE_UNAVAILABLE,
    STATUS_IDENTITY_CONFLICT,
    STATUS_NO_CHANGE,
    STATUS_NO_PROFILE,
    STATUS_PROFILE_MISSING,
    ApplicationPlan,
)
from src.generation_profiles.contract import (
    KIND_CUSTOM,
    SETTING_KEYS,
    SOURCE_INFERRED,
    SOURCE_LEARNING,
    SOURCE_OFFICIAL,
    SOURCE_OPERATOR,
    SOURCE_STABLENEW_TESTED,
    SOURCE_UNVERIFIED,
    GenerationProfile,
    ProfileRef,
)
from src.generation_profiles.service import ProfileOption, SelectionState

SOURCE_LABELS: Mapping[str, str] = {
    SOURCE_OFFICIAL: "Official model recommendation",
    SOURCE_STABLENEW_TESTED: "StableNew-tested",
    SOURCE_INFERRED: "Community or inferred suggestion",
    SOURCE_UNVERIFIED: "Unverified",
    SOURCE_OPERATOR: "Saved by you",
    SOURCE_LEARNING: "Learning evidence",
}
NO_PROFILE_LABEL = "No profile (keep current settings)"
NO_MODEL_TEXT = "Select a model to see its profiles."
_SETTING_NAMES = {
    "sampler_name": "Sampler",
    "scheduler": "Scheduler",
    "steps": "Steps",
    "cfg_scale": "CFG",
    "width": "Width",
    "height": "Height",
    "vae": "VAE",
}


@dataclass(frozen=True)
class StripView:
    labels: tuple[str, ...]
    #: Parallel to ``labels``; ``None`` is the "no profile" row.
    refs: tuple[ProfileRef | None, ...]
    selected_index: int
    status: str
    details: str
    can_restore: bool
    can_save: bool
    can_update_custom: bool
    favorite: bool
    can_favorite: bool


def _option_index(options: tuple[ProfileOption, ...], ref: ProfileRef | None) -> int:
    if ref is None:
        return -1
    for index, option in enumerate(options):
        if option.profile.kind == ref.kind and option.profile.profile_id == ref.profile_id:
            return index
    return -1


def evidence_text(profile: GenerationProfile) -> str:
    """Per-setting source classes and reasons, with the values that are deliberately missing."""

    lines = [f"{profile.name} (revision {profile.revision})"]
    for key in SETTING_KEYS:
        name = _SETTING_NAMES[key]
        if key in profile.settings:
            value = profile.settings[key]
            shown = "model default" if value == "" else str(value)
            note = profile.evidence_for(key)
            if note is None:
                lines.append(f"  {name}: {shown}")
                continue
            label = SOURCE_LABELS.get(note.source_class, note.source_class)
            citation = f" - {note.citation}" if note.citation else ""
            lines.append(f"  {name}: {shown} [{label}]{citation}")
            if note.rationale:
                lines.append(f"      {note.rationale}")
        elif key in profile.unavailable:
            lines.append(f"  {name}: no recommendation - {profile.unavailable[key]}")
    reviewed = sorted({note.reviewed_on for note in profile.evidence if note.reviewed_on})
    if reviewed:
        lines.append(f"Sources reviewed {', '.join(reviewed)}.")
    return "\n".join(lines)


def format_plan_message(plan: ApplicationPlan | None) -> str:
    """One truthful sentence (plus conflicts) about what the latest profile application did."""

    if plan is None:
        return ""
    if plan.status == STATUS_IDENTITY_CONFLICT:
        return plan.message
    if plan.status in (STATUS_NO_PROFILE, STATUS_PROFILE_MISSING):
        return plan.message
    parts = [plan.message]
    for note in plan.notes:
        if note.status in (NOTE_APPLIED, NOTE_POLICY, NOTE_NOT_OFFERED, NOTE_RESET):
            parts.append(note.message)
    if plan.status == STATUS_NO_CHANGE:
        return plan.message
    return " ".join(part for part in parts if part)


def build_strip_view(
    state: SelectionState | None,
    plan: ApplicationPlan | None = None,
) -> StripView:
    if state is None or not state.model_name:
        return StripView(
            (NO_PROFILE_LABEL,), (None,), 0, NO_MODEL_TEXT, "", False, False, False, False, False
        )
    labels = (NO_PROFILE_LABEL, *(option.label for option in state.options))
    refs: tuple[ProfileRef | None, ...] = (None, *(option.ref for option in state.options))
    index = _option_index(state.options, state.selected)
    selected_index = index + 1 if index >= 0 else 0
    status_parts: list[str] = []
    if state.selected is None:
        status_parts.append(
            state.unverified_reason or "No profile selected; your current settings are used."
        )
    elif state.modified:
        status_parts.append("Edited since the profile was applied (Restore returns to it).")
    message = format_plan_message(plan)
    if message:
        status_parts.append(message)
    selected_option = state.options[index] if index >= 0 else None
    details = ""
    if selected_option is not None:
        details = evidence_text(selected_option.profile)
        if selected_option.match.reason:
            details += f"\n{selected_option.match.reason}"
    return StripView(
        labels=labels,
        refs=refs,
        selected_index=selected_index,
        status=" ".join(status_parts),
        details=details,
        can_restore=state.selected is not None,
        can_save=True,
        can_update_custom=bool(selected_option and selected_option.profile.kind == KIND_CUSTOM),
        favorite=bool(selected_option and selected_option.favorite),
        can_favorite=selected_option is not None,
    )


def effective_profile_lines(
    state: SelectionState | None, *, override_enabled: bool | None
) -> tuple[str, ...]:
    """What the Preview's Effective Settings says about the working model and profile."""

    if state is None or not state.model_name:
        return ()
    lines = [
        f"Model: {state.model_name} ({state.identity.family}{'' if not state.unverified_reason else ', unverified'})"
    ]
    selected = next(
        (
            o
            for o in state.options
            if state.selected and o.ref.profile_id == state.selected.profile_id
        ),
        None,
    )
    if selected is None:
        lines.append(
            "Profile: none selected; the working Base Generation values are used as they are."
        )
    else:
        kind = selected.profile.kind.capitalize()
        edited = "; edited since applied" if state.modified else ""
        lines.append(
            f"Profile: {kind} - {selected.profile.name} (revision {selected.profile.revision}){edited}"
        )
    if override_enabled is True:
        lines.append(
            "Override is ON: PromptPacks added to the job use the working settings, so the profile values apply to them."
        )
    elif override_enabled is False:
        lines.append(
            "Override is OFF: PromptPacks keep their own saved settings; the profile only shaped the working settings."
        )
    return tuple(lines)


def format_kept_notes(plan: ApplicationPlan | None) -> tuple[str, ...]:
    """Notes about settings the profile left alone or could not recommend (shown under Details)."""

    if plan is None:
        return ()
    return tuple(n.message for n in plan.notes if n.status in (NOTE_KEPT, NOTE_UNAVAILABLE))


__all__ = [
    "NO_MODEL_TEXT",
    "NO_PROFILE_LABEL",
    "SOURCE_LABELS",
    "StripView",
    "build_strip_view",
    "effective_profile_lines",
    "evidence_text",
    "format_kept_notes",
    "format_plan_message",
]
