"""Truthful wording for the Pipeline's settings sources, actions and empty states (PR-GUI-UX-500, PR-GUI-UX-520, PR-IMG-PROFILE-630).

Pure and toolkit-independent. The Pipeline sidebar mixes four things that look alike and are not:

* a **PromptPack**: an authored prompt file that also stores its own **PromptPack Settings**;
* a **generation profile**: model-aware recommended Base Generation values (Research, Learning or Custom), chosen next to
  the model selector; the retired named "Generation Presets" no longer exist;
* a **Saved Pack List**: a named group of PromptPacks that only filters the pack list, never settings;
* the **working stage settings** (with any unsaved **Current Job Overrides**): what the stage cards and sidebar hold now.

This module owns the words and the small decisions behind them (what to say when a list is empty, which settings
the next job will use, what an apply will write, how a result is reported). It reads and writes nothing; persistence and
the compile path are unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

SOURCE_WORKING = "working"
SOURCE_PACK = "pack"
SOURCE_STARTUP = "startup"

PACK_LIST_FILENAME = "state/custom_pack_lists.json"

NO_PACK_LISTS_TEXT = (
    f"No Saved Pack Lists. A pack list only filters the PromptPacks shown here (it holds no settings) and is read from "
    f"{PACK_LIST_FILENAME}; this version has no in-app action to create one, so all PromptPacks are shown."
)

PACK_SELECTOR_HELP = (
    "PromptPacks are authored in the Prompt tab. Select one or more to add to the draft job. "
    "Load Pack Settings copies a pack's saved settings into the working stage settings; "
    "Apply to PromptPack overwrites the saved settings of the selected packs."
)

LOAD_PACK_CONFIG_LABEL = "Load Pack Settings"
APPLY_PACK_CONFIG_LABEL = "Apply to PromptPack…"
# Kept so existing references keep resolving; the button text is count-aware (see ``apply_button_label``).
SAVE_PACK_CONFIG_LABEL = APPLY_PACK_CONFIG_LABEL
LOAD_PACK_CONFIG_TIP = (
    "Copies the selected PromptPack's saved settings into the working stage settings, replacing the values there. "
    "The pack is not changed."
)
SAVE_PACK_CONFIG_TIP = (
    "Writes the current stage settings into the saved settings of each selected PromptPack, after you confirm. "
    "This changes the pack files; their prompts, Matrix and order are not touched."
)
ADD_TO_JOB_TIP = (
    "Adds the selected PromptPacks to the draft job. Nothing is generated until the job is queued."
)

SAVE_STARTUP_DEFAULTS_LABEL = "Save Current Settings as Startup Defaults"
SAVE_STARTUP_DEFAULTS_TIP = (
    "Remembers the model, its profile, the Base Generation values, which stages are on and their settings, and uses "
    "them the next time StableNew starts. Images, masks, results, jobs and Learning experiments are not saved."
)

OVERRIDE_OFF_TEXT = "PromptPacks added to the job keep their own saved settings."
OVERRIDE_ON_TEXT = (
    "Current Job Overrides: PromptPacks added to the job use the current stage settings instead of their own "
    "saved settings. Nothing is written to the packs."
)


def override_description(enabled: bool) -> str:
    """What the 'override pack configs' checkbox decides, at the moment a pack is added to the job."""

    return OVERRIDE_ON_TEXT if enabled else OVERRIDE_OFF_TEXT


@dataclass(frozen=True)
class SettingsSource:
    """Where the working stage settings were last loaded from. Later stage edits are not tracked."""

    kind: str = SOURCE_WORKING
    name: str = ""

    def describe(self) -> str:
        if self.kind == SOURCE_STARTUP:
            return "Working settings, restored from your saved startup defaults"
        if self.kind == SOURCE_PACK and self.name:
            return f"Working stage settings, last loaded from PromptPack Settings of '{self.name}'"
        return "Working stage settings (no PromptPack settings or startup defaults loaded)"


def source_status_text(source: SettingsSource) -> str:
    """Compact indicator of what the working settings were last loaded from."""

    return f"In use: {source.describe()}"


def startup_save_result_text(ok: bool, message: str) -> str:
    """Inline status after Save Current Settings as Startup Defaults: the controller's own words, never a guess."""

    if ok:
        return message or "Saved the current settings as your startup defaults."
    return f"Startup defaults were not saved. {message}".strip()


