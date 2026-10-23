"""Truthful wording for the Pipeline's settings sources and empty states (PR-GUI-UX-500).

Pure and toolkit-independent. The Pipeline sidebar mixes four things that look alike and are not:

* a **PromptPack**: an authored prompt file that also stores its own saved settings;
* a **saved recipe**: a named copy of stage settings kept in the ``presets`` folder (no prompts);
* a **saved pack list**: a named group of PromptPacks that only filters the pack list;
* the **working stage settings**: what the stage cards and sidebar hold right now.

This module owns the words and the small decisions behind them (what to say when a list is empty, which settings
the next job will use, which recipe actions make sense). It reads and writes nothing; persistence, recipes and the
compile path are unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

SOURCE_WORKING = "working"
SOURCE_RECIPE = "recipe"
SOURCE_PACK = "pack"

# Files in the presets folder that the application itself owns. ``ConfigManager.list_presets`` returns every
# ``*.json`` there, so without this the recipe list offers runtime settings as if they were recipes.
NON_RECIPE_PRESET_STEMS: frozenset[str] = frozenset({"settings", "last_settings", "pack_overrides"})

PACK_LIST_FILENAME = "state/custom_pack_lists.json"

NO_RECIPES_TEXT = (
    "No saved recipes yet. A recipe is a named copy of the current stage settings, kept in the presets folder. "
    "Click + New to save one."
)
NO_PACK_LISTS_TEXT = (
    f"No saved pack lists. A pack list only filters the PromptPacks shown here and is read from "
    f"{PACK_LIST_FILENAME}; this version has no in-app action to create one, so all PromptPacks are shown."
)

PACK_SELECTOR_HELP = (
    "PromptPacks are authored in the Prompt tab. Select one or more to add to the draft job. "
    "Load and Save Config move a pack's own saved settings to and from the stage cards."
)

LOAD_PACK_CONFIG_LABEL = "Load Pack Config"
SAVE_PACK_CONFIG_LABEL = "Save Config to Pack"
LOAD_PACK_CONFIG_TIP = "Copies the selected PromptPack's saved settings into the working stage settings. The pack is not changed."
SAVE_PACK_CONFIG_TIP = (
    "Overwrites the saved settings stored inside each selected PromptPack with the current stage settings. "
    "The pack's prompts are not changed."
)
ADD_TO_JOB_TIP = (
    "Adds the selected PromptPacks to the draft job. Nothing is generated until the job is queued."
)

RECIPE_MENU_LABELS: dict[str, str] = {
    "apply_working": "Apply to Working State (also sets Base Generation)",
    "apply_packs": "Write Recipe into Selected Packs",
    "load_pipeline": "Load to Pipeline (stage settings only)",
    "save_current": "Overwrite Recipe with Current Stages",
    "delete": "Delete Recipe",
}

OVERRIDE_OFF_TEXT = "PromptPacks added to the job keep their own saved settings."
OVERRIDE_ON_TEXT = "PromptPacks added to the job use the current stage settings instead of their own saved settings."


def override_description(enabled: bool) -> str:
    """What the 'override pack configs' checkbox decides, at the moment a pack is added to the job."""

    return OVERRIDE_ON_TEXT if enabled else OVERRIDE_OFF_TEXT


def recipe_names_for_display(names: list[str]) -> list[str]:
    """Saved-recipe names without the application's own settings files, order preserved."""

    return [name for name in names if name not in NON_RECIPE_PRESET_STEMS]


@dataclass(frozen=True)
class SettingsSource:
    """Where the working stage settings were last loaded from. Later stage edits are not tracked."""

    kind: str = SOURCE_WORKING
    name: str = ""

    def describe(self) -> str:
        if self.kind == SOURCE_RECIPE and self.name:
            return f"Working stage settings, last loaded from recipe '{self.name}'"
        if self.kind == SOURCE_PACK and self.name:
            return f"Working stage settings, last loaded from PromptPack '{self.name}'"
        return "Working stage settings (no recipe or pack loaded)"


def source_status_text(
    source: SettingsSource,
    selected_recipe: str,
    selected_detail: str = "",
) -> str:
    """Compact, two-line indicator: what is in use, and what is merely selected.

    Selecting a recipe in the list changes nothing; only an apply/load action does, and the text says so.
    """

    lines = [f"In use: {source.describe()}"]
    if selected_recipe:
        applied = source.kind == SOURCE_RECIPE and source.name == selected_recipe
        state = "applied" if applied else "selected, not applied"
        detail = f": {selected_detail}" if selected_detail else ""
        lines.append(f"Recipe '{selected_recipe}' {state}{detail}")
    return "\n".join(lines)


@dataclass(frozen=True)
class RecipeActionState:
    """Which Actions-menu entries make sense right now (enabled flags only; wording is RECIPE_MENU_LABELS)."""

    apply_working: bool
    apply_packs: bool
    load_pipeline: bool
    save_current: bool
    delete: bool

    @property
    def any_enabled(self) -> bool:
        return any(
            (
                self.apply_working,
                self.apply_packs,
                self.load_pipeline,
                self.save_current,
                self.delete,
            )
        )


def recipe_action_state(has_recipe: bool, has_pack_selection: bool) -> RecipeActionState:
    return RecipeActionState(
        apply_working=has_recipe,
        apply_packs=has_recipe and has_pack_selection,
        load_pipeline=has_recipe,
        save_current=has_recipe,
        delete=has_recipe,
    )


def recipe_empty_hint(recipe_count: int) -> str:
    """Why the recipe list is empty and what populates it; empty when there is nothing to explain."""

    return NO_RECIPES_TEXT if recipe_count <= 0 else ""


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
        text += f" from saved list '{list_name}'."
    elif list_name:
        text += f": saved list '{list_name}' matches none of them, so all are shown."
    else:
        text += "."
    return text


PACK_LIST_CAPTION = "Saved pack list (optional filter):"


def pack_list_caption(saved_list_count: int) -> str:
    """Caption above the saved-pack-list dropdown; when there are none it explains why and how they appear."""

    return PACK_LIST_CAPTION if saved_list_count > 0 else NO_PACK_LISTS_TEXT
