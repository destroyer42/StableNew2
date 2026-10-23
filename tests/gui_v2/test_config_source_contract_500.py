"""PR-GUI-UX-500: the pure wording and decisions behind the Pipeline's settings sources and empty states."""

from __future__ import annotations

from src.gui.view_contracts import config_source_contract as contract
from src.gui.view_contracts.task_navigation_contract import LEGACY_TAB_ORDER, all_tab_ids


def test_application_settings_files_are_not_offered_as_recipes() -> None:
    names = ["Heroe13", "default", "last_settings", "pack_overrides", "settings", "zeta"]

    assert contract.recipe_names_for_display(names) == ["Heroe13", "default", "zeta"]


def test_working_settings_are_the_default_source() -> None:
    text = contract.source_status_text(contract.SettingsSource(), "")

    assert text == "In use: Working stage settings (no preset or pack loaded)"


def test_a_selected_recipe_is_not_reported_as_applied() -> None:
    text = contract.source_status_text(contract.SettingsSource(), "Heroe13", "sdxl | 832x1216")

    assert text.splitlines()[0] == "In use: Working stage settings (no preset or pack loaded)"
    assert (
        text.splitlines()[1] == "Generation Preset 'Heroe13' selected, not loaded: sdxl | 832x1216"
    )


def test_an_applied_recipe_is_reported_as_the_source() -> None:
    source = contract.SettingsSource(contract.SOURCE_RECIPE, "Heroe13")

    text = contract.source_status_text(source, "Heroe13")

    assert "last loaded from Generation Preset 'Heroe13'" in text.splitlines()[0]
    assert text.splitlines()[1] == "Generation Preset 'Heroe13' loaded"


def test_a_different_recipe_selected_after_applying_stays_not_applied() -> None:
    source = contract.SettingsSource(contract.SOURCE_RECIPE, "Heroe13")

    text = contract.source_status_text(source, "Testing")

    assert "Generation Preset 'Heroe13'" in text.splitlines()[0]
    assert "'Testing' selected, not loaded" in text.splitlines()[1]


def test_a_pack_load_names_the_promptpack_as_the_source() -> None:
    source = contract.SettingsSource(contract.SOURCE_PACK, "hero_pack")

    assert "last loaded from PromptPack Settings of 'hero_pack'" in source.describe()


def test_recipe_actions_need_a_recipe_and_pack_writes_need_packs() -> None:
    none = contract.recipe_action_state(False, True)
    assert not none.any_enabled

    recipe_only = contract.recipe_action_state(True, False)
    assert recipe_only.apply_working and recipe_only.load_pipeline
    assert recipe_only.save_current and recipe_only.delete
    assert not recipe_only.apply_packs

    both = contract.recipe_action_state(True, True)
    assert both.apply_packs


def test_every_recipe_menu_action_has_a_distinct_label() -> None:
    labels = list(contract.RECIPE_MENU_LABELS.values())

    assert len(set(labels)) == len(labels)
    assert set(contract.RECIPE_MENU_LABELS) == {
        "apply_working",
        "apply_packs",
        "load_pipeline",
        "save_current",
        "delete",
    }


def test_empty_recipe_list_says_what_populates_it() -> None:
    hint = contract.recipe_empty_hint(0)

    assert "No Generation Presets yet" in hint
    assert "+ New" in hint
    assert contract.recipe_empty_hint(3) == ""


def test_no_packs_found_names_the_folder_and_the_supported_action() -> None:
    text = contract.pack_selector_status(
        shown=0,
        hidden_by_visibility=0,
        packs_dir="C:/Users/x/PromptPacks",
        list_name="",
        list_matched=True,
    )

    assert "No PromptPacks found in C:/Users/x/PromptPacks" in text
    assert "Prompt tab" in text and "Refresh" in text


def test_hidden_packs_are_explained_instead_of_reported_missing() -> None:
    text = contract.pack_selector_status(
        shown=0, hidden_by_visibility=2, packs_dir="d", list_name="", list_matched=True
    )

    assert text.startswith("2 PromptPacks hidden by the content-visibility setting")
    assert "No PromptPacks found" not in text


def test_pack_status_reports_the_active_filter() -> None:
    kwargs = {"hidden_by_visibility": 0, "packs_dir": "d"}

    assert (
        contract.pack_selector_status(shown=1, list_name="", list_matched=True, **kwargs)
        == "Showing 1 PromptPack."
    )
    assert "from Saved Pack List 'Full'" in contract.pack_selector_status(
        shown=4, list_name="Full", list_matched=True, **kwargs
    )
    unmatched = contract.pack_selector_status(
        shown=4, list_name="Old", list_matched=False, **kwargs
    )
    assert "'Old' matches none of them, so all are shown" in unmatched


def test_pack_list_caption_explains_that_no_lists_can_be_created_in_the_app() -> None:
    assert contract.pack_list_caption(2) == contract.PACK_LIST_CAPTION
    empty = contract.pack_list_caption(0)

    assert "No Saved Pack Lists" in empty
    assert "custom_pack_lists.json" in empty
    assert "no in-app action" in empty


def test_override_description_tracks_the_checkbox() -> None:
    assert "keep their own saved settings" in contract.override_description(False)
    assert "current stage settings instead" in contract.override_description(True)


def test_pack_config_buttons_say_which_side_is_written() -> None:
    assert contract.LOAD_PACK_CONFIG_LABEL == "Load Pack Settings"
    assert contract.APPLY_PACK_CONFIG_LABEL == "Apply to PromptPack\u2026"
    assert "pack is not changed" in contract.LOAD_PACK_CONFIG_TIP
    assert "changes the pack files" in contract.SAVE_PACK_CONFIG_TIP


def test_nine_stable_tab_identities_and_legacy_order_are_unchanged() -> None:
    assert LEGACY_TAB_ORDER == (
        "prompt",
        "pipeline",
        "learning",
        "review",
        "photo_optimize",
        "movie_clips",
        "character_training",
        "svd",
        "video_workflow",
    )
    assert sorted(all_tab_ids()) == sorted(LEGACY_TAB_ORDER)