def startup_save_unavailable_text() -> str:
    return "Startup defaults cannot be saved here: no controller is connected."


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def pack_selector_status(
    *,
    shown: int,
    hidden_by_visibility: int,
    packs_dir: str,
    list_name: str,
    list_matched: bool,
) -> str:
    """One status line for the pack list: how many are shown and why, or why there are none."""

    if shown <= 0:
        if hidden_by_visibility > 0:
            return (
                f"{_plural(hidden_by_visibility, 'PromptPack')} hidden by the content-visibility setting. "
                "Change it to show them."
            )
        where = f" in {packs_dir}" if packs_dir else ""
        return f"No PromptPacks found{where}. Create one in the Prompt tab (New, then Save), then press Refresh."
    text = f"Showing {_plural(shown, 'PromptPack')}"
    if list_name and list_matched:
        text += f" from Saved Pack List '{list_name}'."
    elif list_name:
        text += f": Saved Pack List '{list_name}' matches none of them, so all are shown."
    else:
        text += "."
    return text


PACK_LIST_CAPTION = "Saved Pack List (optional filter):"


def pack_list_caption(saved_list_count: int) -> str:
    """Caption above the saved-pack-list dropdown; when there are none it explains why and how they appear."""

    return PACK_LIST_CAPTION if saved_list_count > 0 else NO_PACK_LISTS_TEXT


# ---------------------------------------------------------------------------------------------------------------------
# PR-GUI-UX-520: explicit apply / load / overwrite feedback
# ---------------------------------------------------------------------------------------------------------------------

#: Packs named in a confirmation or result before the list is summarized as "and N more".
_NAMED_PACK_LIMIT = 5


def apply_button_label(selected_count: int) -> str:
    """The apply button names its target count so the operator sees what a click will rewrite."""

    if selected_count <= 0:
        return APPLY_PACK_CONFIG_LABEL
    if selected_count == 1:
        return "Apply to 1 Pack…"
    return f"Apply to {selected_count} Packs…"


def _pack_names(pack_ids: Sequence[str]) -> str:
    names = [str(item) for item in pack_ids]
    shown = ", ".join(f"'{name}'" for name in names[:_NAMED_PACK_LIMIT])
    extra = len(names) - _NAMED_PACK_LIMIT
    return shown + (f" and {extra} more" if extra > 0 else "")


def apply_confirmation_text(source: str, pack_ids: Sequence[str]) -> tuple[str, str]:
    """(title, message) asking the operator to confirm that saved PromptPack settings will be overwritten."""

    target = _plural(len(pack_ids), "PromptPack")
    return (
        "Apply settings to PromptPacks",
        f"Overwrite the saved settings of {target} ({_pack_names(pack_ids)}) with {source}?\n\n"
        "This updates the pack files on disk. Their prompts, Matrix and slot order are not changed, and the settings "
        "they have now are replaced. Nothing is queued.",
    )


def apply_result_text(
    source: str, succeeded: Sequence[str], failed: Sequence[tuple[str, str]]
) -> str:
    """One truthful line (plus failure detail) for the inline status after an apply."""

    total = len(succeeded) + len(failed)
    if total == 0:
        return "No PromptPack was selected; nothing was changed."
    if not failed:
        return f"Applied {source} to {_plural(len(succeeded), 'PromptPack')}: {_pack_names(succeeded)}."
    lines = []
    if succeeded:
        lines.append(
            f"Partly applied {source}: updated {len(succeeded)} of {total} "
            f"({_pack_names(succeeded)}). The others were left unchanged."
        )
    else:
        lines.append(f"Could not apply {source}: no PromptPack was changed.")
    for pack_id, reason in failed[:_NAMED_PACK_LIMIT]:
        lines.append(f"Not updated '{pack_id}': {reason or 'unknown error'}")
    if len(failed) > _NAMED_PACK_LIMIT:
        lines.append(f"...and {len(failed) - _NAMED_PACK_LIMIT} more not updated.")
    return "\n".join(lines)


def replace_working_confirmation_text(source: str) -> tuple[str, str]:
    """(title, message) when loading would replace stage settings the operator has edited since the last load."""

    return (
        "Replace unsaved settings?",
        f"You changed the working stage settings since they were last loaded. Loading {source} replaces those "
        "changes. They are not saved anywhere.\n\nLoad anyway?",
    )


def load_result_text(source: str, *, replaced_edits: bool) -> str:
    """Inline status after a load: says the working settings were replaced and that nothing was written."""

    tail = " Your unsaved changes were replaced." if replaced_edits else ""
    return f"Loaded {source} into the working stage settings. No PromptPack was changed.{tail}"


def load_failed_text(source: str) -> str:
    return f"Could not load {source}; the working stage settings were not changed."
