"""GUI-540: pure presentation contracts for templates, selected-LoRA evidence and Style Consistency (no Tk, no GPU)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config.style_lora_config import StyleLoRADefinition
from src.controller.content_visibility_resolver import REDACTED_TEXT
from src.gui_v2.lora_authoring_view import (
    AVAILABILITY_MISSING,
    AVAILABILITY_UNVERIFIED,
    AVAILABILITY_VERIFIED,
    NO_TRIGGER_METADATA,
    plan_trigger_insertion,
    project_selected_lora,
    split_keywords,
)
from src.gui_v2.prompt_template_view import (
    NO_TEMPLATE_LABEL,
    build_template_preview,
    preview_breakdown,
    seed_template_values,
    template_choices,
    template_guidance,
)
from src.gui_v2.style_consistency_view import (
    build_style_choices,
    describe_style,
    selector_empty_state,
)
from src.training.style_lora_manager import (
    STYLE_AVAILABLE,
    STYLE_FILE_MISSING,
    STYLE_NOT_INSTALLED,
    STYLE_UNVERIFIED,
    ResolvedStyleLoRA,
    classify_style_availability,
)
from src.utils.lora_scanner import LoRAResource
from src.utils.prompt_templates import (
    clear_prompt_template_cache,
    compose_prompt_text,
    list_prompt_templates,
    load_prompt_templates,
)
from tests.gui_v2.test_lora_browser_240 import scanner_at, write_adapter

# --- templates ----------------------------------------------------------------------------------------------------------


def test_choices_show_friendly_labels_but_store_the_stable_ids() -> None:
    choices = template_choices(list_prompt_templates())

    assert choices[0].label == NO_TEMPLATE_LABEL and choices[0].template_id == ""
    by_id = {choice.template_id: choice.label for choice in choices}
    assert by_id["establishing_wide"].startswith("Establishing Wide Shot")
    assert by_id["over_the_shoulder"].startswith("Over-The-Shoulder")
    assert all(
        not label.startswith(template_id) for template_id, label in by_id.items() if template_id
    )


def test_an_unknown_saved_template_stays_selectable_instead_of_being_dropped() -> None:
    choices = template_choices(list_prompt_templates(), "legacy_custom_template")

    unknown = [choice for choice in choices if choice.template_id == "legacy_custom_template"]
    assert len(unknown) == 1 and "not in catalog" in unknown[0].label
    assert "not in the template catalog" in template_guidance(None, "legacy_custom_template")


def test_every_bundled_template_describes_itself_and_offers_examples_for_all_fields() -> None:
    for definition in list_prompt_templates():
        assert definition.description
        assert set(definition.example_values) == set(definition.placeholders), definition.id
        assert definition.label in template_guidance(definition, definition.id)


def test_a_catalog_without_examples_still_loads_and_offers_none(tmp_path: Path) -> None:
    path = tmp_path / "templates.json"
    path.write_text(
        json.dumps(
            {
                "templates": {
                    "plain": {"template": "a {thing}", "examples": {"thing": "  ", "other": "x"}}
                }
            }
        ),
        encoding="utf-8",
    )
    clear_prompt_template_cache()
    definition = load_prompt_templates(path)["plain"]

    assert definition.examples == () and definition.example_values == {}
    values, seeded = seed_template_values(definition, {})
    assert values == {"thing": ""} and seeded == {}


def test_seeding_fills_only_empty_fields_and_never_replaces_typed_text() -> None:
    definition = load_prompt_templates()["establishing_wide"]

    values, seeded = seed_template_values(
        definition, {"scene": "my own scene", "environment": "  "}
    )

    assert values["scene"] == "my own scene" and "scene" not in seeded
    assert (
        values["environment"] == definition.example_values["environment"]
        and "environment" in seeded
    )
    assert set(seeded) == set(definition.placeholders) - {"scene"}


def test_the_preview_is_the_canonical_composition_with_freeform_text_appended() -> None:
    definitions = load_prompt_templates()
    values = {"scene": "a bridge", "environment": "fog", "lighting": "dusk", "style": "film"}

    preview = build_template_preview("establishing_wide", values, " rain on glass ", definitions)

    assert preview.authored_text == compose_prompt_text(
        "establishing_wide", values, "rain on glass"
    )
    assert preview.template_text == compose_prompt_text("establishing_wide", values, "")
    assert preview.freeform_text == "rain on glass" and preview.unfilled == ()
    assert "Freeform text adds: rain on glass" in preview_breakdown(preview, "establishing_wide")


def test_the_preview_names_empty_fields_and_unknown_templates_without_inventing_text() -> None:
    definitions = load_prompt_templates()

    partial = build_template_preview("establishing_wide", {"scene": "a bridge"}, "", definitions)
    assert set(partial.unfilled) == {"environment", "lighting", "style"}
    assert "Freeform text adds: nothing" in preview_breakdown(partial, "establishing_wide")

    unknown = build_template_preview("legacy", {"x": "y"}, "freeform", definitions)
    assert (
        unknown.authored_text == "freeform"
        and unknown.template_text == ""
        and not unknown.template_known
    )
    assert "not in the catalog" in preview_breakdown(unknown, "legacy")
    assert preview_breakdown(build_template_preview("", {}, "text", definitions), "").startswith(
        "No template"
    )


# --- selected LoRA evidence ---------------------------------------------------------------------------------------------


def _resource(name="adapter", keywords=(), source="none", errors=()) -> LoRAResource:
    return LoRAResource(
        name,
        Path("/unused") / f"{name}.safetensors",
        12,
        list(keywords),
        source,
        errors=tuple(errors),
    )


def _view(resource, **overrides):
    options = {"verified": True, "hidden": False, "policy": None, "target": None}
    options.update(overrides)
    return project_selected_lora(resource, **options)


def test_keywords_are_reported_with_their_source_and_without_claiming_they_are_required() -> None:
    view = _view(_resource(keywords=["sunlit", "golden hour, warm"], source="civitai"))

    assert view.trigger_words == ("sunlit", "golden hour, warm") and view.can_insert
    assert (
        "Civitai info file" in view.trigger_line
        and "sunlit, golden hour, warm" in view.trigger_line
    )
    assert "does not state whether they are required" in view.trigger_line
    assert view.availability == AVAILABILITY_VERIFIED


def test_missing_metadata_is_reported_accurately_and_offers_nothing_to_insert() -> None:
    view = _view(_resource("filename_looks_like_a_trigger_word"))

    assert view.trigger_words == () and not view.can_insert
    assert view.trigger_line == NO_TRIGGER_METADATA
    assert "required" not in view.trigger_line and "filename" not in view.trigger_line


def test_unreadable_keyword_metadata_is_not_presented_as_no_trigger_requirement() -> None:
    view = _view(_resource(errors=["Local keyword metadata unavailable"]))

    assert view.trigger_words == () and "could not be read" in view.trigger_line
    assert view.trigger_line != NO_TRIGGER_METADATA
    assert view.warnings and "unverified" in view.warnings[0]


def test_a_missing_or_unverified_asset_has_no_trigger_words_and_says_so() -> None:
    missing = _view(None)
    assert missing.availability == AVAILABILITY_MISSING and not missing.can_insert
    assert "Missing asset" in missing.availability and missing.warnings

    pending = _view(None, verified=False)
    assert pending.availability == AVAILABILITY_UNVERIFIED and not pending.can_insert
    assert "cannot be assessed" in pending.compatibility


def test_an_ambiguous_local_name_is_unverified() -> None:
    view = _view(_resource(errors=["Ambiguous local adapter name"]))

    assert "ambiguous" in view.availability and view.availability != AVAILABILITY_VERIFIED


def test_hidden_content_redacts_every_projected_string() -> None:
    view = _view(_resource(keywords=["secret"], source="txt"), hidden=True)

    assert view.trigger_words == () and not view.can_insert
    for text in (view.compatibility, view.trigger_line):
        assert REDACTED_TEXT in text and "secret" not in text


def test_synthetic_sidecars_yield_only_evidence_backed_words(tmp_path: Path) -> None:
    root, scanner = scanner_at(tmp_path)
    lora = root / "models/Lora"
    write_adapter(lora / "civ.safetensors", {"ss_base_model_version": "sdxl"})
    (lora / "civ.civitai.info").write_text(
        json.dumps({"trainedWords": ["sunlit", "film grain"], "baseModel": "SDXL 1.0"})
    )
    write_adapter(lora / "txt.safetensors", {"ss_base_model_version": "sdxl"})
    (lora / "txt.txt").write_text("Trigger words: glowing edges, neon haze")
    write_adapter(lora / "bare_trigger_name.safetensors", {})
    write_adapter(lora / "corrupt.safetensors", {})
    (lora / "corrupt.civitai.info").write_text("{ this is not json")

    found = scanner.scan_loras(read_only=True)
    views = {name: _view(resource) for name, resource in found.items()}

    assert (
        views["civ"].trigger_words == ("sunlit", "film grain")
        and "Civitai" in views["civ"].trigger_line
    )
    assert views["txt"].trigger_words and "text sidecar" in views["txt"].trigger_line
    assert (
        views["bare_trigger_name"].trigger_words == ()
        and views["bare_trigger_name"].trigger_line == NO_TRIGGER_METADATA
    )
    assert (
        views["corrupt"].trigger_words == ()
        and views["corrupt"].trigger_line != NO_TRIGGER_METADATA
    )
    assert "required" not in views["bare_trigger_name"].trigger_line.replace("does not state", "")


# --- trigger insertion --------------------------------------------------------------------------------------------------


def test_insertion_appends_after_existing_text_without_changing_it() -> None:
    plan = plan_trigger_insertion("a quiet harbor", ["sunlit", "film grain"])

    assert plan.inserted == ("sunlit", "film grain")
    assert plan.new_text("a quiet harbor") == "a quiet harbor, sunlit, film grain"
    assert plan.new_text("a harbor,") == "a harbor, sunlit, film grain"
    assert plan.new_text("") == "sunlit, film grain"
    assert plan.new_text("keep\n  ") == "keep\n  , sunlit, film grain"


def test_repeating_an_insertion_adds_nothing() -> None:
    first = plan_trigger_insertion("a harbor", ["Sunlit"])
    after = first.new_text("a harbor")
    again = plan_trigger_insertion(after, ["sunlit", "SUNLIT"])

    assert first.inserted == ("Sunlit",)
    assert again.inserted == () and again.already_present == ("sunlit",)
    assert again.new_text(after) == after


def test_a_phrase_owned_by_the_automatic_style_trigger_is_not_inserted_again() -> None:
    plan = plan_trigger_insertion(
        "a harbor", ["cinematic grit", "sunlit"], ["cinematic grit, practical lighting"]
    )

    assert plan.inserted == ("sunlit",) and plan.auto_applied == ("cinematic grit",)
    assert "Style Consistency" in plan.summary()


def test_empty_keyword_input_inserts_nothing() -> None:
    plan = plan_trigger_insertion("a harbor", [])

    assert plan.inserted == () and plan.summary() == "No trigger words to insert."
    assert split_keywords("a, b ,, a") == ("a", "b")


# --- Style Consistency --------------------------------------------------------------------------------------------------


def _definition(
    style_id="style_a", lora_name="lora_a", file_path=None, families=("sdxl",)
) -> StyleLoRADefinition:
    return StyleLoRADefinition(
        style_id, style_id.title(), "trigger a, b", lora_name, 0.6, file_path, tuple(families)
    )


def test_classification_uses_only_gathered_inventory_and_an_explicit_file(tmp_path: Path) -> None:
    weight = tmp_path / "w.safetensors"
    weight.write_bytes(b"x")

    assert classify_style_availability(_definition(), {"lora_a"}) == STYLE_AVAILABLE
    assert classify_style_availability(_definition(), {"other"}) == STYLE_NOT_INSTALLED
    assert classify_style_availability(_definition(), None) == STYLE_UNVERIFIED
    assert classify_style_availability(_definition(file_path=str(weight)), None) == STYLE_AVAILABLE
    assert (
        classify_style_availability(_definition(file_path=str(tmp_path / "gone")), {"lora_a"})
        == STYLE_FILE_MISSING
    )


def test_the_primary_selector_offers_installed_styles_and_hides_catalog_examples() -> None:
    catalog = [_definition("style_a", "lora_a"), _definition("style_b", "lora_b")]

    choices = build_style_choices(catalog, {"lora_a"}, "", show_unavailable=False)
    assert [c.style_id for c in choices] == ["", "style_a"]

    everything = build_style_choices(catalog, {"lora_a"}, "", show_unavailable=True)
    labels = {c.style_id: c.label for c in everything}
    assert "example" in labels["style_b"] and "not installed" in labels["style_b"]
    assert "example" not in labels["style_a"]


def test_a_saved_style_stays_listed_whatever_its_state() -> None:
    catalog = [_definition("style_b", "lora_b")]

    listed = build_style_choices(catalog, set(), "style_b", show_unavailable=False)
    assert [c.style_id for c in listed] == ["", "style_b"] and "saved" in listed[1].label

    ghost = build_style_choices(catalog, set(), "removed_style", show_unavailable=False)
    assert ghost[-1].style_id == "removed_style" and "not in the style catalog" in ghost[-1].label

    cold = build_style_choices(catalog, None, "style_b", show_unavailable=False)
    assert cold[1].style_id == "style_b" and "unverified" in cold[1].label


def test_empty_states_explain_why_nothing_is_offered() -> None:
    catalog = [_definition()]

    assert "cataloged yet" in selector_empty_state([], set(), False)
    assert "Checking" in selector_empty_state(catalog, None, False)
    assert "matching installed LoRA" in selector_empty_state(catalog, set(), False)
    assert selector_empty_state(catalog, {"lora_a"}, False) == ""


def test_the_status_reports_availability_strength_trigger_ownership_and_warnings() -> None:
    catalog = [_definition()]
    applied = ResolvedStyleLoRA("style_a", "Style_A", "trigger a, b", "lora_a", 0.6)
    text = describe_style("style_a", catalog, {"lora_a"}, applied)
    assert "installed LoRA found" in text and "Strength 0.6" in text
    assert "added automatically" in text and "do not paste" in text
    assert "not checkpoint-pair qualification" in text

    skipped = ResolvedStyleLoRA(
        "style_a",
        "Style_A",
        "trigger a, b",
        "lora_a",
        0.6,
        applied=False,
        available=False,
        warning="targets sdxl",
    )
    inactive = describe_style("style_a", catalog, {"lora_a"}, skipped)
    assert "targets sdxl" in inactive and "kept unchanged" in inactive and "not applied" in inactive

    example = describe_style("style_a", catalog, set(), None, pending=True)
    assert "catalog example" in example and "kept unchanged" in example and "evaluated" in example

    assert "not in the style catalog" in describe_style("ghost", catalog, set(), None)
    assert REDACTED_TEXT in describe_style(
        "style_a", catalog, {"lora_a"}, applied, phrase_visible=False
    )


@pytest.fixture(autouse=True)
def _reset_template_cache():
    yield
    clear_prompt_template_cache()
